# Usage Hub local database handoff

Prepared October 24, 2026, America/Los_Angeles, against `446e2e0`. Historical status at preparation: **mapping complete; physical schema not implemented**. Current implementation and gate evidence belong to [S11](s11-local-index.md) and the refinement ledger; the mapping below is retained as the original handoff, not current implementation status. This handoff supplements the [integration contract](usage-hub-integration-plan.md), which owns data semantics; the [refinement plan](project-refinement-plan.md) owns dependencies.

## 1. Discovery and local-first decision

The user confirmed that the project should remain local. The planned storage adapter is a per-user local SQLite index, following the existing contract recommendation. No hosted database, collector upload, remote synchronization, or new framework is required. Keep Python, terminal/tray access, explicit dashboard launch, and the existing offline path.

Discovery checked tracked and untracked source/schema filenames in this checkout, local branches/worktrees, nearby development folders, saved local project locations, and the UsageTray application-data directory. No Usage Hub schema, SQL migrations, database configuration, or existing application-data database was found in that bounded search. A neighboring project's migrations belong to a separate planner, not this usage ledger. They were not copied or adopted. No database contents, credentials, or real histories were opened. This is bounded discovery, not a claim that no database exists anywhere on the computer.

The isolated refinement branch `codex/s01-observation-contracts` now contains S01-S07 commits through `461c3a3`; S08 privacy/diagnostic verification is next. Those changes are not merged into this branch. The [S05 dashboard review](s05-dashboard-integration-review.md) pins the completed query/valuation boundaries and records independent service-test evidence. Shared-checkout observation edits remain uncommitted and belong to that core work. Do not infer main-branch readiness from another worktree's gate evidence.

Planned application-owned locations, to implement at S11 after S06 configuration ownership is established:

- Index: `%LOCALAPPDATA%/UsageTray/usage-hub.sqlite3`; use the existing application-data fallback convention on other platforms. Keep it off network/sync folders and out of the source/build directories.
- Configuration authority: S06's `%LOCALAPPDATA%/UsageTray/settings.json`, as decided in S00. Database settings rows are versioned projections of validated configuration, not a second independently editable source of fees or roots.
- Backups: an application-owned local backup directory alongside the index, with database-consistent backups and a separately recoverable configuration copy. Retention limits remain an S07/S11 decision to record before release; no indefinite history collection is enabled by this plan.
- Demo: an explicit separate dataset namespace and synthetic fixture seed. Real failures never select or copy demo data automatically.

No database directory/file, migration, schema version, connection, dependency, or persistent setting was created in this preparation.

### Automatic collection scope — October 24 clarification

The user wants automatic account usage collection if supported, with local recorded usage as the fallback; ordinary ChatGPT conversations are excluded. Local recorded usage remains the authoritative source for detailed project/model accounting. Planned automatic local rescans belong to the existing runtime owner, not a separate Codex chat automation or hosted job.

Optional account refresh is technically supported by the [official app-server protocol](https://learn.chatgpt.com/docs/app-server#7-token-usage-chatgpt): `account/usage/read` returns token-activity summaries and nullable daily buckets; `account/rateLimits/read` returns live limits. Installed `codex-cli 0.163.0` generated a non-experimental protocol schema containing `account/usage/read` during an offline compatibility check. This verifies the method declaration only: authenticated responses, field availability, product coverage, and exclusion of ordinary-chat activity have not been verified. Do not enable account token activity until that scope is established.

When that adapter is implemented, reuse the existing runtime owner for bounded periodic refresh with cooldown/backoff and labeled last-successful state. Account snapshots remain separate from unmatched local records and are never added to local totals, used to invent per-project/model usage, or converted to actual subscription charges. Unsupported methods, unavailable fields, offline state, or authentication errors must leave local views usable without prompting for credentials as an incidental workaround. Account access is optional; no credential changes, account request, scheduler, or persistent background task was performed by this check. Implementation follows the S07 ownership and S11-S13 integration gates.

## 2. Inputs, owners, and outputs

The intended path is approved roots → metadata observations → reconciled canonical events → exact event valuations → committed local index → shared query result → terminal/HTML/API → dashboard. Each arrow is a contract boundary; the database must not derive corrected events from already aggregated report totals.

**S01-S03 collector boundary:** accepts approved JSONL sources and emits typed observations, provenance, accepted events, structured issues, and captured UTC ranges. Persist source generation and counter validity before normalization. The current `Record` projection alone cannot recover epochs, copied-source evidence, or request-context quality.

**S04 valuation boundary:** accepts accepted events plus an immutable price policy and emits event value/state, applied rate, tier, assumptions, source/date, and computation/override versions. Repricing never changes canonical tokens. Use the completed S04 implementation pinned in the S05 review for bounds and constructors, not the preview's temporary `usage_value.py`.

**S05 query boundary:** accepts dataset, captured range/timezone, normalized filters, versions, and ordering. It produces one authoritative summary, issues/coverage, chart buckets, groups, conversation list/detail, and comparisons. Database adapters return typed facts and exact values; they do not create a separate pricing/aggregation policy.

**S06-S07 owner boundary:** owns configuration validation, import/repricing queue, single writer, independent provider scheduler, cross-process ownership, and clean shutdown. Cached usage queries never poll providers. Saved configuration, queued work, and active computed versions are distinct states.

**S11-S13 integration boundary:** stores/publishes corrected results, exposes the versioned local API, and adapts the reviewed dashboard. The current `/api/preview/*` server is an in-memory development adapter, not that API or an index implementation.

## 3. Logical-to-physical mapping worksheet

The following are required logical responsibilities, not executable DDL. Since no existing Usage Hub schema was found, every actual table/column/migration assignment is **pending S11 implementation**. Use these names as mapping labels; do not generate a competing schema if an existing relevant implementation is later located. Every foreign-key relationship must preserve dataset membership, including joins through installation, files, events, prices, and revisions.

### Dataset, source discovery, and runs

- `datasets`: stable opaque `dataset_id`; local `installation_id`; `mode` restricted to `real|demo`; UTC creation time and nullable coverage start. Dataset is the first partition for every usage query. Provider account identity stays nullable and unverified.
- `source_roots`: opaque `root_id`; dataset/provider; approved absolute path; enabled flag; configuration version. Only validated local configuration introduces roots; API mutations select approved IDs, never arbitrary paths.
- `source_files`: opaque `file_id`; root reference; relative path; generation identity; captured size/boundary/fingerprint; parser version; scan timestamps/status and safe issue code. Unique source identity is scoped to its root/generation policy, not basename. One path can have multiple generations; a restart must not equate replacement with append.
- `ingestion_runs`: opaque `run_id`; dataset; operation/job reference; start/completion; status; bounded work counts; resulting committed revision nullable. Failed/in-progress scans are not successful empty revisions.

### Observation evidence and canonical facts

- `source_observations`: opaque source-local observation ID; file/generation/physical position; provider conversation/message/request/turn IDs; event time plus validity; observation kind; model, project identity kind, effort/source; cumulative/message/last counters with separate `valid|missing|invalid` states; session/fork/context references; parser version and allowlisted quality codes. Store only validated fields. Do not retain raw lines, arbitrary nested JSON, transcripts, credential fields, or a serialized whole provider payload.
- Observation uniqueness: `(dataset, file, generation, physical_position, observation_kind)` or an equivalent source-local key approved by the parser contract. This identifies evidence, not global usage. Reconciliation still gathers all copies before deriving deltas.
- `projects`: opaque project ID; dataset/installation; identity kind; normalized identity and original display label/path. Windows path identity may normalize separators/case without resolving arbitrary paths. Source labels remain labels. Unknown identity remains explicit and excluded from the known-project count; do not merge it with a known project or merge folders by basename.
- `conversations`: opaque internal ID; dataset/installation/provider; original provider conversation ID nullable; explicit weak-identity key when absent; optional verified account reference; lifetime first/last accepted usage times. For supplied IDs, enforce uniqueness on `(dataset, installation, provider, provider_conversation_id)`; absent IDs use an explicit source-local policy, not SQL-null uniqueness by accident.
- `usage_events`: reconciliation-assigned opaque `event_id`; dataset/conversation/project references; UTC `occurred_at`; exact model and effort/source; five canonical token categories; nullable reasoning; turn/message/request IDs; source kind; epoch and event anchors; parser/reconciliation versions; request-context count/evidence and quality. Event IDs include reconciled epoch evidence and do not depend on enumeration order. Store project per event; a conversation may span projects/models/effort values.
- `event_sources`: `(dataset, event_id, observation_id)` relationship with foreign keys to both sides. Multiple copied observations can support one accepted event. Removing one copy cannot remove events still supported by another.
- `ingestion_issues`: opaque issue ID; stable code/severity; optional run/file/conversation/interval references; safe explanation; detected/resolved timestamps; nullable unknown skipped-token amount. File counts, event counts, counter quality, and price coverage remain separate dimensions.

### Immutable pricing and valuations

- `price_catalogs`: immutable catalog/pricing version; computation policy version; source/check date; immutable override identity/snapshot. Snapshot only validated rate fields; do not serialize arbitrary configuration content.
- `model_rates`: immutable rate ID; catalog reference; exact model key; USD; five exact category rates; optional context threshold/high-context rates; bundled/custom flag and source. Unknown models have no convenient fallback rate. Dated-model mapping follows the final S04 policy.
- `event_valuations`: unique `(dataset, event_id, pricing_version)`; amount nullable; `priced|unpriced`; rate reference; selected tier; assumptions; computation version and request-context evidence. A priced zero is numeric zero with `priced`; an unpriced event has a null amount. An unfinished valuation batch is `building`, not a collection of unpriced events.
- Token facts remain separate from prices. If canonical events change identity/decomposition after reconciliation upgrades, publish a new usage revision and compute the required valuations before activation; do not relabel old valuations as matching the new event set.

### Configuration, publication, and operations

- `settings` projection: configuration version; validated timezone, fees, approved root references, active/requested catalog references, and update time. Mirror S06's authoritative configuration through one owner. Never seed a second fee-default source in database/frontend code. Initial configured fees remain USD 20 per provider; null, zero, and missing stay distinct where supported.
- Cross-store recovery: atomic JSON replacement and a SQLite transaction are not one atomic operation. After saving validated configuration, record/queue its projection and required work; expose pending state until the active dataset is coherent. On restart, reconcile the file's configuration version with the index projection before serving affected new results. Keep the previous usable publication available. S06/S11 must implement and test the precise recovery protocol.
- `usage_revisions`: dataset-scoped monotonic committed revision; run reference; committed time; parser/reconciliation versions and ready status. Publish events, provenance, issues, and the active revision together.
- Active publication tuple: dataset + usage revision + pricing version + configuration version. Capture it with the resolved range/filters under a consistent read. A valuation relation/index must demonstrate complete coverage of the chosen accepted event set before that tuple is usable.
- Jobs: durable operation identity; kind; `queued|running|succeeded|failed|superseded`; safe phase/code/message; work counts; timestamps; resulting versions. The logical lifecycle is required by S12; physical storage may be a dedicated job relation or a documented run adapter. Recover interrupted work explicitly and never report abandoned work as success.

### Cached limits are a separate data path

- `provider_checks`: provider, attempted/completed UTC time, safe outcome, next eligible wall-clock check time; never persist `time.monotonic()` deadlines.
- `quota_snapshots`: last successful provider check, account scope `active_cli_account`, nullable verified account reference, safe note, nullable structured blocked-usage flag. A failed check preserves the last successful snapshot and marks freshness separately.
- `quota_windows`: snapshot reference; source bucket/window key where supplied; validated display label; finite utilization percentage; duration/reset nullable. Preserve all returned windows; do not add their percentages or infer stable identity from array position.
- Initial delivery retains latest successful state plus enough check/job status for recovery. Historical quota retention/charts require a later explicit policy. Do not imply past limits can be reconstructed from token logs.

## 4. Numeric and identity rules for the adapter

Canonical token categories are nonnegative signed-64-bit integers, `0..9223372036854775807`. Check derived totals and returned aggregate bounds too; Python's arbitrary-sized integers do not waive the contract. Reasoning is null or a subset of output and never enters the total or a sixth charge. Observation missing/invalid counters remain nullable with validity state, rather than observed zero.

For SQLite, use checked integer storage for bounded counters and validated canonical decimal text for money/rates. Do authoritative multiplication, addition, comparison, and sorting with the shared Python `Decimal` service. Do not use SQLite floating `SUM`, lexical decimal sorting, or casts to REAL as authoritative arithmetic. Exact numeric SQL optimizations require separate bounds/equivalence evidence.

The contract proposes 12 fractional USD digits and half-even rounding once per event valuation. Sum the quantized event values; format only at display. Final supported rate/fee precision and maximum money bounds must match completed S04. Reject invalid, non-finite, negative rate/fee, and overflow values with safe errors; never silently truncate or widen into a different pricing policy. Signed comparisons can be negative.

API quantities are integer strings; money/rates are decimal strings; instants are ISO UTC strings ending in `Z`; null means unavailable. SQLite UTC storage may use validated fixed-format text or checked integer epochs, but the implementation must document one precision and preserve ordering/boundaries. Adapt current float timestamps explicitly and test exact boundary conversion. Display timezone remains an IANA name, initially `America/Los_Angeles`.

IDs remain opaque in the browser. Compound dataset-safe foreign keys or equivalent validated constraints prevent cross-dataset joins. A shortened conversation label, Figma node ID, project basename, numeric counter tuple, or source file position is never a global event identity.

## 5. Transaction and lifecycle contracts

### Import publication

1. The one runtime owner validates enabled roots and captures each file generation/consistent prefix. A file failure is an issue, not permission to delete accepted history.
2. Stage metadata-only observations and reconcile every affected conversation, including unchanged overlapping sources. Preserve fork baselines and reset epochs before deriving accepted events.
3. Compute valuations for the event set and selected immutable catalog, or keep the candidate publication explicitly building. Do not expose half an import or mixed valuation versions.
4. In one writer transaction, replace affected canonical facts/source links, publish issues, validate references/invariants/valuation coverage, and advance the active revision/publication. Record the successful run/job outcome consistently with that publication.
5. Commit atomically. Any failure leaves the previous coherent publication queryable with a safe stale/failed status. A first-ever failure remains unavailable; it is not a zero or demo dataset.

### Repricing, configuration, and reads

- Repricing stages a new valuation version against a fixed usage revision and validated configuration. If usage changes before activation, reject/requeue the stale candidate; do not publish incomplete coverage. Activate the new pricing/publication atomically when ready. Never rewrite canonical tokens or event IDs merely because rates changed.
- Capture query range once in UTC `[start,end)` with named-zone calendar boundaries; week is trailing 168 hours. Preserve the same range through chart/day filters, lists, facets, details, Back, and pagination. A filter-only context derives from the frozen base range; explicit Refresh or preset/timezone change captures a new boundary.
- Read related totals/details in one consistent transaction/snapshot. Version changes between requests produce a refreshable 409; old database snapshots need not be retained. A query-context token freezes context, not the existence of an historical snapshot.
- Page after exact aggregation/sorting. Cursors bind dataset/context, endpoint, sort, page size, and exact sort key/stable-ID tie. Summaries and chart columns cover the full matched set, not only the visible page.
- Serialize writes, enable foreign keys on every connection, and use bounded busy timeouts. Persistent journal mode and lock recovery require implementation-time verification on Windows; do not imply an in-process lock solves repeated launches.

### Source removal, migration, and recovery

- Missing/disabled roots or disappearing files retain accepted contributions with an explicit retained-source/stale status. Disabling collection and explicitly removing retained history are separate actions. Only an explicit supported rebuild/removal may delete unsupported contributions and publish a new revision.
- Number migrations monotonically with recorded checksums and app/schema compatibility. Before upgrade, make a database-consistent backup and preserve recoverable configuration. Refuse newer unsupported schemas. On failure preserve the original and show recovery guidance; never overwrite it with a fresh empty database.
- Test backup/restore with journal files handled by the chosen consistent-backup mechanism, foreign-key/integrity checks, interrupted migration, and restored configuration/catalog versions. Copying a live SQLite main file alone is not the backup protocol.
- The index may be rebuildable from allowed observation/source evidence. User settings/overrides are independently valuable; rebuilding must not reset them. No automatic source-history deletion or silent shortening of advertised history.

## 6. Query-to-dashboard mapping and preview differences

The target read contract is [integration contract section 7](usage-hub-integration-plan.md#7-proposed-api-and-input-contract). The current [preview adapter](../windows/usage_hub.py) deliberately differs. S12/S13 must replace or explicitly adapt these differences:

- Preview `dataset: demo|real` is a mode label, not a persistent `dataset_id`. Introduce distinct dataset/mode fields, contract/request/generated metadata, opaque stable IDs, and one captured usage/pricing/configuration tuple.
- Preview `provider=both` becomes repeated `provider=codex&provider=claude`; map existing Python display names explicitly. Empty provider selection is invalid.
- Preview `project` path matching becomes dataset-scoped `project_id` selection; conversation rows derive the full matched project set and show `Multiple projects` where needed. Unknown-project counts remain separate.
- Preview model/effort single values become bounded exact-value arrays. Search expands from preview project/conversation matching to the contract's literal project/conversation/model matching, with the proposed 200-character trimmed limit instead of preview 512.
- Preview page numbers/six-row slices and last-activity ordering become opaque cursors, contract page-size bounds, and exact value-descending default order with stable-ID ties. Preserve full-result summaries and explicit pricing coverage.
- Preview numeric epoch timestamps become contract UTC strings. Add configuration version and explicit base-context derivation; inherited preview hashes are not durable publication or cursor identities.
- Preview facets are simple sets; target facets apply other filters, omit their own filter, and retain selected zero-match choices. Chart-day selection must use the frozen zone/range and reject out-of-range days.
- Preview `summary_dto()` places nullable reasoning beside tokens and uses `record_count`; the contract's concrete event example nests reasoning inside `tokens`. Final machine-readable DTO schemas must specify aggregate reasoning coverage/count names and map them explicitly. The fixture below uses a mapping-only projection, not an invented v1 envelope.
- Preview Settings is read-only; target Save/Cancel/version-conflict behavior must consume S06 configuration and S12 jobs. Preview Limits contains sample readings; real limits must use the owner's cached active-account state. Do not infer quota history or account matches.

Overview cards, daily bars, provider/model/project groups, conversation pages, and detail event lists must derive from the same accepted-event query. Both chart metrics retain labeled zero-based axes scaled to matched daily columns. Display abbreviation (`190,000`, `2.84M`, `5B`) never enters stored counters or authoritative calculations.

## 7. Synthetic alignment fixture and implementation acceptance

[usage-hub-database-alignment.json](fixtures/usage-hub-database-alignment.json) is a local, metadata-only mapping fixture adapted from section 8 of the integration contract. It contains two post-reconciliation events, rates, source links, a frozen query, expected summaries, and qualified monthly comparisons. **It is not raw observation evidence, an import seed migration, a full v1 DTO schema, or the 12-conversation Figma demo.** An S11 test implementation must construct its own source observations and exercise actual reconciliation separately.

Expected values: Codex 2,840,000 tokens / USD 18.42; Claude 65,000 / USD 0.471; Both 2,905,000 / USD 18.891. Both has two conversations and one known project. Reasoning is known for one event and null for the other. All fixture rates are synthetic fixed rates, with no threshold tier; unavailable request context does not imply an observed context size. Calendar-month-to-date full fees are USD 20/20; signed differences are -1.58, -19.529, and -21.109. A provider filter preserves comparison eligibility; metadata/search/day filters do not.

Before enabling a persistent path, demonstrate these scenarios against the actual database adapter, not this Markdown or an arithmetic-only fixture check:

1. Map every logical responsibility above to actual tables/columns, constraints, indexes, owner, and migration. Record omissions explicitly; benchmark indexes for dataset/time, provider/time, conversation/time/ID, project/time, model/effort/time, observation conversation/generation, and valuation version/event.
2. Import unchanged data twice and restart: stable accepted facts, totals, source links and versions; no duplicate charges. Complete `100,200` plus partial `200` totals 200 in both file orders. Reset `100,200,50,100` retains 250 after the ambiguous transition is excluded. Copies, forks, equal timestamps, and conflicting evidence follow corrected core fixtures.
3. Interrupt parse, canonical publication, valuation, and repricing. Readers see the previous complete tuple or a clear first-run/building state. Unreadable/disappearing sources do not erase history.
4. Prove integer overflow rejection, decimal rounding/aggregation/order, priced-zero versus unpriced/empty/partial, unknown skipped amounts, immutable repricing, and unchanged canonical-token fingerprints after a rate change.
5. Prove dataset isolation, cross-dataset FK rejection, DST/UTC end-exclusive boundaries, full-result summary/detail/chart reconciliation, exact-order cursor ties, frozen-range navigation, and version conflicts.
6. Prove configuration projection/restart recovery, first/second launch ownership, migration rollback/newer-schema refusal, consistent backup/restore, and cached usage availability with providers offline.
7. Resolve the [pre-S08 malformed-metadata findings](pre-s08-privacy-handoff.md) before persisting/exporting those values. Run privacy sentinels through the actual observation serializers, database rows, query DTOs, reports, and safe diagnostics; never store nested source content under an ostensibly metadata-only key.

## 8. Handoff readiness and remaining decisions

Preparation delivers the logical mapping, adapter discrepancies, local placement/configuration ownership, fixture inputs/expected outputs, and acceptance scenarios. S04 numeric bounds and S05 Python contracts are now implemented on the isolated branch and pinned in the S05 review. Actual table names/DDL/migrations, numeric storage adapters, API DTO serializers/schemas, cross-store configuration recovery, adaptation of completed S07 ownership/retention, and indexed performance remain pending their integration sessions.

Validation used the project Python interpreter with an independent standard-library `json`/`Decimal`/`zoneinfo` check. JSON syntax and duplicate-key rejection, integer/decimal wire types, signed-64-bit fixture counts, category totals, reasoning subset/coverage, event-level half-even arithmetic, provider/full totals, full-fee differences, frozen UTC/local-day buckets, exact conversation ordering, unique IDs, and source-link references passed. Local Markdown links, balanced code fences, whitespace, and `git diff --check` passed. These checks validate the example's internal consistency; they do not validate SQL constraints, transactional recovery, a machine-readable API schema, or actual reconciliation. No application suite or build was rerun for documentation/fixture-only changes.

Next core work is S08 against the completed S07 branch, then S09 and integration validation of both branches. S11 can begin implementation only after those core gates pass. Do not merge the worktrees, connect real history, or mark S11-S14 complete because this mapping or its example arithmetic validates.
