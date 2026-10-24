# S11: recoverable local usage index

Status: implemented; final acceptance evidence is recorded in the refinement ledger. Windows Python is the implementation target. The index is an explicitly constructed headless adapter; the tray/terminal continue their existing paths and the dashboard remains an explicit demo preview until S12/S13.

## Ownership and entry points

- `windows/usage_index.py`: `UsageIndex`, import/reprice/removal publication, one-snapshot offline queries, status and backup/restore.
- `windows/usage_index_db.py`: two ordered/checksummed schema migrations, SQLite connection policy, validation and consistent backups.
- `windows/usage_index_codec.py`: explicit allowlisted metadata/rate/fact/value projections. No whole-provider or whole-query serialization.
- `windows/usage_ingestion.py`: shared `observations_from_prefix`; both direct scans and the index use the same extraction/quality rules.
- `windows/usage_service.py`: the authoritative summary/group/filter/exact-sort service. Optional committed valuations must match canonical event identity, record and catalog. Optional project IDs count normalized known identities; null means unknown. Legacy calls retain exact-label project counts.
- `windows/tests/test_index.py`: synthetic source, actual SQLite, process-crash, ownership, recovery and equivalence gates.

Default index: `%LOCALAPPDATA%/UsageTray/usage-hub.sqlite3`, following `application_directory()` elsewhere. Configuration remains S06 `settings.json`; index configuration rows are immutable projections, not another fee-default source. Explicit alternate index/config paths support tests and recovery. Reject UNC, linked index files/direct parents and linked backup directories; automatic detection of every mapped network drive/sync product is not claimed. Use an application-owned local directory. No initialization/import happens simply by importing the module. No new package dependency is required (`sqlite3` is standard library). Allowlisted paths/identities can be sensitive metadata; local storage is not encryption or a semantic secret classifier. Content disguised as an otherwise valid metadata string cannot be identified universally.

Development usage, from the repository's project interpreter with `windows` on the module path:

```python
from usage_index import UsageIndex
from usage_service import QueryContext
from usage_time import resolve_range
import time

store = UsageIndex()  # Explicitly creates/opens the optional local index.
store.import_settings()  # Explicitly scans roots from validated local settings.
now = time.time()
zone = "America/Los_Angeles"
context = QueryContext(tuple((p, resolve_range("month", now, timezone=zone))
                             for p in ("Codex", "Claude")), now, "month", zone)
publication = store.query(context)  # Offline; no rescan, provider call or repricing.
result = publication.result       # Ordinary authoritative immutable UsageResult.
```

This example is not a new CLI flag or `/api/v1` endpoint. Running the import is an explicit real-history operation; verification for this session uses synthetic roots only.

## Physical mapping

Migration 1 creates the data relations; migration 2 adds observation-conversation, event-time/provider/conversation/project/model-effort, and valuation-version indexes. Migration checksums cover the exact ordered DDL statements. Schema version is 2 and application ID is `0x55545259`.

- `metadata`: installation identity. `datasets`: stable installation/mode-derived opaque dataset ID, explicit `real|demo`, current usage/pricing/configuration tuple, readiness/freshness/safe operation code. Namespace every relation before provider identity. Provider account identity is not inferred.
- `roots`, `files`, `file_roots`: configured collection membership, enabled state, resolved file path, verified generation fingerprint, captured byte size/parser, accepted/partial/failed/retained/removed status. Overlapping roots refer to one provider/file identity. `provider_scans` stores actual successfully read roots, discovered files and verified files separately from retained history.
- `observations`: source-local ID, file, provider, canonical conversation key and explicitly projected metadata JSON. The projection retains counter validity and nullable values, session/fork/context references, explicit effort and source, and parser version. Physical positions identify evidence, not global token events.
- `projects`: dataset-scoped identity kind, normalized identity, original display label. Windows path identity uses `ntpath` separator/case normalization without resolving source metadata as filesystem paths. Source labels stay separate and case-sensitive; unknown stays explicit and is excluded from indexed known-project counts. Report grouping labels retain compatibility; S12 maps opaque project IDs to normalized selection and facets.
- `conversations`: dataset/provider/full reconciliation identity with display label. Missing provider IDs retain the reconciler's source-local identity, never a basename substitute. Events link conversations and projects per accepted event, supporting multiple projects/models per conversation.
- `events`: canonical opaque ID, conversation/project links, indexed UTC-microsecond projection, five checked integer categories/total, nullable reasoning subset, model/effort and explicit full fact projection. Epoch/event/source-kind and request-context evidence survive. No token delta is inferred in SQL.
- `event_sources`: compound dataset-safe foreign keys from accepted events to all supporting observation IDs.
- `catalogs`: immutable exact full rate/catalog projection, including individual rates/tier definitions/source/date/version. Individual model rates are embedded in this validated versioned projection rather than a second `model_rates` relation.
- `valuations`: dataset/event/pricing key, nullable exact decimal TEXT amount, explicit priced/unpriced state and full allowlisted valuation evidence (rate ID, tier, assumptions, context and computation versions). No unfinished batch is published as unpriced.
- `configurations`: immutable validated S06 projections; no duplicate fee default. `revisions`: committed usage/provenance/quality fingerprint and its originating publication/run. `datasets` owns the current tuple, including later repricing at the same usage revision; old revisions do not promise retained historical query snapshots.
- `issues`: separate scan/accounting kinds, stable safe codes, source references/counts and nullable excluded amounts. Static code-based explanations replace arbitrary exception/provider messages at storage reads.
- `runs`: durable running/succeeded/failed import/reprice/removal attempts, safe outcome, counts, UTC timestamps and resulting usage revision. S12 will add queued/coalesced jobs and the public lifecycle contract; S11 does not claim that API exists.

Provider checks/quota snapshots/windows are deliberately absent: this index stores local usage. The existing runtime retains independent live-limit checks; the production API/runtime integration follows S12. Optional account activity remains unverified and is never imported or added to local totals.

## Import, failure, and publication rules

1. Acquire the application-owned writer lock using S07 `RuntimeOwner` at the index's stable sibling `.writer.lock`. Do not unlink it. This serializes imports, repricing, migrations, backup and restart recovery across processes; it does not start a provider scheduler. S12's runtime owner will call this adapter.
2. Record a durable running attempt, then enter one `BEGIN IMMEDIATE` transaction. Every connection enables foreign keys and a bounded 250 ms busy timeout. WAL is required/verified and writers use `synchronous=FULL`. Readers use independent read-only connections and one read transaction.
3. Discover enabled configured roots and verify each file prefix with the existing bounded read/reread/generation protocol. Verify bytes even for unchanged files; fingerprints are not trusted stat-only caches. Reparse only changed fingerprints or parser versions. Raw bytes/payloads are transient extraction inputs, never persisted.
4. Reconcile all retained observations together, including unchanged copies and fork evidence, before deriving events. This intentionally reconciles the full retained dataset rather than optimizing only affected conversations; correctness and parent evidence take priority. SQL indexes are present, but this is not append-offset parsing or a constant-time importer.
5. A failed/unstable read, malformed suffix or incomplete metadata cannot replace an existing file's accepted evidence with an empty/shorter partial set. Retain that file's last accepted evidence and label it stale; accept a qualified safe prefix on a first partial file. Missing/disabled roots and files retain their contributions. Initial unavailable scans without any accepted events fail as unavailable, not successful zero/demo.
6. A successfully verified valid truncation/replacement is reparsed as the current authoritative generation. Its unsupported old observations are replaced atomically; this is a current-source index, not an archive of every earlier file generation. Copies/other retained source files still participate. The separate failed-read policy above preserves last accepted evidence.
7. Value each accepted event using S04, validate all token/money aggregate bounds, and validate explicit serializers. Stage replacement of evidence/facts/source links, issues and valuations in the same transaction. Deferred foreign keys allow replacement; final coverage/FK checks must pass before activation.
8. Publish the complete tuple and successful run outcome together. Advance the usage revision when canonical facts, provenance or source quality changes; unchanged imports retain the revision. Price changes do not alter event IDs/tokens or advance the usage revision. Any exception/termination before commit leaves the old tuple readable. Safe failed run/status is recorded separately when possible; restart marks an abandoned durable running attempt interrupted.

`remove_retained(file_ids)` is explicit metadata-only removal, allowed only for retained source IDs. It reconciles remaining evidence and publishes another revision; it never deletes source histories or resets settings. Disable collection through settings/import first. An enabled source rediscovered later is imported again. Rebuilding to a separate new index path is supported; there is no automatic destructive in-place rebuild.

## Exact values and time

Canonical categories/totals and observations' known counters must fit nonnegative signed 64-bit integers. Nullable reasoning remains a subset of output. Overflow rejects the candidate and preserves the previous publication; skipped amounts remain unknown. Money/rates are validated exact decimal strings; use S04's 80-digit context, per-event 12-place half-even rounding and bounded aggregation. Never use SQL REAL casts, floating SUM or lexical decimal sorting. Offline reads consume committed valuations and the stored immutable catalog, then call the same shared summary/filter/group/exact-sort code as reports.

The existing core uses finite binary UTC epoch timestamps. Preserve their exact round trip as hexadecimal float TEXT inside explicit metadata projections; store truncated integer UTC microseconds in `events.occurred_us` as an indexed projection only. Authoritative selection still uses the original shared-service timestamps and UTC `[start,end)` boundaries. This avoids silently rounding sub-microsecond boundaries. The hexadecimal representation is internal storage, **not** a v1 wire format; S12 must emit the contract's ISO UTC `Z` instants with documented precision. Run timestamps already use ISO UTC microseconds.

## Configuration and crash recovery

The validated JSON file is authority. `status()` compares its content-derived version with the active database projection and reports pending configuration. Ordinary reads use the previous complete stored configuration/catalog, including fees, while work is pending or settings are malformed. Import activates configured roots and prices atomically with facts. Reprice activates rates/fees without rescanning or modifying canonical facts; root changes require import and cannot be silently activated by repricing. A file-version change detected during a run aborts that candidate. Separate atomic JSON replacement and SQLite commit are not one distributed transaction; a later edit remains pending and the owning runtime must enqueue/retry its work in S12.

A failed/unapplied import stays stale through a subsequent reprice; only a successful import establishes current source quality. No automatic settings rewrite, credential refresh, provider poll or cross-store rollback occurs. `status()` itself rejects malformed settings with S06 recovery guidance; offline committed queries remain usable.

## Migration, backup and restore

Refuse unknown application IDs, unsupported/newer schemas, altered checksums, empty preexisting files and corrupt indexes. Never replace them with a new empty index. Initialization failure preserves its partial/empty file for explicit recovery; rebuilding selects a separate path.

Before upgrading a known older schema, use SQLite's backup API (includes committed WAL state), validate integrity/FKs, and save a separately recoverable validated current configuration snapshot. Backups live under sibling `index-backups` as UUID-named database/settings pairs; keep the latest three application-generated pairs with nonrecursive, non-link cleanup. Locked old pairs can remain temporarily; do not fail the new backup because retention is blocked. No source-history retention/deletion is involved.

Migrations execute transactionally; failed DDL rolls back to the prior version, preserving the backup/configuration. `restore_backup(source, destination, config_destination=...)` validates the backup and restores only to new explicitly selected paths; existing database/configuration targets are refused. It uses the SQLite backup API, not a raw live-main-file copy. A backup's requested settings can be newer than its active publication; restored status reports that pending difference instead of fabricating activation. Physical power-loss/storage-device durability and hostile filesystem replacement races are not certified by process-crash tests.

## Acceptance and remaining scope

Focused persistence tests cover required 200/250 accounting, unchanged reimport/restart/root order, append/truncation/replacement, failed/missing/disabled sources, removal, old history, exact values/coverage/ranking, known/unknown project identity, UTC/DST boundaries, dataset FKs, stored-valuation use, corrupt settings/config activation, all publication fault points, actual process termination and cross-process ownership, WAL readers, migration rollback/newer/corrupt refusal, backup/restore/retention, and privacy sentinels. The final 315-test suite, 34 focused cases, existing packaged compatibility, independent probes and synthetic timings are recorded in the [refinement ledger](project-refinement-plan.md#session-s11--recoverable-local-index).

Not implemented here: `/api/v1`, frozen browser contexts/cursors, queued public jobs, automatic runtime import scheduling, real-data dashboard switch, synthetic demo seeding, quota history, authenticated account-usage collection or macOS support. Demo namespace is reserved and cannot import real configured sources. S12 adds the production API/owner/job contract; S13 adapts the existing dashboard; S14 packages/tests that integration.
