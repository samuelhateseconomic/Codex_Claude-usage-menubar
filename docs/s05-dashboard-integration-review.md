# S05 service to dashboard integration handoff

Integration follow-up (October 24): [the combined branch session](branch-integration-plan.md) now removes duplicate preview event valuation, summary arithmetic and fee subtraction. `usage_value.py` is only a projection over core `value_event`/`summarize_values`; fee comparisons call `compare_plans`. Persistent revisions, canonical ID/wire mapping, whole-query grouping/facet adoption, jobs and real-data publication remain S11-S13 responsibilities. This closes the arithmetic seam without claiming the full production query adapter is implemented.

Reviewed October 24, 2026 against committed core `97b6070` and dashboard base `70dde1f`. Status: **review complete; real-data integration not implemented**. S06 is owned by the other agent. This review changes neither that worktree nor its service/configuration contracts. The [refinement plan](project-refinement-plan.md), [integration contract](usage-hub-integration-plan.md), and [database handoff](usage-hub-database-handoff.md) retain their ownership and gates.

Follow-up: S06 and S07 are now committed on the separate core branch through `461c3a3`; S08 privacy/diagnostic verification is next. The [resilience handoff](dashboard-resilience-handoff.md) closes this review's decimal money-formatting gap and adds focused failure/recovery coverage. This review remains the historical S05 contract baseline; its other integration requirements are still pending. Consult both coverage inventories before duplicating UI checks.

## 1. Verified service boundary

At `97b6070`, `windows/usage_service.py` supplies `collect_usage`, `build_usage_result`, `query_usage`, `UsageFilters`, `QueryContext`, and immutable `UsageResult`. Its committed description is `docs/s05-headless-query-service.md` in that revision; it is not present in this dashboard checkout yet. Inspect that revision with `git show 97b6070:docs/s05-headless-query-service.md` rather than linking to an absent local file.

The service owns range/filter selection, event valuation, totals, reasoning coverage, seven group dimensions, exact ordering, source diagnostics, and qualified signed fee comparisons. The existing [preview](../windows/usage_hub.py) separately implements much of this through [usage_value.py](../windows/usage_value.py). That duplication is a development seam, not the desired real-data architecture.

Use the core's pure result builder over reconciled accepted events when the integration gates permit. Do not call the local scanner or `query_usage` on every browser request. A browser request must not poll providers. The scheduler and configuration remain S06-S07 work; the retained index and API remain S11-S12 work.

## 2. Exact adaptation decisions

### Capture and reuse one dataset

`collect_usage` reconciles observations before applying the captured provider ranges. It returns only entries in those ranges. Its captured context and immutable catalog can be reused for narrower metadata filters with `dataclasses.replace` and `build_usage_result`; calling `query_usage` without a fixed `now` starts a new scan and advances the end.

Changing from Today to Month cannot recover earlier entries from a Today-only collection. S11 must retain sufficient accepted facts for every advertised range, or explicitly collect the wider range before publishing a new snapshot. Preserve the frozen end, named zone, source diagnostics, catalog and fee configuration through filter/detail/Back operations. New committed data becomes visible through explicit revision refresh, not an accidental clock change during navigation.

### Totals, groups and ordering

- Project `UsageResult.total` directly into the full matched headline. Never derive it from the six preview rows or a future cursor page.
- Read provider, day, model/effort and conversation summaries from `groups_for`. Request exact `value_desc` for contribution lists and the future default conversation ordering; preserve stable ties. Preview conversation ordering is currently last activity descending.
- Core project rows are provider-scoped, while `total.project_count` counts exact project strings shared across providers. Adding row counts would overcount shared projects. An all-provider project rollup must be added through the authoritative service contract when scoped, or the UI must retain provider-scoped rows; the HTTP adapter must not invent another aggregation implementation.
- Preserve multi-project/model/effort membership within one conversation. Preview `group_dto` currently chooses the last project's label. Derive the complete set from the referenced core details and label multiple projects explicitly. Unknown-project counting still needs the integration-contract policy; do not assume every placeholder is a known project.

### Identity and detail

The preview hashes `(provider, session)` into a shortened ID. S05 uses full canonical reconciliation identity for `UsageDetail.conversation_id`, with separate `UsageGroup.group_id` and `detail_id` values. Equal display labels can represent distinct weak conversations. Do not reconstruct identity from `UsageGroup.key`, a path or a shortened label.

Serialize a conversation identity from its contributing details, and keep the dataset-scoped persisted/wire ID mapping at S11-S12. `group_id` and `conversation_id` are different contracts. Query details only through IDs belonging to the frozen parent query; preserve its list position and filters for Back. Event token facts and value/provenance come from each detail's existing summary/valuation, never a fresh calculation. A conversation-filtered query is filtered for fee comparison purposes; do not accidentally replace the parent's full-query comparison or headline with a detail-only result.

### Filters and facets

- Map preview `both|codex|claude` to the selected core provider tuple; a future v1 request uses the contract's provider arrays and rejects an empty selection.
- Map project/model/effort selections to immutable `UsageFilters` tuples. Future opaque project IDs must resolve through the dataset registry before selecting exact core metadata values.
- Adopt the core's trimmed, case-insensitive literal search over project/session/model with a 200-character bound. Preview currently searches project/session only and permits 512 characters. Change the input label/bound together with the adapter, not in isolation now.
- Core day filtering validates ISO format and uses the named zone. S12 must additionally reject days outside the frozen query range.
- Core `models` lists matched model keys; it is not an implementation of the proposed self-excluding facets. Requery the same frozen entries/context/catalog with the facet's own filter omitted, retaining the other filters and selected zero-match options. Do not discover facets through another scan or from the paged conversations.

### Numeric wire data and quality

Core token counts are integers and money/rates are bounded `Decimal` values. The wire serializer must explicitly emit integer strings and decimal strings, including nested event valuations; a generic dataclass/JSON conversion is insufficient. Map `input/output/cached/write5m/write1h` to the agreed category names. Keep reasoning null distinct from known zero and expose both known and unknown record counts.

The pinned S04 implementation bounds token counts at `2**63 - 1`, rates/fees at USD `1000000000` with up to 12 fractional digits, and absolute money at `999999999999999999999999.999999999999`. Its policy is `decimal12-event-tier-compat-v1`: half-even quantization once per event at 12 USD fractional digits, then exact aggregation. Validate these bounds at storage/serialization boundaries without introducing different rounding.

Use `summary.value.state`, priced amount/subtotal, unpriced token/record coverage, and event assumptions separately from `result.sources` scan states and scan/accounting issue codes. Never flatten failed ingestion plus empty usage into successful zero. Provider comparisons and `combined_comparison` already carry eligibility/reasons and qualifications; serialize those decisions instead of the preview's calendar/filter heuristic and manual subtraction.

The current browser's `money()` converts decimal text to `Number` for display. Before supporting the full S04 money bounds, replace that formatting with decimal-string rounding/grouping. Keep Number conversion limited to chart geometry; never use it for ordering, totals, comparisons or exact exports. Token formatting already uses exact integer strings/BigInt.

### Versions and missing integration facilities

S05 supplies parser, reconciliation, valuation-policy and query versions plus immutable catalog provenance. Its `QueryContext` is a Python context, not a durable API query token. It does not supply installation/dataset IDs, committed database revision, configuration version, cursor pagination, restart recovery, jobs, HTTP serialization, or retained stale publication. Existing preview revision/context hashes are not replacements for those S11-S12 responsibilities.

Wait for S06's actual persisted configuration and identity outputs before naming their adapter fields. Do not introduce a second default-fee source, settings writer, config version or migration from this review. The active configuration projection and the active fully valued database tuple may differ while repricing is pending; follow the existing publication contract.

### Keep demo fixtures explicit

S05's terminal demo is 108,000 tokens / USD 0.2658; the reviewed dashboard demo is 8,920,000 / USD 49.506. They are intentionally different fixtures. Future dashboard service tests should supply the dashboard's explicit accepted demo records and a synthetic fixed-rate catalog through the core builder, not substitute the terminal fixture or use the real tiered catalog. Neither fixture establishes observed account usage. A failed real scan never selects demo.

## 3. Implementation sequence after the prerequisites

1. Finish S06-S09 and perform combined branch integration validation. Preserve the dashboard's existing preview until those gates pass; this review does not merge either worktree.
2. At S11, persist reconciled facts, exact valuations, source quality, version tuple and ID relationships with atomic publication/recovery. Exercise the existing synthetic alignment fixture through the actual adapter.
3. At S12, add a thin core-result serializer and frozen-query registry, bounded filters/cursors, facets, safe jobs/settings behavior and loopback authorization. Remove duplicate real-path valuation/group/comparison logic. Do not leave the preview's real-reader seam as a competing production path.
4. At S13, adapt the UI to that DTO, exact decimal display and canonical IDs. Preserve explicit launch, provider/day/metric filters, detail/Back and honest unavailable states. Connect cached Limits through the runtime owner only. Account activity remains optional and separate as described in the database handoff.
5. Compare headline/group/chart/detail category counts and exact money, filtered comparisons, immutable context, equal display labels, mixed projects, unknown/zero/partial pricing, failed/stale scans, pagination ties and version conflicts. Complete S14 packaged ownership/restart checks before claiming real-data delivery.

## 4. Independent interaction repairs and evidence

Two defects were reproduced in the actual demo browser before editing:

- Typing `portfolio` and immediately choosing Clear filters briefly cleared the view, then the pending 250 ms callback restored `q=portfolio` and its three matches.
- Pressing `/` while the shortcut modal was open changed the underlying Overview to Explore even though the modal remained open.

[app.js](../windows/dashboard/app.js) now cancels pending search timers on explicit navigation, Back/Forward and rescan, and leaves keyboard handling to the native dialog while it is open. No layout, Figma, pricing, core, persistent setting or account connector changed. The [interaction regressions](../windows/dashboard/tests/interaction.test.mjs) execute the actual handlers with controlled timers and a small DOM simulation. All three failed before the repair and pass afterward; these simulations do not certify browser layout or native focus.

Verification results and remaining limits are recorded in the refinement ledger after the final checks. No S06 or S11-S14 gate is completed by these repairs or this review.
