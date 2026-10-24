# Frontend contract preparation before S13

Prepared October 24, 2026. Status: fixture-backed preparation implemented; backend alignment and S13 activation pending. This is independent preparation for S13, not completion of S11, S12 or S13. See the [handoff](frontend-contract-handoff.md) and execution entry below.

## Verified starting point

- Agent 1's local branch and tracked upstream both point to `88c6786918e9ffb3b808f903b0dd83bd955e6a38`; its working tree was clean at this inspection. This verifies local tracking information, not a new remote fetch.
- That revision records S00–S10 complete and includes the dashboard integration commit `16b7b14`. Dashboard assets, `usage_hub.py` and `dashboard_main.py` have no changes between those checkpoints. Agent 1's S10 ledger records combined tests and packaged/CI evidence; those checks were read, not rerun for this plan.
- The desktop checkout is still `main` at `963275c`, with other work preserved in `windows/usage_reports.py`, `usage_records.py`, `usage_observations.py` and `tests/test_observations.py`. It is not a safe place to implement against the latest combined core without isolation.
- No production OpenAPI/schema artifact was found in the checked tracked `docs` and dashboard files. The [integration contract](usage-hub-integration-plan.md#7-proposed-api-and-input-contract) and [alignment fixture](fixtures/usage-hub-database-alignment.json) remain semantic starting points, not an implemented production API.

The [refinement plan](project-refinement-plan.md) owns gates. Its copy in this desktop checkout is older than Agent 1's S10 ledger. Consult revision `88c6786` for current gate status; do not overwrite either ledger merely to synchronize planning text.

## Ownership

- Agent 1: SQLite schema/migrations, ingestion/reconciliation, shared accounting/configuration, production routes and serializers, query registry/cursor validation, jobs, authentication/bootstrap, runtime ownership, and S11/S12 backend gates.
- Agent 2: frontend contract candidates/fixtures, API adapter, client query/navigation state, dashboard behavior and frontend tests. Preserve the existing compact dashboard and exact formatters.
- The shared machine-readable wire contract needs one authoritative version. Agent 2 may prepare a candidate with explicit open decisions; it becomes a backend target only after alignment with Agent 1. No backend file is edited from this preparation session.
- Use an isolated frontend checkout based on the combined S10 revision, with a `codex/` branch. Recheck current refs and edits before creation; do not copy uncommitted source files. Integrate later backend commits at explicit checkpoints.

## Work sequence and acceptance

1. **Prepare the wire contract candidate.** Document request/response schemas for the thin Overview → conversations → detail/events → Back path, facets, status, safe errors and job status. Follow the existing `/api/v1` names and numeric bounds. Make required, nullable, unavailable and optional fields explicit. Record unresolved details such as token-category shape, overview composition, facet IDs, stale/failed coverage fields, context expiry and capability discovery. Do not quietly choose incompatible shapes on the two sides.
2. **Add schema-validated synthetic response fixtures.** Cover empty, complete, partially priced, entirely unpriced and legitimately zero-priced results; unknown versus known-zero reasoning/fees; retained stale data versus initial failure; duplicate labels with distinct IDs; multi-project conversations; mixed provider coverage; large integer strings and bounded decimal money. Derive expected values from the existing alignment fixture or fixed core-produced examples, without duplicating accounting in the browser. Include 409/422/429 errors and queued/running/succeeded/failed/superseded jobs. These fixtures prove client handling, not ingestion or real API behavior.
3. **Extract a frontend API adapter.** Put transport, input encoding, response validation and view-model mapping behind an injected client interface. Keep the existing preview as an explicit adapter; add production-contract preparation without enabling real collection. Preserve token and money strings through validation/mapping, opaque IDs and cursors, nulls, and independent quality dimensions. Reject malformed responses with a safe actionable error; never substitute demo or zero. Server ordering and totals remain authoritative.
4. **Prepare frozen navigation.** Store dataset/context/version tuple, normalized filters, effective range, sort, page size, opaque cursor history, list position and detail return state. Use `query_context_id` for unchanged queries and `base_query_context_id` for changed filters under the frozen range; never send both. Clear pagination on filter/sort changes. Preserve the parent context through detail and Back. Preset/timezone changes or explicit Refresh establish a new range. Do not compute new clock boundaries in the client.
5. **Prepare coordinated request handling.** Reuse existing cancellation and obsolete-response guards. Validate matching context/version metadata before publishing related widgets together. On revision conflict, discard old cursors and retry a fresh context once for the selected filters; do not mix old summary with new rows. A second conflict stops with an actionable retry state. Treat authorization, validation, cooldown and expired/unknown IDs distinctly. Bound job polling and stop obsolete polls; no browser provider polling or implicit reindex.
6. **Document backend-dependent controls.** Production launch/bootstrap, live limits refresh, index refresh, durable jobs, settings writes and real-data mode remain disabled or explicitly unavailable until their backend contracts/gates exist. Read-only fixture tests cannot establish persistence, authorization or job recovery. Keep explicit dashboard launch and terminal/tray access.

## Verification without repeating completed work

Reuse the [dashboard coverage inventory](dashboard-resilience-handoff.md), [S05 mapping review](s05-dashboard-integration-review.md), and completed [branch integration evidence](branch-integration-plan.md). Do not schedule another generic interaction audit.

- Retain all existing frontend formatter, privacy, interaction and recovery regressions from the combined baseline.
- Add focused tests for wire validation, exact numeric preservation, request encoding, frozen context derivation, cursor traversal/Back, mismatched widget versions, stale versus failed rendering, bounded conflicts and obsolete job/query responses. Reject numeric JSON token/money values, invalid bounds, invalid enums and missing required quality metadata.
- Schema tests must exercise the published candidate and examples together. An adapter-only assertion is not schema validation. Document any new validator dependency and keep it out of runtime packaging unless needed.
- Run the existing Node suite and JavaScript syntax checks after changes; run relevant Python tests only if a Python boundary changes. Run `git diff --check` and validate documentation/fixture links. Browser checks should target changed behavior once connected; record simulations separately from actual browser evidence.
- A fixture-backed adapter is complete when it accepts valid examples, rejects malformed ones, preserves exact identities/numbers and navigation, and leaves the current demo functioning. Production acceptance additionally requires S11/S12 gates and real endpoint contract tests. S14 owns the final packaged lifecycle/security/performance gate.

## Handoff and current evidence

Deliver a contract candidate plus open-decision list, response fixtures, adapter interface/mapping, focused regression results, changed-file inventory and backend-dependent-control list. Add an additive ledger entry in the isolated checkout; preserve prior evidence and responsibilities. Do not mark S13 complete or claim backend agreement from this document.

This planning pass inspected branch ancestry, local/upstream revision equality, Agent 1's clean status, current S10 ledger and relevant contract/handoffs. It did not fetch, send a message to another chat, modify backend/frontend code, run application tests, merge branches, commit or push. Agent 1's quoted message is coordination context, not evidence that either side has started S11 or agreed on a machine-readable schema.

## Execution follow-up

The user authorized implementation after planning. Reused the clean managed integration checkout on new branch `codex/frontend-contract-preparation`, based on combined S10 `88c6786`. The original dirty desktop checkout and Agent 1's files were preserved. All implementation is confined to frontend preparation modules, synthetic schema/fixtures/tests and documentation; the running app/preview and backend were not changed.

Implemented the request/response schema candidate, 29 deterministic synthetic responses, bounded schema/state validation, separate v1/preview clients and v1 view model, frozen navigation/cursor/Back preparation, atomic widget coordinator with bounded conflict recovery, and explicit bounded job observation. Candidate fields and backend-dependent controls are enumerated in the handoff. No schema agreement or production integration is claimed.

Validation results are recorded after final checks below. Packaging, browser DOM/history activation and real backend endpoints remain S12–S14 work. Earlier ordinary interaction evidence is reused without a fresh general audit.

- Final Node suite: **51 passing tests**, zero failures/skips/expected failures, **541.6948 ms**, Node **24.16.0**. Includes all 22 retained frontend regressions plus 29 contract/client/navigation/job tests. All 29 synthetic response examples validate against both their endpoint schema and the portable JSON artifact; schema/fixture mirrors agree.
- Syntax: `node --check` passed for existing `app.js`/`format.js` and four new runtime modules. No new runtime/test dependencies were installed.
- Closing checks: **53 local documentation links/anchors** passed; all **13 deliverable files** have final newlines, no trailing whitespace or conflict markers, and JSON duplicate-key checks passed. `git diff --check` passed. The original checkout's four core edits remained unchanged; Agent 1's branch still points to the inspected `88c6786` checkpoint. No generated build artifact was added.
- Preparation only: no Python boundary change, production API activation, real history/provider query, browser/native playback, package rebuild, commit, push or deployment. The explicit asset/bootstrap gate and schema open decisions remain in the handoff.
- Commit follow-up: the user subsequently requested a local commit of this preparation. Source and fixtures are unchanged from the passing 51-test run; this follow-up adds only the authorization record before staging the 13 documented deliverable files. No push or merge is included.
