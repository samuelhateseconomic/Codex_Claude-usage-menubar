# Frontend contract preparation handoff

S13 follow-up: the published S12 schema supersedes this candidate for the production frontend. Use the [S13 frontend handoff](s13-frontend-handoff.md) for the implemented local dashboard, its exact runtime assets, current checks and remaining Agent 1 integration. The candidate files below remain historical preparation; the new real dashboard does not import them.

October 24, 2026. Base: combined S10 commit `88c6786`. Branch: `codex/frontend-contract-preparation`, using the previously clean managed integration checkout. Status: **fixture-backed preparation complete; candidate requires backend alignment**. S11/S12 implementation and S13 production integration are not completed here.

## Files and ownership

- [Candidate JSON Schema](contracts/usage-hub-v1.candidate.schema.json): machine-readable response definitions plus client selection definitions before GET encoding. This is a candidate for contract `1.0`, not a published backend contract. [Executable schema](../windows/dashboard/contract-schema.js) exports the identical object; tests enforce equality.
- [Synthetic responses](fixtures/usage-hub-v1-responses.json): 29 response examples, with deterministic [fixture construction](../windows/dashboard/tests/v1-fixture-builder.mjs). The complete totals and individual event values come from the existing [alignment example](fixtures/usage-hub-database-alignment.json); no new model rates or browser-side accounting were introduced.
- [Response validation](../windows/dashboard/response-contract.js): bounded validation of the schema's supported assertion keywords, exact int64 token syntax/bounds, fixed decimal syntax, required/null fields, UTC dates, zones and selected state consistency. Unsupported keywords/references fail closed. This is a deliberately limited validator for this candidate, not a general JSON Schema implementation or external conformance certification. No dependency/download was added.
- [API adapter](../windows/dashboard/api-client.js): read-only v1 transport, safe errors, repeated GET field encoding, explicit preview compatibility client, and a view model separate from the preview DTO. Exact strings, complete project sets, row ordering and opaque IDs/cursors are retained. Production mode defaults to `local`; demo responses require explicit `expectedMode:'demo'`. No fallback, provider call, new accounting, mutation or authentication bootstrap is implemented.
- [Navigation/request preparation](../windows/dashboard/query-session.js): retained query/context/version/range, cursor stack, detail return position, coordinated widget publication, obsolete-response guards, one coordinated revision/context retry, and bounded explicit job observation.
- New focused [contract tests](../windows/dashboard/tests/contract.test.mjs), [client tests](../windows/dashboard/tests/api-client.test.mjs), and [navigation/request tests](../windows/dashboard/tests/query-session.test.mjs) reuse synthetic input only. Existing formatter/privacy/interaction/recovery tests are retained.

Agent 1 owns backend files, database/migrations, ingestion, pricing/accounting, routes/serializers, registry/cursor validation, runtime/writers, jobs and authentication. None was edited. The existing `app.js`, HTML, styles, server and launcher are unchanged. The new clients are prepared modules; the running demo has **not** been switched to them or to `/api/v1`.

## Proposed response and request mapping

The [integration contract](usage-hub-integration-plan.md#7-proposed-api-and-input-contract) remains the semantic authority. The candidate follows its success envelope, frozen range/version tuple, lowercase provider values, source/account scope and four aggregate price states.

- `overview` contains `summary`, daily summaries, provider-scoped model/effort groups and provider-scoped project groups. Each summary has exact category counters under `tokens`, separate reasoning coverage, value coverage, known/unknown project counts and a qualified `plan_comparison`. Combined headlines come from the server, never a page/group sum.
- `conversations` has full-result `summary`, paged `items` and `page.next_cursor/page_size`. Rows preserve `conversation_id`, `provider_conversation_id`, complete `projects/models/efforts`, and a matched-query summary. Duplicate labels have different IDs in the examples. There is no invented page count.
- `detail` has a matched `conversation.summary` and separately labeled `lifetime` first/last activity. `events` carries exact token categories, nullable reasoning/effort, event valuations/provenance and opaque event IDs. The client rejects substituted context/conversation IDs and event pricing versions.
- `facets` carries stable IDs/labels/counts/selection per facet; backend self-excluding calculations remain S12. `coverage` separates index freshness, last successful scan, unreadable/missing source counts, unknown excluded amounts, provider source states and issue codes from price coverage.
- `status` and `job_response` are small candidate projections for initial recovery and operation observation. Job polling only reads an explicitly provided job, stops on terminal states/obsolescence, and returns `pending` at its attempt bound. There is no recurring/background monitor.
- `query_selection` describes the client state before GET encoding. Repeated `providers/project_ids/models/efforts` become repeated `provider/project_id/model/effort`; `search` becomes `q`. Period/timezone are sent only for a fresh range. Empty optional fields are omitted where appropriate. `derived_selection` uses `base_query_context_id` with replacement filters; `frozen_selection` represents unchanged context plus list controls. These are not JSON GET bodies.
- Default conversation sort is `value_desc`, then backend stable ID ties; events request `occurred_at_asc`. Client cursors are opaque and are not decoded, created or validated as server authorization. Filter/sort changes clear cursor history. Limits do not inherit a usage range.

Token strings are canonical nonnegative base-10 values at most `9223372036854775807`. Money strings have at most 24 integer and 12 fractional digits, no exponent/binary number representation; only differences may be negative. Individual configuration fee/rate validation remains backend-owned; a combined full-fee comparison is not incorrectly restricted to one provider's fee bound. The adapter does not change accounting or exact values to match display rounding.

## Using the prepared modules after alignment

The caller supplies same-origin fetch and handles deliberate local launch/authentication. No bootstrap secret is read from URLs/storage or manufactured by this layer. Transport accepts only its defined relative read routes, checks JSON content/type and a 2 MiB response limit (streamed where supported), validates responses, and displays fixed safe error messages rather than server exception text.

Create one `QueryNavigation(selection)`, `createV1Client()` and `createQuerySession(client)` for a usage view. Call `session.load({kind:'conversations',request:nav.request(),selection:nav.query,related:['facets']})`. Only an `accepted` bundle may replace the screen. On `refreshed:true`, call `nav.refresh()` before accepting the replacement anchor, clearing old pagination and return state; then call `nav.accept(bundle.anchor)`. Publish the new cursor/page controls with that same bundle.

Use `nav.change(...)` to derive replacement metadata/provider/day filters under the frozen base, or start a new range on preset/timezone/dataset changes. Use `nav.next(returnedCursor)`/`nav.prev()` for pages, retaining full-result headlines. Use `nav.detail(id,scrollY)` to capture a parent, read detail/events through the client and verify the context with `nav.accept(detailResponse)` before display. `nav.back()` returns the original request and scroll position. After an invalidated context, refresh the parent coherently rather than replaying an old cursor.

Always pass the full selected query separately as `selection` when loading with a context-only request. It is captured immutably and allows a bounded fresh retry. Without a retained selection, the coordinator cannot safely reconstruct filters after a 409 and surfaces the error. Authorization, configuration conflicts, validation errors and cooldowns are not treated as revision retries. A second revision conflict stops; the last accepted bundle remains available to show with its original filters.

This is a library-level handoff. Browser history/focus/DOM binding stays in S13, using the existing [interaction coverage](dashboard-resilience-handoff.md). No new browser/native layout or focus certification is claimed.

## Decisions Agent 1 must align before S12 freezes the contract

1. Confirm field names and required/null behavior, especially aggregate `tokens`, reasoning record counts, qualified comparisons and the detail/lifetime nesting. Do not adopt this candidate silently if the final serializer differs; update one schema, fixtures and adapter mapping together.
2. Confirm overview composition/provenance: chart/group completeness, tier assumptions near the headline, pricing-policy/provenance projection, and provider fee comparisons. Current candidate examples are a thin subset, not the complete production Overview specification.
3. Confirm coverage/status projections, retained-failed versus stale semantics, source/counter issue allowlists, freshness timestamps and provider check states. The status example is intentionally minimal; it does not replace the full runtime status contract.
4. Confirm normalized filter ordering, ID registry semantics, unknown-project representation and self-excluding facets. Candidate arrays are bounded at 100 (daily buckets 370); define pagination/capability/error behavior for larger results. Never silently truncate a full summary or facet universe to satisfy these example bounds.
5. Confirm context lifetime, restart expiry codes, cursor binding and error codes. The frontend retries only 409 `revision_changed`/`context_expired` once. The registry remains responsible for base-context inheritance, range/day validation and cursor integrity.
6. Confirm job envelope, timestamps, retained completed results and resulting version tuple. This observer creates no jobs, does not infer publication from persisted settings, and requires the caller to refresh query data after successful publication.
7. Confirm session/bootstrap/read authorization and mutation CSRF policy. The prepared v1 reads use same-origin cookies and `Accept: application/json`; the preview's `X-Usage-Hub` marker is confined to its explicit adapter. No production mutation/security contract is guessed here.
8. Add the four prepared JS modules to the server's explicit asset allowlist after agreement, then connect the existing UI in S13. Current routes only serve the older frontend files. Enabling imports now would break the demo, so HTML/app imports were intentionally left alone.

These decisions need backend alignment, not another design exploration or accounting rewrite. No message was sent to Agent 1; this document is ready to share through the user or under explicit messaging authorization.

## Controls still dependent on backend gates

Production-data launch, retained index reads, context creation/derivation/expiry, authenticated asset serving, exact cursor pagination/facets and real detail/event routes depend on S11/S12. Settings Save/conflict/repricing, index refresh, live-limit refresh and durable jobs also remain backend-dependent. No new enabled control, real-data flag or sample fallback was added. Existing demo-only controls/labels keep their current scope.

S13 must bind the prepared clients to current DOM/history and adapt status/coverage/provenance honestly, then run targeted actual browser checks for changed flows. S14 owns packaged lifecycle/security/offline/performance acceptance. Terminal/tray behavior and explicit dashboard launch remain intact.

## Evidence and remaining checks

Final counts and commands are recorded in the [plan execution entry](frontend-contract-preparation-plan.md#execution-follow-up) and [refinement ledger](project-refinement-plan.md#frontend-contract-preparation--october-24-2026). Preparation tests are schema/client/coordinator simulations, including an in-memory Fetch Response journey; they are not a running backend, persisted query, browser interaction or packaged acceptance test. No Python/accounting/backend file changed, no real history was read and no live provider request, Figma change, deployment or push occurred.
