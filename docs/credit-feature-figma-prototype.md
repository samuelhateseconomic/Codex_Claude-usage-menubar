# Credit feature: confirmed desktop prototype

Updated October 27, 2026, America/Los_Angeles. The latest cleanup supersedes both the smaller “Estimated” prefix and the later teal/semibold label treatment.

## Explore methodology refresh — October 27

After approving the proposed plan, the user requested replacing only Explore's estimate box with the methodology-card treatment. Node `101:1138` now contains paired token-breakdown/calculation-basis cards, exact USD/app-credit results and compact coverage notes. Category rows show uncached input, reads, separate 5-minute/1-hour writes and output with token counts, USD-per-million rates and contributions. Reasoning is an output subset; unknown reasoning/speed remains qualified. Input/total formulas, app normalization, below-threshold assumptions and unestimated-token labeling remain explicit.

The box remains **1180 × 572**. Read-back hashes match for all five canonical screens when excluding only this box; every page position, the rest of Explore and shared component definitions remain unchanged. Extended the existing 108 Explore conditional actions with box-only string projections; the original actions are preserved. Independent Python Decimal fixture arithmetic and **2,060 saved-action/structure assertions** pass. Final screenshot reviewed: 51 editable text layers, correct Geist/Geist Mono, no raster UI or overflow. Synthetic node/projection evidence is retained as `credit-prototype-state-v5.json` in the task visualization workspace.

The prototype retains its existing synthetic catalog examples; this is not a fresh provider-rate verification or production calculation change. Cache-write counts are zero in matching fixtures, with unavailable write rates shown as a dash; empty queries retain unavailable states. Partial/unpriced behavior is explained but no new partial fixture or native Figma playback/keyboard test is claimed. Production B3 integration remains separate.

## Open the current design

- [Overview prototype](https://www.figma.com/proto/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-43&starting-point-node-id=2%3A43).
- [Explore prototype](https://www.figma.com/proto/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-44&starting-point-node-id=2%3A44).
- [Settings prototype](https://www.figma.com/proto/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-47&starting-point-node-id=2%3A47).
- [Editable desktop file](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-43).

The canonical desktop nodes are updated in place: Overview `2:43`, Explore `2:44`, conversation detail `2:45`, existing Limits `2:46`, Settings `2:47`. All eleven original/new mobile screen/loading frames are removed, together with mobile starts and destinations. Six superseded desktop unit-switch overview frames are retired. The earlier separate native-credit example/detail and methodology reference frames remain editable references.

## Confirmed layout and scope

- Keep the original Overview arrangement: top stats, daily chart beside live capacity, and model/project breakdowns below. Its simultaneous labels are **ESTIMATED API VALUE**, **ESTIMATED APP CREDIT**, **RECORDED TOKENS**, **PROJECTS COUNTED**. Both estimate labels reuse the exact **12px Geist Regular muted text style** of RECORDED TOKENS, as single editable text layers. There is no headline USD/app-credit switch.
- Overview's ten daily columns have **flat bottom corners**, retaining the small top radius. Keep only one **All live limits** action inside Capacity; the query-actions duplicate is removed. Existing sidebar navigation remains.
- Descriptive subtitles beneath the main page headings are removed from Overview, Explore, Live Limits and Settings. Conversation/model metadata, account notices, units, calculation explanations and sample-state labels remain functional content.
- Overview's daily chart offers **API value · USD**, **App Credit** and **Recorded tokens**, including a more visible zero baseline and a **$0** tick for USD. Its date menu offers **Today**, **Last 7 days**, **Month to date**. The scripted Today choice uses the fixed October 26 fixture date, not the current computer date.
- Overview capacity shows Codex **62%** and Claude **28%** left in their five-hour windows, with 12px bars, reset timing and sample last-check status. These are synthetic provider readings, not app-credit balances, and do not change with historical filters.
- Preserve the Hub's Geist/Geist Mono typography, dark surfaces, teal/amber palette, navigation outline, token formatting and editable components.
- The subsequent user instruction is **calculate the main model only**. The current prototype maps Codex to GPT-6.1 Sol and Claude to Claude Opus 5.5. This is a query filter, not source deletion or agent attribution. A helper using the same model is not distinguishable from the main agent by model identity alone.
- Explore selects **Codex or Claude**, with its own project, primary-model, effort, date and analysis-metric state. These variables are disjoint from Overview's filters. Global saved configuration such as timezone remains shared.
- Explore shows **total tokens/API value/app credits** summary cards, equally sized **model-share and project-share pies**, a full-width daily AI Credit/Price/Tokens chart, aligned full-width conversation history and the matching calculation breakdown. Duplicate input/output/reasoning top cards are removed; category details remain below. Date choices are month to date, last seven days and Today (a fixed October 26 sample). The three chart layouts have matching day scales, labeled Y axes/gridlines, a zero baseline, adaptive maximums and hidden zero columns.
- The project pie replaces “This query only”; the removed panel's context/speed/unit explanations move to the bottom calculation section. Both pies follow Explore's same filters and metric. Default primary Codex project shares are **60.8% usage-hub / 39.2% portfolio** by app credits or USD, and **57.9% / 42.1%** by tokens. Single-project matches show 100%; empty selections use a neutral ring and no percentage claim.
- Under one-model scope the model pie is **100%** when records match, not a fabricated main/helper comparison. Empty selections show unavailable monetary values and a neutral empty ring. USD and app-credit percentages necessarily coincide.
- History exposes project/chat, model, app credits, exact USD, tokens and **unestimated tokens**. This last field means known recorded tokens lacking a usable price in the selected query; it never estimates missing source usage.
- Bottom calculations use the same filter state as every chart/history summary. They disclose category charges, exact USD, app normalization, rates and context/speed/coverage qualifications. Cached is an input subset; reasoning is an output subset, with missing counters labeled.
- Settings has independent Codex/Claude monthly-fee drafts and system/manual timezone choices, with Save/Cancel. Saving updates the sample fee labels without mixing USD fees and credit units.

The display decision is now confirmed for design. This session updates Figma and documentation; it does not implement or install the production dashboard changes.

## Shared fixture and exact examples

The source fixture contains twelve synthetic conversations across two projects, including secondary and unknown-model records. The confirmed primary-model query selects six, retaining all source records outside that filter.

Each provider's primary-model records have aggregate uncached input 60,000, cache reads 60,000 and output 6,000: **126,000 total tokens**. Codex records 1,800 reasoning tokens within output; Claude reasoning is unavailable. Cache writes are zero.

- Codex: USD **0.186000**, **18.600 app credits**, three matched conversations.
- Claude: USD **0.372000**, **37.200 app credits**, three matched conversations.
- Both on Overview: **252,000 tokens**, exact USD **0.558000**, **55.80 app credits**, two projects. The USD headline rounds to **0.56**.
- Primary-model rates are the sourced examples in [the research](credit-calculation-research.md). One app credit means exactly USD0.01 of API-equivalent value. Native Codex paid-credit equivalents remain a different unit.
- Both providers' primary records on October 18/23 belong to usage-hub; October 26 belongs to portfolio. Project/date filters therefore produce meaningful nonempty and empty selections. Secondary/unmapped records remain outside the current primary-model query, without being destroyed or relabeled as zero.
- The selected primary fixture is fully token-priced, so unestimated tokens are zero. This does not establish complete account coverage. Broader unknown/partial examples in the methodology references are distinct demonstrations.

The below-threshold context scenario remains visible. Standard is an API list-price basis, not evidence of observed speed or historical billing. No allowance use or remaining balance is inferred.

## Verification

The latest typography/subtitle cleanup verified ten flat bar bases, exact shared text style/font/fill/size on both estimate labels, one Capacity live-limits action, absent page-header subtitles and unchanged Overview/Explore calculation actions. Reviewed the four changed screen compositions; all content fits, all linked destinations resolve, all 388 text layers use Geist/Geist Mono, and there are no image-filled UI layers. This is structural/screenshot evidence; native presentation click-through was not rerun. The earlier numerical/filter checks below describe the preceding revision, whose calculation actions remain unchanged.

The October 27 refinement passed **308 saved-action/structure assertions**: all 108 Explore combinations and 27 Overview combinations, project shares and empty states, credit-axis projections, date labels, page-filter isolation, history column widths/visible alignment, uniform label sizes, baseline bounds and editable/font checks. Python Decimal generated all project percentages and Overview app-credit geometry from the existing fixture; Figma only stores the resulting fixture values. An initial one-pixel heading inset was corrected. Hidden rows retain matching widths; their unrendered positions are not claimed as playback evidence.

Current read-back of the two changed screens found **295 text layers**, **zero raster UI layers** and correct Geist/Geist Mono families. The Overview/Explore conditional matrices now contain 27 and 108 cases. The earlier October 26 five-screen review and settings/detail checks remain historical evidence; they are not re-certified by this narrower refinement. An unsupported decimal-containing variable name was rejected transactionally and corrected before the write committed.

Reviewed the refined Overview and full-height Explore/history/calculations screenshots. Applied targeted final fixes to equalize the pie-card heights, use amber for Claude's capacity fill, and account for the history-row border inset.

Independent project-Python Decimal and documentation checks are recorded in the refinement ledger. Native presentation click-through, keyboard/focus, Back timing, arbitrary text input, persistent settings, and real OS-timezone rebinning remain unverified. The prototype uses scripted fee/timezone choices and a fixed synthetic calendar.

## Implementation handoff

[Plan B](credit-calculation-plan.md) owns the revised B3 requirements. [B1/B2](b1-b2-calculation-foundation.md) owns the verified headless contract. The design settles simultaneous stats and primary-model scope; the authenticated credit HTTP contract, client validation, authoritative primary-model queries, real filters/charts, settings publication and executable/browser acceptance remain production work.

Keep all monetary computation in the shared Python service with exact string contracts. Figma's native fixture actions are prototype machinery and must not be ported as financial JavaScript. Reuse existing timezone detection/configuration and provider-specific fee authority. A primary-model filter makes a full-fee comparison ineligible.

No production source, histories, actual settings/fees/timezone, database, installation, commit or push changed in this design revision. Concurrent backend/source work was preserved.
