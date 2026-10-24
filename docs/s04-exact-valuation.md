# S04 — Exact, versioned, explainable valuation

Started at clean `b9495f0` on `codex/s01-observation-contracts`. This session implements F3/F6 in the isolated Windows refinement worktree. It does not merge the separately developed original checkout or add a database/API/dashboard. The user authorized committing and pushing this session after validation.

## Exact arithmetic and supported bounds

`windows/usage_valuation.py` is a pure service over accepted `CanonicalEvent` or compatible `Record` inputs. It imports neither readers, providers, GUI modules nor report rendering. Parsing/reconciliation still own token acceptance. Valuation never changes canonical facts or event IDs.

- Required and used token quantities, each event's category sum, and aggregate token sums must be nonnegative signed-64-bit integers: **0 through 9,223,372,036,854,775,807**. Booleans, fractional counters and overflow are rejected, including for unpriced records. Reasoning remains a nullable subset of output.
- Rates are exact USD per million tokens. Rates and monthly fees support **0 through 1,000,000,000**, at most **12 meaningful fractional decimal digits**. Non-finite, negative, over-precision and excessive values fail explicitly; values are never silently truncated. Trailing zeros do not add meaningful scale; zero is canonicalized. Input precision is bounded to avoid unbounded numeric text.
- Money supports absolute values up to **999,999,999,999,999,999,999,999.999999999999 USD**. Check bounds on valuation, sums and differences. The count/rate bounds normally constrain results more tightly than this defensive limit.
- Use an isolated Decimal context with precision 80 and half-even rounding; caller/global Decimal settings cannot alter results. Compute each event's category charges and divide by one million, then quantize **once per event to 12 fractional USD digits**. Aggregate those quantized values exactly; do not round an aggregate as though it were a request.
- Round separately for display. Positive amounts below four-decimal display resolution appear as `<$0.0001`, rather than a displayed priced zero. A positive value can quantize to zero at the documented 12-digit event scale; provenance and the priced state remain available. Signed differences retain their exact Decimal amount even when display rounds to cents.

`Price` converts legacy numeric constructor arguments via decimal text; bundled rates are now spelled as decimal strings. `load_prices` uses Decimal for fractional JSON numbers and accepts decimal-string rates. It rejects explicit null/non-finite/invalid rates. CLI fee arguments are parsed directly as bounded decimal text. There is no binary-float arithmetic in authoritative event valuation, aggregation, fee subtraction or either renderer.

Compatibility `usage_reports.estimate` still returns `float | None` for callers that depend on that API. It projects an already-computed Decimal event value and is **not** used by text/HTML calculations. Tests prohibit either renderer from calling it. Existing bounded ordinary fixtures differ from the former float formula by no more than 0.000000000001 USD; this is not a universal float-error guarantee at huge values. Counts beyond JavaScript's safe integer range have independent exact-decimal expectations.

## Catalog and provenance

The existing bundled rate amounts and **2026-10-23** checked date are retained. No fresh online price verification or historical-billing claim was made in S04.

A report captures an immutable catalog snapshot. Content hashes identify the normalized catalog, override snapshot, applied rate, and combined pricing version. The combined version includes the computation policy, `decimal12-event-tier-compat-v1`. Equivalent decimal spellings and override insertion order do not change numeric identity. Changed rates/source/date/policy produce the corresponding changed version.

Every event valuation carries its canonical event ID when available, requested/matched model, exact-versus-dated mapping, amount/state/unpriced reason, rate ID, rate source, checked date, custom flag, catalog/override/pricing versions, computation policy, selected tier, request-context evidence and assumptions. Custom rates use `custom configuration` as the source and have no invented checked date. Exact override keys take precedence; only the existing documented eight-digit or dashed-date suffix mapping inherits a known base rate. Unknown variants and unknown models stay unpriced.

Overrides replace an exact model's full rate definition; they do not silently merge the bundled tier definition. Optional cache-write prices now remain **unconfigured** when omitted. If an event uses a category with no configured rate, its whole monetary value is unpriced with `cache_write_rate_unavailable`; known token facts remain intact. An unused category does not block pricing. An explicitly configured zero is a known priced rate. This deliberately corrects the older implicit-zero cache-write default, and reports display missing used rates as unconfigured. The three input/output/cache-read prices remain required in the existing JSON format.

Changing the original override dictionary or the report's compatibility `prices` dictionary does not mutate an existing captured catalog. Create a new report/valuation snapshot for repricing (for example `dataclasses.replace(report, prices=new_prices)`); event IDs and canonical records remain unchanged. Persistent publication/repricing jobs are later sessions.

## Tier evidence and independent quality dimensions

When a canonical event supplies request-context count plus an evidence source, apply its catalog threshold to that count. The threshold comparison is strictly greater-than: 272,000 remains standard; 272,001 selects the higher tier in the current tiered catalog.

Current readers generally cannot prove one request's context from a cumulative delta. Keep the existing **event uncached-input + cache-read** tier calculation as a compatibility policy, and attach `event_input_tier_compatibility`; both monetary headlines and comparisons label the assumption. Do not use monthly/group totals, model context-window capacity, reasoning effort or thinking budgets as request-size evidence. A long-context capacity is not a recorded request size. Canonical legacy Claude TTL assumptions survive as `legacy_cache_ttl_assumed` and appear beside value as well.

Coverage states concern configured rates only:

- `empty`: no accepted matched events; amount is null.
- `unpriced`: matched events but none has every used rate; amount is null.
- `partial`: priced and unpriced events; amount is the exact priced subtotal.
- `complete`: every matched event is priced, including explicit priced zeros.

Summaries separately retain priced/unpriced record and token counts, assumption-bearing record counts and assumption codes. S03 scan quality and S02 accounting issues remain separate; full rate coverage does not certify ingestion, tier evidence or account coverage. Aggregation rejects mixed pricing versions. Unknown missing token amounts remain unknown.

## Signed monthly comparison

`compare_plans` returns structured per-provider and combined comparisons, not preformatted savings claims. `ComparisonScope` requires explicit selected providers, period, a verified calendar-month-to-date condition and a filter flag. The report adapter checks the captured named-zone range starts/ends/provider coverage; it does not trust a period label alone.

Compare only unfiltered calendar-month-to-date, optionally by provider. Today/week/session, any metadata/day/search filter, or a noncalendar range makes comparison unavailable with a reason. Filtered report adapters suppress the fee block. No new filtering UI or query API was introduced by this session; future callers must preserve the scope condition.

`DEFAULT_PLAN_FEES` is the one temporary default source: **Codex USD 20.00/month and Claude USD 20.00/month**, reused by report construction and CLI defaults. Persistence remains S06. Null/missing fee, no records or all-unpriced usage makes that provider unavailable. Combined comparison remains unavailable if any selected provider is unavailable; it never drops one silently while calling the result Both. Otherwise compute **priced value minus full monthly fee**, preserving the sign and attaching local/unmatched-account, ingestion, accounting, tier/TTL and partial-pricing qualifications. There is no prorating, forecast, realized-savings assertion or actual-bill estimate.

Text/HTML renderers build one event-valuation view per render and consume the same exact aggregation and comparison functions. Canonical records retain their attached context through `Report.events`; standalone legacy/demo Records explicitly lack it. The process-local object keys in this compatibility view are only an adapter join to those existing objects, never global/persisted event identity. S05 still owns the larger immutable shared query/summary service and group/query sorting contract.

## Acceptance evidence and limits

The **27 focused S04 tests** cover:

- The integration fixture: Codex **2,840,000 tokens / 18.420000000000 USD**, Claude **65,000 / 0.471000000000 USD**, combined **2,905,000 / 18.891000000000 USD**.
- Exact fee differences: **-1.580000000000**, **-19.529000000000**, **-21.109000000000 USD**.
- Empty/unpriced/partial/zero states; optional missing write rates versus explicit zero; half-even ties and per-event rounding; tiny values; 2^53+1 and maximum counts; invalid inputs/overflow; hostile caller Decimal precision.
- Exact/datestamped mapping, override provenance, snapshot isolation, repricing without fact/ID changes, mixed-version rejection, threshold edges, supported/missing context, no aggregation-based tier selection, and no reasoning/effort multiplier.
- Real synthetic-log adapters preserve unavailable request context despite model capacity and retain legacy TTL flags. Both renderers bypass the float helper. Exact CLI fees and JSON fractional/string rates are verified. Scope and unavailable-provider cases have specific reasons.

The first report integration run found three deliberate old expectation mismatches: unsigned/savings wording and a 100-second fake month range. Those fixtures now use the real calendar-month start and signed labels. The first focused run also caught a leftover renderer float-helper call (removed) and an incorrectly hand-transcribed large-number expected constant (corrected from its independent exact component arithmetic). No incorrect implementation result was adopted as an accounting oracle.

Final `windows/build.ps1` passed **163 tests in 10.293 seconds** and built the executable on project Python 3.14.5 with installed dependencies and workspace-local TEMP/TMP. **Ten packaged offline cases passed**: Both text/HTML, each provider, mixed pricing text/HTML, all-unpriced, explicit zero rates, missing write rates, and demo. The exact fixture displays 18.8910 USD and signed rounded differences -1.58 / -19.53 / -21.11; partial pricing keeps the same subtotal, all-unpriced stays unavailable, and zero rates remain complete/zero. Missing write rates block the combined fee comparison. Demo remains 108,000 / 0.2658 USD. An empty `PYTHONTZPATH` forced bundled timezone fallback; all processes exited 0, without private sentinels or old savings labels. See the ledger for case details. The mandatory independent overlap/reset probes remain **200/200**, **200/200**, **250/250**, all printed `matches_expected=true`.

Limits: no refreshed online prices, historical billing rates, real account/log checks, live provider polling, interactive tray lifecycle, macOS, Figma or remote CI checks. No settings persistence, database, API, dashboard integration, merge into main or S05 gate is claimed. The retained Record compatibility container remains mutable; S05 will formalize the shared query result rather than treating process-local joins as durable identity. Next ready: **S05 shared headless report/query service**.
