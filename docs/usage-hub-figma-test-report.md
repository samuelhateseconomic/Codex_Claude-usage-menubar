# AI Usage Hub: Figma prototype repair and test report

Reviewed October 23, 2026, America/Los_Angeles.

Historical report: the October 26 [desktop-only credit revision](credit-feature-figma-prototype.md) supersedes the screen inventory, shared-filter behavior and mobile playback paths below. The user removed all mobile prototype frames and selected primary-model calculations, independent Explore filters and simultaneous Overview value/credit stats. The earlier checks remain historical evidence, not acceptance of the revised design.

## Result and scope

Updated the existing Figma design according to the interaction backlog in [the integration plan](usage-hub-integration-plan.md). Application code, database schema, migrations, credentials, and real account data were not changed by this work.

- [Desktop prototype](https://www.figma.com/proto/6Axot2OcYiKcSfGYcLh3Jh?node-id=2-43&starting-point-node-id=2%3A43).
- Mobile prototype: retired at the user's request on October 26, 2026.
- [Editable design file](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh).

The prototype now has 10 product screens, seven overlays, and two shared calculation/loading frames. It remains native editable Figma content: 561 text layers and no image-filled UI layers in the product screens.

## What changed

- Both / Codex / Claude controls use shared filter state. Claude has an action, and Explore provider selection stays in Explore.
- Overview totals, daily bars, model/effort groups, and project values use one coherent demo dataset.
- Project and model/effort drill-downs carry their labeled filters. Provider-specific Limits links select that provider in Explore.
- Explore supports Conversations / Projects, project/model/effort menus, scripted metadata searches, no-results feedback, and two pages of conversation rows.
- Every demo conversation row selects its own ID, project, model/effort, token categories, reasoning availability, and cost breakdown.
- Detail Back uses prototype history; shared query variables retain the originating filters and page.
- Date presets, chart value/token selection, selected-day filtering, and Clear selected day have actions.
- Settings demonstrates Codex fee editing, Save, Cancel, and rejection of a negative fee. Unimplemented appearance preferences are labeled read-only.
- Keyboard help opens an overlay. Search and Escape/help key triggers are present.
- Limits demonstrates cached readings and cooldown feedback. Report date controls were removed from live Limits and Settings.
- Mobile has its own Overview, Explore, detail, Limits, and Settings destinations. Mobile controls have explicit mobile calculation routes.
- Desktop frames were resized to fit their content; mobile number sizing and text wrapping were corrected.
- The old standalone Codex-filtered screen was removed after checking its incoming links. Provider changes now occur through shared prototype state.

## Demo fixture and expected values

The prior disconnected sample totals were replaced with 12 demo conversations, one accepted usage event per conversation, across four projects. These are synthetic values at fixed sample rates, not live usage or verified current pricing.

- Both: 12 conversations, 8,920,000 tokens, USD 49.506.
- Codex: six conversations, 5,900,000 tokens, USD 28.740.
- Claude: six conversations, 3,020,000 tokens, USD 20.766.
- Today with Both: three conversations, 4,740,000 tokens, USD 33.170.
- Claude + portfolio + high effort: one conversation, `demo-claude-02`, 1,070,000 tokens, USD 8.450.
- No matched records: zero matched token records and an unavailable estimated value, rather than a zero-dollar account-usage claim.

Reasoning remains a subset of output. Claude examples with no reasoning counter show an unavailable counter. Demo fees start at USD 20 for each provider; the Codex draft offers USD 20, USD 25, and a negative-value validation example.

The two-event contract example in the integration plan is a separate, explicitly labeled example. It is not the full Figma fixture.

## Checks performed

- Evaluated the actual saved native prototype action expressions across **2,160 combinations**: three provider selections, three date presets, five project selections, three model selections, four effort selections, and four search examples.
- Compared simulated matched token totals, conversation counts, visible first-page row counts, total value strings, and project value strings against independently filtered demo records. Final result: **zero failures**.
- Audited **129 action/control instances**: every one has an `ON_CLICK` reaction.
- Recursively inspected destinations inside conditional actions as well as direct navigation. Final result: **zero missing destinations** and **zero mobile-to-desktop navigation links** in mobile screen controls.
- Inspected native screen editability and reviewed desktop Overview/Explore/Settings and mobile Explore/detail/Limits/Settings screenshots. Corrected the observed clipping and sizing defects.
- The file contains 29 keyboard triggers. Their presence is structural evidence; it is not a keyboard-accessibility certification.

The currency-branch check initially failed because the saved Figma conditions did not preserve a multi-branch expression as intended. Flattening the branches into supported conditions fixed the issue; the full simulation was rerun successfully. Final checks also distinguish an empty query's unavailable value from a priced zero.

## Playback limitations

The validation above combines saved-action simulation, link/structure inspection, and screenshot review. It is **not** a completed end-to-end click-through in Figma's presentation engine. The embedded app surface did not expose the design's full playback controls during this run, so presentation timing, Back/history behavior through the shared calculation frames, and native key handling still need the manual review below.

Free-text search uses selectable examples. Clipboard feedback, refresh feedback, and settings persistence are simulated. No provider network requests, database writes, or actual clipboard writes occur. Browser Tab/focus behavior, arbitrary text input, real persistence, and API integration belong to application implementation and its browser tests.

## Manual review checklist

Restart the prototype to restore the default demo state before each independent case.

1. Overview: click Claude, then Codex, then Both. Compare the values above and check that the provider highlight and breakdowns change together.
2. Open Explore. Change providers and date presets; confirm the page stays in Explore. Try the project, model, and effort menus together.
3. Select Claude + portfolio + high. Open the single matching row. Check its ID, token categories, and USD 8.450 value, then use Back and confirm the filters remain.
4. Search: choose the usage-hub example, the exact conversation-ID example, and the no-match example. Confirm the no-results message and unavailable value, then clear the filters.
5. Both + month to date + no metadata filters: use Next page, open a row, and return. Confirm page two is retained, Previous works, and Next is absent at the end.
6. Switch to Projects, select a project, then use a model/effort link from Overview. Confirm the resulting Explore context matches each label.
7. Click a chart day. Confirm Explore uses that day and Clear selected day restores the previous report range. Switch chart metric and inspect the active control.
8. Settings: choose USD 25, Cancel, and confirm the draft returns to USD 20. Choose USD 25 again and Save. Try the negative example and confirm validation prevents it from becoming the saved fee.
9. Limits: use each provider's recorded-usage link and the sample refresh action. Confirm the provider selection and cooldown message, with no report date selector.
10. Mobile: repeat provider -> Explore -> matching detail -> Back, then navigate to Limits and Settings. Confirm there is no desktop-width destination.
11. Check search/help shortcuts and Escape in the actual Figma presentation. Record any engine-specific behavior before treating keyboard playback as verified.

## Implementation handoff

Use the [integration plan](usage-hub-integration-plan.md) for database/API contracts. These prototype improvements do not approve or implement that backend work. Replace the synthetic fixture with the agreed API outputs only after reconciliation and contract tests pass.

Keep real-data coverage labels, pricing completeness, unknown metadata, active-account quota scope, and query preservation when implementing the reviewed flows. The shared calculation frames are Figma prototype machinery; they are not an application architecture requirement.

## Token formatting and chart-axis revision

Applied the subsequent design feedback throughout desktop and mobile token labels: thousands remain comma-separated integers, millions use `M`, and billions use `B`. Examples checked include `190,000`, `1M`, `2.84M`, `8.92M`, `5B`, and `12.35B`. M/B labels use at most two decimals and trim trailing zeros. Exact source counters remain unchanged.

Replaced the unlabeled chart scale with a Y-axis, aligned horizontal gridlines, and proportional daily columns. The API-value metric uses USD labels; the recorded-token metric uses formatted token labels. The five-interval range adapts to the largest matching daily value after metric/filter changes. Zero values do not produce artificial two-pixel bars.

Validated saved prototype actions across **4,380 cases**: 2,160 filter combinations for each of the two metrics, plus 60 provider/selected-day/metric combinations. Token summaries and groups, unchanged monetary totals, bar heights, axis bounds, and zero-bar visibility passed with **zero failures**. Formatter boundary/example checks also cover billions, although the synthetic usage fixture itself remains below one billion tokens.

Visually reviewed both metric states. In the default demo, the API-value axis is `$0` to `$50`; the token axis is `0` to `5M`. The tallest daily column is USD 33.170 or 4.74M tokens respectively. Default API-value mode was restored after the token-chart visual check.

These are native Figma layer and saved-action checks. The full presentation-playback limitation described above still applies; no application code or database changes were made by this revision.
