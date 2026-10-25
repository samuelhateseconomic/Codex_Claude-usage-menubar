# AI Usage Hub: integration contract and delivery plan

Status: proposed contract and work sequence; no application, database, or Figma fixes are implemented by this document.

Implementation work order and session gates: [engineering refinement plan](project-refinement-plan.md). Agent working instructions: [AGENTS.md](../AGENTS.md). This document remains the detailed contract for the optional hub integration track.

Prepared against the local working tree at Git base `f93f87e`, October 23, 2026, America/Los_Angeles. Local modifications are part of the inspected baseline and must be preserved.

Refinement: checked against the current Python collectors, report/tray code, packaging workflow, original hub plan, and accounting evaluation. Figma control IDs below are carried forward from the supplied plan; they were not re-audited in this revision. This document takes precedence over the older hub plan for data contracts, correctness gates, and delivery order.

## Decision brief

The foundation is suitable for a local usage hub. The critical dependency is reconciling usage correctly before storing or displaying authoritative totals. A database makes queries persistent; it does not resolve duplicate histories by itself.

Recommended first implementation: retain Python and the tray, use a local SQLite index, and expose one shared query service to the terminal and an optional local web dashboard. FastAPI and React/TypeScript are reasonable proposed web adapters, not installed dependencies or a requirement for the accounting layer. Confirm any already-started database work before introducing a competing schema or engine.

First-release vertical slice: select month-to-date and provider, see API-equivalent value, fees and coverage, inspect a conversation, and return to the same results. Keep active-account limits separate. Defer extra presentation choices and historical quota charts until that slice works with correct local data.

Before implementation, resolve four decisions in section 13: existing database/placement, launch preference, reconciliation policy, and uncertain context-tier pricing. Defaults proposed here are local-only storage, terminal preserved with dashboard opened explicitly, conservative reconciliation with visible exclusions, and an explicitly labeled compatibility tier estimate. None constitutes approval to deploy or to modify an external Figma file.

## 1. Purpose and current scope

Use this document to connect three pieces of work:

1. The existing Python collectors and token accounting produce normalized usage and active-account quota readings.
2. The database stores reconciled usage, source provenance, configuration, and prospective quota history.
3. The dashboard requests filtered results and displays them through the interactions reviewed in Figma.

The proposed dashboard interface is a compact dark developer console. Its first job is to explain recorded tokens and estimated API-equivalent value for Codex and Claude. Users must be able to select either provider, locate the contributing projects and conversations, and return from details without losing their filters. Preserve the existing terminal entry point; a dashboard launch must be explicit unless the user later chooses it as the default.

The immediate deliverable is this refined Markdown plan. After contract alignment, accounting/database work and representative design review can proceed in parallel. A complete prototype of every future screen is not a prerequisite for correctness work. Review the first-release flows before implementing their UI; schedule the remaining prototype backlog separately.

This plan does not assume that your database has already adopted SQLite, PostgreSQL, an ORM, or particular table names. No database schema or migrations were found in the inspected project files. The earlier web plan proposed SQLite; that remains a recommendation for a local index, not a requirement imposed on your current database work.

## 2. Existing foundations and gaps

### Reuse these modules

- [usage_core.py](../windows/usage_core.py): `Window`, `Snapshot`, Codex CLI app-server adapter, and Claude usage adapter. These provide quota readings, not token-ledger events.
- [usage_reports.py](../windows/usage_reports.py): `Tokens`, `Record`, provider log readers, `price_for()`, `estimate()`, period selection, report collection, and plan comparison.
- [usage_tray.py](../windows/usage_tray.py): `ProviderState`, refresh locks, independent provider checks, five-minute success polling, failure backoff, and retention of the last successful reading.
- [test_reports.py](../windows/tests/test_reports.py) and [test_usage.py](../windows/tests/test_usage.py): existing fixture and adapter regression coverage.

There is no implemented dashboard API, browser frontend, or database query layer in this baseline. New routes and entities in this document are proposed contracts, not existing capabilities.

### Accounting work required before trusted database totals

The existing [project evaluation](project-evaluation-2026-10-23.md) and [synthetic probes](review_accounting_probes.py) document two unresolved reconciliation cases:

- A complete Codex history with cumulative totals `100, 200`, combined with a truncated copy containing `200`, can produce `300` when files are read in one order. The accepted total should be `200`, independent of file order.
- Cumulative counters `100, 200, 50, 100` should retain `250` after excluding the ambiguous reset interval. The current deduplication can instead retain `200` because a post-reset counter repeats an earlier numeric value.

Both synthetic failures were reproduced again during this refinement. They do not prove that the user's actual histories contain those shapes. Treat their regression fixtures as a release gate before calling imported totals trustworthy. A database uniqueness constraint cannot repair incorrect deltas that were already produced upstream.

The earlier user preference was a lightweight terminal. This document develops the supplied Figma/web proposal without treating that proposal as authorization to replace the terminal. Both presentations should consume the same accounting/query service. The evaluation's accounting findings remain release gates for either interface.

## 3. Non-negotiable data semantics

### Scope and unknown values

- Usage reports cover records available on this computer, potentially across accounts. Their account scope is `all_local_accounts_unmatched`.
- Live limits cover the active CLI account at the time of collection. Their account scope is `active_cli_account`.
- Do not join these datasets as if an account match were established. Account IDs remain nullable unless a source supplies reliable evidence.
- Browser chat, other devices, absent logs, and remote work without local records are outside current usage coverage.
- No records means no recorded activity was found in that scope. It does not establish zero account usage.
- Missing prices, missing reasoning counters, missing effort, inaccessible roots, and skipped intervals remain distinguishable.
- No prompt text, response text, authentication tokens, or raw credential payloads enter the dashboard database or API.

### Token accounting

Canonical names and existing Python mappings:

- `uncached_input_tokens` <- `Record.tokens.input`.
- `output_tokens` <- `Record.tokens.output`; reasoning is already included.
- `cache_read_tokens` <- `Record.tokens.cached`.
- `cache_write_5m_tokens` <- `Record.tokens.write5m`.
- `cache_write_1h_tokens` <- `Record.tokens.write1h`.
- `reasoning_tokens` <- `Record.reasoning_tokens`; nullable, a subset of output.

`total_tokens = uncached_input_tokens + output_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens`.

Never add reasoning again. For Codex, provider input counters include cache reads; subtract cache reads when deriving uncached input. For Claude, retain separate cache categories and the existing legacy-TTL assumption notice where applicable.

Required token categories are nonnegative integers. Existing readers sometimes normalize absent or invalid counters to zero; do not claim those values were explicitly observed. Preserve an observation-quality flag where a field was absent or invalid, and do not fabricate an unknown historical count later.

Effort is recorded metadata, not an extra token category or cost multiplier. Preserve `high`, `xhigh`, `max`, `ultra`, custom wire values, and `unknown` distinctly.

### Money and pricing

- Display `Estimated API-equivalent value`, never an actual subscription bill.
- Apply prices to each event before aggregating. Do not price an entire month's tokens as one request, especially with context tiers.
- Unknown model rates yield an unpriced event, not a zero-dollar event.
- A mixed query yields a priced subtotal plus unpriced record/token counts. All-unpriced and empty queries return a null amount with different states.
- API `value.state` describes rate availability only. Report tier assumptions and unknown/malformed counter fields separately; a fully rate-covered subtotal can still be uncertain or incomplete. Label it accordingly beside the value, not only in a distant diagnostics page.
- Keep model, rate-catalog version, rate source, checked date, override status, and tier assumptions with each valuation.
- Existing tier selection uses an event's input counters. Those counters do not always prove per-request context size. Preserve whether request context is known; label an applied compatibility assumption until a request-aware policy is approved.
- Initially use current/configured rates, as the existing reports do. Historical billing rates require a later explicit policy.
- Monthly plan fees are user configuration. Compare them only for calendar-month-to-date with the full configured monthly fee, not a prorated fee or presumed billing cycle.
- Seed the user's fees as Codex `20.00` USD/month and Claude `20.00` USD/month. Persist one configuration source; do not maintain separate defaults in terminal, API, and frontend.
- Show a signed difference: `priced value - configured monthly fee`. Avoid claiming realized savings. If providers have no records, missing fees, or all-unpriced records, their comparison is unavailable.
- Project/model/effort/search/day filters make a plan comparison potentially misleading. Hide it unless the query contains only provider and month-to-date filters.
- Return a signed per-provider difference and its pricing/ingestion qualifications. A combined comparison is available only when every selected provider has records, a configured fee, and at least one priced event. Never drop an unavailable provider while still labeling the result Both. Do not calculate a savings percentage or project a full month from partial-month activity.

### Time and consistency

- Store instants in UTC. Use a named IANA display timezone; initial preference: `America/Los_Angeles`.
- API ranges use inclusive start and exclusive end: `[start_at, end_at)`.
- On the first query, resolve a preset once into a UTC range ending at `range.end_at`. Subsequent list/facet/detail/page requests must carry that same resolved range and query context. `generated_at` is each response's generation time and may differ from the captured range end. A data revision alone does not freeze a moving month-to-date/today/week boundary.
- `today`: local midnight to captured now. `month`: local first-of-month midnight to captured now. `week`: trailing 168 hours to captured now, matching the existing rolling-week intent; label it accordingly.
- Current `collect_report()` uses an inclusive upper bound and host-local preset boundaries. The new query service must explicitly adapt and test these differences rather than silently reuse them.
- Provider quota-session ranges can differ by provider. Keep `session` as an advanced provider-specific report period; do not imply one shared session boundary for Both.
- A daily chart uses local calendar dates in the selected zone; days can have 23 or 25 hours. Its sum must equal the same query's totals.
- Every related API result carries a usage revision and pricing version. Details and aggregates must not silently mix revisions.
- Include `configuration_version` and `query_context_id` as well: fee/timezone changes can alter results without changing usage or prices. Capture all versions and the resolved range under one consistent read; on mismatch return a refreshable conflict rather than quietly mixing results.

## 4. Input-to-output workflow

### Usage path

1. Discover approved local log roots using the current defaults or explicitly saved settings.
2. Read metadata-only observations from JSONL files. Capture source identity, position, provider IDs, counters, model/effort metadata, and timestamps without persisting conversation content.
3. Reconcile overlapping observations for each provider/conversation across all contributing files. Identify counter epochs and duplicated streamed messages before emitting deltas.
4. Persist canonical usage events and their source links in one transaction for the affected conversation set.
5. Resolve a versioned price policy and compute event valuations. Keep canonical token facts independent of prices so repricing does not reimport logs.
6. Query the committed revision using one normalized filter object.
7. Return totals, coverage, chart buckets, ranked groups, conversations, and details with stable IDs.
8. Render the API response. The browser formats units and manages navigation; it does not recalculate authoritative estimates.

### Quota path

1. A single shared scheduler invokes the existing provider adapters independently.
2. A successful check stores a snapshot and all returned windows atomically.
3. A failed check stores a sanitized attempt status, preserving the previous successful snapshot.
4. Limits queries read cached state. Page navigation must not invoke a live provider request.
5. An explicit refresh request is accepted or returns the existing cooldown/in-progress state. It cannot bypass provider backoff.

The current `next_check` is monotonic process time. Never store that number as a UTC timestamp. Derive a safe wall-clock `next_eligible_check_at` for display and reconstruct scheduling conservatively after restart.

### Settings path

1. Settings opens a draft of persisted configuration with a configuration version.
2. Editing updates only the local form draft.
3. Save validates the draft, rejects version conflicts, and commits atomically.
4. Root changes queue an index operation; rate changes create a new pricing version; fee changes affect comparisons; appearance changes affect presentation only.
5. Cancel discards the draft. Show success only after persistence succeeds.

### Process ownership and refresh lifecycle

- One per-user application instance owns the database writer, import queue, provider scheduler, and local API. The tray and web clients attach to that owner; they must not each create their own scheduler. Enforce ownership across processes, not only with `threading.Lock` inside one process.
- On a second launch, reuse the healthy instance. If it is stale, acquire ownership before recovery; do not kill an arbitrary process because it occupies a remembered port. Store endpoint discovery and authorization material in the user's application-data directory with user-only access where supported.
- Starting the application must not automatically open a browser. An explicit tray/CLI action opens the dashboard. Closing a browser tab leaves the tray running; Quit stops accepting jobs and closes provider subprocesses/database connections cleanly. An interrupted import leaves only the previous committed revision visible.
- Initial indexing starts after local settings validation. For the first release, scan enabled roots at startup, on explicit refresh, and on a coalesced five-minute check while running. Bound concurrent work to one writer/import job; queue/coalesce additional triggers. No filesystem watcher is required initially.
- `/status` distinguishes `never_indexed`, `indexing`, `ready`, `ready_with_issues`, and `failed`. On first import, show loading rather than synthetic zero totals. During subsequent imports, serve the last committed revision with an indexing/freshness badge. Show counters/phases, not an invented percentage or ETA.
- Terminal/HTML exports must use the same query result once the service integration is enabled. Offline fallback, if retained, must use the same reconciliation policy and identify its scope/version; do not silently switch to the old parser to obtain a different total.

## 5. Proposed database entities

These are logical entities. Map names and physical types to your database rather than replacing your schema without review. Every usage-related key must include or reference a dataset namespace. Keep real and demo datasets separate.

### `datasets`

- Primary key: `dataset_id`, opaque stable string.
- Fields: `mode` (`real` or `demo`), `installation_id`, `created_at`, `coverage_started_at` nullable.
- One local installation is the initial scope. A hosted or multi-device database needs a separate tenancy/authentication and sync design before collectors send data to it.

### `source_roots`, `source_files`, and `ingestion_runs`

- Root fields: `root_id`, `dataset_id`, `provider`, approved absolute path, enabled flag, created/updated timestamps.
- File fields: `file_id`, `root_id`, relative path, file-generation identity, size, modification time, content fingerprint, parser version, last successful scan, scan status, and safe issue code.
- Run fields: `run_id`, `dataset_id`, start/end, status, discovered/processed/failed file counts, committed revision, and issue counts.
- File modification time is an optimization, not event time or proof that historical data is irrelevant. Initial imports and explicit backfills must not skip old files based only on a requested dashboard period.
- Track replacement/truncation separately from append. The same pathname can refer to a new file generation.

### `source_observations` and `event_sources`

- Observation fields: `observation_id`, `file_id`, file generation, line/offset, provider, provider conversation ID, event timestamp nullable, observation kind, provider message/request/turn IDs nullable, cumulative or message counters, model, effort/source, safe metadata-quality flags, and parser version.
- Only retain allowlisted metadata. Do not persist entire source lines or raw payload JSON that may contain prompt content.
- Observation uniqueness is source-position-based within a file generation. It does not deduplicate usage across copied files.
- If a provider conversation ID is missing, a source-local surrogate may preserve observations, but mark its identity as weak. Do not merge unrelated files by basename or claim cross-copy deduplication; ambiguous contributions need an explicit exclusion/coverage policy.
- `event_sources` links accepted canonical `event_id` values to contributing observations. Multiple copies may support one canonical event.
- Preserve enough counter and sequence evidence for reconciliation; a flattened `Record` alone loses that evidence.

### `projects`

- Primary key: `project_id`.
- Fields: `dataset_id`, `installation_id`, path identity, original display path, display name, identity kind (`path`, `source_label`, `unknown`), created/updated timestamps.
- Normalize Windows path separators and case for Windows path identity without resolving arbitrary user-supplied paths or merging folders by basename.
- Existing Claude fallback labels may be folder names rather than trustworthy full paths. Mark them `source_label`; do not invent a full path.
- Unknown projects remain visible and are not collapsed into an unrelated known project. Project counts exclude the unknown bucket and report its record count separately.
- Optional aliases map multiple explicit identities to one logical project only after a user decision. Keep that separate from automatic normalization.

### `conversations`

- Primary key: `conversation_id`, opaque internal ID.
- Proposed local uniqueness: `(dataset_id, installation_id, provider, provider_conversation_id)`.
- Fields: provider, original provider conversation ID, first/last accepted usage timestamps, nullable verified account reference, and optional provenance flags.
- Do not use a shortened displayed ID, model, effort, or project name as identity. A conversation can contain different models/effort values and potentially different project attribution over time.
- Keep project on each event; derive a conversation's project set from its events. Where a list row needs one label, show its sole project or `Multiple projects`.
- A database containing multiple installations must preserve installation/source namespaces unless a later sync policy explicitly reconciles them.

### `usage_events`

- Primary key: `event_id`, opaque reconciliation-assigned ID.
- Foreign keys: dataset, conversation, project nullable.
- Required fields: provider, `occurred_at`, exact model string (including `unknown`), effort string, effort source, five token categories, parser version, reconciliation version, source kind, and quality status.
- Optional fields: provider turn/message/request IDs, reasoning tokens, epoch reference, request-context token count, and request-context evidence type.
- `source_kind`: `codex_cumulative_delta`, `codex_last_usage`, or `claude_message`.
- `total_tokens` is derived or maintained with a checked invariant. Reasoning must be null or between zero and output inclusive.
- Do not use `(conversation, cumulative counters)` alone as the event's uniqueness key: resets can repeat counters.
- Do not use `(file, line)` as global usage identity: copied files must not multiply usage.
- Canonical identity must be independent of file enumeration order. When a corrected reconciliation changes event decomposition, publish a new usage revision and invalidate old cursors/details rather than pretending every old event ID remains valid.

### `ingestion_issues`

- Fields: issue ID, dataset/run/file/conversation references where known, stable issue code, severity, safe explanation, affected interval nullable, and detection/resolution timestamps.
- Initial codes: `missing_root`, `unreadable_file`, `malformed_record`, `missing_message_id`, `invalid_timestamp`, `counter_reset`, `overlap_conflict`, `cache_exceeds_input`, `legacy_cache_ttl_assumed`, and `partial_counter_metadata`.
- Unknown skipped token amounts remain null. Never invent the missing-token count from a warning count.
- Do not sum per-record coverage counts with per-file counts as one generic percentage.

### `price_catalogs`, `model_rates`, and `event_valuations`

- Catalog fields: catalog ID/version, policy version, source description, checked date, created timestamp, and immutable override snapshot.
- Rate fields: exact model key, currency (`USD` initially), rates for each token category per million, optional tier threshold and high-context rates, source reference, and custom/bundled status.
- Valuation uniqueness: `(event_id, pricing_version)`.
- Valuation fields: amount nullable, state (`priced` or `unpriced`), applied rate reference, tier selection, assumption flags, and computation version.
- D03 implementation handoff: [applied pricing explanation contract](d03-applied-pricing.md) defines frozen event evidence and bounded mixed-rate previews. Existing event amounts retain twelve-place rounding; unrounded explanation charges/adjustments use up to eighteen fractional digits to reconcile exactly. No competing storage schema is introduced.
- Store money/rates as exact decimals. Proposed scale: 12 fractional USD digits, rounding half-even once per event valuation; sum those persisted values and round only for display. The compatibility test must allow at most that per-event quantization difference from existing float estimates.
- On SQLite, use validated decimal text with Python `Decimal` calculations or a documented scaled-integer design; do not assume a `DECIMAL` declaration gives exact decimal arithmetic. On engines with exact numeric types, use a bounded exact numeric type.
- Require safe bounds on counts and money. Reject overflow; do not silently truncate.
- Exact aggregation and sorting are part of the query contract. SQLite decimal text cannot be summed or ordered lexically, or cast to binary float for authoritative totals. For the initial modest dataset, use Python `Decimal` to aggregate/filter/sort and page the exact result with stable-ID ties, then measure it. A scaled-integer SQL optimization requires documented bounds and equivalence tests first.

### `provider_checks`, `quota_snapshots`, and `quota_windows`

- Check fields: check ID, dataset, provider, attempted/completed timestamps, success/error category, safe message, and next eligible check timestamp.
- Snapshot fields: snapshot ID, dataset, provider, successful check timestamp, account scope, nullable verified account reference, availability status, and safe provider note.
- Window fields: window ID, snapshot ID, source bucket/window key where available, display label, used percentage, duration minutes nullable, and reset instant nullable.
- Store all windows returned by a provider. Do not assume exactly two or aggregate their percentages.
- Existing `Window` retains a display label but not every stable source key. Enrich the adapter contract if stable cross-snapshot window matching is required; do not infer identity from array position.
- Codex's blocked-usage signal currently becomes a note. Add a structured `ordinary_usage_allowed` nullable boolean while preserving the note; null means not supplied.
- History starts when snapshots are actually collected. Failed checks do not create invented quota readings.
- Latest-state limits are first-release scope. Historical snapshot retention/charts are a later opt-in capability with an explicit start date and retention setting; do not silently enable indefinite history simply because these entities exist.

### `settings` and `usage_revisions`

- Settings: singleton or namespace-scoped configuration version, timezone, density, theme, monthly fees per provider, approved root references, active price catalog, and update timestamp.
- Initial fees may follow current defaults, but must be labeled configurable. Validate finite nonnegative values; null means not configured.
- Revisions: monotonic committed usage revision, dataset, committed timestamp, run reference, parser/reconciliation versions, and status.
- Related rows and aggregates become visible together at commit. If derived aggregates are cached, key them by full normalized query plus usage revision plus pricing version.

### Indexes and lifecycle

- Index events by dataset/time, dataset/provider/time, conversation/time/event ID, project/time, and model/effort/time according to measured query patterns.
- Index observations by provider/conversation and source file generation; enforce provider message/request identity through reconciliation rather than treating every observation as usage.
- Enable foreign-key enforcement. Dataset deletion removes its dependents transactionally; deleting one copied source file must not delete events still supported by another source.
- File disappearance or disabled roots should retain last accepted data with a visible stale/retained-source status until explicit rebuild/removal. An explicit authoritative rebuild can remove unsupported events and must publish a new revision.
- Define backup, migration, and retention behavior before release. Retention must never silently shorten the dashboard's advertised history.
- For the proposed local SQLite implementation, enable foreign keys on every connection, serialize writers, use bounded busy timeouts, and read related aggregates within a consistent transaction. Keep the database on a local application-data path; do not put a writable SQLite file in a network/sync folder.
- Version migrations and back up with a database-consistent method before upgrade. On failure, preserve the original database and show recovery guidance. A newer unsupported schema must fail clearly rather than being overwritten. The index is rebuildable; saved fees, roots, and rate overrides need a separate recoverable configuration export/backup.
- Before first release, document storage growth and retention for observations, issues, checks, and generated reports. Retain the counter/provenance metadata needed to rebuild advertised history. Removing a root from collection is distinct from explicitly deleting its retained history.

## 6. Import and reconciliation rules

### Codex

1. Gather observations for the whole affected conversation, including observations from unchanged overlapping files.
2. Establish ordering using source sequence, timestamps, session creation/fork metadata, and counter evidence. Timestamp alone is insufficient when records share a timestamp.
3. Identify equivalent observations across copies and distinguish counter-reset epochs. Do not hash only the cumulative numeric tuple.
4. Derive nonnegative deltas within an unambiguous epoch. Exclude and flag ambiguous reset transitions.
5. Seed fork counters from inherited pre-fork observations, but do not count inherited work as new fork usage.
6. Attribute model and effort using the corresponding recorded context. A context change without new token usage does not relabel historical usage.
7. Where no cumulative counters exist, use the existing last-usage fallback with an explicit weaker-deduplication flag. Do not claim strong request identity when it is absent.
8. If copies conflict and evidence cannot resolve them, publish an issue and exclude the ambiguous contribution. Never choose a convenient largest sum silently.

The exact canonical sequence algorithm requires a focused implementation design and fixture review. Preserve observations now so that a better reconciliation can rebuild events later without requiring prompt-content storage.

### Claude

1. Group streamed observations by provider conversation ID, message ID, and request ID where available, following the current reader's identity semantics.
2. Keep maxima per token category for repeated updates; do not add stream chunks.
3. Attribute the accepted event to the final recorded response timestamp and preserve explicit message effort or recorded turn fallback.
4. New user turns reset inherited effort when no new effort was recorded. Thinking budgets do not imply an effort label.
5. Missing message identity produces a coverage issue; do not manufacture an identity that silently double-counts copies.

### Transaction and recovery

- First version: full reparse of changed files and reconciliation of all affected conversations. Optimize append-only reading only after correctness fixtures pass.
- Stage work, then replace affected canonical events/source links and update the committed revision atomically. A failed run keeps the previous committed dataset queryable.
- Valuations must be ready for the published usage/pricing revision or the API must report `building`; never present missing computation as unpriced usage.
- Reimporting an unchanged source is idempotent. Rotation, truncation, copied files, parser upgrades, and interrupted imports must have explicit fixtures.
- A scan status and a provider connection status are separate. Usage remains available when live authentication fails.
- Parse a consistent file prefix: capture a file generation and byte boundary, ignore an incomplete final JSONL line until the next scan, and detect replacement/truncation while reading. An actively appended log is normal, not automatically a malformed-file error. Do not publish deltas derived from a mixture of file generations.
- A corrupt/unreadable file must not silently replace previously accepted observations with an empty set. Retain the last accepted contribution as stale, mark the issue, and retry; explicit authoritative removal/rebuild is a distinct user action with its own revision semantics. Well-formed records around a malformed complete line may be accepted only with a visible partial-source issue.
- Source metadata and absence of content must be verified at the extraction boundary. Parsing JSONL necessarily reads lines that may contain conversation text; the guarantee is allowlisted metadata extraction and no content persistence/exposure, not that the source bytes are never read.

## 7. Proposed API and input contract

Use `/api/v1` for the proposed local API. Python remains responsible for collection/accounting. Framework and database engine remain implementation decisions.

Implementation checkpoint, October 24: [S12](s12-local-api.md) implements the explicit production local service against S11 SQLite, with [OpenAPI](api/usage-hub-v1.openapi.json), [response schema](api/usage-hub-v1.schema.json) and [synthetic response fixtures](api/usage-hub-v1.fixtures.json). Those files pin the implemented first-release shapes/session-resume addition; the reviewed dashboard still requires S13 adaptation. The original proposal below retains semantic ownership and historical planning context.

### Shared query input

The client owns one serializable query state:

```json
{
  "dataset_id": "demo-local",
  "providers": ["codex", "claude"],
  "range": {
    "preset": "today",
    "timezone": "America/Los_Angeles"
  },
  "project_ids": [],
  "models": [],
  "efforts": [],
  "search": "",
  "view": "conversations",
  "sort": "value_desc",
  "page_size": 50
}
```

- API provider values are lowercase `codex` and `claude`; adapt existing Python display strings `Codex`/`Claude` explicitly. Both is the two-value selection, not a third provider.
- Empty provider selection is invalid. Empty project/model/effort arrays mean no restriction.
- Initial presets are `today`, `week`, and `month`. Custom ranges are a later extension unless explicitly scheduled; reject unsupported presets rather than ignoring them.
- For GET requests, flatten fields: `dataset_id`, repeated `provider`, `period`, `timezone`, repeated `project_id`, repeated `model`, repeated `effort`, `q`, `selected_day`, `sort`, `page_size`, and optional `cursor`, `query_context_id`, or `base_query_context_id` as defined below. The nested object above is client state, not a JSON GET body. `view` chooses an endpoint and is not an accounting filter.
- A first `/overview` or Explore request resolves the preset and returns `query_context_id` plus `range` (resolved UTC bounds/timezone/preset), `usage_revision`, `pricing_version`, and `configuration_version`. The context binds dataset, normalized accounting filters, range, and versions; it does not imply that old database snapshots are retained. Follow-up requests use it so later clock ticks cannot shift the period. Facets and conversation details derive their documented subquery from that context, preserving its range/versions.
- A preset/timezone/filter change starts a new context and clears pagination. Filter-only changes and drill-downs inherit the existing resolved base range; only a preset/timezone change or explicit Refresh captures a new clock boundary. A view or sort change preserves the resolved accounting context but clears the cursor. Reject conflicting explicit filters and context fields with 422; never silently favor one. Refresh replaces related widgets together.
- Define context derivation explicitly: accept `base_query_context_id` with replacement filter fields for a new context, keeping its range/versions. This differs from `query_context_id`, which requests the existing query unchanged. Do not accept both fields together. A stale base returns 409 and requires a coordinated refresh.
- Filters across categories combine with AND; selected values within a category combine with OR.
- Search is a bounded, case-insensitive literal substring over metadata: full provider conversation ID, project display path/name, and exact model string. No regex, SQL syntax, or prompt search. Proposed maximum: 200 characters after trimming.
- Provider and model/effort matching use explicit known keys, not substring identity. Validate project IDs within the selected dataset.
- Changing provider/date/filter/search/sort clears the page cursor. Changing list view preserves filters.
- Default sort: exact priced subtotal descending, unpriced-only rows after rows with priced contributions; ties break by stable ID. This ranks recorded priced contributions, not a bound on unknown value. Other sorts: `tokens_desc`, `last_activity_desc`. Surface incomplete pricing in each row. Event detail defaults to `(occurred_at, event_id)` ascending and uses that stable chronological cursor.
- Page size: default 50, range 1–100. Cursor binds to query context, endpoint, sort, page size, and last exact sort key/ID. Treat it as an opaque validated token, not executable SQL or a raw client-chosen offset. Reject malformed/tampered cursors. Summaries cover the full matched result, never only the current page.
- Search typing uses a short debounce and cancels/ignores obsolete responses. An older response must not overwrite a newer query state.

### Response conventions

- Every successful response includes `contract_version`, `dataset_id`, `mode`, `generated_at`, and request ID. Usage responses also include `query_context_id`, committed `usage_revision`, `pricing_version`, `configuration_version`, effective UTC range/timezone, and normalized applied filters. Settings responses contain their configuration version; limits contain their own successful-snapshot/check timestamps and are not frozen by a usage query context.
- UTC instants are ISO 8601 strings with `Z`. Optional unavailable fields are explicitly null.
- Internal token counters use checked 64-bit integers. API token quantities are base-10 integer strings, avoiding JavaScript precision loss. UI code must not coerce them through `Number` before exact summation/comparison.
- USD amounts and rates are decimal strings, never binary floats in the contract. Percentages are finite JSON numbers. Small bounded row counts/page sizes may be JSON integers.
- Internal IDs are opaque strings; the UI must not derive database identity from a displayed label or a Figma node ID.
- Error shape: `error.code`, safe `error.message`, optional `field_errors`, optional `retry_at`, and `request_id`. Do not return raw exceptions, SQL, paths to credential files, or provider response bodies.
- Invalid input returns 422; unknown IDs return 404; configuration conflicts or stale revisions/cursors return 409; cooldown returns 429 with retry metadata. A provider being offline does not make cached usage routes fail.
- Revisions need only retain the current consistent queryable dataset initially. If a requested revision was replaced, return 409 `revision_changed`; the client reloads related widgets together. Historical snapshot retention is an optional later optimization.
- Publish an initial machine-readable schema/OpenAPI contract and JSON fixture set during Phase A. This Markdown supplies semantics; it is not a substitute for schema validation. Bound array lengths, metadata lengths, query work, and response size; return field errors instead of silently truncating a request.

### Read endpoints and their outputs

- `GET /status`: build/contract versions, indexing state, committed revision, source coverage summary, provider check states, active job IDs, and configuration version. This powers connection badges and first-run recovery.
- `GET /overview`: summary, daily series, provider breakdown, model/effort rows, top projects, and recent conversations under one query/revision. This prevents cards and charts from disagreeing.
- `GET /usage/conversations`: filtered paginated conversation aggregates with matched-period totals, project set, model set, effort set, last matched activity, and next cursor.
- `GET /usage/projects`: filtered project aggregates and conversation counts. Selecting a project keeps the query and adds its stable project ID.
- `GET /usage/facets`: available project/model/effort choices and counts. For each facet, apply all other filters but omit that facet's own selection when calculating its options; retain selected zero-match options so they can be cleared.
- `GET /conversations/{id}`: identity, full-lifetime first/last recorded usage labeled as lifetime, matched-query summary, coverage, and token/value breakdown. Clearly distinguish lifetime metadata from filtered totals.
- `GET /conversations/{id}/events`: paginated accepted usage events under the same filters/revision. Show event metadata and valuation provenance; no transcript content.
- `GET /limits`: cached provider states, latest successful snapshots, every returned quota window, last attempt/success timestamps, cooldown, and structured blocked-usage status.
- `GET /settings`: sanitized editable settings, validation bounds, and configuration version. It must never return CLI credentials.
- `GET /jobs/{id}`: operation kind, `queued|running|succeeded|failed|superseded`, start/completion timestamps, phase, work counts, safe issue code/message, and resulting versions. Reindex/repricing/settings callers use this to distinguish persisted settings from usable recomputed results. Keep completed states long enough for a restarted client to discover the outcome; cancellation is deferred.

Project detail initially reuses Overview/Explore with `project_id`; no dedicated project-detail API is necessary. For chart selection, add an optional `selected_day` (`YYYY-MM-DD`) to the shared query. Resolve its local midnight boundaries in the context's timezone and intersect them with the frozen preset range. Reject days outside that range; an empty valid intersection is an empty result. Return the effective range and visible day filter. This bounded day filter is first-release scope; arbitrary custom ranges remain deferred. Clear comparison whenever a day is selected.

### Mutation endpoints

- `POST /limits/refresh`: input selected providers; output per-provider accepted/in-progress/cooldown results, check IDs where known, and next eligible times. It respects shared ownership/locks and backoff. Return 202 for accepted work, 200 for existing in-progress work, and 429 only when all selected providers are cooling down; a mixed result must explain each provider independently.
- `POST /index/refresh`: input approved root IDs or all enabled roots; output run/job ID/status. Return 202 for accepted work or 200 with the coalesced current job. No arbitrary path or shell execution parameter. Queue importer and repricer writes through the same owner.
- `PATCH /settings`: input expected configuration version plus allowed changes; output new version, persisted values, and any queued reindex/repricing job IDs. Reject the whole draft on validation/version failure. Distinguish saved configuration from an active pricing dataset: continue serving the last complete pricing version, visibly marked pending, until the new valuations publish atomically. Repeated submissions must not enqueue duplicate equivalent work.

The proposed local service binds to loopback and serves UI/API from one origin. Use an explicit Host allowlist, reject foreign browser Origins, and do not enable permissive CORS. Protect read access as well as mutations: project paths and activity are private metadata. Bootstrap a short-lived local session through an explicit application launch handoff, exchange it for an HttpOnly same-origin cookie, and require an anti-CSRF token plus Origin checks for mutations. Never use a long-lived secret in a URL/query, frontend bundle, logs, or localStorage. Define browser cookie/launch behavior in the backend design and test it on Windows before release. Credentials remain with the local adapters. Remote database deployment or access from another device needs a separate transport/authentication design.

Treat model names, paths, IDs, and error metadata as untrusted display text. Escape HTML, avoid raw-HTML rendering, and strip terminal control sequences in text output. Log only redacted operation IDs/codes/counts by default. The proposed same-origin boundary must be tested against hostile web origins, invalid Hosts, cross-site mutations, and unauthenticated reads rather than assuming loopback implies authentication.

## 8. Concrete output examples for database alignment

All values below are synthetic contract examples. They are not live readings, verified current model prices, or the full Figma demo dataset. IDs are illustrative. The two events share one known project and use two distinct conversations.

### Canonical event after reconciliation

This is the proposed DTO produced from persisted canonical facts plus one selected valuation:

```json
{
  "event_id": "evt-demo-codex-001",
  "dataset_id": "demo-local",
  "provider": "codex",
  "conversation_id": "conv-demo-codex-001",
  "provider_conversation_id": "demo-codex-session",
  "project_id": "project-demo-001",
  "occurred_at": "2026-10-23T12:00:00Z",
  "model": "fixture-codex-model",
  "effort": "high",
  "effort_source": "fixture explicit metadata",
  "turn_id": null,
  "source_kind": "codex_cumulative_delta",
  "tokens": {
    "uncached_input_tokens": "10000",
    "output_tokens": "1830000",
    "cache_read_tokens": "1000000",
    "cache_write_5m_tokens": "0",
    "cache_write_1h_tokens": "0",
    "reasoning_tokens": "1260000",
    "total_tokens": "2840000"
  },
  "valuation": {
    "pricing_version": "fixture-prices-v1",
    "state": "priced",
    "amount_usd": "18.420000000000",
    "rate_id": "fixture-rate-codex",
    "tier": "standard",
    "assumptions": []
  },
  "quality": {
    "status": "accepted",
    "issue_codes": [],
    "request_context_evidence": "unavailable"
  }
}
```

Synthetic rates per million: uncached input `2`, output `10`, cache read `0.1`. No tier rule in this fixture. Calculation: `0.02 + 18.30 + 0.10 = 18.42`. Reasoning contributes no additional cost or total tokens.

A second Claude fixture event at `2026-10-23T13:00:00Z` has uncached input `10000`, output `20000`, cache read `30000`, 5-minute cache write `5000`, 1-hour cache write `0`, and reasoning null. Total: `65000`. With synthetic rates `4`, `20`, `0.2`, `5`, and `8`, its value is `0.471000000000` USD.

### Overview summary projection

The following summary is a projection inside the `/overview` envelope; chart/group/list fields are omitted from this example for readability:

```json
{
  "contract_version": "1.0",
  "dataset_id": "demo-local",
  "mode": "demo",
  "request_id": "request-demo-001",
  "generated_at": "2026-10-23T14:00:00Z",
  "usage_revision": "revision-demo-1",
  "pricing_version": "fixture-prices-v1",
  "configuration_version": "config-demo-1",
  "query_context_id": "query-demo-today-1",
  "range": {
    "start_at": "2026-10-23T07:00:00Z",
    "end_at": "2026-10-23T14:00:00Z",
    "timezone": "America/Los_Angeles",
    "preset": "today"
  },
  "applied_filters": {
    "providers": ["codex", "claude"],
    "project_ids": [],
    "models": [],
    "efforts": [],
    "search": ""
  },
  "summary": {
    "total_tokens": "2905000",
    "conversation_count": 2,
    "project_count": 1,
    "unknown_project_record_count": 0,
    "value": {
      "state": "complete",
      "amount_usd": "18.891000000000",
      "priced_record_count": 2,
      "unpriced_record_count": 0,
      "priced_tokens": "2905000",
      "unpriced_tokens": "0"
    },
    "reasoning": {
      "known_tokens": "1260000",
      "known_record_count": 1,
      "unknown_record_count": 1
    },
    "plan_comparison": {
      "state": "unavailable",
      "reason": "period_not_month_to_date"
    }
  },
  "coverage": {
    "scope": "local_logs",
    "account_scope": "all_local_accounts_unmatched",
    "index_status": "ready",
    "last_successful_scan_at": "2026-10-23T13:59:00Z",
    "missing_root_count": 0,
    "unreadable_file_count": 0,
    "skipped_interval_count": 0,
    "skipped_tokens": null,
    "issue_codes": []
  }
}
```

Aggregate value states:

- `complete`: at least one record and all are priced; amount may legitimately be zero if configured rates are zero.
- `partial`: some records priced and some unpriced; amount is the priced subtotal.
- `unpriced`: records exist but none priced; amount is null.
- `empty`: no matched records; amount is null, with zero matched token totals.

These states describe pricing coverage, not complete account coverage or flawless ingestion. A `complete` valuation may coexist with ingestion issues that must remain visible.

Minimum fixture assertions: Both returns `2905000` tokens and `18.891000000000` USD; Codex returns `2840000` and `18.420000000000`; Claude returns `65000` and `0.471000000000`; conversation count is 2 for Both and 1 for either provider; project count stays 1. Clearing a provider filter restores the Both results.

Required companion fixtures: add an unpriced event to produce `partial` with the same priced subtotal; query only that event to produce `unpriced`/null; query an empty range to produce `empty`/null; and apply a zero-rate catalog to produce `complete`/zero. A separate month-to-date case with the same two events and configured fees of `20.00` each must yield signed differences Codex `-1.580000000000`, Claude `-19.529000000000`, and Both `-21.109000000000`. Use decimal assertions, not rounded display strings. Changing to Today, selecting a day/project/model/effort, or searching makes the plan comparison unavailable with a specific reason.

## 9. UI controls connected to data and actions

### Overview

- Both / Codex / Claude updates `providers` while preserving date and every compatible filter; request a new `/overview`. Update totals, chart, groups, and recent rows together.
- Date selector updates the shared range. A selected chart day adds a visible range chip; clearing it restores the prior range.
- Show local scope, last successful scan, price coverage, cache-read share, and any tier/counter assumptions next to the headline. A large token count must not read as the same number of newly generated tokens. Label output/reasoning and cache categories in the value explanation.
- Chart metric toggle switches between returned token and value series without changing their query scope.
- Model/effort row opens Explore with both model and effort plus its provider preserved.
- Project row opens Explore with the stable project ID. Provider-specific links preserve that provider.
- Conversation row opens the matching internal conversation ID with the originating query and scroll position saved.
- Limits teaser opens Limits with the provider context where relevant. It does not manufacture date-filtered live quotas.

### Explore and conversation detail

- Conversations / Projects changes the grouping endpoint, preserving all filters.
- Provider controls remain within Explore. They must not navigate back to Overview.
- Project/model/effort menus come from `/usage/facets`; removable chips expose the selected keys.
- Metadata search filters rows and totals consistently. Empty search results retain the query and provide Clear filters.
- Next requests the returned cursor. Previous uses a client cursor stack. Both are disabled when no corresponding page exists.
- Every enabled conversation row opens matching details, not the same sample conversation.
- Detail token categories and event rows reconcile to that conversation's matched-period total. Lifetime first/last timestamps have explicit labels.
- Back restores provider/date/search/view/sort/cursor and list position. If the revision has changed, refresh safely and explain that results changed.
- Copy ID/path acts on full original metadata. In Figma, show a copy-feedback simulation; real clipboard behavior belongs to application implementation.

### Limits

- Render `/limits` cached state, all windows, active-account scope, last success/attempt, and next eligible check.
- Refresh uses `/limits/refresh`; disable or explain cooldown/in-progress state.
- When a reset timestamp passes, show `Awaiting refreshed limit` until a successful new snapshot arrives.
- `View recorded usage` opens Explore with the provider selected and the user's last report range. It must not imply account matching.
- Remove the report date selector from the live Limits screen. A future history view would need its own explicit date context.

### Settings and shared interactions

- Settings uses draft / Save / Cancel, validation errors, saving, saved, and conflict states.
- Use a read-only label for a setting without an approved alternate state. Do not present an inert selected-looking setting as an enabled toggle.
- Remove irrelevant report date controls from Settings.
- Search shortcut opens/focuses metadata search; shortcuts button opens a real help overlay. Escape closes overlays and returns focus to the trigger.
- In the application, support Tab/Shift+Tab, visible focus, Enter/Space activation, and arrow keys in composite selectors. Add `/` for search only outside text inputs. Document shortcuts rather than overriding browser defaults.
- Mobile navigation stays on mobile-width destinations, including provider states, Explore, details, Limits, and Settings.
- Loading, empty, partial, stale, unavailable, and error states use the same domain semantics on desktop and mobile.
- The first release uses one dark compact appearance. Additional theme/density controls remain read-only or absent until implemented; they are not prerequisites for usable accounting. Narrow desktop layouts and keyboard access are release gates; a complete mobile prototype can follow the first vertical slice.

## 10. Specific Figma repair backlog

Design file: [AI Usage Hub — Developer Console](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh).

Screens recorded in the supplied plan: Overview `2:43`, Explore `2:44`, conversation `2:45`, Limits `2:46`, Settings `2:47`, mobile Overview `2:48`, and Codex Overview `2:49`. Treat these node IDs as inspection starting points before future edits.

Evidence boundary: these locations and reported interaction defects come from the supplied plan, not a new Figma inspection in this refinement. Before editing, inspect the current design and record which issues still reproduce. Preserve useful completed work; stale node IDs or already-fixed links must not create a replacement backlog by assumption.

### Priority 1: provider selection and navigation context

- Wire Overview Claude `4:343` and filtered Overview Claude `9:218` to a coherent Claude state.
- Repair Explore Both `6:84` and Codex `6:86`, which currently leave Explore; wire Claude `6:88` within Explore.
- Repair Codex inspect link `9:353` to preserve its provider.
- Repair model rows `10:190`, `10:197`, `10:204`, `10:211`, `9:338`, and `9:345` to preserve the labeled model/effort/provider filters.
- Repair project drill-downs and Limits provider links `8:218` and `8:249` to retain their project/provider context.

### Priority 2: complete Explore and details

- Add metadata search behavior/examples for header search `6:72` and field `6:93`.
- Add Project `6:99`, Model `6:101`, and Effort `6:103` menus, selected chips, and clear states.
- Add Projects view `6:110` and Next-page state `6:191`.
- Add matching details for rows `6:140`, `6:149`, `6:158`, `6:167`, and `6:176`; validate first row `6:131` too.
- Repair Back `7:143` to restore the originating filtered Explore state.
- Include an intentional no-results state and disabled pagination at boundaries.

### Priority 3: shared controls, settings, mobile, and polish

- Add date menus for `4:336`, `6:81`, `7:141`, and `9:211` with supported presets. Remove the irrelevant date controls `8:183` and `8:337` from Limits and Settings.
- Replace settings shortcut button `8:316` behavior with a help overlay; make other shortcut triggers consistent.
- Add reversible Settings drafts, Save/Cancel, and validation examples for approved editable fields.
- Replace mobile routes `9:391`, `9:393`, `9:448`, `9:453`, `9:456`, `9:458`, and `9:460` with mobile-width destinations.
- Resolve the Overview's small bottom overflow; inspect desktop/narrow/mobile clipping and readable focus/selection states.
- Document intentionally disabled/selected controls and distinguish them from controls with missing actions.

Build a control inventory during the repair with: screen, node/control name, action, resulting state, preserved filters, loading/disabled behavior, keyboard behavior, and validation result. Completion means every enabled-looking control has its labeled action or a clearly stated preview limitation.

Figma is a scripted design review, so representative search queries, pagination, and settings outcomes may use prebuilt states. Arbitrary typing, real persistence, clipboard access, and full browser keyboard behavior must be validated in the implemented app. Do not claim Figma proves those runtime behaviors.

## 11. Work sequence and handoff points

Dependency order: Phase A establishes the contract; B (representative design) and C (accounting/ingestion) may then proceed independently. D depends on the relevant C invariants and can use fixture-backed handlers while ingestion matures. E integrates only reviewed flows against D. F is a packaged release gate. Use this order to deliver a thin working path rather than completing every schema/UI feature before integration.

### First release versus later work

First release includes correct Codex/Claude reconciliation, local storage/settings, month-to-date/Today/Last 7 days, provider and metadata filtering, Overview, conversation list/detail/Back, value provenance/coverage, $20/$20 fee comparison, cached Limits, explicit refresh, and an explicit tray-to-dashboard launch. Preserve terminal reports with shared accounting. Use one theme/density; settings need only the fees, source roots, and rate configuration actually supported by the contract. Ship pricing provenance before a rich rate editor.

Later work includes a richer Projects presentation beyond a project filter, arbitrary custom ranges, historical quota charts, additional themes/densities, a complete phone flow, a command palette, and exports beyond existing reports. Keep their design notes, but do not expose enabled controls ahead of supported behavior. The contract can reserve their endpoints/entities without requiring all of them in the first migration or UI.

### Phase A — Contract alignment; database and design can then proceed separately

Owner: database developer with dashboard/collector review.

- Confirm database engine, local versus remote placement, existing schema names, migration conventions, and decimal/time representations.
- Map existing entities to sections 3–7; retain source observations and canonical events as separate responsibilities.
- Agree enum spelling, IDs/namespaces, unknown values, revision behavior, and pricing policy.
- Prepare the two-event synthetic fixture and additional partial/unpriced/empty states.
- Write typed observation/event/query/coverage DTOs and schema-validated example responses. Specify the frozen query context, fee versions, async job lifecycle, authentication bootstrap, and shared-process ownership before frontend integration.
- Record decisions and deviations in this document before implementation diverges.

Exit: the database developer can identify where every first-release event field is stored and the UI developer can consume a validated example without raw logs. Assign responsibility by role even if one developer implements every layer; no external team or database owner is presumed.

### Phase B — Figma repair and user review

Owner: design work.

- Execute section 10 in priority order using native editable Figma layers.
- Use one coherent demo fixture across provider states and drill-downs; rebuild demo summaries where needed rather than mixing unrelated totals.
- Review first-release Both/Codex/Claude, filters, search examples, details/Back, pagination, fee settings, limits, and keyboard affordances. Track mobile/additional preferences as the later backlog instead of blocking accounting work on every frame.

Exit: user can review a complete representative flow and every remaining prototype limitation is explicit. No production app changes are required for this phase.

### Phase C — Reconciliation and database ingestion

Owner: collector/database work after the contract is agreed.

- Add the overlap/reset regressions and define canonical epoch/observation reconciliation.
- Implement migrations, metadata-only observation storage, transactional canonical-event updates, coverage issues, and usage revisions.
- Add versioned event valuations without changing canonical tokens when rates change.
- Demonstrate idempotent import, copied-file independence, reset handling, restart recovery, and backfill correctness.
- Preserve reset/overlap/fork evidence in the fixtures. Parser output equality is not always the oracle: where the current reader has a documented bug, assert the intended invariant and record the deliberate compatibility change.

Exit: fixture totals and coverage are correct independent of file order and import repetition. Existing tray/report behavior still works. Do not import real histories until the fixture path is sound.

### Phase D — Query service and shared provider scheduler

Owner: backend integration.

- Implement validated queries and response envelopes with the agreed precision and range rules.
- Extract GUI-independent polling state from the tray into a shared service; avoid importing tray GUI dependencies into API accounting.
- Enforce one scheduler/writer across two application launches as well as multiple tabs. Add `/jobs/{id}`, context/version conflicts, one consistent-read boundary, and exact decimal sorting/pagination.
- Keep cached usage routes available through quota failures and route reads independent of network polling.
- Implement settings version checks, reindex/repricing jobs, and sanitized errors.

Exit: API fixtures match the database and report compatibility checks; provider failures do not block unrelated usage queries.

### Phase E — Approved dashboard implementation

Owner: frontend integration, after Figma approval.

- Build the approved screens against the stable DTOs, initially with the same labeled fixtures.
- Use shared URL/query state and one navigation-return contract.
- Wire API results, discard obsolete requests, handle revision changes, and add keyboard/focus behavior.
- Ensure every enabled UI control corresponds to an implemented action and supported backend contract.
- Complete one end-to-end month/provider → summary → conversation → Back path with seeded fixtures, then a controlled local import, before extending the remaining screens. Update the terminal consumer against the same summary service and compare its exact underlying results.

Exit: design flows work with real local data, and token/value totals reconcile through provider, project, model, conversation, and event drill-downs.

### Phase F — Windows delivery and acceptance

- Verify migrations/backups, local service startup, tray-to-dashboard launch, packaged frontend assets, and shutdown/restart behavior.
- Verify local authorization, safe exports if added, no credentials/content leakage, and independent provider cooldown behavior.
- Measure representative indexed query performance; initial target is under two seconds for Overview/Explore queries on the agreed local fixture, without waiting on provider network calls.
- Record tested history size and machine instead of claiming a universal performance guarantee.
- Test the packaged executable, not just Python: one first launch, second launch reuse, explicit dashboard opening, terminal report generation, frontend assets with network disconnected, correct timezone data, job recovery, and clean Quit. Bundle the IANA timezone database needed by Python on Windows; do not assume `ZoneInfo` data exists on every installation. Browser assets must be local, with no CDN dependency.
- After a controlled import, perform a sanitized real-log reconciliation check: inventory observed model keys, report priced/unpriced coverage and issues, and reconcile category/provider/detail totals. This validates internal consistency for available local logs; it does not certify complete provider-account usage.

## 12. Acceptance checklist

### Accounting and database

- [ ] Exact copies and partial overlapping copies do not change totals, regardless of file order.
- [ ] The `100, 200, 50, 100` reset fixture retains 250 after the ambiguous interval is excluded.
- [ ] Fork history, model changes, effort changes, streamed updates, missing IDs, and malformed records have explicit outcomes.
- [ ] Crash/retry/reindex does not duplicate accepted events or publish half-replaced data.
- [ ] Token category sum equals the total; reasoning is counted once.
- [ ] Unpriced, partial, empty, unknown metadata, and ingestion issues remain distinct.
- [ ] Repricing changes valuation version/results without changing canonical token facts.
- [ ] Daily groups, providers, and paginated full-result aggregates reconcile to the same query/revision.
- [ ] Two source enumeration orders, repeat import, and indexed/non-indexed consumers produce the same accepted usage under one reconciliation policy.
- [ ] An incomplete appended line, file replacement during read, unreadable changed file, and interrupted transaction preserve a coherent last committed result.
- [ ] Exact decimal aggregation, value ordering, ties, and page traversal remain correct beyond JavaScript's safe integer range and at documented count/money bounds.
- [ ] Root disable/removal, file disappearance, and retention have explicit visible behavior.

### API and UI

- [ ] Both/Codex/Claude works in Overview and Explore without unintended page changes.
- [ ] Provider/project/model/effort/date/search intersections affect all relevant widgets consistently.
- [ ] Detail and Back restore the originating query and position, including pagination.
- [ ] Every enabled conversation/project/model link opens its matching context.
- [ ] Cursor reuse after changed filters or revisions is rejected safely; the UI recovers.
- [ ] A clock advance between Overview, facets, pages, and details does not change their frozen range. Explicit Refresh creates a new context.
- [ ] Fee/timezone changes and repricing jobs cannot mix old values with new comparison/settings labels.
- [ ] Obsolete in-flight responses cannot overwrite newer filter results.
- [ ] DST, midnight, month boundaries, and the exclusive end boundary have fixtures.
- [ ] Limit states distinguish successful, stale, cooldown, login required, blocked, and unavailable readings.
- [ ] Settings Save/Cancel, validation, and concurrent configuration edits have clear outcomes.
- [ ] Keyboard-only use, focus return, and narrow desktop layouts work in the real browser. Mobile paths stay mobile when that later flow ships.
- [ ] Prompt content and credentials are absent from storage DTOs, API payloads, diagnostics, and any exports.
- [ ] Two app processes/tabs share one scheduler/writer; a quota failure does not block usage queries, and a cooldown cannot be bypassed by repeated launches.
- [ ] Job status survives client restart; a saved-but-repricing setting is never presented as fully active before publication.
- [ ] Host/Origin, unauthenticated reads, cross-site mutations, untrusted HTML/terminal metadata, and session bootstrap have executable checks.
- [ ] Packaged offline launch, timezone boundaries, terminal output, explicit web launch, migration failure/backup, and Quit/restart are verified on Windows.

Existing tests should be run with an available project interpreter, such as `windows/.venv/Scripts/python.exe`, rather than relying solely on the system Python launcher. During this refinement, all **57 existing tests passed** after using a writable workspace-local temporary directory; the sandbox's default temporary directory initially prevented fixture writes. The separate accounting probes still reproduce the two failures above. Passing the existing suite does not satisfy those missing regression gates or certify the proposed API/database/UI, which are not implemented.

Documentation checks also parsed all three JSON examples, verified token sums and exact decimal estimates/fee differences, and checked relative links/code fences. No application code, schema, executable, or Figma file was changed by this refinement.

## 13. Database developer handoff

The [local database mapping handoff](usage-hub-database-handoff.md) records October 24 discovery, the user's local-first direction, logical storage responsibilities, exact numeric/transaction rules, preview-to-v1 differences, and a [synthetic alignment fixture](fixtures/usage-hub-database-alignment.json). It is preparation for S11, not a physical schema, migration, or implemented API.

Before committing migrations, record these decisions:

1. Engine and placement: local index or remote service; existing schema/migration path.
2. Existing entities reused and proposed entities added; dataset/installation namespace policy.
3. Exact counter/decimal/time types and their overflow/rounding rules.
4. Observation provenance, canonical event identity, epoch reconciliation, and transaction boundary.
5. Price catalog/override versions, tier assumptions, and whether valuation is materialized or queried through a versioned calculation service.
6. Index revision/cursor invalidation, root deletion/retention, and migration/backup policy.
7. API field/name deviations from this proposed v1 contract and their adapter mapping.

Record an owner, chosen option, rationale, and acceptance evidence for each item. Recommended decisions where no existing implementation constrains them:

- **Placement/engine:** one local SQLite database per Windows user; use an adapter if an existing approved database must be retained. No remote collector uploads in this release.
- **Launch/product:** retain terminal as the existing default; add an explicit dashboard action. Keep one background owner rather than a second independently polling application.
- **Accounting:** observation-first reconciliation, explicit ambiguous-interval exclusions, current/configured rates, and visible request-tier assumptions. Decide the concrete epoch algorithm with fixtures before schema migrations make a weak key permanent.
- **Stack:** keep Python; proposed SQLite/FastAPI plus React/TypeScript for web delivery. Pin tested runtime/dependency versions at implementation time, including Windows timezone data; this planning revision does not assert current library versions.
- **Consistency/lifecycle:** exact decimal service aggregation initially, one committed read context, queued single-writer work, coalesced refresh, conservative retained-source policy, and versioned migration/backup recovery.

The implementation handoff should contain migrations, fixture seeds, a mapping from this plan's logical entities to the actual schema, sample route outputs, and reconciliation/contract test results. These are future deliverables, not files created by this planning task.

Deferred: hosted dashboard access, cross-device sync, automatic multi-account attribution, transcript search, live conversation-running status, agent conversation deep links, billing-cycle accounting, forecasts, and notifications. Each requires a separate data or behavior contract beyond the existing local collectors.

## 14. Related references

- [Original UX/UI and web build plan](usage-hub-plan.md): broad product direction; this document provides the more specific integration and interaction-repair contract.
- [Project evaluation](project-evaluation-2026-10-23.md): accounting evidence and runtime-review limits.
- [Accounting probes](review_accounting_probes.py): synthetic overlap/reset cases.
- [Figma design file](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh).
- [Figma desktop prototype](https://www.figma.com/proto/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-43&starting-point-node-id=2%3A43).

This is the current proposed handoff. Confirm the database choices in section 13, keep Figma repairs reviewable, and use the acceptance checklist before connecting the production interface to imported totals.

## 15. Confirmed token formatting and chart-axis rules

- Display token values below one million as comma-separated integers: `190,000`, not `190K`.
- Use `M` for millions and `B` for billions, with at most two decimal places and no trailing zeros: `2.84M`, `8.92M`, `5B`.
- Abbreviations are rounded presentation values. Keep exact integer counts in database fields, API contracts, calculations, and aggregation. Never replace a stored count with a string such as `2.84M`.
- Apply the display rule consistently to summary cards, model/project groups, conversation rows, token breakdowns, and token-axis labels.
- Both chart metrics require a visible Y-axis and horizontal gridlines. API value uses USD ticks; recorded tokens use the token formatting above.
- Start the Y-axis at zero. Choose a readable scale from the largest matched daily column, using the selected metric and filters; do not scale from the all-period summary total or reuse one numeric range for both units.
- Keep bar height proportional to its value and the labeled axis maximum. Zero-value bars are hidden rather than assigned an artificial minimum height.
- The revised Figma demo uses five equal grid intervals. Its default API-value axis is USD 0–50 and its token axis is 0–5M. Other provider/date/metadata filters select the appropriate smaller range.

See [the Figma test report](usage-hub-figma-test-report.md) for prototype validation and playback limits. This revision changes presentation, not the database/API token contract.
