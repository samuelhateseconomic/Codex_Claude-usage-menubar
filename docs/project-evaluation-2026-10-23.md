# Usage Tray: product and engineering evaluation

Reviewed October 23, 2026, America/Los_Angeles. Scope: the current working folder, including the recent local pricing and terminal changes. Windows is the primary target. macOS findings are source inspection only; the Swift app was not built or run on Windows.

## Overall assessment

The project has a useful, reasonably small foundation for a personal usage monitor. The Windows adapters, normalized token categories, independent provider refresh, offline reports, and existing tests are worth keeping. Its main weakness is that the reporting experience grew by adding information rather than deciding which question the first screen should answer.

For your use, the primary question should be: **What would my recorded usage cost at API token prices, and how does that compare with my $20 Codex and $20 Claude monthly plans?** Remaining subscription capacity is a second question. Project, conversation, model, and effort analysis are explanations of those answers, rather than equally prominent first-screen content.

The terminal clutter is real, but a presentation rewrite alone would be insufficient. Two isolated probes also reproduced accounting edge cases absent from the passing test suite. I would fix those before expanding the interface or calling the estimates dependable across arbitrary imported histories.

## Evidence and limits

One month-to-date scan of the local logs took **0.942 seconds** and produced **3,649 usage records**, **3 models**, **9 provider/project groups**, and **32 provider/conversation groups**. These counts change as work continues. This is one measured scan, not a general performance benchmark.

The generated text report contained **352 lines**, of which 343 were nonempty. Even the small demo report contained **120 lines**. About **96.70% of recorded tokens were cache reads**, and **97.43% of tokens had configured rates**. That last percentage measures token coverage, not the percentage of dollar value known and not a confidence score.

All **57 existing Windows tests passed** during this review. Additional synthetic probes exposed two failures described below. The review did not perform a fresh comparison of live quota readings against provider websites, a Windows terminal usability session, a macOS runtime test, or a comprehensive security audit. Token and report measurements came from the report functions; no prompt content or raw local logs are included in this document.

## What the functions currently provide

### Live subscription limits

`windows/usage_core.py` obtains Codex limits through a short-lived local CLI app-server and Claude limits through the existing Claude login and usage endpoint. It normalizes quota windows into remaining percentages and reset times. This answers how much allowance remains for the **active CLI account**, independently of token reports.

The design has useful safeguards: bounded RPC waits, child-process cleanup, independent provider workers, backoff, preservation of previous successful readings, and explicit stale-data messages. Claude redirects are rejected, and the Windows adapter does not write or refresh Claude credentials.

### Local token accounting

`windows/usage_reports.py` reads local JSONL histories, extracts token metadata, computes Codex cumulative deltas, merges streamed Claude message updates, and groups results by provider, model, effort, project, conversation, and day. Cached input is separated from uncached input; reasoning stays a subset of output. These choices avoid common double-counting mistakes.

Reports may cover several accounts represented in the local folders. Browser conversations, other computers, absent logs, and remote work without local records are outside the measured scope. A report and a live quota reading must not be presented as an account-matched pair unless that relationship is actually established.

### API-equivalent estimates and plan comparison

Recorded token categories are multiplied by configured model rates. Unknown models remain unpriced. The recent changes correctly avoid displaying fully unpriced usage as a zero-dollar estimate. The monthly comparison subtracts the selected providers' monthly fees from the priced value so far.

This is a counterfactual comparison, not a bill or proof of money actually saved. The current period is the **calendar month**, not necessarily the subscription billing cycle. The applied rates are a bundled/configured snapshot, rather than historical rate schedules.

### Presentation and delivery

`windows/usage_tray.py` supplies the tray menu and report generation. A text report is saved, then PowerShell displays it with `Get-Content -NoExit`. This is a static text dump: it has no in-report filtering, paging, navigation, or live refresh. Each report action opens another window and creates another saved report.

The project also has an HTML exporter and a separate Swift macOS application. Windows packaging uses PyInstaller; the GitHub workflow tests and builds on Python 3.12, while the most recent local build used Python 3.14.5. They are related products with different capabilities, rather than one shared cross-platform implementation.

## Findings in priority order

### P1 — Overlapping copies can inflate Codex totals

**Confirmed with an isolated synthetic reproduction.** In `windows/usage_reports.py`, `read_codex()` resets its cumulative baseline for each file, then deduplicates emitted deltas using `(session, cumulative counters)` and `records.setdefault()`.

Suppose a complete file records cumulative input totals 100 and 200. Another, truncated copy of the same session contains only the final total 200. When the truncated file is scanned first, its 200-token delta is retained. The complete file later contributes another 100-token delta. The final result is **300 tokens although the session total is 200**. Reversing file order produces 200. No notice was generated in the failing case.

This does not prove your present local total is inflated: I did not establish that your histories contain this shape. It does prove the importer is not invariant to overlapping file copies, and existing exact-copy tests do not cover it.

**Recommendation:** establish canonical cumulative observations per provider/session before converting them to deltas. Reconcile overlapping observations by timestamp, counter sequence, and available provenance; flag irreconcilable conflicts. Verify that file order and exact or partial copies do not change the result. Simply adding file names to deduplication keys would preserve duplicates rather than solve the problem.

### P2 — A reset can silently discard later valid usage

**Confirmed with an isolated synthetic reproduction.** For cumulative input counters `100 -> 200 -> 50 -> 100`, the reset interval is intentionally excluded and reported as ambiguous. The later increment from 50 to 100 is still a valid 50-token increment, but its numeric final total collides with the earlier `(session, 100)` key.

Expected retained usage is **250 tokens after excluding the ambiguous reset interval**; observed usage is **200**. The reset warning does not explain the additional dropped increment.

**Recommendation:** preserve reset epochs/sequence identity in the normalized accounting model, distinguish duplicate observations from a later recurrence of the same numbers, and add a regression fixture for resumed counting after a reset. Epoch identity must also work consistently when histories overlap across files.

### P1 product priority — The summary does not have a clear hierarchy

`render_text_report()` expands Provider, Model + effort, Project, Conversation, and Day consecutively. Every group repeats several token-category lines. Groups are sorted alphabetically rather than by contribution to API value. A small number of conversations therefore becomes hundreds of lines.

These sections are different views of the **same usage**, not additional usage, but the repeated totals are easy to misread as independent amounts. The first screen also introduces raw token totals before explaining that nearly all observed token traffic is cached context.

**Recommendation:** make the default report about 20–30 lines, with the selected period, estimated API value or priced subtotal, monthly plan fees, signed comparison, pricing coverage, and freshness visible without scrolling. Show abbreviated units such as `470.1M recorded tokens` and `96.7% cache reads`; full counters belong in details. Use two decimal places for summary USD. Keep additional decimal places in an audit view when useful.

### P2 — Coverage and scope need first-class states

Coverage currently appears mainly in notes and appended phrases. Those notes can be hundreds of lines below the initial totals. Several different states are involved: no local records, unknown model rates, unreadable files, skipped counter intervals, unknown effort, and unavailable reasoning counters.

**Recommendation:** use a structured coverage object with separate flags and counts. Show `Local logs / all accounts`, `Priced subtotal`, `Unpriced tokens`, and `Last scanned` beside the headline. Display quota scope as `Active CLI account`. Do not collapse these into a single percentage or claim account-wide completeness. Keep missing effort distinct from missing token counts or prices.

### P2 — Pricing provenance needs a maintained contract

The previous zero-dollar problem demonstrated that exact model coverage can become stale while arithmetic tests remain green. The current strict unknown-model handling is preferable to silently guessing a price.

There is also a modeling limitation to verify: context-tier pricing is request-based, but `estimate()` receives a usage record derived from a cumulative delta. A delta spanning several requests or a missing baseline does not automatically establish a single request's context size. This is a design risk; this review did not prove a specific incorrect context-tier charge in your live data.

**Recommendation:** version the rate catalog, retain exact model and rate source/as-of metadata, and test each observed supported model explicitly. Preserve request-context evidence separately from aggregate token counters where logs provide it. Mark tier assumptions when that evidence is missing. Expose custom rates in settings, and label estimates as using current/configured rates rather than historical invoices. Models with no public/configured rate should stay unpriced.

### P2 — Report logic, aggregation, and formatting are too intertwined

The broad split between provider adapters, local reports, and the tray is useful. Within `usage_reports.py`, parsing, deduplication, valuation, comparison, grouping, text layout, HTML strings, and output files still share one module. Multiple render paths recompute related summaries, and `plan_comparison()` returns already-formatted text that HTML must wrap back into paragraphs.

**Recommendation:** define one typed report result containing totals, ranked groups, comparison amounts, and coverage. Render text and HTML from that same result. Keep formatting out of accounting. This gives tests one consistent place to validate the numbers and reduces disagreement between views.

### P2 — Static report windows and generic errors impede normal use

The terminal is currently a file viewer, rather than a small interactive application. It stays open at a PowerShell prompt after printing. There is no way to select a project, switch period, or refresh in place. Broad exception handling reports most report failures as log/output permission problems, even if the cause was parsing, rendering, or starting PowerShell.

**Recommendation:** start with a compact report plus explicit detail modes and a pager, or add a small keyboard-driven terminal interface if you want navigation in one window. Reuse one report window where practical. Provide errors with a safe category and useful next action; retain redacted diagnostics locally. Do not include credentials or prompt text in diagnostics.

### P2 — Configuration and build identity are too implicit

Your $20 fees are defaults in both report data and CLI setup. The executable has no normal settings flow for changing fees, choosing billing dates, or selecting detail level. Runtime identity still contains `0.1.0`, and there is no visible application build/rate-catalog identity to help distinguish a stale running executable from a new build.

**Recommendation:** one validated local settings file with $20/$20 as initial defaults; persist report preference, fee changes, and optional billing anchors. Add an About/status line containing build version and rate catalog date. Verify the supported Python versions in CI rather than inferring coverage from a single local runtime. Keep a packaged-executable smoke test in the release workflow.

### P3 — Optimize measured work before introducing infrastructure

Report actions rescan applicable log files; the provider workers also redraw the icon/menu roughly once per second even though network fetches are much less frequent. Saved reports and uniquely named build directories have no automatic retention policy.

The measured scan was under one second, so a database is not the first solution to the current problem. The main immediate cost is information overload, not a demonstrated indexing bottleneck.

**Recommendation:** redraw on meaningful changes, bound generated-report retention, and offer cleanup controls. Add file-level caching or SQLite only after larger histories show a real need, with rotation/truncation/overlap correctness tests before incremental indexing is trusted.

### P2 cross-platform — macOS and Windows do not share accounting policy

Source inspection of `SessionReports.swift` shows substring-based price matching with a default price for unknown names. Windows uses exact/snapshot matching and an explicit unpriced state. The Swift transcript parser also keeps the first seen message identity, while Windows merges streamed usage maxima. This can produce different results for the same kind of history.

This is a consistency finding from source, not a measured macOS failure. The macOS outside-Claude-Code estimates additionally use quota calibration, which is a different estimation method from the Windows local-token report.

**Recommendation:** share a documented rate/normalization contract and cross-language fixture expectations before advertising consistent cross-platform numbers. Keep quota-based inference separate from observed local token values. A shared data specification is more valuable than forcing both UIs into one framework.

## Recommended terminal experience

The default view should answer the value question in one screen. Use this order:

1. Period and scope: month-to-date, local timezone, usage recorded on this computer, all local accounts.
2. Dominant metric: estimated API value when fully priced; otherwise priced subtotal.
3. Compact provider rows: Codex and Claude values, $20 monthly fees, and signed differences. A combined row follows when comparable.
4. Coverage: unpriced-token count/models, skipped-data indicator, and last scan time. Do not bury an incomplete-estimate warning.
5. Explanation: cache-read share and a brief statement that repeated cached context is still recorded token traffic, not uniquely generated text.
6. Detail choices: models, projects, conversations, rates, export. Show one grouping at a time, sorted by estimated value by default.

Do not put full project paths, UUIDs, effort-source strings, every day, and all rates on the first screen. Shorten identifiers for display and allow an explicit full-detail/copy view. Unknown values need short consistent labels, with explanations in the relevant detail view.

Live limits should be a separate compact view: remaining percent, each window's reset time, last successful check, and next permitted retry. Keep the existing independent refresh and backoff behavior. Never combine percentages into a fictional overall balance.

For your preference, keep the tray as an entry point and use a lightweight terminal presentation. First deliver compact output and paging. Introduce a fuller terminal UI only if in-window navigation is useful. There is no need for a browser server, React frontend, cloud storage, or a new authentication system to solve this usability problem.

`docs/usage-hub-plan.md` proposes a future local web dashboard. It is a plan, not an implemented frontend. Its data-boundary guidance is useful; its browser-first delivery is a separate product choice and should not override your stated preference for a terminal.

## Suggested internal design

Preserve two independent data paths:

```text
Local log files
  -> provider-specific observations with source provenance
  -> session reconciliation and reset-aware deduplication
  -> normalized usage records
  -> rate lookup and per-record valuation
  -> report service: totals, ranked groups, comparison, coverage
  -> compact terminal / detail terminal / optional HTML export

Provider quota sources
  -> existing adapters and polling policy
  -> active-account limit snapshot, freshness, retry state
  -> tray / terminal limits view
```

Proposed report fields include `period_start`, `period_end`, `timezone`, `account_scope`, `generated_at`, `tokens_by_category`, `priced_value_usd`, `priced_tokens`, `unpriced_tokens`, `skipped_intervals`, `models`, `plan_fees`, `comparison_kind`, and rate-catalog identity. Use structured `available`, `partial`, and `unavailable` states for valuations. Preserve unknown usage rather than converting it to zero.

Keep Python, the current provider adapters, and PyInstaller. Split modules by responsibility only as behavior moves; avoid a large rewrite merely to obtain more files. A shared report service should be usable without importing tray libraries or contacting a provider.

## Delivery order and acceptance criteria

### First: accounting invariants

Add the two reproductions to the regression suite and fix them with one coherent reconciliation policy. Test input-order independence, exact and overlapping copies, counter resets, model/effort changes, and repeated post-reset totals. Verify that category totals reconcile and partial coverage cannot become a zero-dollar estimate.

Complete when both demonstrated cases produce the correct values independent of file order, existing tests still pass, and intentionally excluded intervals are explicit.

### Second: compact report and one source of totals

Extract a typed summary/coverage result, then render a concise default report and opt-in details. Keep a full export for investigation.

Complete when the primary comparison and coverage fit within about 20–30 terminal lines at a normal 80-column width, details do not repeat every other grouping, and provider/group totals reconcile to the same summary object. Verify narrow-width and Unicode/path behavior with representative fixtures.

### Third: settings and operational clarity

Add persisted fees, period preference, optional billing anchors, price catalog information, actionable error categories, freshness/retry displays, and report retention.

Complete when changing a fee survives restart, the comparison period is explicit, a stale build can be identified, and missing login/logs/prices lead to distinct useful states.

### Fourth: interaction and release polish

If compact output is still awkward, introduce a small terminal UI with period/provider selection, sorted drill-down, keyboard navigation, and refresh in place. Add packaged smoke checks and cross-platform fixture parity before wider distribution. Measure large-history behavior before choosing storage/indexing work.

## Recommendation

Keep the existing foundation. Fix the accounting edge cases first, then replace the expanded diagnostic report with a summary-first terminal experience. This directly addresses both your need to trust the estimate and your preference for a simple, low-overhead interface.

The passing arithmetic tests and earlier real-log smoke checks remain useful evidence, but they establish narrower properties than complete accounting correctness. In particular, the new probes show why model-price correctness and large token totals alone are insufficient release criteria.

## Source references

- `windows/usage_core.py:124` — RPC lifetime and protocol; `:235` — Codex adapter; `:254` — Claude adapter.
- `windows/usage_reports.py:91` — price matching; `:101` — valuation; `:113` — unavailable/partial dollar display.
- `windows/usage_reports.py:185` — log discovery; `:226` — Claude message merging; `:290` — Codex deltas and identities.
- `windows/usage_reports.py:375` — periods; `:401` — collection; `:425` — plan comparison.
- `windows/usage_reports.py:464` — HTML rendering; `:554` — terminal rendering; `:634` — saved reports.
- `windows/usage_tray.py:30` — PowerShell report opening; `:45` — refresh state; `:95` — tray/report lifecycle; `:193` — recurring redraw; `:217` — fee defaults.
- `windows/tests/test_reports.py:153` — exact-copy coverage; `:242` — 400M-token arithmetic test; `:287` — reset warning coverage; `:407` — mocked terminal-launch check.
- `SessionReports.swift:36` — macOS rate matching; `:109` — first-seen transcript deduplication; `:163` — inferred outside usage.
- `.github/workflows/windows-usage-tray.yml:25` — CI Python version; `windows/build.ps1` — packaging workflow.
- `docs/usage-hub-plan.md` — separate proposed web-dashboard direction.

The confirmed synthetic reproductions are retained in `docs/review_accounting_probes.py`. They are diagnostic evidence, not production changes or additional passing regression tests.
