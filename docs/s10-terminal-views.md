# S10 — Compact terminal summary and ranked details

Status: **complete**. Version 0.10.0. Scope: Windows terminal expression over the completed core, retaining Agent 2's dashboard. No accounting, price, settings schema, database or API semantics change.

## Existing dashboard and branch checkpoint

The user authorized automatic continuation and clarified that Agent 2's dashboard remains in scope. The refinement branch incorporates `codex/dashboard-core-integration` at `16b7b14` through merge `29f80dc`. Seven dashboard compatibility tests passed in 0.646 seconds; all 22 frontend tests passed. The sole merge conflict was the refinement ledger's status/handoff text; both implementation histories and the final S09 evidence were retained. Other worktrees and original-checkout edits were read-only. Existing dashboard assets, demo API, shared arithmetic delegation and privacy/interaction coverage are reused. Real data remains gated through S11–S14.

## Default and compatibility

`usage_terminal.py` formats one immutable `UsageResult`, using precomputed totals, category/reasoning summaries, group ordering, source states and comparison eligibility. It does not scan logs, poll providers, value events or recompute aggregates. The default CLI/tray text report becomes a roughly 20–30-line summary at 80 columns. It prioritizes selected period/providers/currency, available unmatched-local scope or explicit demo, named-zone half-open range, estimated value or qualified priced subtotal, category counters, full-fee signed comparisons and source/pricing/counter/tier/effort limitations.

Cached input is explained as reused context, counted once and separate from output. Reasoning stays an informational subset of output; missing coverage remains unknown. Live limits are explicitly separate and belong to the active CLI account. The report's captured range end supplies freshness; an offline report does not refresh provider state. Empty/failed-source and all-unpriced states never become an observed zero or a claimed complete account total. Known zero rates/fees retain their meaning.

Existing direct `render_text_report(result)` and `save_report(..., format="text")` calls retain full legacy audit output for compatibility. New programmatic projections use `view="summary"` or `view="details"` and `text_view=...` respectively. CLI and tray explicitly select summary. `--audit` selects full legacy text, including exact counts, groupings, rates, provenance and detailed notes; HTML remains the existing explicit full report. No dashboard calculation or sample total is copied into these views.

## Detail navigation

```powershell
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --report month
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --report month --details model
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --report month --details conversation --page-size 10 --page 2
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --report month --details project --width 40
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --report month --audit
```

`--details` presents one selected group dimension: provider, model, model_effort, effort, project, conversation or day. It uses the core's exact `value_desc` ranking and stable ties. All-unpriced groups follow priced groups, including legitimate priced zero; partial subtotals remain labeled. A page is only a display slice, with full matched headline, page/group counts and explicit navigation hints. It does not narrow the query or enable otherwise ineligible fee comparisons.

Use `--page` (starting at 1) and `--page-size` (1–50, default 10). Omit `--details` to return to summary; use `--audit` for exact full details. This deliberately uses CLI detail modes before introducing a full interactive TUI or external pager. One in-memory result can be rendered across pages without rescanning or changing its time. Separate CLI invocations each capture a new scan; no persisted frozen cross-command query, cursor or in-window Back state is claimed. S12 retains ownership of durable/frozen dashboard query contracts.

Terminal options require `--report` and effective text format; add `--report-format text` when HTML is the saved preference. Invalid widths, sizes, modes and pages fail safely. Format conflicts are rejected before a requested settings save. Rendering validates before creating a generated file, preventing an invalid page from leaving an empty automatic report. These view choices are temporary; existing fee/root/rate/timezone persistence is unchanged.

## Display and privacy

Width defaults to 80 columns, selectable 40–160. Display-only token abbreviations match the existing dashboard: exact integer/Decimal operations, half-up rounding to two places for M/B, trailing zeros omitted and M-to-B carry. Accounting remains exact; USD retains the existing shared money formatting/rounding. Long labels wrap by Unicode combining/East-Asian cell widths after terminal controls, bidi and format controls become visible escapes. Arbitrary metadata never becomes a control sequence. This approximation does not certify every terminal font or emoji grapheme width.

Project paths use basenames plus existing digests and conversation labels use existing metadata projections. Explicit `--include-metadata` reveals full supported path/ID labels, with a sharing notice. It does not change internal canonical identities, grouping, filters or counts. Reduced labels remain metadata, not anonymization. Compact views bound ordinary summary verbosity without silently dropping quality counts; full issue/rate/model details stay in audit. Extreme numeric/label/quality cases may need extra wrapped lines; the one-screen target is approximate, not a reason to hide limits.

## Verification and remaining gates

Nine focused tests passed in 8.376 seconds before the final render-before-write guard: normal summary size/width and exact 2,905,000-token/USD18.891 fixture; every grouping/page retaining the full context; empty/unpriced/partial/zero; source/counter/rate separation; hostile Unicode/controls/long metadata; dashboard-compatible abbreviations under a low-precision caller context; provider/null-fee/filter/period guards; legacy audit compatibility and real CLI summary/detail/page/audit/error/recovery commands. Early fixture assertions were corrected for display wrapping, and token display was aligned with the existing dashboard's half-up policy; no accounting expectation changed.

The combined full suite passed **281 tests in 92.693 seconds**; Windows build succeeded and all **18 expanded executable cases passed**. Fixed demo render measurements: summary **26 lines / max 72 cells**, model detail page **34 / 73**, 40-column project detail **60 / 40**, legacy audit **125 / 508**. All retain 108,000 tokens / USD 0.265800000000. Mandatory accounting comparisons inspected at 200/200, 200/200 and 250/250; all three strict privacy probes passed. Four Markdown files / **54 local links**, six Python parses and `git diff --check` passed. The packaged dashboard check passed: **8,920,000 / USD 49.506 / 12 conversations**, bundled local UI/icons/fonts and named timezone; terminal demo, build identity, report/config diagnostics and mixed-mode guards also passed. No browser was opened. [CI run 40122961321](https://github.com/samuelhateseconomic/Codex_Claude-usage-menubar/actions/runs/40122961321), revision `62089dec8d79aecdf1a143fa992d20317f3665a2`, passed all four Windows jobs: Python **3.11.9 / 3.12.10 / 3.13.16 / 3.14.9**, **281 source tests**, **18 executable cases**, **22 frontend tests**, packaged dashboard compatibility and artifact upload in each job. Inspected logs confirm each result. Final evidence changes are documentation-only. Native terminal UI automation/playback, tray menu interaction, screen-reader behavior and arbitrary emulator/font coverage are not claimed. CLI subprocess interaction and source simulations are reported separately. The existing dashboard remains a demo preview until its real-data gates pass.
