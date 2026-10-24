"""Checksummed SQLite migrations and consistent backups for the optional local index."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import stat
import sqlite3
import uuid

from usage_config import load_settings, settings_data
from usage_index_codec import dumps

SCHEMA_VERSION = 3
APPLICATION_ID = 0x55545259
BUSY_MS = 250
RECOVERY = 'Cannot open the usage index. Preserve it and restore a verified backup or explicitly rebuild to a separate file.'


class IndexErrorBase(ValueError):
    pass


class IndexUnavailable(IndexErrorBase):
    pass


class IndexQueryBudget(IndexUnavailable):
    pass


class IndexBusy(IndexErrorBase):
    pass


class IndexRecoveryError(IndexErrorBase):
    pass


MIGRATIONS = (
    (
        'CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
        'CREATE TABLE migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)',
        "CREATE TABLE datasets (id TEXT PRIMARY KEY, installation TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('real','demo')), revision INTEGER NOT NULL DEFAULT 0, pricing TEXT, configuration TEXT, ready INTEGER NOT NULL DEFAULT 0 CHECK(ready IN (0,1)), freshness TEXT NOT NULL DEFAULT 'unavailable', code TEXT)",
        'CREATE TABLE configurations (dataset TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(dataset,version), FOREIGN KEY(dataset) REFERENCES datasets(id))',
        "CREATE TABLE roots (dataset TEXT NOT NULL, id TEXT NOT NULL, provider TEXT NOT NULL CHECK(provider IN ('Codex','Claude')), path TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), PRIMARY KEY(dataset,id), FOREIGN KEY(dataset) REFERENCES datasets(id))",
        "CREATE TABLE files (dataset TEXT NOT NULL, id TEXT NOT NULL, provider TEXT NOT NULL CHECK(provider IN ('Codex','Claude')), path TEXT NOT NULL, generation TEXT, size INTEGER NOT NULL DEFAULT 0, parser TEXT NOT NULL, status TEXT NOT NULL, issues TEXT NOT NULL, PRIMARY KEY(dataset,id), FOREIGN KEY(dataset) REFERENCES datasets(id))",
        'CREATE TABLE provider_scans (dataset TEXT NOT NULL, provider TEXT NOT NULL, roots_read INTEGER NOT NULL, files_discovered INTEGER NOT NULL, files_read INTEGER NOT NULL, PRIMARY KEY(dataset,provider), FOREIGN KEY(dataset) REFERENCES datasets(id))',
        'CREATE TABLE file_roots (dataset TEXT NOT NULL, file TEXT NOT NULL, root TEXT NOT NULL, PRIMARY KEY(dataset,file,root), FOREIGN KEY(dataset,file) REFERENCES files(dataset,id), FOREIGN KEY(dataset,root) REFERENCES roots(dataset,id))',
        'CREATE TABLE observations (dataset TEXT NOT NULL, id TEXT NOT NULL, file TEXT NOT NULL, provider TEXT NOT NULL, conversation TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(dataset,id), FOREIGN KEY(dataset,file) REFERENCES files(dataset,id))',
        "CREATE TABLE projects (dataset TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('path','source_label','unknown')), identity TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY(dataset,id), FOREIGN KEY(dataset) REFERENCES datasets(id))",
        'CREATE TABLE conversations (dataset TEXT NOT NULL, id TEXT NOT NULL, provider TEXT NOT NULL, identity TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY(dataset,id), UNIQUE(dataset,provider,identity), FOREIGN KEY(dataset) REFERENCES datasets(id))',
        'CREATE TABLE events (dataset TEXT NOT NULL, id TEXT NOT NULL, conversation TEXT NOT NULL, project TEXT NOT NULL, provider TEXT NOT NULL, occurred_us INTEGER NOT NULL, input INTEGER NOT NULL CHECK(typeof(input)=\'integer\' AND input>=0), output INTEGER NOT NULL CHECK(typeof(output)=\'integer\' AND output>=0), cached INTEGER NOT NULL CHECK(typeof(cached)=\'integer\' AND cached>=0), write5m INTEGER NOT NULL CHECK(typeof(write5m)=\'integer\' AND write5m>=0), write1h INTEGER NOT NULL CHECK(typeof(write1h)=\'integer\' AND write1h>=0), total INTEGER NOT NULL CHECK(typeof(total)=\'integer\' AND total>=0 AND total=input+output+cached+write5m+write1h), reasoning INTEGER CHECK(reasoning IS NULL OR (typeof(reasoning)=\'integer\' AND reasoning>=0 AND reasoning<=output)), model TEXT NOT NULL, effort TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(dataset,id), FOREIGN KEY(dataset,conversation) REFERENCES conversations(dataset,id), FOREIGN KEY(dataset,project) REFERENCES projects(dataset,id))',
        'CREATE TABLE event_sources (dataset TEXT NOT NULL, event TEXT NOT NULL, observation TEXT NOT NULL, PRIMARY KEY(dataset,event,observation), FOREIGN KEY(dataset,event) REFERENCES events(dataset,id), FOREIGN KEY(dataset,observation) REFERENCES observations(dataset,id))',
        'CREATE TABLE catalogs (dataset TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(dataset,version), FOREIGN KEY(dataset) REFERENCES datasets(id))',
        "CREATE TABLE valuations (dataset TEXT NOT NULL, event TEXT NOT NULL, pricing TEXT NOT NULL, amount TEXT, state TEXT NOT NULL CHECK(state IN ('priced','unpriced')), payload TEXT NOT NULL, CHECK((state='unpriced' AND amount IS NULL) OR (state='priced' AND typeof(amount)='text')), PRIMARY KEY(dataset,event,pricing), FOREIGN KEY(dataset,event) REFERENCES events(dataset,id), FOREIGN KEY(dataset,pricing) REFERENCES catalogs(dataset,version))",
        'CREATE TABLE issues (dataset TEXT NOT NULL, id TEXT NOT NULL, provider TEXT NOT NULL, kind TEXT NOT NULL, code TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(dataset,id), FOREIGN KEY(dataset) REFERENCES datasets(id))',
        "CREATE TABLE runs (id TEXT PRIMARY KEY, dataset TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')), started TEXT NOT NULL, finished TEXT, code TEXT, revision INTEGER, counts TEXT NOT NULL, FOREIGN KEY(dataset) REFERENCES datasets(id))",
        'CREATE TABLE revisions (dataset TEXT NOT NULL, revision INTEGER NOT NULL, run TEXT NOT NULL, fingerprint TEXT NOT NULL, pricing TEXT NOT NULL, configuration TEXT NOT NULL, committed TEXT NOT NULL, PRIMARY KEY(dataset,revision), FOREIGN KEY(dataset) REFERENCES datasets(id), FOREIGN KEY(run) REFERENCES runs(id), FOREIGN KEY(dataset,pricing) REFERENCES catalogs(dataset,version), FOREIGN KEY(dataset,configuration) REFERENCES configurations(dataset,version))',
    ),
    (
        'CREATE INDEX observation_conversation ON observations(dataset,provider,conversation)',
        'CREATE INDEX event_time ON events(dataset,occurred_us)',
        'CREATE INDEX event_provider_time ON events(dataset,provider,occurred_us)',
        'CREATE INDEX event_conversation_time ON events(dataset,conversation,occurred_us,id)',
        'CREATE INDEX event_project_time ON events(dataset,project,occurred_us)',
        'CREATE INDEX event_model_effort_time ON events(dataset,model,effort,occurred_us)',
        'CREATE INDEX valuation_version ON valuations(dataset,pricing,event)',
    ),
    (
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, dataset TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('import','reprice')), request_key TEXT NOT NULL, configuration TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','superseded')), phase TEXT NOT NULL, code TEXT, created TEXT NOT NULL, started TEXT, completed TEXT, counts TEXT NOT NULL, result TEXT, payload TEXT NOT NULL, FOREIGN KEY(dataset) REFERENCES datasets(id))",
        "CREATE UNIQUE INDEX active_job_request ON jobs(dataset,request_key) WHERE status IN ('queued','running')",
        'CREATE INDEX job_queue ON jobs(dataset,status,created,id)',
        'CREATE TABLE provider_cache (provider TEXT PRIMARY KEY, payload TEXT NOT NULL)',
    ),
)


def checksum(statements):
    return hashlib.sha256('\n'.join(statements).encode()).hexdigest()



def reject_link(path):
    path = Path(path)
    if str(path).startswith('\\\\'):
        raise IndexRecoveryError('The usage index and its backups require a local path.')
    if path.exists():
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
            raise IndexRecoveryError('Linked index or backup paths are unsupported; choose an application-owned local path.')

def connect(path, readonly=False, *, check_same_thread=True):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                                 uri=True, timeout=BUSY_MS / 1000, isolation_level=None, check_same_thread=check_same_thread)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute(f'PRAGMA busy_timeout={BUSY_MS}')
        if not readonly:
            connection.execute('PRAGMA synchronous=FULL')
        return connection
    except BaseException:
        connection.close()
        raise


def verify(connection, *, allow_older=False):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    app = connection.execute('PRAGMA application_id').fetchone()[0]
    if app != APPLICATION_ID or version < 1 or version > SCHEMA_VERSION or (not allow_older and version != SCHEMA_VERSION):
        raise IndexRecoveryError(RECOVERY)
    rows = connection.execute('SELECT version,checksum FROM migrations ORDER BY version').fetchall()
    if [(r[0], r[1]) for r in rows] != [(i, checksum(MIGRATIONS[i-1])) for i in range(1, version+1)]:
        raise IndexRecoveryError(RECOVERY)
    if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or connection.execute('PRAGMA foreign_key_check').fetchone():
        raise IndexRecoveryError(RECOVERY)
    return version


def backup(connection, directory, config_path=None):
    """SQLite backup API includes committed WAL state; raw main-file copies do not."""
    directory = Path(directory)
    reject_link(directory)
    directory.mkdir(parents=True, exist_ok=True)
    config = settings_data(load_settings(config_path)) if config_path is not None else None
    token = uuid.uuid4().hex
    destination = directory / f'index-backup-{token}.sqlite3'
    target = sqlite3.connect(destination)
    try:
        connection.backup(target)
        verify(target, allow_older=True)
    finally:
        target.close()
    (directory / f'index-backup-{token}.settings.json').write_text(dumps(config), encoding='utf-8')
    # Keep three application-generated pairs. Never recurse or touch source histories.
    generated = sorted(directory.glob('index-backup-*.sqlite3'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in generated[3:]:
        suffix = path.stem.removeprefix('index-backup-')
        companion = path.with_suffix('.settings.json')
        if len(suffix) == 32 and all(c in '0123456789abcdef' for c in suffix) and companion.is_file() and not path.is_symlink() and not companion.is_symlink():
            try:
                reject_link(path)
                reject_link(companion)
                path.unlink()
                companion.unlink()
            except OSError:
                pass  # Retention is best effort; never fail a valid backup for a locked older pair.
    return destination


def initialize(path, config_path=None):
    path = Path(path)
    reject_link(path)
    reject_link(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    if existed:
        connection = connect(path)
    else:
        # Exclusive creation; never replace a corrupt/unknown existing index.
        with path.open('xb'):
            pass
        connection = connect(path)
    try:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if existed:
            if not tables:
                raise IndexRecoveryError(RECOVERY)
            version = verify(connection, allow_older=True)
        else:
            version = 0
        if version and version < SCHEMA_VERSION:
            backup(connection, path.parent / 'index-backups', config_path)
        if version < SCHEMA_VERSION:
            connection.execute('BEGIN IMMEDIATE')
            try:
                for next_version in range(version+1, SCHEMA_VERSION+1):
                    for statement in MIGRATIONS[next_version-1]:
                        connection.execute(statement)
                    connection.execute('INSERT INTO migrations VALUES (?,?)', (next_version, checksum(MIGRATIONS[next_version-1])))
                    connection.execute(f'PRAGMA user_version={next_version}')
                connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
                if version == 0:
                    connection.execute('INSERT INTO metadata VALUES (?,?)', ('installation', uuid.uuid4().hex))
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower() != 'wal':
            raise IndexRecoveryError(RECOVERY)
        verify(connection)
    finally:
        connection.close()


@contextmanager
def transaction(connection, write=False):
    try:
        connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield connection
        connection.commit()
    except sqlite3.OperationalError as error:
        connection.rollback()
        if 'locked' in str(error).lower() or 'busy' in str(error).lower():
            raise IndexBusy('The usage index writer is busy; retry after the current operation.') from None
        raise IndexRecoveryError(RECOVERY) from None
    except BaseException:
        connection.rollback()
        raise
