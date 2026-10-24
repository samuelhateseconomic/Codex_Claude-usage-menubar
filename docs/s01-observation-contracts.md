# S01 observation and canonical-event contracts

Status: **complete in the isolated S01 worktree**. Integration into the concurrently changing original checkout is not included.

This session prepares the [S02 accounting fixes](project-refinement-plan.md) without changing the active legacy reconciliation policy. It follows the [S00 baseline](s00-baseline.md) and the [integration contract](usage-hub-integration-plan.md). No database, API, dashboard, configuration migration, or new pricing policy is introduced.

S02 now activates this extraction seam in the report readers; see the [reconciliation handoff](s02-reconciliation.md). The S01 behavior and results below are historical session evidence.

## Ownership and compatibility

S00 was committed as `854ac73`. During S01, concurrent work changed the shared checkout's readers, valuation, and dashboard files, including a call to an incompatible `reconcile_codex` contract. The first shared-checkout focused run passed 13 tests and failed one on that missing import. Those edits were preserved; this session did not overwrite the other implementation to make its tests pass.

S01 was reconstructed against `854ac73` in an isolated validation snapshot, then copied to this chat's managed `s01-observation-contracts` worktree. Claims below apply to that isolated implementation, not the concurrently changing original checkout. The original checkout may retain overlapping drafts; integrating the two versions requires one explicit owner and a reviewed contract mapping.

The existing reports continue using legacy readers in this worktree. `usage_reports.Record` and `usage_reports.Tokens` re-export the same classes now owned by [usage_records.py](../windows/usage_records.py). Shared timestamp/effort helpers moved to the observation module without changing legacy semantics. Physical-line extraction preserves the prior `lines()` interface.

## Pure domain boundary

[usage_observations.py](../windows/usage_observations.py) imports only the standard library and shared record types. It performs no filesystem/network/provider/GUI/pricing work. It accepts `(physical_line_number, parsed_object)` iterables and returns immutable metadata observations. File discovery and byte parsing stay in [usage_reports.py](../windows/usage_reports.py).

The new `read_observations(provider, roots, notices, since=None)` is the filesystem adapter. It projects parsed objects immediately and returns only allowlisted metadata. S02 can pass the resulting objects to reconciliation without GUI, valuation, or rendering dependencies. This is a parallel extraction seam until S02 replaces legacy acceptance; no new duplicate reconciler has been added.

### Counter evidence

`Counter` carries either a valid nonnegative integer, or a missing/invalid state with no retained raw value. These are distinct:

- Missing field: `value=None`, `state=missing`.
- Null, boolean, negative, float, string, or object counter: `value=None`, `state=invalid`.
- Observed zero: `value=0`, `state=valid`.

`Counters` also distinguishes absent, invalid, and present containers, including an empty present object with missing fields. Codex provider input remains inclusive of cached input in observation evidence; only accepted `Tokens.input` is uncached. Both cumulative and last-usage counters survive extraction independently.

Claude evidence retains uncached input, output, cache reads, detailed five-minute/hour writes, and legacy aggregate writes separately. Extraction does not sum legacy and detailed writes or assign an unrecorded TTL. S02/S04 must select the supported representation and label legacy assumptions.

Reasoning remains raw nullable counter evidence until acceptance. A numeric reasoning value greater than output is retained for diagnosis, not clamped or silently erased. `CanonicalEvent` rejects an accepted record with reasoning outside output. Neither reasoning nor effort adds a token category or invented price multiplier.

### Identity, sequence, and context

Each `Observation` carries:

- Provider, usage kind, parser version, event time/state, source reference, and metadata issue codes.
- Provider conversation ID when usable; message/request/turn IDs when supported explicit string fields exist.
- Model, project with path/source-label/unknown kind, and explicit effort/source.
- Codex session creation time, fork parent, session/context source references, cumulative/last counters, and context-window capacity.
- Claude per-message usage and user-turn context, including tool-result continuation and new-user reset behavior.

Supported ID fields are Codex session `payload.id`, context `turn_id`, usage `message_id`/`request_id`, fork `forked_from_id`/`forked_from_thread_id`; Claude `sessionId`, message `id`, `requestId`, and user `uuid`. Unsupported variants are not guessed. Missing/invalid Claude message IDs remain observations with issues so reconciliation can explicitly exclude them. Invalid object-valued IDs are never stringified into payload text.

`model_context_window` is capacity, not proof of request input. Last-usage and message counters retain their native scope; no extraction step turns a cumulative delta or capacity into a verified request-context count. Tier-evidence selection remains S04 work.

### Source identity versus global event identity

`SourceRef` contains source identity, positive physical line, and optional file generation. Its observation ID hashes parser version plus those fields. Copies produce separate evidence references. The current filesystem adapter leaves generation unknown: these are scan-local references until S03 verifies append/replacement/truncation generations. They must not be used as durable source identity across rewrites yet.

Provider conversation identity is namespaced by provider. When unavailable, the conversation key is explicitly source-local, derived from the full source identity. Two files with the same basename do not merge. Missing IDs do not establish cross-copy equivalence.

`group_observations()` gives S02 deterministic conversation groups and preserves every observation. Sorting by timestamp then source/line makes the input repeatable under reversed enumeration; tied-source order is a transport order, not evidence of causality. Source positions and IDs must still resolve ties or expose ambiguity.

### Canonical acceptance and provenance mapping

`CanonicalEvent` is the accepted-event contract; active legacy readers do not emit it in S01. It contains the compatible `Record`, conversation key, epoch/event anchors, source kind, contributing source references, quality flags, reconciliation version, and optional request-context count/source.

The event ID hashes reconciliation version, provider, conversation key, epoch anchor, event anchor, and source kind. Adding/reordering copy provenance does not alter it. Changing the reset epoch does. Source kind must match the provider; token categories must be nonnegative integers; timestamps finite; reasoning a nullable output subset; known request context must have an evidence source.

S02 must derive anchors from reconciled evidence before constructing accepted events. A caller-supplied anchor is not itself proof of correctness. Neither a cumulative tuple nor a file position alone is a permitted global identity. Repricing does not enter event identity or mutate token facts. If corrected decomposition changes identity, later revisioned consumers must invalidate affected views as specified by the integration contract.

Mapping policy for S02:

1. Retain separate source-local observations from every available copy.
2. Reconcile matching provider identity/time/sequence/context evidence across copies before deriving deltas; map all supporting source references to one accepted event.
3. Within a resolved epoch, derive nonnegative category increments. Zero-delta notifications are evidence rather than new usage; inherited fork observations seed baselines without charging child usage.
4. A decrease opens a reset epoch. Exclude/flag the ambiguous transition; preserve valid later increments even when numeric totals repeat an earlier epoch.
5. Merge Claude streamed counters only for supported message/request identity, retaining contributing references and context evidence. Preserve explicit-message versus inherited-turn effort sources when resolving updates.
6. Conflicting evidence without a defensible resolution produces a qualified exclusion/issue. Do not pick a filename winner or greatest sum. The actual equivalence, tie, and epoch algorithm is S02's implementation gate.

Mandatory expected results remain overlap `100,200` plus partial `200` -> **200** in either order; reset `100,200,50,100` -> **250** excluding the unknown transition. S01 does not claim to fix them.

## Privacy and verification boundary

Only declared metadata fields cross extraction. Prompts, responses, thinking text, arbitrary payload objects, request messages/headers, credentials, and source lines have no storage field in these contracts. Extraction inspects Claude block types solely to identify tool-result continuation. Synthetic sentinels verify that nested content and invalid object counters/IDs do not appear in dataclass serialization or representations.

Allowlisted metadata itself may be identifying or hostile display text. This session does not certify every exporter or implement S08 terminal/HTML hardening. Existing rendering safeguards remain covered by the legacy suite.

[Contract tests](../windows/tests/test_observations.py) cover both providers, missing/invalid/zero counters, raw stream updates, legacy TTL evidence, explicit effort/reset behavior, missing identities/timestamps, privacy sentinels, physical line provenance, copy-order independence, epoch-sensitive accepted IDs, shared record compatibility, and headless imports.

The initial isolated snapshot passed 14 focused and 71 full-suite tests. Two additional contract checks were then added in the managed worktree; its final focused run passed **16 tests**. Full-suite, packaging, probe, and documentation results are recorded in the session ledger after final verification.

Remaining limits: legacy accounting defects, unverified source generations, file-mtime filtering, partial-read recovery, structured scan completeness, exact monetary service extraction, and request-tier uncertainty remain later-session work. No real usage history, live account, Figma, or macOS runtime was tested in S01.

## Final evidence

- Focused managed-worktree suite: **16 passed**.
- Full managed-worktree suite through `windows/build.ps1`: **73 passed in 6.293 seconds**, no skips reported.
- Build: `powershell -NoProfile -ExecutionPolicy Bypass -File windows/build.ps1` succeeded with installed dependencies and `PIP_NO_INDEX=1`. The worktree reused the existing project virtual environment through an ignored local junction; no new dependency versions were installed.
- Fresh packaged offline month-demo saved output: exit **0**, DEMO label, **108,000** tokens, **USD 0.2658**, and monthly comparison confirmed. No interactive tray was launched.
- Probes in this worktree still show overlap truncated-first **300/200** (observed/expected), complete-first **200/200**, and reset **200/250**. These are open S02 gates.
- Documentation links, fences, trailing whitespace, and `git diff --check` passed. No real histories, credentials, live provider requests, external Figma edits, or CI execution were involved.

Next: implement S02 against this observation seam, first promoting the mandatory accounting expectations into regression assertions. Resolve the other checkout's competing contract before integrating either implementation there; the isolated results do not certify that mixed checkout.
