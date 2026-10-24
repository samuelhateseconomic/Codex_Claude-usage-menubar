# S05: one headless usage query and report result

Implemented October 24, 2026 in the isolated refinement worktree, starting at `15219d5`. This session extracts shared query behavior from the existing reports; it does not introduce a database, HTTP API, dashboard, or new output styling.

## Responsibility and entry points

[usage_service.py](../windows/usage_service.py) owns offline collection, selection, ordering, group membership and summary assembly. It depends on the metadata scanner, reconciliation, record/time contracts and exact S04 valuation. It never imports the provider adapters, tray, Pillow, pystray or report renderers, and never polls a provider. Optional supplied snapshots are read only to resolve the existing provider-specific five-hour boundaries.

- `collect_usage(...)` captures one clock/range context and reconciles available local observations, returning immutable `CollectedUsage` metadata. Its entries are selected by the provider range after reconciliation; earlier observations still establish deltas and fork/reset baselines.
- `build_usage_result(entries, context, catalog, fees, sources, notices)` is the pure query seam over accepted events or explicit legacy `Record` occurrences. It applies the captured half-open ranges and metadata filters, values each selected event once, then assembles all views from those valuations.
- `query_usage(...)` combines these steps for on-demand offline reports. CLI and tray report generation use this entry point directly. `--once` live-limit checks keep their existing separate path.
- `CollectedUsage.query(...)` supports in-memory reuse. To refine a query without advancing its clock, reuse its entries and captured context with `dataclasses.replace`, the original immutable catalog, the same fee configuration and source diagnostics. Calling `query_usage` again is an explicit rescan with a new captured end unless `now` is supplied.

From a Python process whose import path includes `windows`:

```python
from usage_service import query_usage
from usage_reports import render_text_report, render_report

result = query_usage("month", demo=True, timezone="UTC")
assert result.total.tokens.total == 108_000
text = render_text_report(result)
html = render_report(result)
```

The example deliberately selects demo scope. Real queries read configured local roots without a demo fallback. No production network connection is required.

## Immutable result and independent quality dimensions

`UsageResult` stores frozen dataclasses and immutable tuples: scope (`local_unmatched_accounts` or `demo`), selected providers, resolved UTC ranges, named timezone, filters, generation/capture time, total and group summaries, event details, source/issue metadata, catalog/version provenance, and structured per-provider/combined fee comparisons. `generated_at` is the operation's one captured timestamp, not a second completion-time clock reading. Provider-specific session starts can differ, while all ranges share the captured exclusive end and named zone.

Each `UsageSummary` contains exact token categories, the S04 `ValueSummary`, record/conversation/project counts and explicit reasoning coverage. Known reasoning zero remains zero; absent reasoning remains null, and mixed coverage carries known/unknown record counts. Reasoning remains a subset of output.

Source states and allowlisted scan/accounting issues remain separate from pricing coverage and tier/TTL assumptions. Source diagnostics describe the scanned provider inputs, even when a metadata filter narrows the matched records; they are not a claim that a particular filter accounts for an unknown exclusion. `excluded_tokens` remains null when unknown. The result contains no raw source lines, transcript content, credentials or retained provider payloads. Missing roots can yield an empty usage summary with failed ingestion; this is different from an empty readable folder or a partial scan.

The immutable catalog and event provenance preserve S04 rates, mappings, checked dates, request-context evidence, assumptions and exact money. Repricing cannot change token facts or canonical event IDs. No new price verification is claimed.

## Group membership, identities and sorting

Provider, model plus effort, effort, model, project, conversation and local-day groups partition the same matched event details. Every group retains its contributing detail IDs, category/value summary and last matched activity. Summaries always describe the full matched result; taking a display slice of a sorted group list does not recompute or narrow the total.

Groups use structured keys rather than joined display labels, preventing delimiter collisions. Canonical conversation membership/counts use the full provider/reconciliation conversation identity, including weak source identity; a shortened display surrogate cannot merge two conversations. `UsageDetail.conversation_id` is an opaque stable projection for drilldowns. `UsageGroup.key` contains display metadata, and `group_id` identifies the structured group. Two distinct weak conversations may therefore have equal display keys and different group IDs. A conversation can contribute to multiple model, effort, project or day groups. Project count uses exact project text shared across providers, while project breakdown rows retain provider scope; no filesystem alias normalization or verified account matching is inferred.

Canonical detail IDs retain accepted event IDs. Duplicate canonical IDs at this seam are rejected: reconciliation must happen first. Legacy `Record` inputs retain repeated occurrences using a metadata fingerprint plus deterministic occurrence suffix; these are compatibility detail IDs, not evidence for cross-file deduplication or canonical event identity. A legacy record's full provider/session label supplies its weaker conversation identity.

Detail order is `(timestamp, detail_id)` ascending. Default group order is structured display key ascending, with group ID ties, preserving ordinary terminal/HTML ordering. `groups_for(dimension, sort)` also supports exact `value_desc`, `tokens_desc`, and `last_activity_desc`, with stable group ID ties. Value order ranks priced contributions, including partial subtotals; all-unpriced groups follow priced zero. Decimal sort keys use exact sign inversion, unaffected by binary floats or a caller's low-precision Decimal context. There is no pagination, cursor, persisted ID registry or server query-context token in S05.

## Filters and comparison scope

`UsageFilters` supports exact project/model/effort strings, provider plus full session metadata pairs, returned opaque conversation IDs, selected local day, and bounded literal case-insensitive metadata search (session, project, model; 200 trimmed characters). Selections normalize to immutable sorted distinct tuples. Search has no regex or transcript interpretation. These are Python service contracts; no extra CLI switches or dashboard controls are claimed.

Filters keep the supplied captured range and disable full-fee comparisons, even when a filter happens to match every event. Provider-only selection remains eligible for an otherwise valid calendar-month-to-date comparison. All other S04 guards remain: signed exact API value minus full configured fee, explicit unavailable reasons, no silent omission of an unavailable selected provider, and separate source/pricing/assumption qualifications.

## Compatibility and intentional corrections

[usage_reports.py](../windows/usage_reports.py) retains `collect_report`, mutable `Report`, legacy readers, `estimate`, and formatting/saving entry points. `Report.query_result()` snapshots its current inputs through the service; each renderer takes exactly one snapshot when passed a legacy container. Passing the same `UsageResult` to both renderers avoids requerying or repricing. CLI/tray already do this directly. Compatibility `valuation_view` uses process-local object identities only as an adapter projection; new consumers use detail and conversation IDs. The optional old comparison `view` argument no longer overrides the service snapshot.

Both renderers now format precomputed summaries, groups, event details and comparison amounts. They do not value events, group records, sum reasoning, or compute competing totals. Existing terminal default, explicit HTML launch, output formats and report locations are preserved. S10 remains responsible for expression changes.

One intentional correction affects manually constructed/mutated legacy reports: records outside the selected providers or captured `[start, end)` range no longer enter summaries. Existing real collection already applied that rule. Six synthetic fixture timestamps formerly at exactly `end` move one second inside their intended report range; their numeric expectations are unchanged. New tests assert exclusion at the exact end for both canonical and legacy inputs. Structured grouping also separates formerly colliding joined labels and full canonical conversation identities without changing accepted token facts.

## Verification and limits

Verification commands use the project interpreter and workspace-local `windows/build/s05-temp` for TEMP/TMP. Final evidence: **24 focused tests**, **187 full-suite tests**, the Windows build and **10 packaged offline cases** passed. Parsing the packaged HTML separately reconciled all seven group dimensions against every category and the exact fixture subtotal. Changed documentation links/fences/whitespace, the demo example, source syntax and `git diff --check` passed; see [the ledger](project-refinement-plan.md#session-s05--shared-headless-reportquery-service) for commands, outcomes and development corrections. The S05 tests exercise exact fixture amounts, all category/group/detail reconciliation, provider/filter/drilldown scope, named-day boundaries, stable identity/order, adjacent Decimal ranking that binary floats collapse, reasoning coverage, source/price state separation, immutable snapshots, renderer authority, and an offline fresh-process scan with sockets/subprocess launch blocked. The metadata sentinel stays out of the returned result.

No persistent configuration/version, database revision, retained stale dataset, API wire serializer, large-history benchmark, live user histories/accounts, interactive tray lifecycle, Figma, macOS or remote CI verification is implied. Full scans and all matched details/groups remain in memory. S06 is the next dependency: persist validated settings/fees/roots/timezone/rates and identify configuration/build versions without moving calculations back into renderers.
