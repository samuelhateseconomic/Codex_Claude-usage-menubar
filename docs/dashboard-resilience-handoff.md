# Dashboard exact display and request recovery

Status: **complete for the demo preview**, October 24, 2026. Independent work while the other agent owns S07 on `codex/s01-observation-contracts`. Main starts at `70dde1f`; S06 is committed on that separate refinement branch at `6a29b00`. No core session gate advances here. Follow-up: the user authorized a local commit; S07 is now committed separately at `461c3a3`. Commit validation is recorded in the refinement ledger. This does not merge the core branch or authorize a push.

## Ownership and overlap guard

Read this document together with the [previous S05 dashboard review](s05-dashboard-integration-review.md) before further dashboard work. The [refinement plan](project-refinement-plan.md) owns dependencies; the [integration contract](usage-hub-integration-plan.md) owns future data semantics.

- Previously completed: normal provider/metric/day navigation, summary/detail reconciliation, Back context, narrow layout, native dialog focus/Escape, pending-search cancellation, and the modal shortcut guard. Preserve those checks and their existing three interaction regressions; do not redo the whole interaction review without a relevant change.
- This slice: exact decimal-string money formatting, deferred/out-of-order query responses, failed-query recovery, bounded revision-conflict retry, and focus after those failures. Add tests for new behavior, keeping earlier regression coverage.
- Owned files: `windows/dashboard/format.js`, `windows/dashboard/app.js`, the initial badge in `windows/dashboard/index.html`, dashboard tests, this handoff and documentation cross-references/ledger. No provider, polling, process ownership, settings writer, core reader, database, API contract, Figma, or account-access work.
- Evidence-driven extension: the held-query browser check exposed a response-write traceback in `windows/usage_hub.py` when the browser cancelled the request. The narrow response helper and `windows/tests/test_hub.py` disconnect regression also belong to this slice. Response contracts and loopback authorization did not change; this does not take over S07 provider/runtime ownership.
- Existing shared core edits (`usage_reports.py`, observation/record modules and their tests) belong to other work and must remain intact. S01-S06 are not integrated into main. Preview remains explicitly demo-only.

## Implemented behavior

1. Money and signed fee differences format directly from decimal strings, including values above JavaScript's exact integer range, zero/null and rounding boundaries. Display rounding never reprices or changes source strings. Approximate chart geometry/ticks stay separate.
2. A slow or superseded request cannot publish results, errors or focus over a newer query. Loading is visible and old interactive results do not masquerade as the pending query.
3. A failed query retains an honest previous result with its matching filters/URL and an explicit retry of the failed selection. Initial query retry is a read, not a rescan. No failure becomes zero usage or demo fallback.
4. A revision conflict retries once without the obsolete revision, retains the requested filters, and stops with an actionable error if the retry fails/conflicts again.
5. Recovery focus does not escape an open native modal. Tests distinguish controlled handler simulations from actual rendered/browser checks.

The formatter uses BigInt fixed-point arithmetic with half-even display rounding, three fractional USD digits by default and two for monthly fees. Zero through twelve fractional display digits are supported. Signed decimal strings with up to 24 integer and 12 fractional digits after normalization are accepted, including bounded exponent notation used by the preview's legacy Decimal fee serialization (`1E-8`). Malformed, absent, oversized and numeric inputs display Unavailable. Backend validation still owns the exact S04 bounds. Grouping and rounding can produce a displayed carry beyond the maximum input magnitude without changing that input. Signed comparisons retain the source sign even when a tiny nonzero difference displays as `−$0.000`; ordinary money suppresses negative rounded zero. This deliberately replaces Intl's default tie rounding with an explicit decimal policy. No event valuation, ordering, totals or exact export changes.

Query publication tracks the last accepted result and a copy of its view/filter state. Loading temporarily replaces interactive content. On failure, the last accepted result and its matching URL/filters return with one recovery banner; the failed selection is retained only as the explicit Retry target. Failed navigation may leave an extra equivalent history entry because its URL is replaced with the accepted context; Back remains functional. This is an in-memory preview behavior, not durable frozen-query recovery.

Initial Retry issues a GET query, not a rescan POST. Successful rescan plus failed query retains the previous result and does not announce a refreshed view. A small frontend guard prevents duplicate concurrent rescan POSTs; server cooldown remains authoritative. Initial failure shows PREVIEW / No snapshot loaded rather than claiming local or demo data was successfully read. Superseded requests cannot publish or move focus; async search and history handlers share that guard. Completion does not focus outside an open modal. A resize during loading tolerates the absent chart.

## Coverage inventory: reuse before adding work

### Previously completed; retained rather than repeated wholesale

- Existing [format/axis tests](../windows/dashboard/tests/format.test.mjs): token abbreviation and five-interval chart scale. Neither token formatting nor chart scale changed.
- Existing [three interaction regressions](../windows/dashboard/tests/interaction.test.mjs): pending search followed by Clear, pending search followed by navigation, and shortcuts behind a modal. They now reuse the same test harness as recovery tests, with the assertions retained.
- The previous review's actual browser evidence remains the baseline for ordinary provider/metric/day navigation, headline/detail reconciliation, normal Back, narrow layout and dialog Escape/opener focus. A routine repeat of all those checks is not the next task.

### Newly automated in this slice

- Four money tests in `format.test.mjs`: exact large strings/full money-bound carry, half-even ties and negatives, absent/invalid inputs, and exact signed comparisons.
- Eleven [recovery tests](../windows/dashboard/tests/recovery.test.mjs): failed filter restoration/Retry; initial failure/read-only Retry; loading/out-of-order publication/focus; obsolete errors; bounded repeated conflicts; successful revision replacement; modal focus during completion; rescan success/query failure; superseded search focus; duplicate pending rescans; and rendered exact large summary/fee strings.
- [Shared harness](../windows/dashboard/tests/dashboard-harness.mjs) runs the actual app handlers with a small synthetic DOM, controlled timers and deferred fetch responses. It deliberately permits an aborted fetch to resolve, verifying the publication guard independently of browser abort behavior. It does not emulate native focus, SVG layout, browser history or accessibility announcements completely.

The initial eight new recovery tests ran against the unfixed app: **two passed and six failed**. After fixes and three additional cases, the complete Node suite has **20 passing tests**: the original five plus fifteen new cases. Syntax checks for both app/formatter and AST parsing of the browser fault driver passed.

### Newly checked in the actual browser

The opt-in [fault driver](../windows/tests/dashboard_fault_server.py) serves the actual current assets and production loopback handler over a synthetic demo service. Only query outcomes/delays are injected; cookie/header/origin protections remain active. No real histories, credentials or provider polling are involved.

- Failed Claude selection restored Both, the URL, twelve results and USD 49.506. Keyboard Return on Retry then selected Claude and showed six results / USD 20.766, with main content focused.
- A held Codex request removed the old rows and showed loading. Opening the shortcut dialog before completion left Close focused after the query finished; `aria-busy` became false behind the modal.
- Initial 503 showed Usage unavailable, PREVIEW, Snapshot unavailable and No snapshot loaded, with no usage totals. Keyboard Retry recovered the requested Codex query / USD 28.740.
- Two successive synthetic 409s stopped after the one permitted fresh retry, restored Codex results and left the third queued control entry unconsumed. No retry loop occurred.
- A held Claude query followed by Settings navigation did not replace Settings or move focus when the earlier request was released. URL, heading, focus and busy state matched the newer view.
- A failed conversation request restored its Claude parent list. Keyboard Retry opened the requested 830,000-token / USD 6.300 detail; keyboard Back returned to the Claude list / USD 20.766 with main content focused.
- Rendered recovery banner was visually inspected and captured to `dashboard-recovery.png` in this chat's artifact directory. Browser warning/error inspection returned no entries. This is browser UI evidence, not native Figma playback or a complete accessibility audit.

The current working-tree Python suite ran **88 tests in 10.802 seconds: 85 passed, three expected privacy failures**. It includes the separate shared observation edits; it is not an isolated main-baseline or integrated-S06 certification. Those legacy metadata/limit-label failures remain open for S08. Loopback checks ran outside the socket-restricted sandbox. No accounting code changed, so accounting probes were not repeated here.

Late server verification found that the browser cancellation above caused `ConnectionAbortedError` while writing the response; the handler then tried to send another error response on the closed socket. The response helper now closes the connection quietly for broken-pipe/reset/aborted errors at either headers or body. After correcting a missing request-line field in the synthetic test setup, the regression reproduced all six actual write failures before the fix. The **10 focused hub tests passed in 2.827 seconds** afterward. Final full Python verification ran **89 tests in 13.664 seconds: 86 passed, the same three expected privacy failures**. The actual held-query → Settings → release case was repeated against the corrected server: newer view/focus/busy state remained correct, and server output contained only synthetic action names, no traceback.

Final app/formatter syntax and fault-driver syntax/help checks passed. Five changed documents have **38 existing local file link targets**, balanced fences, and passing whitespace checks. The temporary browser tabs were closed and both test servers stopped; test control files remain ignored. The fault driver lives under `windows/tests`, outside the dashboard asset folder copied by the current build script.

## Reproduce only the needed check

From the repository root:

```powershell
node --test windows/dashboard/tests/*.test.mjs
node --check windows/dashboard/app.js
node --check windows/dashboard/format.js
```

For an actual browser fault path, launch this test-only server explicitly:

```powershell
.\windows\.venv\Scripts\python.exe windows/tests/dashboard_fault_server.py --control-dir windows/build/dashboard-resilience --port 8769
```

Open `http://127.0.0.1:8769/#view=explore`. In a second terminal, while no query is consuming the control file, set the next outcomes:

```powershell
Set-Content -LiteralPath windows/build/dashboard-resilience/steps.json -Value '["fail"]' -Encoding utf8
# Other queues: ["conflict","conflict","normal"] or ["hold","normal"].
# Before each hold, remove only this driver's release marker if it exists:
Remove-Item -LiteralPath windows/build/dashboard-resilience/release -ErrorAction SilentlyContinue
# Release a held query (it also times out after 20 seconds):
New-Item -ItemType File -Path windows/build/dashboard-resilience/release -Force | Out-Null
```

Arm a hold before the UI action; create release only after inspecting loading/the newer view. The driver accepts control directories only beneath `windows/build`, is not wired into the application/build, and emits only synthetic action names. Stop with Ctrl+C. Generated control files remain ignored; there is no source-history cleanup.

## Remaining work and next ownership

- **Do not restart this slice:** exact money formatting and the recovery cases above are implemented. Reuse their tests when touching requests or formatting. Rerun normal interaction checks only when a related UI/contract change creates a reason; do not call new simulations fresh browser verification.
- **Completed S07 boundary:** provider scheduling, real stale-limit states, process ownership and artifact retention are recorded complete at `461c3a3` on the separate branch. This dashboard slice does not implement or certify those; use the S07 handoff for its evidence and remaining native lifecycle limits.
- **S08/S09:** final core privacy/diagnostics and packaged release evidence remain pending. No fresh executable build, packaged lifecycle, real-account/history, macOS, remote CI or benchmark was performed here.
- **S11-S14:** persistent snapshots, v1 DTO validation, canonical IDs, revision/query registry, jobs, settings wiring and real-data dashboard integration remain gated. The previous S05 handoff's money-formatting gap is now closed for decimal strings; its other service/index/API replacements remain open. Browser geometry/ticks remain approximate, and full-bound chart label layout was not certified.
- Cross-tab publication, expired-cookie handling, every HTTP/error variant, sustained outage/timeout UX and full keyboard/screen-reader coverage were not exhaustively checked. The preview does not substitute demo data for a failed real connection.
- Commit/push and branch integration are separate scoped actions. Preserve the other agent's shared core files when staging dashboard work.
