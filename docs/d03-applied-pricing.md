# D03: applied pricing explanation contract

Implemented source contract for the [dashboard sessions](dashboard-refinement-sessions.md). D04 owns its visible Explore Usage presentation and packaged delivery. No database migration or price refresh is required.

## Authority and storage

`usage_pricing_explanation.py` consumes an accepted `EventValuation` and its immutable `IndexSnapshot.catalog`. The existing index already stores both in one publication. It verifies pricing/catalog/override/policy versions, requested-to-matched model mapping, rate identity and source evidence before exposing rates. It never looks up the current bundled registry or pending settings to explain a committed amount.

`usage_valuation.applied_rates()` is shared by valuation and explanation for the five selected category rates. Tier selection remains the event's recorded selection, with existing request-context evidence and compatibility/TTL assumptions. Prices, token facts, event identities and the 12-place valuation policy are unchanged. A new publication invalidates old query contexts exactly as before; saving configuration alone does not change the active explanation.

Missing verification yields `unavailable` explanation evidence, retaining the authoritative amount and original metadata rather than substituting rates. This does not weaken existing index decoding, corruption or recovery checks. `valuation_evidence_mismatch` also suppresses rates if their rounded calculation disagrees with the stored event amount.

## Wire fields

The published [JSON Schema](api/usage-hub-v1.schema.json), frontend mirror and [23 synthetic examples](api/usage-hub-v1.fixtures.json) ship together. Existing envelopes/frozen contexts and routes are retained.

- Event `value.explanation`: evidence state/reason, currency `USD`, rate unit `1000000`, requested/matched models and mapping, rate ID, selected tier, source/checked date, custom flag, pricing/catalog/override/policy versions and assumption codes.
- `categories`: exactly five ordered entries when evidence is available: uncached input, output, cache reads, five-minute writes, one-hour writes. Each has `category`, exact integer-string `tokens`, nullable decimal-string `rate_usd_per_million`, and nullable decimal-string `unrounded_usd`.
- `rounding_adjustment_usd`: signed decimal string for priced evidence; null for an unpriced event or unavailable explanation. Category charges/adjustments allow up to **18** fractional USD digits; existing event/group/headline money stays at **12**. Rates retain their existing zero-through-USD1-billion/1M bound and at most 12 fractional places.
- List rows (including the shared project/recent-row type) and conversation detail add `pricing`: `group_count`, `total_record_count`, `shown_record_count`, `truncated`, and at most **eight** `groups`. Each group includes its record count, exact tokens, complete/unpriced state, nullable summed amount, and explanation. Reasoning tokens report the known subset when present; they are never an additional charge category.

These are coordinated local v1 contract additions: strict clients and the service must be delivered together. Existing demo/candidate DTOs remain separate. The client validates category ordering, group display counts/truncation, signed-64-bit category token bounds and full-string decimal patterns; it performs no pricing calculation.

## Exact arithmetic and unavailable states

For each category, `unrounded_usd = tokens × applied rate / 1,000,000`, calculated with the existing 80-digit Decimal context. Do not independently round each category to cents or to the event's twelve-place scale. For a priced event:

```text
sum(category unrounded_usd) + rounding_adjustment_usd = stored amount_usd
```

The stored amount is rounded once per event, half-even at twelve fractional places. Example: one token at USD0.0000005/1M contributes USD0.0000000000005; its stored event amount is zero, and its adjustment is -0.0000000000005. Three such events still sum to zero; rounding their combined raw charge would incorrectly produce a nonzero result. Group explanations sum event charges and adjustments without rounding again.

- Unknown model: explanation unavailable, `model_rate_unavailable`, no fabricated category rates; existing event value stays unpriced/null.
- Missing rate for an active cache-write category: evidence can be available for the known rates, but that category's rate/charge is null and the whole event remains unpriced/null. Known contributions must not be presented as a priced event total.
- Missing rate for an unused category: rate null, zero charge from zero tokens. An absent rate is never displayed as a configured zero rate.
- Explicit configured zero: rate `0`, priced zero amount, available evidence.
- Empty matched conversation: zero groups/records and the existing empty/null summary.
- Stale retained history: its accepted snapshot's explanation remains coherent; existing freshness/coverage qualifications remain visible. Evidence availability does not imply complete local account coverage.

## Mixed-rate groups and D04 handoff

Group only equal model/mapping/rate/tier/source/version/coverage/assumption evidence. Different rates, tiers and assumptions remain separate; there is no blended average rate. The first eight groups follow the service's deterministic matched-event order. Build summaries from **all matched records**, independent of the preview and event page size. Count omitted groups/records explicitly. Accumulation retains only one event explanation at a time, limiting temporary category-object growth for large same-rate groups.

D04 should show a concise per-1M rate line beneath each usage's price/tokens, then expand categories/provenance and label mixed or truncated previews. Conversation details already offer frozen chronological event pagination (up to 100 records/page) for every omitted group's evidence; project rows can narrow the conversation list using the existing project filter. Preserve filters/context/Back and never claim an eight-group preview reconciles the full amount when `truncated` is true. Format exact API strings; do not reconstruct charges in JavaScript. Explain missing evidence rather than opening arbitrary source metadata as trusted links.

No new endpoint, schema migration, provider polling, credential operation, transcript retention, pricing update, frontend redesign, macOS change, package or installation is part of D03. Existing release/native limitations remain open.
