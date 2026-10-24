"""Recoverable, metadata-only local index. No GUI, HTTP, credential or provider I/O.

The existing reconciliation, valuation and summary services remain authoritative.
Writers publish a complete tuple in one transaction; readers use one WAL snapshot.
"""
from dataclasses import dataclass, replace
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import ntpath
from pathlib import Path
import re
import sqlite3
import uuid

from usage_config import (application_directory, settings_path, load_settings, settings_from_data,
                          settings_data, save_settings, PROVIDERS)
from usage_ingestion import discover, verified_prefix, observations_from_prefix, ScanIssue, _id
from usage_observations import PARSER_VERSION
from usage_reconciliation import reconcile_observations, RECONCILIATION_VERSION, AccountingIssue
from usage_runtime import RuntimeOwner, AlreadyRunning
from usage_service import build_usage_result, SourceQuality, UsageResult
from usage_valuation import build_catalog, value_event, aggregate_values
import usage_index_codec as codec
from usage_index_db import (connect, initialize, transaction, backup, verify,
                            IndexBusy, IndexRecoveryError, IndexUnavailable, RECOVERY)


def digest(*values):
    return hashlib.sha256(codec.dumps(values).encode()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def safe_code(code):
    if not isinstance(code, str) or re.fullmatch('[a-z][a-z0-9_]{0,100}', code) is None:
        raise ValueError('Invalid index issue code.')
    return code


def scan_data(issue):
    return {'code': safe_code(issue.code), 'source_id': codec.text(issue.source_id), 'line': issue.line,
            'count': codec.count(issue.count), 'excluded_tokens': codec.count(issue.excluded_tokens, True),
            'affects_completeness': issue.affects_completeness}


def scan_from(data):
    return ScanIssue(message='Local index source issue (' + data['code'] + ').', **data)


def accounting_data(issue):
    return {'code': safe_code(issue.code), 'sources': [codec.ref_data(ref) for ref in issue.sources],
            'excluded_tokens': codec.count(issue.excluded_tokens, True)}


@dataclass(frozen=True)
class Publication:
    dataset_id: str
    installation_id: str
    mode: str
    usage_revision: int
    pricing_version: str
    configuration_version: str
    freshness: str
    result: UsageResult


class UsageIndex:
    def __init__(self, path=None, *, mode='real', config_path=None):
        if mode not in ('real', 'demo'):
            raise ValueError('Index mode must be explicit real or demo.')
        self.path = application_directory() / 'usage-hub.sqlite3' if path is None else Path(path).absolute()
        self.mode = mode
        self.config_path = settings_path() if config_path is None else Path(config_path)
        self.owner_path = self.path.with_suffix(self.path.suffix + '.writer.lock')
        try:
            with RuntimeOwner(self.owner_path):
                initialize(self.path, self.config_path)
                with self.connection() as connection, transaction(connection, True):
                    installation = connection.execute("SELECT value FROM metadata WHERE key='installation'").fetchone()[0]
                    self.dataset_id = 'dataset-v1:' + digest(installation, mode)
                    connection.execute('INSERT OR IGNORE INTO datasets(id,installation,mode) VALUES (?,?,?)',
                                       (self.dataset_id, installation, mode))
                    interrupted = connection.execute("SELECT id FROM runs WHERE dataset=? AND status='running'", (self.dataset_id,)).fetchall()
                    if interrupted:
                        connection.execute("UPDATE runs SET status='failed',finished=?,code='interrupted' WHERE dataset=? AND status='running'",
                                           (utc_now(), self.dataset_id))
                        connection.execute("UPDATE datasets SET freshness=CASE WHEN ready=1 THEN 'stale' ELSE 'unavailable' END,code='interrupted' WHERE id=?", (self.dataset_id,))
        except AlreadyRunning:
            raise IndexBusy('The usage index writer is busy; retry after the current operation.') from None
        except sqlite3.DatabaseError:
            raise IndexRecoveryError(RECOVERY) from None

    def connection(self, readonly=False):
        # sqlite Connection context managers do not close handles; use explicit closer.
        return closing(connect(self.path, readonly))

    def _dataset(self, connection):
        return connection.execute('SELECT * FROM datasets WHERE id=?', (self.dataset_id,)).fetchone()

    def status(self):
        settings = load_settings(self.config_path)  # Reject corrupt configuration; never overwrite it.
        with self.connection(True) as connection, transaction(connection):
            row = self._dataset(connection)
            last = connection.execute('SELECT * FROM runs WHERE dataset=? ORDER BY started DESC,id DESC LIMIT 1', (self.dataset_id,)).fetchone()
            return {'dataset_id': self.dataset_id, 'mode': self.mode, 'ready': bool(row['ready']),
                    'usage_revision': row['revision'], 'pricing_version': row['pricing'],
                    'configuration_version': row['configuration'], 'requested_configuration_version': settings.version,
                    'configuration_pending': settings.version != row['configuration'],
                    'freshness': row['freshness'], 'code': row['code'],
                    'last_run': None if last is None else {key: last[key] for key in ('id', 'kind', 'status', 'code', 'revision')}}

    def import_settings(self, *, fault=None):
        """Explicit import from validated configured roots; no real/demo fallback.

        Only changed verified prefixes are reparsed. Full retained evidence is
        reconciled together (also preserves fork parents outside changed files).
        fault is a test-only stage callback; nothing callable is persisted.
        """
        if self.mode != 'real':
            raise ValueError('Configured-source imports are restricted to the real dataset; demo requires a separate explicit synthetic seed.')
        return self._operate('import', fault=fault)

    def reprice(self, *, fault=None):
        """Activate configured rates/fees without changing any canonical token facts."""
        return self._operate('reprice', fault=fault)

    def remove_retained(self, file_ids, *, fault=None):
        ids = tuple(dict.fromkeys(file_ids))
        if not ids or any(not isinstance(value, str) for value in ids):
            raise ValueError('Explicit retained-file IDs are required.')
        return self._operate('remove', remove_ids=ids, fault=fault)

    def _operate(self, kind, *, remove_ids=(), fault=None):
        run = uuid.uuid4().hex
        try:
            with RuntimeOwner(self.owner_path):
                settings = settings_from_data(settings_data(load_settings(self.config_path)))
                catalog = build_catalog(dict(settings.rate_overrides))
                with self.connection() as connection:
                    with transaction(connection, True):
                        connection.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',
                            (run, self.dataset_id, kind, 'running', utc_now(), None, None, None, codec.dumps({})))
                    try:
                        with transaction(connection, True):
                            connection.execute('PRAGMA defer_foreign_keys=ON')
                            dataset = self._dataset(connection)
                            if kind != 'import' and not dataset['ready']:
                                raise IndexUnavailable('No committed usage publication; import explicitly first.')
                            if kind != 'import':
                                active = settings_from_data(codec.loads(connection.execute('SELECT payload FROM configurations WHERE dataset=? AND version=?', (self.dataset_id, dataset['configuration'])).fetchone()[0]))
                                if active.log_roots != settings.log_roots:
                                    raise ValueError('Root configuration changed; import before activating the new configuration.')
                            if kind == 'import':
                                counts = self._scan(connection, settings)
                                self._fault(fault, 'parsed')
                                events, issues = self._reconcile(connection)
                                if not dataset['ready'] and not events and any(codec.loads(row[0])['affects_completeness'] for row in connection.execute("SELECT payload FROM issues WHERE dataset=? AND kind='scan'", (self.dataset_id,))):
                                    raise IndexUnavailable('Initial import has unavailable usage sources; no successful empty publication was created.')
                            elif kind == 'remove':
                                for file_id in remove_ids:
                                    row = connection.execute('SELECT status,path FROM files WHERE dataset=? AND id=?', (self.dataset_id, file_id)).fetchone()
                                    if row is None or not row['status'].startswith('retained_'):
                                        raise ValueError('Only explicit retained source IDs can be removed; disable collection first.')
                                    connection.execute('DELETE FROM observations WHERE dataset=? AND file=?', (self.dataset_id, file_id))
                                    connection.execute("UPDATE files SET status='removed',generation=NULL,issues='[]' WHERE dataset=? AND id=?", (self.dataset_id, file_id))
                                    source_ids = {file_id, _id(row['path'])}
                                    for issue in connection.execute("SELECT id,payload FROM issues WHERE dataset=? AND kind='scan'", (self.dataset_id,)).fetchall():
                                        if codec.loads(issue['payload'])['source_id'] in source_ids:
                                            connection.execute('DELETE FROM issues WHERE dataset=? AND id=?', (self.dataset_id, issue['id']))
                                counts = {'removed_files': len(remove_ids)}
                                events, issues = self._reconcile(connection)
                            else:
                                events = self._events(connection)
                                issues = self._accounting(connection)
                                counts = {'repriced_events': len(events)}
                            # JSON settings are authority. A racing external edit aborts publication.
                            if load_settings(self.config_path).version != settings.version:
                                raise ValueError('Configuration changed during indexing; retry.')
                            revision = self._publish(connection, run, settings, catalog, events, issues, kind, counts, fault)
                        return revision
                    except BaseException:
                        with transaction(connection, True):
                            connection.execute("UPDATE runs SET status='failed',finished=?,code='operation_failed' WHERE id=?", (utc_now(), run))
                            connection.execute("UPDATE datasets SET freshness=CASE WHEN ready=1 THEN 'stale' ELSE 'unavailable' END,code='operation_failed' WHERE id=?", (self.dataset_id,))
                        raise
        except AlreadyRunning:
            raise IndexBusy('The usage index writer is busy; retry after the current operation.') from None
        except sqlite3.DatabaseError:
            raise IndexRecoveryError(RECOVERY) from None

    @staticmethod
    def _fault(fault, stage):
        if fault is not None:
            fault(stage)

    def _scan(self, connection, settings):
        dataset = self.dataset_id
        connection.execute('UPDATE roots SET enabled=0 WHERE dataset=?', (dataset,))
        connection.execute("UPDATE files SET status='retained_disabled' WHERE dataset=? AND status!='removed'", (dataset,))
        connection.execute("DELETE FROM issues WHERE dataset=? AND kind='scan'", (dataset,))
        counts = {'files_verified': 0, 'files_parsed': 0, 'files_reused': 0, 'retained_files': 0}
        for provider, roots in settings.roots().items():
            root_ids = []
            for path in roots:
                root_id = digest(provider, _id(path))
                root_ids.append((root_id, Path(path)))
                connection.execute('INSERT INTO roots VALUES (?,?,?,?,1) ON CONFLICT(dataset,id) DO UPDATE SET enabled=1',
                                   (dataset, root_id, provider, str(Path(path).absolute())))
            paths, issues, roots_read = discover(roots)
            files_read = 0
            for path in paths:
                file_id = digest(provider, _id(path))
                previous = connection.execute('SELECT * FROM files WHERE dataset=? AND id=?', (dataset, file_id)).fetchone()
                if previous is not None and previous['status'] == 'removed':
                    # Explicit removal remains excluded while the source is disabled;
                    # an enabled rediscovered source intentionally imports again.
                    previous = None
                data, generation, file_issues = verified_prefix(path)
                if data is not None:
                    counts['files_verified'] += 1
                    files_read += 1
                if data is not None and previous is not None and generation == previous['generation'] and previous['parser'] == PARSER_VERSION:
                    observations = None
                    file_issues.extend(scan_from(item) for item in codec.loads(previous['issues']))
                    counts['files_reused'] += 1
                elif data is not None:
                    observations, parse_issues = observations_from_prefix(provider, path, data, generation)
                    file_issues.extend(parse_issues)
                    counts['files_parsed'] += 1
                else:
                    observations = None
                unsafe = data is None or any(issue.affects_completeness for issue in file_issues)
                retain = previous is not None and unsafe
                status = 'retained_failed' if retain else 'failed' if data is None else 'partial' if unsafe else 'accepted'
                if previous is None:
                    connection.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?)',
                        (dataset, file_id, provider, str(path.resolve()), None, 0, PARSER_VERSION, status, '[]'))
                for root_id, root in root_ids:
                    if path.absolute().is_relative_to(root.absolute()):
                        connection.execute('INSERT OR IGNORE INTO file_roots VALUES (?,?,?)', (dataset, file_id, root_id))
                if not retain and data is not None:
                    if observations is not None:
                        connection.execute('DELETE FROM observations WHERE dataset=? AND file=?', (dataset, file_id))
                        for observation in observations:
                            payload = codec.dumps(codec.observation_data(observation))
                            connection.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',
                                (dataset, observation.source.observation_id, file_id, provider, observation.conversation_key, payload))
                    connection.execute('UPDATE files SET generation=?,size=?,parser=?,issues=? WHERE dataset=? AND id=?',
                        (generation, len(data), PARSER_VERSION, codec.dumps([scan_data(issue) for issue in file_issues]), dataset, file_id))
                connection.execute('UPDATE files SET status=? WHERE dataset=? AND id=?', (status, dataset, file_id))
                issues.extend(file_issues)
                del data  # Source bytes live only during extraction, never in database state.
            old = connection.execute("SELECT id,path FROM files WHERE dataset=? AND provider=? AND status='retained_disabled'", (dataset, provider)).fetchall()
            for row in old:
                active = connection.execute('SELECT 1 FROM file_roots fr JOIN roots r ON r.dataset=fr.dataset AND r.id=fr.root WHERE fr.dataset=? AND fr.file=? AND r.enabled=1 LIMIT 1', (dataset, row['id'])).fetchone()
                status = 'retained_missing' if active else 'retained_disabled'
                connection.execute('UPDATE files SET status=? WHERE dataset=? AND id=?', (status, dataset, row['id']))
                issues.append(ScanIssue(status, 'Accepted history retained; collection is unavailable.', row['id']))
            connection.execute('INSERT OR REPLACE INTO provider_scans VALUES (?,?,?,?,?)', (dataset, provider, roots_read, len(paths), files_read))
            for index, issue in enumerate(issues):
                payload = codec.dumps(scan_data(issue))
                connection.execute('INSERT INTO issues VALUES (?,?,?,?,?,?)',
                    (dataset, digest(provider, 'scan', index, payload), provider, 'scan', issue.code, payload))
        counts['retained_files'] = connection.execute("SELECT count(*) FROM files WHERE dataset=? AND status LIKE 'retained_%'", (dataset,)).fetchone()[0]
        return counts

    def _reconcile(self, connection):
        observations = tuple(codec.observation_from(codec.loads(row[0])) for row in connection.execute(
            'SELECT payload FROM observations WHERE dataset=? ORDER BY id', (self.dataset_id,)))
        result = reconcile_observations(observations)
        return result.events, result.issues

    def _events(self, connection):
        events = []
        for row in connection.execute('SELECT id,payload FROM events WHERE dataset=? ORDER BY occurred_us,id', (self.dataset_id,)):
            event = codec.event_from(codec.loads(row['payload']))
            if event.event_id != row['id']:
                raise IndexRecoveryError('Committed event identity mismatch; preserve the index and explicitly rebuild.')
            events.append(event)
        return tuple(events)

    def _accounting(self, connection, provider=None):
        return tuple(AccountingIssue(data['code'], 'Accounting issue (' + data['code'] + ').',
                    tuple(codec.ref_from(ref) for ref in data['sources']), data['excluded_tokens'])
                    for row in connection.execute("SELECT payload FROM issues WHERE dataset=? AND kind='accounting' AND (? IS NULL OR provider=?) ORDER BY id", (self.dataset_id, provider, provider))
                    for data in (codec.loads(row[0]),))

    def _publish(self, connection, run, settings, catalog, events, issues, kind, counts, fault):
        dataset = self.dataset_id
        values = tuple(value_event(event, catalog) for event in events)
        aggregate_values(values)  # Validate aggregate token/money bounds before any activation.
        self._fault(fault, 'valued')
        # All projections are explicit; serialization failures abort the entire candidate.
        encoded_events = [(event, codec.dumps(codec.event_data(event))) for event in events]
        encoded_values = [(value, codec.dumps(codec.value_data(value))) for value in values]
        configuration = codec.dumps(settings_data(settings))
        catalog_payload = codec.dumps(codec.catalog_data(catalog))
        connection.execute('INSERT OR IGNORE INTO configurations VALUES (?,?,?)', (dataset, settings.version, configuration))
        connection.execute('INSERT OR IGNORE INTO catalogs VALUES (?,?,?)', (dataset, catalog.version, catalog_payload))
        if connection.execute('SELECT payload FROM catalogs WHERE dataset=? AND version=?', (dataset, catalog.version)).fetchone()[0] != catalog_payload:
            raise IndexRecoveryError('Immutable price catalog mismatch; preserve the index and explicitly rebuild.')
        fingerprint = digest(PARSER_VERSION, RECONCILIATION_VERSION,
            [(event.event_id, payload) for event, payload in sorted(encoded_events, key=lambda x: x[0].event_id)],
            sorted((accounting_data(issue) for issue in issues), key=codec.dumps),
            [tuple(item) for item in connection.execute('SELECT id,generation,status FROM files WHERE dataset=? ORDER BY id', (dataset,))],
            [tuple(item) for item in connection.execute("SELECT id,payload FROM issues WHERE dataset=? AND kind='scan' ORDER BY id", (dataset,))])
        row = self._dataset(connection)
        prior = connection.execute('SELECT fingerprint FROM revisions WHERE dataset=? AND revision=?', (dataset, row['revision'])).fetchone()
        changed = not row['ready'] or prior[0] != fingerprint
        revision = row['revision'] + int(changed)
        # Repricing leaves events/source evidence byte-for-byte unchanged.
        if kind != 'reprice':
            for table in ('event_sources', 'valuations', 'events', 'conversations', 'projects'):
                connection.execute(f'DELETE FROM {table} WHERE dataset=?', (dataset,))
            observation_map = {o.source.observation_id: o for r in connection.execute('SELECT payload FROM observations WHERE dataset=?', (dataset,))
                               for o in (codec.observation_from(codec.loads(r[0])),)}
            for event, payload in encoded_events:
                record = event.record
                evidence = [observation_map[ref.observation_id] for ref in event.sources]
                kinds = {o.project_kind for o in evidence if o.project == record.project}
                project_kind = 'path' if 'path' in kinds else 'source_label' if 'source_label' in kinds else 'unknown'
                identity = ntpath.normcase(ntpath.normpath(record.project)) if project_kind == 'path' else record.project if project_kind == 'source_label' else 'unknown'
                project_id = 'project-v1:' + digest(dataset, project_kind, identity)
                conversation_id = 'conversation-v1:' + digest(dataset, record.provider, event.conversation_key)
                connection.execute('INSERT OR IGNORE INTO projects VALUES (?,?,?,?,?)', (dataset, project_id, project_kind, identity, record.project))
                connection.execute('INSERT OR IGNORE INTO conversations VALUES (?,?,?,?,?)', (dataset, conversation_id, record.provider, event.conversation_key, record.session))
                connection.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (dataset, event.event_id, conversation_id, project_id, record.provider, codec.micros(record.timestamp),
                     *(getattr(record.tokens, key) for key in codec.COUNTS), record.tokens.total, record.reasoning_tokens,
                     record.model, record.effort, payload))
                for ref in event.sources:
                    connection.execute('INSERT INTO event_sources VALUES (?,?,?)', (dataset, event.event_id, ref.observation_id))
            connection.execute("DELETE FROM issues WHERE dataset=? AND kind='accounting'", (dataset,))
            for index, issue in enumerate(issues):
                payload = codec.dumps(accounting_data(issue))
                provider = observation_map[issue.sources[0].observation_id].provider if issue.sources else 'Codex'
                connection.execute('INSERT INTO issues VALUES (?,?,?,?,?,?)', (dataset, digest('accounting', index, payload), provider, 'accounting', issue.code, payload))
        self._fault(fault, 'facts')
        for value, payload in encoded_values:
            connection.execute('INSERT OR REPLACE INTO valuations VALUES (?,?,?,?,?,?)',
                (dataset, value.event_id, catalog.version, None if value.amount_usd is None else format(value.amount_usd, 'f'), value.state, payload))
        covered = connection.execute('SELECT count(*) FROM valuations WHERE dataset=? AND pricing=?', (dataset, catalog.version)).fetchone()[0]
        if covered != len(events) or connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Incomplete candidate publication.')
        # File evidence can change even if no token facts did. Source status never masquerades as price coverage.
        partial = connection.execute("SELECT 1 FROM files WHERE dataset=? AND status NOT IN ('accepted','removed') LIMIT 1", (dataset,)).fetchone()
        scan_partial = connection.execute("SELECT payload FROM issues WHERE dataset=? AND kind='scan'", (dataset,)).fetchall()
        prior_failure = kind != 'import' and row['code'] in ('operation_failed', 'interrupted')
        stale = bool(prior_failure or partial or any(codec.loads(r[0])['affects_completeness'] for r in scan_partial))
        stale_code = row['code'] if prior_failure else 'retained_or_partial_sources' if stale else None
        connection.execute('UPDATE datasets SET revision=?,pricing=?,configuration=?,ready=1,freshness=?,code=? WHERE id=?',
            (revision, catalog.version, settings.version, 'stale' if stale else 'current', stale_code, dataset))
        if changed:
            connection.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?)',
                (dataset, revision, run, fingerprint, catalog.version, settings.version, utc_now()))
        connection.execute("UPDATE runs SET status='succeeded',finished=?,revision=?,counts=? WHERE id=?", (utc_now(), revision, codec.dumps(counts), run))
        self._fault(fault, 'before_commit')
        return revision

    def query(self, context):
        """One consistent publication read, offline; never scans, polls or reprices."""
        if context.demo != (self.mode == 'demo'):
            raise ValueError('Query mode must match the explicit dataset namespace.')
        with self.connection(True) as connection, transaction(connection):
            dataset = self._dataset(connection)
            if not dataset['ready']:
                raise IndexUnavailable('No committed usage publication; import explicitly first.')
            events = self._events(connection)
            catalog = codec.catalog_from(codec.loads(connection.execute('SELECT payload FROM catalogs WHERE dataset=? AND version=?', (self.dataset_id, dataset['pricing'])).fetchone()[0]))
            settings = settings_from_data(codec.loads(connection.execute('SELECT payload FROM configurations WHERE dataset=? AND version=?', (self.dataset_id, dataset['configuration'])).fetchone()[0]))
            if catalog.version != dataset['pricing'] or settings.version != dataset['configuration']:
                raise IndexRecoveryError('Committed configuration/catalog identity mismatch; preserve the index and explicitly rebuild.')
            by_id = {event.event_id: event for event in events}
            values = {row['event']: codec.value_from(codec.loads(row['payload']), by_id[row['event']].record)
                      for row in connection.execute('SELECT event,payload FROM valuations WHERE dataset=? AND pricing=?', (self.dataset_id, dataset['pricing']))}
            if set(values) != set(by_id):
                raise IndexRecoveryError('Incomplete committed valuation coverage; preserve the index and explicitly rebuild.')
            sources = []
            for provider in context.providers:
                scans = tuple(scan_from(codec.loads(row[0])) for row in connection.execute("SELECT payload FROM issues WHERE dataset=? AND provider=? AND kind='scan' ORDER BY id", (self.dataset_id, provider)))
                accounting = self._accounting(connection, provider)
                files = connection.execute("SELECT status FROM files WHERE dataset=? AND provider=? AND status!='removed'", (self.dataset_id, provider)).fetchall()
                has_events = any(event.record.provider == provider for event in events)
                scan_counts = connection.execute('SELECT roots_read,files_discovered,files_read FROM provider_scans WHERE dataset=? AND provider=?', (self.dataset_id, provider)).fetchone()
                roots_read, discovered, files_read = tuple(scan_counts) if scan_counts is not None else (0,0,0)
                if any(r[0].startswith('retained_') for r in files):
                    state = 'stale'
                elif not roots_read or (discovered and not files_read):
                    state = 'failed'
                else:
                    state = 'partial' if any(issue.affects_completeness for issue in scans) else 'complete' if has_events else 'empty'
                if dataset['freshness'] == 'stale' and dataset['code'] in ('operation_failed', 'interrupted'):
                    state = 'stale' if has_events else 'failed'
                sources.append(SourceQuality(provider, state, scans, accounting, roots_read, discovered, files_read))
            notices = ('Local index: accepted unmatched-account histories; retained/partial sources are explicitly qualified.',)
            project_ids = {row['id']: row['project'] if row['kind'] != 'unknown' else None for row in connection.execute('SELECT e.id,e.project,p.kind FROM events e JOIN projects p ON p.dataset=e.dataset AND p.id=e.project WHERE e.dataset=?', (self.dataset_id,))}
            result = build_usage_result(events, context, catalog, dict(settings.plan_fees_usd), sources, notices, valuations=values, project_ids=project_ids)
            result = replace(result, settings_version=settings.version)
            return Publication(self.dataset_id, dataset['installation'], self.mode, dataset['revision'],
                               catalog.version, settings.version, dataset['freshness'], result)

    def backup(self, directory=None):
        try:
            with RuntimeOwner(self.owner_path), self.connection(True) as connection:
                return backup(connection, self.path.parent / 'index-backups' if directory is None else directory, self.config_path)
        except AlreadyRunning:
            raise IndexBusy('The usage index writer is busy; retry after the current operation.') from None


def restore_backup(source, destination, *, config_destination=None):
    """Restore only to new explicit paths; never overwrite a live index or settings."""
    source, destination = Path(source), Path(destination)
    companion = source.with_suffix('.settings.json')
    raw_settings = codec.loads(companion.read_text(encoding='utf-8'))
    settings = None if raw_settings is None else settings_from_data(raw_settings)
    if destination.exists() or (config_destination is not None and Path(config_destination).exists()):
        raise ValueError('Restore targets must be new files; preserve the existing index/configuration.')
    with closing(connect(source, True)) as connection:
        verify(connection, allow_older=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb'):
            pass
        target = sqlite3.connect(destination)
        try:
            connection.backup(target)
            verify(target, allow_older=True)
        finally:
            target.close()
    if config_destination is not None and settings is not None:
        save_settings(settings, config_destination)
    return destination
