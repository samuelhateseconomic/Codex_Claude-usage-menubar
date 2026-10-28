# Plan B: provider credits and a compact token view

Status: backend calculation/foundation verified in **0.15.0**; desktop prototype and revised B3 design confirmed October 26, 2026. See [the scoped B1/B2 evidence](b1-b2-calculation-foundation.md), [research](credit-calculation-research.md) and [current desktop prototype](credit-feature-figma-prototype.md). Plan A's scoped gate is verified. The user selected simultaneous USD/app-credit stats and primary-model calculations for the design. Production credit HTTP/frontend integration remains separate; this design revision does not change the installed dashboard.

October 27 implementation follow-up: the user subsequently authorized the Windows dashboard replacement. B3-01–B3-06 are implemented and scoped automated/browser/executable acceptance passes in 0.16.0, including opt-in authenticated credit projections, independent page state and the reviewed desktop layout. [The refresh plan](dashboard-refresh-plan.md) and latest refinement ledger own the candidate evidence and remaining native/distribution limits. Historical pending HTTP/frontend statements below describe their original scope, not the current implementation. No real installation, Figma or macOS changes are implied.

## Goal and feasibility

Show AI credits and a simple input/output/reasoning breakdown, without code-change counts. Keep the existing API-equivalent estimate available for the user's original subscription-value comparison. Changing units alone cannot correct excessive token counts or lower the underlying estimate.

Official documentation checked October 26, 2026:

- **Codex:** publishes model-specific credits per million uncached input, cached input and output tokens. Paid-credit speed multipliers differ from included-plan usage; no separate cache-write credit charge. These rates do not reconstruct subscription allowance consumption. [Official pricing](https://learn.chatgpt.com/docs/pricing).
- **Claude:** paid-plan usage credits cover overage at standard API rates and are separate from included limits. The checked documentation does not establish a universal numeric Claude credit unit for converting Pro allowance. [Claude usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans).
- **Copilot:** the documented Business/Enterprise AI-credit unit is **USD0.01**. This does not make that unit Codex's or Claude Pro's allowance unit. [GitHub billing](https://docs.github.com/en/copilot/concepts/billing-and-usage/organizations-and-enterprises/billing).
- Claude API valuation distinguishes input, output, cache reads and cache writes. Preserve applicable model-specific rates. [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing).

Research clarification: Claude also documents USD0.01 marketplace consumption units for specific billing paths. Those are not evidence of a Claude Pro allowance unit. Codex documents optional account/workspace usage fields, but installed-account availability and per-event credit attribution remain unverified; see the research before treating provider-reported balances as local usage.

The example's **19.64 AI Credits cannot be reproduced from token totals alone**: its model, rates, cache/input convention, speed and credit definition are needed. Do not target that number as a test expectation.

## Confirmed desktop display policy — October 26, 2026

Use clearly named quantities with explicit units:

1. **Codex credits — estimated:** calculate from the official matching credit rate card. Show the recorded model/speed basis and any assumptions. This is a paid-credit equivalent of observed work, not a claim that the account spent those credits.
2. **Claude usage value — estimated:** preserve the API-equivalent USD valuation. If a numeric AI-credit display is desired for Claude, use the explicit app-defined normalization below and label it as estimated AI credits.
3. **Estimated app credits — simultaneous overview stat:** one app credit is **USD0.01 of API-equivalent value**, giving `credits = API-equivalent USD / 0.01`. Show it beside the USD estimate with its definition. Native Codex credits remain a separate provider detail; neither quantity is a provider balance or subscription consumption.

The user replaced the proposed USD/app-credit switch: retain the original Overview layout and show four simultaneous stats, in order: **ESTIMATED API VALUE**, **ESTIMATED APP CREDIT**, **RECORDED TOKENS**, **PROJECTS COUNTED**. The latest October 27 refinement supersedes the smaller prefix and teal/semibold label treatment: both estimate labels use exactly the same uppercase 12px Geist Regular muted text style as RECORDED TOKENS. Remove descriptive page-header subtitles across the desktop pages; retain model metadata, units, account-scope and calculation disclosures in their relevant controls/panels. Keep the current desktop outline, navigation and styling. No mobile prototype is required; original and newly added mobile frames are removed. This settles the design's display decision without silently changing installed settings or fees.

The subsequent instruction **calculate the main model only** narrows the displayed query, not canonical ingestion. The prototype maps Codex to GPT-6.1 Sol and Claude to Claude Opus 5.5. Keep the exact selected model and scope visible; retain other records in storage. Model identity does not identify main agents versus helper agents, and a helper using the selected model remains indistinguishable without additional evidence. With a single model selected, its model-share pie is 100% when records match; no matches are unavailable, not an invented comparison.

This normalization is a presentation conversion: **USD16 becomes 1,600 estimated AI credits**. It will not make the same work cheaper or inherently produce smaller numbers. If the intended goal is matching the provider's actual allowance, only an appropriate provider-reported source can establish that; show unavailable when it is absent.

## Confirmed context assumption — October 26, 2026

The user explicitly selected **assume every request remains below its model's context-price threshold**, because they intend to compact before reaching it. For the planned calculations, select the model's below-threshold rates and label the result **Below-threshold context assumed**. This settles the context-tier policy; it does not select the default display unit or implement the calculator.

- Session/day/month token totals may exceed the threshold. Do not use those totals as evidence that a single request incurred the context premium.
- Preserve every accepted token, category and any recorded request-context evidence. Never truncate token counts to a threshold or record the user's compaction intention as observed context size. If explicit evidence conflicts with the assumption, disclose that conflict and retain the calculation's scenario label.
- Context tier and speed are independent: below-threshold Standard rates still need the applicable evidenced Fast/Ultrafast rate when that speed was used. Unknown speed remains qualified.
- When implemented, freeze this explicit assumption in a versioned valuation policy/publication and reprice through the shared service/index path. Normalized app credits must use the USD result under the selected policy, not silently retain the old context-tier valuation. Preserve old frozen contexts and canonical facts. Do not add an undocumented context modifier to the native credit card.

For GPT-6.1 Sol, the earlier synthetic `280,000 uncached input + 1,000 output` example becomes **USD0.570** under this requested scenario, rather than the existing calculator's **USD1.135** high-context result. The 281,000 tokens stay unchanged. Neither that example nor a compaction preference proves actual historical request sizes. No production code or installed settings changed by recording this decision.

## B1 — Freeze units, rate catalog and coverage rules

Target effort: roughly one third of Plan B.

- The display choice is now confirmed for the desktop design: simultaneous USD/app-credit stats in the original Overview layout. Preserve production behavior until the separately scoped credit HTTP/frontend integration is implemented and verified; do not ask the user to choose the same switch/default again.
- Backend-only scope clarification: the earlier opt-in Python/CLI foundation proceeded before the display decision. The later user instruction confirms the desktop design above; neither headless delivery nor Figma work alone authorizes or verifies the credit HTTP/frontend implementation. See the scoped contract for finalized backend bounds and policy identity.
- Define a separate versioned credit catalog containing provider, model identifier/approved alias, category rates, unit, source URL, checked date, applicable speed/billing scope and effective-date evidence. Do not reuse USD prices as if they were native credit rates.
- Retain exact event token facts. Add allowlisted speed/billing metadata only where actually recorded. Reasoning effort is not speed mode; elapsed time is not billed usage. Unknown model/speed/account terms cannot be silently mapped to an exact credit result. A standard-speed assumption, if selected, must stay visible.
- Apply the confirmed below-threshold context assumption above as an explicit valuation policy, independently from speed. Its visible assumption must survive summaries, details, exports and frozen API contexts.
- Preserve recorded provider credit quantities separately if a supported source supplies them later, with coverage and scope. Do not add them to an estimate of the same activity or infer per-session credits by subtracting account balances/limit percentages.
- Distinguish historical effective rates from a current-rate counterfactual. If an earlier valid credit rate is unavailable, label a current-rate estimate; do not backdate today's prices. Special tools, images and other uncovered usage stay outside token-only estimates with an explicit coverage note.
- Unknown/uncovered, empty, partial, assumed and genuinely zero-credit results remain distinct. Do not assume every model currently priced in USD has a known credit rate.

Deliverable: a small documented contract with exact units/formulas, rate provenance, assumptions and synthetic acceptance values. No new provider login, credential refresh or billing integration is required for estimates.

## B2 — Implement one exact headless calculation

Target effort: roughly one third. Depends on Plan A's accounting gate and B1's approved unit policy.

- Add an independent credit-valuation policy alongside `usage_valuation.py`, consumed through `usage_service.py` and the existing index/API publication path. Keep canonical tokens, event identities and existing USD valuations unchanged.
- For a supported Codex event, compute `((uncached input × input rate) + (cached input × cached rate) + (output × output rate)) / 1,000,000`, with any applicable evidenced speed factor from the separate credit catalog. Reasoning has no additional term.
- For normalized app credits, convert the authoritative API-equivalent amount with the fixed app unit. It must round-trip to that amount at the documented internal precision. Keep it distinct from native provider credit calculations.
- Use bounded Decimal arithmetic, exact decimal strings and an explicit per-event rounding policy. Aggregate authoritative results without summing display-rounded values. Freeze credit catalog/policy versions with the query context; changing rates cannot mutate old contexts or token facts.
- Extend immutable summaries and versioned API schemas/fixtures/client validation together. Inspect the existing SQLite publication model and add a transactional migration only if required; do not introduce a competing database or calculate money in JavaScript. Preserve old index recovery and offline reads.
- Keep fees denominated in USD. Never subtract a USD20 fee directly from a credit quantity. Preserve existing unfiltered calendar-month-to-date comparison eligibility; the credit display does not prove realized savings or remaining allowance.

Acceptance examples:

- Synthetic native catalog, **not published provider pricing**: input 50, cache 2.5 and output 250 credits per million. An event with 1M uncached input, 2M cached input and 100,000 output yields **80 credits**. Recorded 30,000 reasoning within output leaves **80**, not an additional charge. The same synthetic policy's evidenced 2× speed factor yields **160**.
- USD16.2246908 API-equivalent value converts to **1,622.46908** normalized credits; display **1,622.47**, retaining exact disclosure. Empty/unpriced is not displayed as 0 credits; partial results show a priced subtotal and coverage.
- Reimport/reprice/restart and large counters do not change token facts or mix unit/catalog versions. Totals reconcile with details and existing USD estimates.

## B3 — Compact dashboard, verification and delivery

Implementation sequence: [dashboard refresh plan, B3-01–B3-06](dashboard-refresh-plan.md). The October 27 replan is documentation-only; all six implementation sessions are not_started. It replaces older dashboard layout proposals while preserving the completed backend and D01–D04 reliability work.

The revised desktop design below supersedes the initial unit-switch/mobile prototype. Figma design work is authorized and reviewed separately from application implementation. The headless B1/B2 foundation remains verified; credit HTTP/schema/client integration and B3 delivery still need their own implementation acceptance.

### Overview

- Retain the original daily chart + live-capacity row and model/project breakdown row, with the four simultaneous stats specified above. Keep primary-model scope explicit and all summaries drawn from one frozen result.
- Keep API value in USD, app credits in their defined unit, recorded tokens and distinct matched project count. No request-count or duration inference. Native Codex credits do not replace the app-credit stat.
- Daily usage offers API value (USD), App Credit (the same defined API-value normalization) and recorded tokens. Keep a clearly visible zero line and corresponding zero tick for every metric, including **$0** for USD. Date choices are **Today**, **Last 7 days**, **Month to date**.
- Capacity right now shows only provider **5-hour remaining** percentages, 12px progress bars, reset timing and labeled refresh status for the active CLI accounts. Keep this live-limit context independent of historical report filters; it does not measure remaining app credits. Prototype readings are explicitly synthetic.
- Overview daily columns have flat bottom corners aligned with the zero baseline; retain the existing small top radius. Keep a single **All live limits** button inside Capacity, removing the duplicate from query actions. Sidebar navigation remains available.
- Preserve the dark outline, exact disclosures, existing token formatting, explicit dashboard launch and qualified local-account scope.

### Explore tokens — independent page filters

- Require one selected app, **Codex or Claude**, without a Both option. Use a page-local filter context for provider, primary model, project, effort, date range, selected day and chart metric. Overview/other pages must neither reset nor inherit these filters implicitly; Back/refresh/Update view retain them. Global saved settings such as timezone remain shared configuration.
- The user selected primary-model calculations only. The prototype names the primary model explicitly and retains a model-scope control; do not invent agent/subagent attribution from the model, session name or effort.
- At the top, show total tokens and both estimates. Remove the duplicate input/output/reasoning summary cards; retain those categories and subset/availability explanations in the bottom breakdown. Keep essential coverage/context/speed qualifications visible.
- Follow with a model-share pie and percentages for **AI Credit / Price / Tokens**. Under the confirmed single-model scope, show 100% for a nonempty matched model and unavailable for an empty/unpriced monetary result. App-credit and USD percentages coincide by definition. A broader comparison requires an explicitly broadened model scope, not fabricated helper-agent shares.
- Replace the “This query only” panel with a second, equally sized **project-share pie**, using the same provider, primary model, project, effort, date and metric filters. The denominator is matching usage; a selected single project is 100%, and an empty selection is a neutral ring without a percentage claim. Move the former panel's assumptions into the bottom calculation section. History headings and values use matching aligned columns rather than space-padded text.
- Below it, place a **full-width daily bar chart** for the selected metric, date range and project. Include a labeled Y axis/gridlines, zero baseline, matching day labels and a scale derived from the largest matched daily column. Zero columns are invisible. Keep exact values authoritative; chart geometry alone may use numeric display projections.
- Below the chart, show filtered conversation history with project/chat, model, **app credits / USD price / tokens / unestimated tokens**, and a matching detail/Back route.
- **Unestimated tokens** means accepted recorded tokens in unpriced/uncovered records within the query. It is not unknown missing usage, a reasoning surcharge or a fabricated skipped amount. Keep token/record price coverage and ingestion quality separate.
- At the bottom, show **Estimate methodology** using paired token-breakdown/calculation-basis cards, followed by exact USD/app-credit results and compact coverage notes. Use aligned category, token count, USD rate per million and USD contribution columns for uncached input, cache reads, separate 5-minute/1-hour writes and output; reasoning remains a recorded subset of output. Explain input/total definitions and app normalization; preserve unpriced counters, selected rate provenance, policy/context/speed assumptions and rounding. The same Explore filters/context drive it. Keep general Data details/diagnostics closed initially. The October 27 prototype refresh is confined to this box and retains its footprint and surrounding screen/canvas positions.

### Settings

- Provide separate validated USD monthly plan-fee fields for **Codex** and **Claude**. Reuse the single configuration authority; edits to one must not alter the other. Preserve draft, validation, Save/Cancel, publication and recovery behavior.
- Offer **Use local computer timezone** (`auto`) or an explicit manual named timezone. Reuse existing system-zone detection and persistence; label a UTC fallback. Resolve the zone before freezing query boundaries and rebin daily/monthly results through the authoritative service after an applied change.
- Keep the actual configured fees unchanged until an explicit settings save. Compare fees only in USD and only for eligible unfiltered calendar-month-to-date queries; primary-model-filtered queries are not eligible for a full-fee comparison.

Rules:

- Display input = uncached input + cache reads + 5-minute writes + 1-hour writes. Display total = that input + output. Cache writes remain available in the breakdown and correctly valued. Do not change the core's disjoint categories to achieve this grouping.
- Preserve existing comma-separated thousands and up-to-two-decimal M/B formatting. Exact token/credit values and rate explanations remain expandable. No code changes, request-count inference or duration figure is needed for this requested view.
- Keep rate details and the detailed orange report collapsed initially, with essential partial/stale/assumed qualifications adjacent to the headline. Explain native versus normalized units before a user can mistake one for the other.
- Keep Overview, Explore, detail, charts and exports consistent for matching queries. Use independent page context identifiers and the same authoritative service/unit definitions. Do not relabel a USD series as credits without transforming its authoritative values.
- Implement credit HTTP responses, schemas, fixtures and `v1-*` client validation together; the existing headless JSON is not an already implemented HTTP route. Preserve exact strings, frozen queries, offline operation, approved mutation roots and account-scope/privacy limits.
- Test provider/project/date/metric selection, page-filter isolation, primary-model scope, pie denominator/empty states, history/calculation reconciliation, Update view/Back, saved fees/timezone, catalog changes, exact disclosures, keyboard/focus and desktop resizing. No mobile Figma deliverable is required. Run appropriate Python/Node/API and real browser checks; packaging acceptance must use the shipped executable before installation is offered.

## Completion and release boundaries

Record B1–B3 evidence separately from Plan A in the refinement ledger. Completion requires explicit units, correct provenance/coverage and exact cross-view reconciliation. No fabricated provider balance or subscription-credit budget, no change to the user's monthly fees, and no implicit browser launch. Commit/push/install remain separate user-directed actions.

## Feature prototype — October 26, 2026

The initial mobile/unit-switch prototype is superseded by the confirmed desktop revision above. See [the editable desktop prototype and validation report](credit-feature-figma-prototype.md) for Overview/Explore/Settings links, primary-model scope, synthetic fixtures, saved-action evidence and playback limits. The design choice is settled; production HTTP/frontend integration and B3 release gates are not completed by Figma work.
