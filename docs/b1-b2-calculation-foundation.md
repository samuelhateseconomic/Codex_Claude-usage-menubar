# B1/B2 calculation foundation

Status: requested backend calculation/foundation scope verified in **0.15.0**, October 26, 2026. The user explicitly excluded dashboard frontend work. See [Plan B](credit-calculation-plan.md), [research](credit-calculation-research.md) and [the refinement ledger](project-refinement-plan.md). Credit HTTP/frontend integration is not claimed complete.

Later Windows replacement work: the user subsequently authorized [B3-01–B3-06](dashboard-refresh-plan.md). The [dashboard projection contract](b3-dashboard-contract.md) implements opt-in authenticated app credits and primary-model analysis on the existing API. This does not change the historical B1/B2 scope, native-credit calculation rules or its recorded evidence; use the latest refinement ledger for B3 delivery status.

## Scope and decisions

Subsequent design decision: the user approved the [desktop-only Plan B revision](credit-calculation-plan.md#confirmed-desktop-display-policy--october-26-2026): simultaneous USD/app-credit stats, original Overview layout, primary-model calculations, independent Explore filters and separate fee/timezone settings. This supersedes the historical open-display statements below for design; the backend scope and its existing verification remain unchanged. Figma completion does not implement the credit HTTP/frontend path.

- Keep the existing dashboard frontend, display preferences and USD HTTP responses. The credit headline/default choice remains a future frontend decision; it does not block an explicitly selected headless unit. No B3 completion is claimed.
- Implement the confirmed **Below-threshold context assumed** scenario through the authoritative USD service. It preserves counters and recorded context, qualifies contrary evidence and uses a new pricing-policy identity. Speed is independent: the existing USD estimate remains a Standard API list-price equivalent, not evidence of actual request speed.
- Native Codex credits and normalized app credits are separate immutable quantities. Neither reconstructs subscription allowance, actual billing, remaining credits or missing account activity. Fees and eligible subscription differences stay in USD.
- No personal settings/history edits, provider polling, billing integration, installation, automatic browser launch, commit or push are part of this session.

## Frozen calculation contract

`usage_valuation.py` now defaults to policy `decimal12-below-threshold-v1`. For models with a context-price threshold, select lower-tier rates and attach `below_threshold_context_assumed`. An explicitly recorded larger request adds `recorded_context_exceeds_assumed_threshold`; it is not erased or converted into an observed lower context. Absent request-context evidence remains absent. Session/day/month totals never prove one request crossed a threshold.

The old `decimal12-event-tier-compat-v1` remains supported through an explicit legacy catalog. Its hash, stored payload and valuations round-trip unchanged. New normal imports/reprices publish the new pricing version transactionally without changing event/observation identities, token categories or usage revision solely for a price-policy change. Previously captured in-memory snapshots remain immutable; the existing HTTP context rules reject a changed publication rather than silently replacing it. No schema migration or competing database is needed.

### Units and precision

- `app_api_value_credit`: one unit is exactly **USD0.01** of the authoritative API-equivalent estimate. Divide each accepted event's already-rounded USD amount by Decimal `0.01`, without rounding again, then sum. Carry USD overrides, coverage, policy and assumptions. Twelve fractional USD places need at most ten fractional app-credit places. Maximum app amount is `MAX_MONEY / 0.01`, not the same numeric USD bound.
- `codex_credit`: a sourced native rate catalog, independent of USD. Compute `(uncached input × input rate + cache reads × cached rate + output × output rate) / 1,000,000`, then apply the supported paid-credit speed factor. No extra reasoning term or invented cache-write charge. Nonzero write counters with no documented native category mapping stay uncovered.
- Native arithmetic uses local Decimal precision 80, half-even rounding once per event to twelve fractional credit places, then exact summation. Rates are finite/nonnegative, at most 1,000,000,000 per million and twelve fractional digits. Tokens retain the signed-64-bit bound; native totals are bounded by `MAX_MONEY` (below `10^24`). These are application bounds, not provider billing precision. Detailed native valuations retain their rounding adjustment.
- Display rounding is separate, defaults to two places and uses a less-than label for tiny nonzero amounts. Aggregation rejects mixed units or policy versions. Empty, wholly uncovered, partial and covered zero remain distinct.

Acceptance values: the plan's synthetic native card gives **80 credits**, or **160** at its evidenced 2× speed. USD16.2246908 becomes **1,622.46908 app credits**, displayed 1,622.47. The confirmed 280,000 uncached input / 1,000 output scenario is **USD0.570 / 57 app credits**, with all 281,000 tokens retained; the legacy high-context policy remains USD1.135 when explicitly selected. These values do not reproduce or validate the unexplained Copilot 19.64 example.

### Native catalog and evidence

The initial exact-model text catalog covers `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-sol` and `gpt-6-luna`. Standard/Fast paid-credit factors are 1×/2×; Ultrafast 6× is supported only for Astra and Sol 6.1 in this snapshot. The [official credit table](https://learn.chatgpt.com/docs/pricing) and [speed policy](https://learn.chatgpt.com/docs/agent-configuration/speed) were fetched and checked October 26, 2026. Included-plan usage multipliers are a different quantity.

Each immutable entry carries exact model, rates, supported speeds, source URLs, checked date, billing scope and optional effective interval. There is no fuzzy/dated alias fallback. Today's table has no established historical effective interval, so bundled estimates carry `current_rate_counterfactual`. Older USD-priced models remain uncovered by this native snapshot rather than receiving invented rates. Claude's available API value can normalize into app credits; no native Claude Pro allowance conversion is introduced.

`CreditEvidence` accepts explicitly supplied per-event speed and billing-source fields with provenance. Current collectors do not yet establish these fields. Native queries are strict about unknown speed by default; `speed_assumption` explicitly selects a visibly qualified Standard/Fast/Ultrafast scenario. Recorded speed takes precedence over a scenario. Unknown/API-key/included-plan scope is qualified as a hypothetical paid-credit equivalent, never credits spent. No account-balance subtraction or inference from effort, elapsed time or current settings is allowed.

## Service, persistence and export

- `UsageResult.credits(...)` reuses existing filtered details and every group membership. All headline/detail/day/provider partitions reconcile; no browser calculation or competing selector is introduced.
- `IndexSnapshot.query_credits(...)` derives credits offline from its committed valuations and binds dataset, usage, pricing and configuration versions. `UsageIndex.read_existing_snapshot(path)` opens an explicitly selected current-schema index read-only, without initialize/migration, owner acquisition, JSON settings reads, imports or polling. Unsupported schema/corruption fails without fallback.
- Credit query identity includes unit, native catalog/scenario or authoritative USD pricing version, publication versions, captured period/timezone/filter context, selected events and supplied evidence. Rate/policy changes cannot mutate an earlier returned result. Native catalogs are held in immutable credit results and exported as public rate snapshots; no native valuation table or durable native-credit publication has been added.
- `usage_credit_contract.py` exposes the allowlisted **`usage-credit-summary-v1`** headless JSON projection: exact decimal-string amounts and integer-string tokens, unit/basis/policy identity, reasoning coverage, provider summaries, source-health counts, rate snapshot and the existing USD comparison. It excludes paths, conversation IDs, search text, raw event graphs, prompts, responses and credentials. Token-only coverage does not establish complete monetary/account coverage.
- This is a Python/CLI contract, **not a new authenticated HTTP endpoint**. Existing v1 responses remain compatible. A future credit HTTP route, pagination and frontend client/schema integration must be scoped and verified together; do not claim those gates are complete.

## Usage

From the `windows` folder, with the project environment installed:

```powershell
# Explicit synthetic example; no personal files or provider access.
.\.venv\Scripts\python.exe usage_credit_cli.py --demo --unit app

# Read the last committed local publication, without scanning/repricing it.
.\.venv\Scripts\python.exe usage_credit_cli.py --index "$env:LOCALAPPDATA\UsageTray\usage-hub.sqlite3" --unit app --format json

# A visibly assumed native paid-credit scenario; not actual allowance use.
.\.venv\Scripts\python.exe usage_credit_cli.py --index "$env:LOCALAPPDATA\UsageTray\usage-hub.sqlite3" --provider codex --unit codex --native-speed-scenario standard

# Explicit read-only source scan; other roots are not silently added.
.\.venv\Scripts\python.exe usage_credit_cli.py --scan --codex-root "$env:USERPROFILE\.codex\sessions" --provider codex --unit app
```

`--config PATH` explicitly selects an existing settings file for a source scan; it never saves it. Missing explicit configs/indexes fail without creating them. `--timezone auto` detects the system zone; the JSON/text identify fallback versus manual/system selection. Metadata search is optional and never exported. Index reads retain the committed pricing policy: this command does not silently reprice an old publication. A normal owner import/reprice activates the new policy after a source/runtime update.

The installed application was not replaced. The new opt-in calculator runs from Python. The tested 0.15.0 installer is available as `windows/dist/Usage_Dashboard.exe`; installing it and a future frontend credit display remain separate user-directed actions.

## Verification ledger

- Focused checks passed: **143 existing/new calculation, service, index, pricing and report tests / 16.674s**, then the final **18 credit regressions / 3.191s**. The latter also exercise terminal rendering, exact exports, native evidence and direct-query identity with explicit fees/source health/token/grouping facts.
- Final normal `windows/build.ps1`: **437 Python tests / 78.791s**, PyInstaller6.16.0 app/setup builds, **19 offline executable checks** and isolated exact-payload installer acceptance pass. Python3.14.5 from the repository environment; workspace-local TEMP/TMP, LOCALAPPDATA, CODEX_HOME and CLAUDE_CONFIG_DIR isolated. No new dependency or live-provider access.
- Initial local test issues included an unused nonexistent renderer import, incorrect handwritten fixture totals and an inconsistent synthetic priced/unpriced value; corrected without changing accounting to match the mistakes. An earlier full run had **436 tests / 76.817s / three failures** from previous high-context expectations. Current-policy expectations now follow the confirmed scenario; explicit legacy-policy regressions remain. Earlier successful builds preceded final query-identity/terminal adjustments; the final build above includes those changes.
- Existing frontend compatibility suite: **107 tests / 4103.6301ms**, all pass. **All 47 files under `windows/dashboard` are byte-identical to this task's starting snapshot**, including pre-existing uncommitted frontend work. No frontend code, style, client schema or fixture was edited by this task; no new browser/native UI acceptance is claimed.
- Printed accounting probes inspected: **200/200, 200/200, 250/250**, all match. Synthetic CLI JSON/text: **26.58 app credits**, 108,000 total / 96,000 input / 12,000 output; reasoning coverage remains three known / three unknown records. Exact values, cached/write grouping and existing USD fee differences reconcile.
- Actual executable regression passes: legacy persisted **USD1.135 → USD0.570**, **281,000 tokens unchanged**, summary/detail/restart/terminal agreement and visible context qualification. Headless projections of that committed executable publication yield **57 app credits** and the explicitly assumed **14.25 native Standard credits**; strict unknown speed remains uncovered. This does not claim a packaged credit HTTP endpoint exists.
- Packaged fork regression passes old cached attribution repair, 350 tokens / USD0.0007, separate child/parent details, append450 and restart/terminal. Existing packaged local API launcher passes **2,840,000 tokens / USD18.42**, assets/auth/resume/offline limits/detail/owner reuse. Full packaged recovery harness passes schema-2 migration/checksummed backup/restore, multi-session authentication/grant expiry, interruption/restart, invalid-settings retention, diagnostics and terminal fallback.
- Performance evidence is separate from functional acceptance: the full harness's first Overview bundle was **2.179781s**, exceeding its 2s fixture target while packaging was also running; following samples were 1.092549/1.054013s. One bounded repeat after this task's build/test workers ended measured Overview **1.167482/0.786849/0.769245s**, Explore **0.548148/0.438393/0.444846s**. Fixture40 files / 4,000 events / 4M tokens / USD8, Windows11 / Python3.14.5 / 22 logical CPUs. All repeat samples meet the target; the earlier miss remains recorded and no cause or universal timing guarantee is inferred.
- Logs/measurements are ignored under `windows/build/credit-*`. Final portable SHA-256: `8ceed84a3c16cb84f5dc836d35e56f9fad09868c6f3da1c7b1729d8112048071`; setup SHA-256: `122ddf76ef3f71992092fc730e54c18229056fc641bae5f977d806b35b53b010`. The sole visible dist file is the byte-identical tested setup renamed `Usage_Dashboard.exe`. Named build variants and the prior 0.14.2 installer are preserved in `windows/build/credit-release-0.15.0`; no source-history cleanup or real installation occurred.
- Documentation/source checks: six documents / 105 local links / nine anchors, Markdown fences/newlines/whitespace, application/new-test syntax, version badge and `git diff --check` pass. Real histories/settings/fees, active installation, hosted CI and macOS/native taskbar acceptance were not changed or newly tested. No commit/push performed. Requested backend scope is complete; future credit HTTP integration and the dashboard display/default/B3 decision remain explicit follow-up work.
