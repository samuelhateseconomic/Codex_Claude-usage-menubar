# Token-to-credit feasibility research

Researched October 26, 2026, America/Los_Angeles. Scope: [Plan B](credit-calculation-plan.md), official public documentation and the current Windows source. This is a proposed B1 contract and implementation handoff, not a shipped calculator or completion of [Plan A](missing-codex-usage-plan.md). No personal histories or authenticated billing services were queried.

## Finding and recommendation

Token-to-credit estimation is feasible when the unit, model, token categories and rate policy are explicit. Reconstructing actual subscription consumption or a provider balance from local token totals is not established. Mathematical precision does not remove missing source coverage or billing assumptions.

Keep the existing USD display as the compatibility default. Offer **App credits — estimated API value** as an optional combined Codex/Claude view, with the visible definition **1 app credit = USD0.01 of estimated API value**. Show **Codex credits — estimated paid-credit equivalent** separately in provider details. This is a research recommendation; the default/preference decision remains open before B2/B3.

Use different unit identifiers for those quantities even if both are displayed as credits. The optional app unit is a product convention, not a provider allowance. Relabeling USD16 as 1,600 app credits changes neither the underlying value nor the accounting. It cannot repair an inflated or missing token observation.

## Official evidence and its boundaries

### Codex

The current Standard credit card lists GPT-6.1 Sol at **50 input / 2.5 cached input / 250 output credits per million tokens**. It specifies no separate credit charge for cache writes. The page distinguishes credit pricing from included-plan usage and allows plan/agreement differences. This supports a current-rate paid-credit equivalent, not a reconstruction of historical allowance use. [Official pricing](https://learn.chatgpt.com/docs/pricing).

Fast uses **2x paid credits** versus **2.5x included usage**; Ultrafast uses **6x paid credits** versus **8x included usage**, subject to model/plan availability. These are separate from reasoning effort. API-key work follows API pricing. Do not apply subscription multipliers to API-key estimates. [Official speed policy](https://learn.chatgpt.com/docs/agent-configuration/speed).

The API model page identifies `gpt-6.1-sol` and lists Standard USD rates of **2 input / 0.10 cached input / 10 output per million tokens**, plus cache-write and request-context pricing rules. This is a different pricing policy; its modifiers must not be copied into native credit pricing without matching evidence. [Official model specification](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

Neither a checked date nor an unchanged-looking model name establishes when a rate began applying. The fetched card does not establish complete historical rates for the repository's older GPT models. Those native-credit estimates remain uncovered until individually sourced. A matching USD rate is insufficient.

### Claude and other credit units

Claude's paid-plan usage credits fund usage beyond included limits at API rates, separately from the subscription. The checked article does not define a universal numeric credit unit for converting Pro allowance. [Usage-credit policy](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans).

Claude pricing distinguishes input, output, cache reads and two write durations. Opus 5.5 Standard rates are USD4 / 20 / 0.20 / 5 / 8 per million respectively. Fast, routing, long-context and tool terms require their own evidence. Its USD0.01 Claude Consumption Unit is explicitly for certain marketplace billing paths; it is not evidence of a Claude Pro allowance unit. [Official pricing](https://platform.claude.com/docs/en/about-claude/pricing).

GitHub documents USD0.01 per AI credit for Copilot Business/Enterprise. That can illustrate normalization, but cannot establish Codex or Claude subscription semantics. Copilot collection is outside this application's current providers. [GitHub billing](https://docs.github.com/en/copilot/concepts/billing-and-usage/organizations-and-enterprises/billing).

### Provider-reported quantities: possible separate work

The Codex app-server documents optional remaining workspace credit details on `account/rateLimits/read`, account token summaries/daily buckets on `account/usage/read`, and thread token-usage notifications. These do not establish a supported per-event credit ledger here. Earned **rate-limit reset credits** are another quantity, not spendable usage credits. Availability on the installed CLI/account was not tested. [App-server contract](https://learn.chatgpt.com/docs/app-server).

The workspace Analytics API offers aggregated reporting and requires endpoint enablement and an appropriately scoped workspace Admin key. It is not a guaranteed personal-plan source or raw per-conversation billing ledger. Its current metric schema/access would require separate verification. [Analytics access boundaries](https://learn.chatgpt.com/docs/enterprise/analytics-api).

If a supported provider source later supplies credits, preserve its unit, account/workspace scope, covered interval and timestamp. Never add account totals to overlapping local estimates. Balance changes can reflect purchases, shared activity and adjustments; quota percentages can reset and need not have a known token denominator. Neither permits allocating credits to local sessions by subtraction.

## Current implementation: what can be reused

Inspected source, rather than the older integration document's baseline descriptions:

- [usage_records.py](../windows/usage_records.py): immutable disjoint token counters; reasoning is nullable and belongs inside output.
- [usage_observations.py](../windows/usage_observations.py): extracts token observations, model, explicit effort and identity evidence. `Observation`, `Record` and `CanonicalEvent` currently have no event speed, billing-source or native credit amount field. This proves an application data gap, not that every underlying log lacks such metadata.
- [usage_valuation.py](../windows/usage_valuation.py): exact Decimal USD event valuation, rate provenance, request-context evidence, coverage states and fee comparison. This supports app-credit normalization without revaluing tokens. Its USD catalog is not a native credit catalog; existing custom USD overrides must remain visible in normalized results.
- [usage_service.py](../windows/usage_service.py): immutable summaries and shared grouping/selection. Every view must obtain credits here alongside the existing valuations.
- [usage_index.py](../windows/usage_index.py), [usage_index_db.py](../windows/usage_index_db.py) and [usage_index_codec.py](../windows/usage_index_codec.py): an existing SQLite publication and explicit allowlisted codecs. Native credit evidence cannot be retained merely by adding a renderer field.
- [usage_api_query.py](../windows/usage_api_query.py) and [usage_api_contract.py](../windows/usage_api_contract.py): frozen queries, publication checks, exact token/decimal strings and strict response contracts. Their version identity currently follows the existing usage/pricing/configuration publication; new credit policy identity must participate too.
- [usage_core.py](../windows/usage_core.py): live adapters currently project quota windows and blocked status into `Snapshot`; they do not preserve credit balances or a credit ledger. A source response containing extra fields would not make them available to offline summaries today.

The production dashboard is [local.html](../windows/dashboard/local.html), using `local-*` and `v1-*` modules. The explicit demo is not a fallback for a failed real query. Keep the terminal/tray paths and [S11](s11-local-index.md)/[S12](s12-local-api.md) publication rules.

## Proposed B1 calculation contract

These names and fields are design proposals, not existing Python APIs or wire fields.

### Units and formulas

For accepted event `e`, use disjoint counters `I` (uncached input), `C` (cache reads), `O` (output including reasoning), `W5` and `W1` (cache writes). Preserve the facts:

```text
total_tokens = I + C + O + W5 + W1
display_input = I + C + W5 + W1
display_output = O
```

Reasoning has no extra term. Unknown reasoning remains unknown or partly recorded. Display grouping must not replace the canonical counters.

**Native unit `codex_credit`:** select a separately sourced native credit rate entry and, where supported, an evidenced speed multiplier `s`:

```text
native_credits(e) = s * (I * r_input + C * r_cached + O * r_output) / 1000000
```

Do not introduce a cache-write credit term. If a future Codex source supplies separate write counters, require evidence of how they map to the documented native categories before claiming event coverage; absence of a separate charge is not permission to discard or reclassify tokens. Unknown speed produces unavailable native valuation under strict policy. An explicitly selected Standard scenario may produce a labeled assumption; it must not be silently treated as recorded speed.

Native valuation of API-key or unknown billing-source work, if offered, is only a **hypothetical paid-credit equivalent**. It cannot be labeled credits spent. Model/speed support, unsupported categories and assumption policy must be checked before arithmetic.

**App unit `app_api_value_credit`:** divide the existing authoritative USD event amount by the fixed Decimal `0.01`, then sum those exact values. Carry over USD provenance, overrides, tier assumptions and coverage. Null USD remains null. This is an optional normalization of the existing API valuation, not independent evidence of provider pricing or consumption.

### Catalog, evidence and coverage

Each native entry needs exact model ID, explicitly approved aliases, category rate strings, unit ID, source URL, checked date, historical effective interval if established, supported speed modes and billing scope. A rate card checked today with no effective-date evidence is `current_rate_counterfactual`; it must not be labeled historically applied. Do not use fuzzy family matching, unknown-model fallbacks or automatically copy USD aliases.

Capture any new event metadata through allowlisted typed fields with source provenance. Current user configuration, elapsed time, effort labels and thinking budgets do not prove past event speed. A mixed-model/speed cumulative delta may be unattributable; reconciliation must retain that uncertainty rather than assign the latest setting to the entire interval.

Keep independent dimensions:

- Coverage: empty, uncovered, partially covered, fully covered. A known zero amount is fully covered zero, not empty or unavailable.
- Assumptions: unknown speed, unknown billing source, current-rate scenario, context-tier compatibility and other explicit qualifications. Fully covered arithmetic can still be assumed.
- Source health: current, stale, retained or failed/excluded observations, using the existing source accounting. Do not invent excluded token amounts.

Publish covered/uncovered event and token counts plus reason codes, never an invented missing-credit amount. Token coverage is not a percentage of known monetary value or a confidence score. Unsupported images, voice and non-token tools must remain outside a token-only estimate with a coverage note; do not omit their ordinary model tokens when those are recorded.

### Exactness and versioning

Propose native Decimal arithmetic at precision 80, half-even rounding once per accepted event to 12 fractional credit digits, then exact summation. Validate finite nonnegative rates up to 1,000,000,000 per million with at most 12 fractional digits; use only catalog-approved speed factors. Reuse the signed-64-bit bound on total token quantities, and reject aggregate overflow with a documented native amount bound, proposed below `10^24` credits. Record rounding adjustments in detailed explanations. These are proposed bounds, not measured provider billing precision.

App normalization must not round again internally: existing 12-place USD values become values with at most 10 fractional app-credit digits. Its maximum amount must be derived from `MAX_MONEY / 0.01`, not incorrectly capped at the same numeric USD bound. Use explicit local Decimal contexts for both conversion and aggregation. Wire quantities remain exact decimal strings; display rounding is separate, including a less-than indication for small nonzero values.

Freeze unit definition, native catalog, valuation policy and assumption selection with the existing query context. Rate changes require a new publication/context and cannot alter old results, canonical event IDs or tokens. Never aggregate native and app units, or different credit policies, into one scalar. Fees and signed subscription comparisons stay in USD; choosing a credit display does not change their eligibility or prove savings.

## Worked acceptance values

All events below are synthetic. Published rates are checked-current examples, not evidence of a real account charge.

1. GPT-6.1 Sol, `I=10,000`, `C=20,000`, `O=1,000`, of which reasoning is 300: **31,000 total tokens**. Native Standard formula gives **0.8 Codex credits**. Its Fast/Ultrafast paid-credit scenarios give **1.6 / 4.8**, only where the mode is supported. Without speed evidence these are scenarios, not a selection of what actually ran.
2. The same synthetic request with explicit 30,000-token request context yields **USD0.032000000000** through the existing bundled Standard API valuation, hence **3.2000000000 app credits**. This demonstrates why native and app credits cannot share a headline unit. The equality for this one model/scope does not establish a universal exchange rate.
3. The original plan's USD16.2246908 becomes **1,622.46908 app credits**, displayed **1,622.47** with exact disclosure. Even USD0.000000000001 round-trips through normalization without additional rounding.
4. At the example native Standard rates, the same 31,000 total tokens can be **1.55** credits if entirely uncached input, or **0.0775** if entirely cache reads. Total tokens alone therefore cannot identify a credit amount.
5. Adding 300 reasoning tokens again would corrupt the total and valuation. Unknown speed/model, no accepted events, unknown USD price and an explicitly zero rate must each exercise their distinct outcomes; a supported zero-priced event is not an unavailable result.

The previously referenced **19.64 AI Credits** has no established rate/unit/context provenance in this research. Do not reverse-engineer a conversion constant to reproduce it.

## Implementation sequence and honest limits

1. Finish Plan A's specific missing-session/source and freshness gate. Passing old synthetic accounting cases is necessary but does not establish that the real desktop activity was captured.
2. Finalize B1's optional display/default policy and rate/evidence contract. Keep unsupported historical models uncovered. Research can close before a new credit engine exists, but B1 approval and implementation completion must remain separate.
3. B2 first implements app normalization over existing authoritative valuations. Add native valuation separately, initially strict or explicitly scenario-based. Share aggregation through the headless service; do not make browser code calculate financial quantities.
4. Inspect the SQLite publication/schema version before deciding a migration. App normalization alone need not persist redundant amounts; native catalogs/evidence and exact event results need publication ownership. If new persistence is required, use the existing transactional migration/backup/recovery path. Do not create another database or alter USD catalog identity just to hide a credit version.
5. Extend API schema, fixtures and `v1-*` validation together. B3 integrates the saved optional display preference, details, charts and exports with exact cross-view reconciliation. Run old-index/restart/reprice, frozen-query, unknown/partial/zero, numeric bounds, provider/filter, Back/refresh, keyboard/narrow-layout and packaged acceptance checks before shipping.

Local logs cover available unmatched accounts and devices only. They do not prove the active quota account, full cloud/browser coverage, billing terms or all charged tools. No historical rate archive, installed-CLI credit response, account matching or provider invoice reconciliation was verified in this session. No quantitative billing accuracy percentage or delivery-time estimate is justified by this research.

## Verification from this session

Used `windows/.venv/Scripts/python.exe`, separate workspace-local TEMP/TMP and isolated LOCALAPPDATA for each test suite:

- `-m unittest discover -s windows/tests -p test_valuation.py`: **27 passed / 4.012s**.
- `-m unittest discover -s windows/tests -p test_reconciliation.py`: **28 passed / 1.416s**.
- `-m unittest discover -s windows/tests -p test_service.py`: **24 passed / 1.649s**.
- `-m unittest discover -s windows/tests -p test_pricing_explanation.py`: **6 passed / 0.010s**.
- `docs/review_accounting_probes.py`: inspected printed comparisons, **200=200, 200=200, 250=250**, all true; retained zero-origin/reset qualifications.
- Temporary inline Decimal checks: native example 0.8, speed scenarios 1.6/4.8, existing USD valuation 0.032, normalization 3.2, 1,622.47 display rounding and smallest-quantum round-trip passed. These check worked arithmetic and existing USD behavior, not an implemented native credit engine.

This research changed documentation only. Separate edits to `usage_observations.py` and a new `test_codex_fork_headers.py` appeared during the session and were preserved; the test run above is not certification of those concurrent edits. Full application/Node suites, live provider queries, real-history imports, UI interactions, packaging, installation and macOS checks were not run; they are not credit acceptance evidence. Documentation checks passed for three documents, 71 local link targets, six anchors, balanced fences, final newlines and no trailing whitespace; `git diff --check` passed. The handoff is recorded in the [refinement ledger](project-refinement-plan.md#credit-calculation-research--plan-b-follow-up-october-26-2026).

## Follow-up: comparison with the current Python calculator

October 26, 2026, subsequent source inspection. Plan A now records A1–A3 accounting/freshness acceptance for 0.14.2; the earlier pending-gate statements above describe the original research snapshot. This comparison changes no production behavior and does not rerun Plan A's real-history acceptance.

Excluding credit conversion, the existing authoritative `usage_valuation.value_event()` already implements the same weighted Standard USD formula. `usage_reports.estimate()` delegates to it and exposes a legacy float projection; shared service/index/API consumers retain Decimal amounts.

- **Same:** uncached input, cache reads, output including reasoning, and Claude's 5-minute/1-hour writes. The bundled GPT-6.1 Sol and Opus 5.5 Standard rates match the examples discussed. Neither effort nor reasoning adds a separate multiplier/charge. Accepted events are valued before aggregation.
- **Missing speed selection:** observation/record/event schemas and `Price` have no actual-speed selector. Current valuation deliberately estimates Standard list-price value. For identical synthetic counters `I=10,000, C=20,000, O=1,000`, current Codex USD0.032 and Claude USD0.064 equal the earlier Standard math; evidenced Fast pricing would instead give USD0.064 and USD0.128 respectively. Unknown historical speed cannot be repaired by multiplying the full report.
- **More context handling than the simple example:** GPT-6.1 Sol's bundled threshold is 272,000; high-context rates are USD4 input / 0.20 cached / 15 output per million. `I=280,000, O=1,000` yields USD1.135, versus USD0.570 from an inapplicable Standard-tier-only formula. Normal reconciled events currently do not populate request-context size; the fallback uses event uncached input plus reads and labels `event_input_tier_compatibility`. An accumulated interval does not prove one request's context.
- **Cache-write boundary:** Claude writes already work: adding 5,000 five-minute and 2,000 one-hour writes to the sample yields USD0.105 Standard, or USD0.210 under the matching hypothetical Fast policy. Codex's current native log path supplies no separate write category; its USD `Price` also lacks write rates. A hypothetical nonzero Codex write counter therefore returns `cache_write_rate_unavailable`, not zero. The current official API model page documents a write price, but this is a source/category support gap, not demonstrated lost billing in the existing logs. Native Codex credit billing still has no separate write charge.
- **Existing safeguards beyond the hand math:** 12-place half-even USD rounding per event, exact aggregation, explicit custom rate overrides, approved dated-snapshot matching for the USD catalog, and empty/unpriced/partial/zero distinctions. Current rates are checked snapshots, not a complete historical billing schedule. Discounts, routing/tool/tax adjustments remain outside the default estimate.

Verification: project Python inline synthetic assertions passed for both Standard values, Claude writes, explicit/assumed high context, unchanged value when reasoning is absent, and hypothetical uncovered Codex writes. Fast figures are independently calculated expectations; no production Fast engine exists. Rechecked official [GPT-6.1 Sol pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Opus 5.5 pricing](https://platform.claude.com/docs/en/models/opus-5-5/overview) and [Claude Fast pricing](https://platform.claude.com/docs/en/build-with-claude/fast-mode). No personal settings, live account or real histories read; no new full-suite, UI or executable acceptance claimed.

## Confirmed follow-up: below-threshold context scenario

The user subsequently instructed us to assume all requests stay below the context-price threshold because they plan to compact beforehand. The [confirmed plan policy](credit-calculation-plan.md#confirmed-context-assumption--october-26-2026) now governs the proposed calculations. Earlier discussions of evidence-based/fallback high-context selection describe the existing calculator and historical research, not this newly chosen scenario.

Use below-threshold model rates, with an explicit **Below-threshold context assumed** qualification. Keep speed selection independent. Preserve tokens and any observed context evidence; a scenario is not proof of actual historical request size. A session's cumulative input may exceed 272,000 without any single request crossing it. The sample with 280,000 uncached input and 1,000 output is USD0.570 at the selected lower-tier rates; a matching Fast scenario would be USD1.140 for identical counters. Neither statement changes the existing engine, which still returns USD1.135 under its high-context policy for that sample.

This turn records the user's calculation-policy choice only. No calculator implementation, settings edit, reprice, provider query, installation or release check occurred. A future implementation must version/freeze the assumption and use the resulting authoritative USD valuation before app-credit normalization.
