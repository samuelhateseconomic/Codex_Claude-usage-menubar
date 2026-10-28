# Dashboard refresh: reviewed desktop design to production

Status: **B3-01–B3-06 implemented and automated Windows acceptance verified in 0.16.0**. Prepared October 27, 2026, America/Los_Angeles. The subsequent user request authorizes replacing the Windows dashboard under AGENTS.md. Figma changes, macOS, real installation, commit and push remain outside this request. Native/distribution checks retain their separate S14 limits. See the latest [implementation ledger](project-refinement-plan.md#plan-b--windows-dashboard-replacement-implementation-october-27-2026) for evidence, earlier failures and final fixture timings.

## Ownership and starting point

This is the implementation sequence for [Plan B's B3 desktop requirements](credit-calculation-plan.md#b3--compact-dashboard-verification-and-delivery). It supersedes older dashboard layout proposals and the former USD/app-credit switch/mobile proposal. It preserves the completed [D01–D04 work](dashboard-refinement-sessions.md), [B1/B2 calculation foundation](b1-b2-calculation-foundation.md), Plan A accounting/freshness acceptance, and S11–S14 implementation evidence. Their recorded tests are historical evidence, not fresh acceptance of this refresh. S14's remaining native/distribution checks remain open.

The [main refinement plan](project-refinement-plan.md) owns priorities and the ledger. The [integration contract](usage-hub-integration-plan.md), [S12 API contract](s12-local-api.md), and B1/B2 own data semantics. The [current prototype report](credit-feature-figma-prototype.md) owns the reviewed visual decisions. Later confirmed user decisions take precedence over historical open questions.

Read-only planning inspection covered the production HTML/JavaScript entry points, query service, credit export, pricing explanations and the above documents. Current Figma design context and screenshots were obtained for [Overview `2:43`](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-43), [Explore `2:44`](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-44), [Settings `2:47`](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-47), and [Estimate methodology `101:1138`](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh?node-id=101-1138). Detail `2:45` and Limits `2:46` remain reference screens to reinspect before their implementation. No Figma changes or running-dashboard browser acceptance occurred during planning.

## What exists and what changes

- Keep the production entry point [local.html](../windows/dashboard/local.html), [local-app.js](../windows/dashboard/local-app.js), [local-session.js](../windows/dashboard/local-session.js), [local-view.js](../windows/dashboard/local-view.js), and the `v1-*` modules. Retain native HTML/CSS/JavaScript, local Geist fonts, SVG assets and existing CSS tokens. No React/Tailwind migration or new chart framework is justified by this refresh. Shared `style.css` changes must be scoped so the explicit demo remains functional.
- Reuse the exact Python valuation, `UsageResult.credits(...)`, existing immutable group memberships, SQLite publication, authenticated local service, jobs, provider cache and native launcher. [usage_credit_contract.py](../windows/usage_credit_contract.py) is a headless export; it does not already supply dashboard credit routes or paginated conversation credit DTOs.
- The current Overview has USD/tokens/conversations/projects and a two-metric chart. Replace the conversations stat with app credits, retain four stats in the confirmed order, and add the third metric. Its capacity card currently shows provider state; connect the confirmed five-hour bars to cached limit readings. The existing limits projection already includes `duration_minutes`, remaining percent and reset timestamps, so window identity does not require a new provider integration.
- Explore currently uses the same navigation selection as Overview, supports Both providers and renders a table with applied-rate rows. Give it independent app-focused state, three totals, model/project pies, a full-width daily chart, aligned history and the bottom methodology panel. Preserve detailed evidence through expandable sections and detail routes.
- Separate provider fees, auto/manual timezone, Save/Cancel, publication feedback and failure handling already exist. Restructure and verify these controls; do not implement a second settings authority or discard D01's reliability work.
- Keep the existing detail and Live Limits behavior, accounting evidence, terminal/tray access and explicit launch. Apply only shared visual consistency, credit disclosure and navigation changes required by this refresh. Remove descriptive page-header subtitles; retain essential scope, freshness, failure and estimate qualifications.

## Confirmed behavior to implement

### Scope, units and query identity

- Overview supports Both/Codex/Claude. Explore requires exactly Codex or Claude. Both pages calculate the selected provider's primary model only, retaining every other canonical event in storage. Initial exact identities follow the reviewed design: Codex `gpt-6.1-sol`, Claude `claude-opus-5-5`. This is an explicit, versioned query policy, not automatic selection of the newest, most-used or most-expensive model. No matching model produces an empty selection; do not silently broaden it. Refresh the approved mapping only through a separately documented policy change.
- A Both query means `(Codex AND its selected model) OR (Claude AND its selected model)`. A global provider list crossed with a model list is insufficient. Apply selection to accepted events before aggregating mixed-model conversations. The matched conversation detail must not include excluded model activity in its headline.
- Publish API-equivalent USD and `app_api_value_credit` simultaneously. One app credit is exactly USD0.01; the Python service normalizes already-authoritative USD event amounts without another internal rounding step. Do not calculate financial amounts, category charges or monetary percentages in JavaScript. Numeric projections may drive chart geometry only; exact values, labels and shares come from validated server results.
- Native Codex credits stay a separate unit/service capability. This refresh does not add a native-credit chart, guess past speed, or establish a Claude subscription conversion. No amount is actual billing, consumed subscription allowance or remaining provider credits.
- Freeze dataset/usage/pricing/configuration versions, captured clock, resolved named timezone, primary-model mapping version, projection/unit definition and valuation policy in query identity. Context/speed assumptions remain independent. Preserve `Below-threshold context assumed`, contrary recorded evidence, Standard API-equivalent basis and rate provenance.
- Whole-query summaries, pies, daily buckets and methodology cover every matched event, independently of history/legend/rate-detail pagination. A new publication notice cannot silently replace displayed results or settings drafts. Explicit Update view captures a coherent replacement; failed loads retain labeled accepted results. Existing expiry/revision recovery must never mix widgets from different contexts.

### Overview

- Keep the reviewed arrangement and dark outline. Four simultaneous stats: **ESTIMATED API VALUE**, **ESTIMATED APP CREDIT**, **RECORDED TOKENS**, **PROJECTS COUNTED**. Labels use the same uppercase 12px Geist Regular muted style. Exact amounts remain available; small nonzero values must not look like recorded zero.
- Retain Today, Last 7 days, Month to date using real local boundaries, including cross-month weeks and DST. Daily metrics are API value · USD, App Credit and Recorded tokens. All have labeled axes/gridlines and a zero baseline; USD includes `$0`. Bars have flat bases, small top corners and no artificial minimum height. Scale follows the largest matching day.
- Capacity shows only explicitly identified five-hour windows from active CLI accounts, with 12px remaining bars, reset time and last-success/refresh state. Select the window from normalized duration evidence, not list position, a reset countdown or arbitrary label matching. If that identity is absent, display five-hour capacity unavailable; do not substitute weekly capacity. Keep stale/login-required/blocked/cooldown states. Navigation and historical filters do not poll providers or change this account scope.
- Keep one All live limits action inside Capacity. Retain model/project breakdowns and explicit drilldowns. Show configured fees as USD context; full-fee comparison is unavailable under the primary-model filter. Preserve eligible unfiltered comparisons for existing consumers rather than removing their core behavior.

### Explore

- Maintain page-local provider, project, primary model, effort, period, selected day, metadata search, metric, sort and pagination. Entering from Overview must not overwrite existing Explore state. An explicit project/model/day drilldown creates a visible derived Explore selection, preserves its prior state for Back, and never changes Overview implicitly. For a Both-provider project link, retain Explore's selected provider and identify that provider scope; never create a hidden Both selection. Limits provider links are likewise explicit actions.
- Show Total tokens, API value · USD, and App credits above the two equally sized pies. Model share is 100% only when a nonzero selected metric has a valid denominator in the single-model query. Empty/unpriced monetary results use an unavailable neutral ring; a fully priced zero result is labeled zero with no percentage. Project shares use the same matched query. A selected project is 100% only with a valid denominator. USD and app-credit shares coincide by definition.
- Calculate shares in Python over all matched projects, not the current history page or Overview's top ten. Bound the rendered legend/slices and include an explicit Other group for any omitted projects, retaining exact totals and a drilldown. Partially priced monetary pies identify the priced-subtotal denominator and uncovered tokens; they never imply complete monetary coverage. Token pies include all accepted matched tokens regardless of pricing coverage.
- Place the full-width daily chart below the pies, then history with aligned project/chat, model, app credits, USD price, tokens and unestimated-token columns. Preserve sorting, paging, exact identities, keyboard activation and detail/Back position. Remove duplicated input/output/reasoning cards and repeated full rate tables from every visible row; retain access to evidence in methodology/details.
- Unestimated tokens are accepted recorded tokens in uncovered/unpriced matched records, supplied by the authoritative service. Unknown missing usage remains unknown. No invented skipped count or missing-credit amount.

### Estimate methodology and Settings

- Reproduce the reviewed methodology composition: paired Token breakdown / Calculation basis cards, exact USD/app-credit result strip and compact Coverage footer. Use real data rather than prototype constants, fixed October dates or Figma calculation variables. Preserve the desktop proportions while allowing content height and horizontal table scrolling for actual data and narrow desktop widths.
- Show uncached input, cache reads, separate five-minute/one-hour writes and output, with count, USD-per-million rate and contribution. Reasoning is nullable, a subset of output and never an extra charge. Explain input = uncached + reads + both writes; total = input + output. Existing rate explanations distinguish unrounded category contributions from per-event rounded results: show the aggregate rounding adjustment so category contributions plus adjustment reconcile exactly to authoritative USD. App credits use those authoritative amounts.
- One primary model can still have multiple rates, overrides or source policies. Show Mixed rates with bounded/paginated expandable groups; do not invent an average rate. Keep unknown rates unavailable, covered zero distinct, and nonzero writes visible and correctly valued. Preserve provenance, checked/effective-date limitations, context/speed assumptions, unpriced reasons, reasoning coverage, retained-source status and unsupported non-token charges.
- Restyle Settings as separate Codex/Claude USD fee cards plus report-timezone controls and shared Save/Cancel. Preserve arbitrary validated entry, blank versus zero, version conflict, draft recovery and durable Saving/Applying/Applied/failure feedback. Real configured values win over the Figma USD20 examples.
- Preserve `auto` and manual named-zone configuration; label UTC fallback. Resolve the zone before freezing new day/month boundaries. Applying a change must invalidate/recreate affected query contexts coherently, retain each page's filters, and explicitly notify the user rather than rebin old frozen results in place. System timezone changes while `auto` is active take effect on a new capture, not within an existing result.

## Implementation sequence and gates

Work one requested session at a time. Sessions have different sizes; no equal-effort or calendar promise is implied. Each records exact checks, limitations and the next dependency in the main ledger. B1/B2 and D01–D04 are reused, not reopened as unfinished tasks.

### B3-01 — Credit-aware dashboard contract and authoritative query scope

Status: implemented; focused Python/API/Node contract gates passed. Depends on the existing B1/B2 foundation.

- Preserve the backward-compatible opt-in `projection=app_api_value_v1` on the existing authenticated usage routes, now implemented with [the frozen B3 contract](b3-dashboard-contract.md). Existing requests without the selector keep their current DTOs. Python schema, fixtures, `v1-schema.js`, `v1-client.js` and validation change together; the CLI export remains a separate headless contract.
- Extend existing query/context handling for the versioned provider/model mapping and credit identity. Reuse `UsageResult.credits(...)` and accepted event memberships for overview, analysis, conversations/projects, details and events. Add a bounded whole-query analysis projection for complete project/model shares and methodology; never fetch all history pages in the browser to reconstruct totals. Freeze exact wire shapes, group paging and resource bounds in the session contract before wiring views.
- Inspect the current SQLite codecs/publication first. Prefer derived app-credit projections from the committed USD values; no redundant credit table or migration is expected. Any demonstrated persistence need requires an explicit transactional migration/recovery rationale. Reuse cached limit duration evidence; extend its allowlisted projection only if the five-hour identity is missing from the existing wire DTO.
- Gate: Python/API/Node fixtures prove exact whole-query/day/detail agreement, provider/model pair selection, mixed-model conversation exclusion, projection compatibility, malformed/bounded payload rejection, old-index recovery, reprice/restart and changed-policy/context/cursor isolation. Missing provenance, empty/unpriced/partial/zero and unsupported writes remain distinct. No UI may consume a field before this gate passes.

Likely files: `usage_service.py`, `usage_api_query.py`, `usage_api_contract.py`, existing API dispatch/limits modules as needed, credit/pricing projection helpers, [v1 schema](api/usage-hub-v1.schema.json), and `windows/dashboard/v1-*` plus matching Python/Node fixtures. Extend existing storage only if inspection proves necessary.

### B3-02 — Independent page state and coherent loading

Status: implemented; mounted-handler and real API interaction checks passed. Depends on B3-01.

- Refactor existing location/session state into independent Overview and Explore selections and captured contexts. Keep settings drafts, detail origin, scroll/focus, sort/cursors and explicit drilldown provenance. Do not introduce a second query engine or polling owner.
- Migrate existing dashboard hashes defensively: valid old links restore supported values; invalid/provider-Both Explore links resolve to a visible single-app selection without discarding historical data. Persist page state across ordinary navigation, browser Back/Forward and reload without storing prompts, credentials or raw query graphs. Document which state belongs in URL/history versus runtime memory; capture a fresh query after reload/expiry rather than pretending a lost server context survived.
- Keep request cancellation, obsolete-response rejection, failure retention, publication notices and explicit Update view. Changing metric alone uses the same accepted result; changing filters creates the corresponding frozen query and resets only its paging. Shared settings changes require coordinated context invalidation without merging page selections.
- Gate: actual mounted handlers and session tests cover alternating pages/providers, explicit drilldowns, independent reset, detail/Back/Forward, reload, failed requests, out-of-order replies, expiry/revision change and unsaved drafts. Exact displayed quantities must come from one accepted bundle per page.

Likely files: `local-app.js`, `local-session.js`, `local-freshness.js` only if needed, client/state fixtures and integration tests.

### B3-03 — Overview and five-hour capacity

Status: implemented; rendered desktop and browser interaction checks passed. Depends on B3-02.

- Implement the four stats, three daily metrics, real date options, reviewed labels/flat bar bases, model/project rows, single capacity action and five-hour cached bars. Reuse fonts/assets/tokens. Preserve production freshness/authentication/operation controls even when they are absent from the synthetic mockup.
- Gate: rendered comparisons at the reviewed desktop width and narrower desktop widths; actual provider/date/metric and explicit drilldown interactions; axis/zero/tiny/large values; remaining bars at 0/50/100%; missing five-hour versus weekly-only, stale, blocked and failed states. Bars and labels agree; token/USD/app amounts reconcile with the service. No provider polling occurs from view navigation.

Likely files: `local-view.js`, `local-app.js`, scoped `style.css`, existing chart/format helpers and display/integration fixtures.

### B3-04 — Explore totals, pies, daily chart and history

Status: implemented; full-result display and browser interactions passed. Depends on B3-02; integrate after B3-03's shared chart primitives stabilize.

- Implement the single-app filters, three totals, paired pies, full-width three-metric daily chart and aligned paginated history. Use the authoritative analysis projection, primary-model policy and independent page state.
- Gate: provider/project/effort/search/day/date/metric intersections, no matches, zero denominators, partial/unpriced usage, nonzero tiny amounts, many-project Other reconciliation, more history than one page, cross-month weeks, daylight changes, detail/Back and page isolation. Validate model/project percentages against exact server totals; histogram, pies, history whole-query summary and headline agree under the same context.

Likely files: `local-view.js`, chart render helpers extracted only where reused, scoped `style.css`, `local-app.js` and API/frontend fixture tests.

### B3-05 — Methodology, settings and cross-page consistency

Status: implemented; category/settings/browser checks and the combined executable gate passed in 0.16.0. Depends on B3-03/B3-04.

- Build the bottom methodology panel with category counts, rates/contributions, grouped evidence, rounding adjustment, exact results and coverage. Keep Data details initially closed and essential qualifications visible.
- Restyle existing fee/timezone controls, remove descriptive page subtitles, and align detail/Live Limits with the shared shell. Preserve existing arbitrary inputs, publication/failure feedback, rate evidence, matched-versus-lifetime scope and active-account separation. Settings' lower position on the Figma canvas is editor organization, not an application page offset.
- Gate: real nonzero reads/writes and reasoning known/unknown/partial; mixed rates/overrides; missing provenance; exact contribution-plus-adjustment agreement; USD/app tiny/zero/unavailable states. Save distinct fees, Cancel, invalid/conflicting/failed/pending saves, restart, `auto` fallback/manual timezone and boundary rebinning in an isolated runtime. Test keyboard/focus, long labels and narrow layouts, including the methodology table and dialogs. No user settings or histories are changed by tests.

Likely files: `local-view.js`, `local-app.js`, scoped `style.css`, existing pricing/settings helpers only if a demonstrated gap requires them, plus integration fixtures.

### B3-06 — Integrated browser and packaged Windows acceptance

Status: verified for the scoped automated/browser/executable gate in 0.16.0; native/distribution sign-off remains separate. Depends on all prior gates.

- Run focused suites per change, then the relevant full Python and Node suites after final changes. Use `windows/.venv/Scripts/python.exe`; isolate workspace-local TEMP/TMP, LOCALAPPDATA, CODEX_HOME and CLAUDE_CONFIG_DIR. Inspect printed accounting probes, including **200/200, 200/200, 250/250**, and preserve fork/parser-cache regressions. Check docs/links and `git diff --check`.
- Exercise the actual authenticated real-data dashboard in a browser against a controlled local fixture: launch, Overview → Explore → detail → Back, page isolation, three metrics, primary scope, exact totals, Update view, settings publication/restart, unavailable/stale sources/limits, keyboard/focus and narrow desktop. DOM harnesses, screenshots, native Figma playback and native Windows interactions are separate evidence; do not substitute one for another.
- Use `windows/build.ps1`, `windows/tools/release_smoke.py`, `windows/tests/packaged_credit_foundation.py`, `windows/tests/packaged_local_hub_smoke.py` and `windows/tests/packaged_hub_release.py` as applicable to the actual candidate executable. Verify offline assets/fonts/timezones, authentication, recovery/migration, owner reuse and shutdown, plus the new credit projection and UI entry point. Measure Overview/Explore on the established 40-file/4,000-event fixture against its existing two-second target, recording machine/load and misses honestly. No universal performance claim.
- Gate: exact service/API/browser/executable reconciliation with reviewed visual comparisons and actual interaction evidence. Record candidate version/hash, commands/outcomes, measured fixture, unrun checks and remaining native/distribution sign-off. A build alone does not complete B3 or S14. Installation, real-history audits, commit/push and publication require their applicable user direction.

## Limitations and handoff

- The tested 0.16.0 portable/setup packages are available in `windows/dist`; exact hashes, final passing fixture timings and earlier misses are recorded in the implementation ledger. `Usage_Dashboard.exe` matches the tested setup. The real launch reused the user's existing 0.14.2 service owner; that owner remains running, and the active installation was not replaced. Normal tray Quit is needed before launching the new candidate. Native tray/menu and distribution acceptance remain separate from fixture-browser/executable checks.
- The current prototype's selected primary fixtures are fully priced with zero writes. Its 108 saved filter combinations and screenshot checks are useful design evidence; they do not test production partial pricing, nonzero writes, arbitrary settings, ticking reset times or native keyboard behavior. Those cases are explicit implementation gates above.
- Filtering to a model cannot separate a main agent from a helper using the same model. Local unmatched-account history cannot prove full account coverage, cloud/browser usage, actual billing or remaining subscription credits. No accuracy percentage or provider allowance estimate is promised.
- The methodology screenshot is a visual reference. Production must expose true mixed/unknown rates and rounding; its content can grow beyond the Figma box to preserve information. Unsupported non-token charges and unavailable historical rates remain qualified. This plan changes no provider rate catalog and does not reverify current published prices.
- Production work was subsequently requested, starting with B3-01. The original planning session changed documentation only; the latest implementation ledger separates current acceptance from that historical planning evidence.

## Methodology display follow-up — October 27, 2026

The user requested a narrower calculation display after B3 delivery: omit zero-token cache-write rows whose rate is unavailable, show the named below-threshold assumption once at the top of Calculation basis, and use two decimal places for displayed USD amounts/rates with a basis note. This supersedes the earlier requirement to always show five category rows or unrounded amounts in the main table. Recorded nonzero writes, configured zero rates, mixed-rate evidence, contrary context warnings and exact accounting remain available. Tiny nonzero USD amounts use `<0.01`; signed tiny adjustments preserve their sign. Exact amounts remain in hover evidence/explicit precision details and wire data. Display rounding never changes token facts, stored valuations, app-credit normalization or totals; rounded displayed rows need not sum exactly. No layout redesign or Figma update is required for this scoped presentation fix. See the main ledger for fresh verification and packaging evidence.

## Conversation history follow-up — October 27, 2026

Explore now defaults to ten conversation entries. Load more appends another batch within the same frozen query and disappears at the end; existing explicit batch-size choices remain available. Headline totals, charts and methodology still cover the full query. Filters/sort/batch changes and explicit refreshed queries restart the list; detail/Back and ordinary page navigation retain expanded history when its context remains valid. Reload captures a fresh query and starts at the selected batch size. Signed server cursor pages remain individually bounded and validated; only the current explicitly expanded history is retained in session memory, while browser history stores its cursor chain rather than row payloads. Failed or obsolete loads cannot replace accepted rows, and expiry recovery refreshes the complete query rather than mixing publications. Project/event paging stays separate. This supersedes the earlier conversation Previous/Next display requirement; it changes no API, storage or accounting semantics.


## Scan timestamp consistency follow-up — October 27, 2026

The user requests the Settings scan timestamp to use the same saved report timezone as the other pages, and **Last successful local scan** at the bottom left of each page. Production `local-view.js` reads Settings' nested resolved timezone instead of silently falling back to UTC. A shared page footer holds scan/captured-view timestamps below content, aligned to its left edge; short pages keep it near the viewport bottom, long pages scroll to it. Update/publication/failure notices retain their existing top location and actions. Frozen report zones and pending settings semantics remain unchanged; DST labels follow the timestamp's named zone (PDT/PST), never a hardcoded offset. The explicit demo and backend accounting/configuration contracts are unchanged. See the main ledger for fresh browser and package evidence.


## Bounded history and daily average follow-up — October 27, 2026

The user's revised history behavior supersedes the earlier unbounded append/batch-picker follow-up. Production Explore removes the row/batch-size selector. A validated cursor page holds at most **50 conversations**; its initial presentation shows **10**. **Load more** adds ten visible rows up to that page's end, **Load less** removes ten down to ten, and Previous/Next navigate the 50-row pages with ten initially visible on each. Either direction is available without first expanding the page. Controls disappear or disable at the corresponding bounds. Detail/Back and ordinary navigation preserve expansion and cursor within a valid frozen query; filters, sorting, new publications and reload reset the relevant page/expansion. One current 50-row page may be reused only after successful context validation; expansion/collapse themselves do not read the API or rescan. Browser history retains cursor/navigation state, not row payloads. Projects and events keep their existing paging. Whole-query totals, pies and methodology never depend on visible history.

Explore's daily chart adds a dashed **Daily average** reference for the selected metric and full filtered query. Its approximate SVG position is the arithmetic mean over selected local calendar days, including days without matched records; a selected-day filter uses that day alone. Exclusive midnight endpoints do not add an extra day. Empty results have no line; unavailable monetary estimates have no monetary average; legitimate zero estimates retain a zero reference. Partial pricing labels the reference **Daily average · priced subtotal**, excluding unknown amounts without inventing their value. No new financial number is calculated or displayed in JavaScript: this is chart geometry only, with exact source labels/totals still supplied by Python. Overview's display and backend pricing/configuration/API schemas remain unchanged. See the main ledger for verification and package evidence.


## Date control placement and average-axis value — October 27, 2026

The user's follow-up moves Explore's report-period selector into the filter panel and removes the long zero-baseline/average subtitle there. Overview starts on **Last 7 days**; its selector shares a centered row with Both agents/Codex/Claude, below the title. Explicit supported date selections and independent page selections survive navigation/reload. This supersedes the earlier default/heading placement only; core range semantics stay the same.

Explore's average now has a numeric Y-axis value in the same amber color and at the same height as its dashed line, with exact service-decimal evidence in its hover title and existing partial-price qualifications retained. The service supplies bounded Decimal means through the optional [daily-average projection](b3-dashboard-contract.md), retaining full-query facts and frozen timezone/filter context. The frontend only formats the provided value and uses numeric conversion for chart geometry. Two-decimal display, tiny-value qualification and compact million/billion token formatting remain separate from underlying precision. Empty/unpriced/zero distinctions, 10–50 history expansion, Report Log and footer placement remain intact.


## Checkbox filters and page text cleanup — October 27, 2026

Confirmed follow-up supersedes earlier subtitle/fee-context visibility and Explore's monthly default: both usage pages start with Last 7 days. Remove the requested Overview fee/caption, Explore chart captions, Live limits explanatory paragraphs, rail workspace block and Settings helper text. Keep chart metric/axis labels, reset/attempt/last-success values, failure/fallback and operation feedback. Settings shows one timezone label beside the mode selector.

Project, Model and Effort use native checkbox menus with Select all, indeterminate state, explicit Apply, Escape and outside-click dismissal. A dimension supports OR among chosen values, with AND across dimensions; existing primary-model scope remains authoritative. All is unrestricted, a subset is bounded to 64 values and none is an explicit empty query, never unrestricted. Explore metric tabs remain before charts; the existing history sort moves alongside its heading. Preserve independent selections, URL/Back/reload, failure recovery, frozen summaries and bounded history. No rates, canonical facts, settings storage or migrations change.


## Overview project names — October 27, 2026

Overview project rows display the last folder component of the retained project label, accepting Windows, POSIX and trailing separators. A small upper-right information disclosure reveals the complete existing label on click; Enter/Space, Escape and outside-click dismissal remain accessible. Label width is bounded independently from recorded tokens and API value. Full opaque project IDs still own queries, including projects with identical final folder names. Explore, source paths, database facts, accounting and provider behavior are unchanged; no filesystem lookup is used to infer or expand an address.
