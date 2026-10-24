# Usage Hub dashboard implementation and core handoff

Status: functional **demo development preview**. Real-data integration and the S11-S14 release gates remain incomplete. Prepared October 23, 2026, America/Los_Angeles.

## Delivered slice

- Native HTML/CSS/JavaScript frontend adapted from current Figma design context for Overview `2:43`, Explore `2:44`, Detail `2:45`, Limits `2:46`, and Settings `2:47` in [AI Usage Hub](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh). No screenshot is used as application UI.
- Compact dark console with local semantic CSS tokens, the original navigation SVG variants, and locally bundled Geist/Geist Mono fonts with their OFL license.
- Working provider/period/metadata filters, arbitrary project/conversation search, ranked model/project groups, six-row pagination, conversation detail, and Back state preservation.
- Exact token strings with comma-separated thousands and M/B display. The chart has zero-based labeled Y axes and gridlines; its scale follows the largest matched daily bucket and selected metric. Bar heights represent values without an artificial minimum.
- Explicit demo mode: 12 conversations, four projects, 8,920,000 tokens, USD 49.506 at sample rates. Codex is 5,900,000 / USD 28.740; Claude is 3,020,000 / USD 20.766. These are synthetic fixtures, not live rates or user history.
- CLI launcher and demo-tray action preserve existing terminal reports. A packaged dashboard opened normally has a tray owner; Quit shuts down its server. Standalone source mode stops with Ctrl+C.

## Scope and concurrency decision

The starting commit was `854ac73`, with S00 complete and a clean working tree. During dashboard work, another session introduced `usage_records.py`, `usage_observations.py`, `test_observations.py`, and an observation-reader seam in `usage_reports.py`. Those changes belong to the concurrent core work and were preserved.

A provisional overlap/reset fix and shared-renderer changes were withdrawn after this overlap became evident. This dashboard turn does not claim to own or complete S01/S02. The known accounting failures remain core prerequisites; do not infer they were fixed from the preview's passing demo tests.

The user requested dashboard implementation. To allow useful UI development without taking over the concurrently edited core or inventing a competing database, this first slice is an isolated, demo-only preview. This is a development-scope deviation from the otherwise sequential S11-S13 implementation path; it does **not** waive the core, persistence, authentication, or release gates for real-data delivery. The next integration step is replacing the preview adapter with the corrected shared query service after its gates pass and the separately developed database is inspected.

## Boundaries and data flow

1. `usage_tray.py --dashboard --demo` invokes `dashboard_main.py`. Real-data dashboard launch is rejected explicitly. Demo never follows a failed real connection automatically.
2. `HubService` captures one immutable in-memory dataset and one named timezone. All filters, buckets, groups, and details use that snapshot. A rescan publishes a new revision; previous revisions cause a refreshable conflict.
3. `usage_value.py` performs exact Decimal arithmetic for this preview from the core's existing `Record`, `Tokens`, and configured price lookup. It is a temporary service seam, not a second production valuation owner. S04/S05 must consolidate it with terminal/HTML valuation before real mode is enabled. No current report renderer was switched by this dashboard work.
4. `summary_dto()` returns integer-string counters and decimal-string money. Reasoning remains a nullable subset of output. Empty, all-unpriced, partially priced, and priced-zero values remain distinct.
5. The frontend renders the server result and formats units. Browser arithmetic is limited to display, chart geometry, and axis ticks; it does not calculate authoritative token aggregates, prices, or fee differences.

The development endpoints are deliberately named `/api/preview/query` and `/api/preview/rescan`. They are **not** the proposed `/api/v1` contract, persistent index, full job lifecycle, or proof that S12 is complete. A query includes `usage_revision`, a derived `query_context_id`, captured `[start_at,end_at)`, timezone, and pricing version. Query contexts stay stable across page/detail navigation for the same normalized filters and snapshot. Settings are immutable for the process lifetime; persistence and configuration versioning remain core work.

The service has an unexposed local-reader seam and a cached-provider-state adapter for future integration. The shipped CLI/tray dashboard path selects only demo data until the core gates are met. No real usage histories or credentials were read to validate this preview.

## Local access and lifecycle

- Bind only to `127.0.0.1`; exact Host and Origin checks reject alternate/hostile origins. API reads and rescans require an HttpOnly, SameSite=Strict session cookie plus a custom request header. No credential or bootstrap secret appears in a URL or browser storage.
- Serve only an explicit static-file allowlist. Security headers include a restrictive CSP and frame denial; source metadata is HTML-escaped. Request logging is disabled to avoid recording IDs, queries, and cookies.
- Provider polling is absent from the dashboard preview. Existing tray/provider behavior remains independent. Demo Limits is labeled as sample; Settings has no fake Save action.
- Rescans are serialized and have a five-second local-scan cooldown. The failure path retains an earlier snapshot and labels it stale. Persistence/restart recovery is not implemented by an in-memory snapshot.
- An occupied port produces a startup error. Full cross-process ownership/reuse and packaged lifecycle checks remain S07/S14 work; this preview does not claim them complete.

## Verification and limits

The review used the project Python 3.14.5 interpreter, `tzdata==2026.2`, workspace-local TEMP/TMP, and local loopback tests. Sandbox networking denied loopback connections; the same HTTP tests passed outside that sandbox. This was an environment restriction, not a skipped security assertion.

Automated checks cover exact demo expectations, all 12 conversation detail summaries, provider/filter/day reconciliation, empty/unpriced/partial/zero states, large integer token strings, exact money, captured boundaries, a DST fall-back day, revision conflicts, source-failure retention, API authentication/origin/Host rejection, static-file isolation, and the real-mode CLI gate. The Node tests exercise the actual formatter/scale module, including 190,000, 2.84M, 5B, values above JavaScript's exact integer range, and small currency scales.

Actual browser interactions confirmed Claude selection, token metric switching, a day-to-Explore drill-down, matching detail totals, Back with filters preserved, pagination, arbitrary no-match search, clear-filter recovery, Settings, and help/Escape/slash shortcuts. Narrow-width inspection found no page-level horizontal overflow; the conversation table and compact navigation can scroll within their own containers. Image assets loaded at 16 × 16 design geometry. Native Figma presentation playback was not part of these browser checks.

The Windows executable was built with the existing script and exercised using `packaged_dashboard_smoke.py`: demo query and exact totals, bundled UI/icons/fonts, America/Los_Angeles timezone, and the existing saved terminal-demo report. This is a bounded smoke check, not completion of the core or hub release gates. Interactive packaged tray/Quit/restart, real history, persisted settings, database migrations, full provider refresh behavior, CI, macOS, and full accessibility certification remain unverified here.

Final checks: **80 Python tests passed in 8.862 seconds**, including nine new hub tests and the concurrent observation-contract tests; **two Node formatter/axis tests passed**. `windows/build.ps1` rebuilt the final source successfully with installed pinned dependencies and `PIP_NO_INDEX=1`. The final executable smoke checks passed for both dashboard and terminal modes; cleanup verification found no remaining packaged smoke-test process. Markdown links/fences/whitespace, all eight SVGs' 16 × 16 root geometry, JavaScript syntax, and `git diff --check` passed. Browser error/warning inspection returned none. Helper preview servers were stopped after verification; launch commands above remain available for review.

A final run of `docs/review_accounting_probes.py` still printed truncated-first **300 vs 200**, complete-first **200 vs 200**, and reset **200 vs 250**. These failures are why real-data launch remains gated despite the passing preview checks. Source report behavior remains the concurrent core session's responsibility.

Before committing, the staged dashboard files were exported with the committed core baseline into an ignored workspace validation directory. That isolated snapshot passed **66 Python tests in 8.864 seconds**, **two Node tests**, JavaScript syntax, and staged whitespace checks, without the concurrent observation-contract files. The initial sandbox run encountered WinError 10013 on the two loopback tests; the complete rerun with loopback access passed. Two whitespace-only issues in the font license and preview valuation file were corrected. The earlier 80-test result includes the concurrent core tests and is separate from this commit-isolation check. No new packaged build or browser pass was needed for these whitespace-only corrections.

## Next integration steps

1. Let the current core work finish its observation, reconciliation, source-quality/time, exact valuation, shared-summary, settings, reliability, and release gates. The overlap invariant is 200; the reset invariant is 250. Keep these as executable regressions owned by S02.
2. Inspect the user's separately developed database location/schema before adding any storage or migrations. No such schema was found in this checkout; a location was requested during this work.
3. Replace the preview adapter with the authoritative shared service and versioned index/API. Preserve integer/decimal strings, immutable query contexts, quality dimensions, provider scope, and configuration versioning from the integration contract.
4. Enable real mode only after contract/core regression and controlled local-data reconciliation checks pass. Connect persistent settings and cached live limits without browser-triggered polling.
5. Complete packaged ownership, multi-tab/restart, hostile-origin, migration/recovery, and full end-to-end gates before marking S11-S14 complete.

See the [refinement plan](project-refinement-plan.md), [integration contract](usage-hub-integration-plan.md), and [prototype test report](usage-hub-figma-test-report.md) for the controlling requirements and remaining scope.
