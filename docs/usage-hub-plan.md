# AI Usage Hub — UX/UI and build plan

Status: product/design background. The [integration contract and delivery plan](usage-hub-integration-plan.md) is the current authority for data semantics, API routes, storage/reconciliation, first-release scope, and release gates. Where the documents differ, follow that contract. Keep the existing terminal entry point; the local web dashboard is an explicit launch option.

## Product direction

Build a desktop-first, local web dashboard for understanding Codex and Claude token usage, estimated API-equivalent value, and the projects and conversations behind that activity.

Confirmed design preferences: a developer console with dark surfaces, compact information, and strong keyboard support. The first priority is understanding token usage and estimated costs. Subscription capacity and reset times support that primary workflow.

The core question is: **Where did my AI usage go, and what would the recorded work cost at API token prices?**

This document is a build plan. It does not implement the web application. Figma deliverables below describe the proposed design work; a navigation diagram is pending selection of a Figma team or organization in the tool's widget.

## What the folder already provides

Use the Windows Python companion as the foundation for the web application:

- `windows/usage_core.py`: provider adapters, quota windows, remaining percentages, reset timestamps, and last successful check time. Codex uses a local app-server process. Claude uses its existing CLI credentials and a provider usage endpoint.
- `windows/usage_reports.py`: local log discovery, normalized usage records, deduplication, model prices, per-record estimates, period boundaries, monthly plan comparisons, and offline reports.
- `windows/usage_tray.py`: independent provider refresh, five-minute polling, exponential backoff, stale-data handling, and report entry points. Its state management currently lives alongside the tray UI.
- `windows/tests/test_reports.py` and `windows/tests/test_usage.py`: existing regression coverage for parsing, quota adapters, token accounting, effort, estimates, and error handling.
- The Swift application supplies additional UX precedent for account management and reports, but its multi-account capabilities are not implemented in the Windows companion.

The folder has no existing browser frontend or persistent query API. Existing Python files have local modifications; the web work should build on that working state and preserve those edits.

## Data boundaries that shape the interface

1. **Local usage and live limits have different coverage.** Reports include records found on this computer, potentially across accounts. Live limits represent the active CLI account for each provider. Do not imply they are an account-matched dataset.
2. **API-equivalent value is an estimate, not a bill.** Use recorded tokens and configured model rates. Never convert a quota percentage into dollars.
3. **Missing data is not zero.** Unknown prices, missing folders, unrecorded effort, and unavailable reasoning counters need distinct states.
4. **Token categories must not overlap.** The normalized input counter is uncached input. Cache reads and cache writes are separate categories. Reasoning is already included in output and must not be added again.
5. **Local logs are incomplete account coverage.** Browser chat, remote/cloud work, other devices, and absent logs are outside the current report scope. Even a fully indexed local folder does not establish complete account-wide usage.
6. **History requires new storage.** Live limit snapshots currently exist only in memory. Historical quota charts need explicitly collected snapshots and cannot be reconstructed from token logs.
7. **Activity is recorded, not necessarily live.** Do not mark a conversation as running merely because it has recent usage. Current records contain identifiers and usage metadata, not a reliable running-state signal.
8. **Search starts with metadata.** Search project paths, conversation IDs, providers, and model names. Prompt search and conversation titles are outside the initial content-free data model.

## Information architecture

Keep the primary navigation small:

- **Overview:** month-to-date value, recorded tokens, daily usage, provider comparison, and recent conversations.
- **Explore:** a filterable usage ledger with Projects and Conversations views, plus detail drawers.
- **Limits:** all returned provider windows, remaining capacity, resets, and freshness.
- **Settings:** connections, log roots, model rates, monthly plan fees, appearance, and data controls.

Model and effort analysis belong inside Overview and Explore rather than additional navigation sections. This preserves context when moving from a chart to the records behind it.

## Landing screen composition

Design first at 1440 × 900, then verify at 1280 × 800 and narrow widths.

1. **Compact left rail:** product name, four navigation destinations, and connection indicators. A bottom action opens Settings. Labels stay visible on desktop.
2. **Header:** page name, provider selector, date range, search trigger, and index freshness. Default range is month to date to match the cost-first priority.
3. **Summary strip:** estimated API-equivalent value is the dominant figure; recorded tokens, conversations with usage, and optional configured monthly plan fee follow. Show the word “Estimated” beside the dollar metric.
4. **Main chart:** daily API-equivalent value, with a token/value toggle and Codex/Claude series. Display units, range, legend, and local-log coverage. Selecting a day filters the ledger; a visible clear action restores the full range.
5. **Compact capacity panel:** each provider's most constrained returned window, reset countdown, and last successful check. Expand to see every returned window, including additional Codex buckets and model-specific Claude windows.
6. **Model and effort breakdown:** sortable rows for provider, model, recorded effort, tokens, estimated value, and share of the priced subtotal. Expand a row into matching usage records. Preserve unknown effort as a visible bucket.
7. **Recent conversations:** provider, project, shortened conversation ID, most recent recorded usage, tokens, and estimated value. Open a detail drawer without losing filters.
8. **Scope caption:** “Usage recorded on this computer.” Show “All local accounts” on report views and “Active CLI account” on capacity views. Coverage details explain excluded activity.

Use the chart and ledger as the main workspace. Avoid giving every statistic an equally large card.

## Key interactions

### Understand costs

- Change Today / Last 7 days / Month to date. Add arbitrary ranges after extending the backend beyond its existing preset periods.
- Toggle Both / Codex / Claude; apply the choice consistently to the chart, totals, breakdowns, and ledger.
- Sort models by estimated value, then open a model/effort row to inspect contributing conversations and events.
- Expand a value explanation to see uncached input, output, cache reads, cache writes, applied rate, and rate source/check date.
- Display reasoning as “Included in output” when recorded. Show unavailable counters without inferring zero.
- For unpriced models, show token usage and “Unpriced.” Summary dollars become “Priced subtotal” with an incomplete-estimate indicator; never silently treat unpriced records as free.
- Keep plan comparison secondary. Use user-configured monthly fees and a signed “Estimated API value minus monthly fee” comparison. Explain that this is a calendar-month comparison, not realized savings or a billing-cycle invoice.

### Locate work

- Search project paths and conversation IDs across both providers. Use provider plus conversation ID as the identity key.
- Group by normalized project path, with an expandable full path to distinguish identical folder names. Allow explicit aliases for different paths that represent the same project; do not merge solely by basename.
- A project detail shows both providers, daily usage, model/effort breakdowns, and its conversations.
- A conversation detail shows its ID, project, first/last recorded usage, totals, and usage events ordered by timestamp. Events are not necessarily one-to-one with turns; group by recorded turn ID when present.
- Filters appear as removable chips. Switching views preserves them, and Back returns to the prior scroll position.
- Start with Copy conversation ID and Copy project path. Opening an agent conversation needs a verified provider-specific launch/deep-link contract and belongs in a later release.

### Monitor capacity

- Show percent remaining with a text label and horizontal bar; color supplements the number.
- Show a relative reset countdown and the absolute timestamp in the user's selected display timezone. Use America/Los_Angeles initially for this user.
- Keep quota windows separate. Do not sum percentages or blend them into an overall remaining balance.
- Respect a provider's blocked-usage status even when a window still reports remaining percentage.
- “Check for updates” respects polling and backoff. During cooldown, display the next eligible check time. Retain the last successful reading with a stale label after failures.
- Recent local records can remain available when live quota authentication fails, and live limits can remain available when logs are missing.

### First run

Detect each CLI and configured log root independently. Present each provider with a plain status and one relevant next step: install CLI, sign in through the CLI, select log folder, or view available data. Allow entry with one provider connected. Offer clearly labeled demo data only as an explicit mode; never substitute it for a failed real connection.

## Visual language and accessibility

- Dark neutral background, slightly lighter panels, subtle separators, and restrained accents. Use a warm rust accent for Claude and a cool teal accent for Codex; pair both with provider names.
- Use a system sans-serif for labels and a system monospace for IDs, paths, model names, and detailed numeric rows. Use tabular numerals for comparisons.
- Proposed typography: 14px body/ledger, 12–13px supporting labels, 20–24px page titles, and one 32px primary cost metric. Validate legibility in Figma before finalizing tokens.
- Use an 8px spacing rhythm, compact rows, modest corner radii, and no decorative gradients or oversized empty panels.
- Provide comfortable and compact density settings; compact is the user's default.
- Charts need visible units and a tabular alternative. Status, selection, and provider identity must remain understandable without color.
- All controls need keyboard access, visible focus, and readable contrast. Respect reduced-motion settings.
- Proposed shortcuts: `/` focuses search, `Esc` clears/dismisses the current overlay, and a documented shortcut opens a command palette. Avoid overriding common browser shortcuts. Use standard Tab navigation and appropriate arrow-key behavior within composite controls.
- Detail drawers manage focus and return it to the originating row when closed. They become full-width panels on narrow screens. Wide ledgers allow intentional horizontal scrolling without hiding column labels.

## States to design explicitly

- Initial scan with progress and counts; partial results remain usable.
- No recorded usage in the selected period: suggest another period and show coverage, without claiming zero account usage.
- No search matches: retain filters and offer Clear filters.
- One connected provider and one unavailable provider.
- Expired login with a CLI sign-in instruction; other data remains accessible.
- Provider cooldown or failed refresh with last successful data and next retry.
- Missing log roots, malformed records, and unavailable timestamps.
- Unpriced model, unknown effort, missing reasoning counter, and partially priced totals.
- Quota reset time reached: show “Awaiting refreshed limit” until a new snapshot arrives; do not invent restored capacity.
- Explicit demo mode with a persistent label and separate storage namespace.

## Proposed implementation

**Keep Python for collection and calculation; add a local API and browser frontend.** The browser cannot directly reuse these Python collectors or read the CLI's local credentials. A local companion service supplies sanitized usage data.

Recommended stack: a Python FastAPI service and React with TypeScript for the interface. FastAPI suits the existing Python data model; React supports the shared interactive filter state and reusable detail views. These are proposed choices, not existing dependencies. References: https://fastapi.tiangolo.com/ and https://react.dev/learn.

- Extract provider polling/state management into a GUI-independent service shared by the tray and web interface. One service owns provider checks so multiple tabs do not multiply network polling.
- Adapt `Record`, `Tokens`, `Snapshot`, and `Report` into explicit JSON response contracts. Add freshness, coverage, pricing-completeness, and indexing metadata.
- Reuse token category semantics and pricing metadata, but fix the documented overlap/reset accounting defects before treating current parser output as a trusted oracle. Both terminal and web aggregates must consume the same reconciled query result; the browser must not reimplement valuation.
- SQLite is the proposed local index, subject to existing database work. Reparse changed files, reconcile whole affected conversations across copies, and atomically publish canonical events/provenance. Replacing per-file rows alone does not prevent cross-file double counting. Quota history remains a later opt-in feature.
- Track each indexed file's identity, changes, parser version, and scan status. Preserve stable event identity/deduplication across restarts and streamed record updates.
- Preserve full project identity and source metadata internally. Return only the fields needed by each screen; do not parse or expose prompt/response text.
- Use the integration plan's `/api/v1` contract, including frozen query contexts, exact decimal/integer-string fields, versioned settings/pricing, and asynchronous job status. The older unversioned route sketches are superseded.
- Add validated local settings routes for fees, rates, and approved log roots. Do not permit arbitrary shell commands or arbitrary file reads through route parameters.
- Bind to loopback, serve frontend and API under one origin, validate Host/Origin, and protect mutations with a per-install/session authorization mechanism. Credentials stay in the existing local provider route and never appear in browser storage, API responses, exports, or logs.
- Start with lightweight browser polling of the cached service state; it must not trigger provider checks on every page request. Evaluate server-sent events only if needed.
- Store instants in UTC, label display timezone, and define local-day/month boundaries consistently in the API. Custom display-zone selection requires explicit timezone-aware period handling; current report presets use host-local boundaries.
- Add a tray action to open the dashboard and a web launch command. Serve compiled frontend assets from the local service for a simple Windows launch.

A hosted dashboard or access from another device requires a separate sync/authentication design. The initial scope is a web interface on this Windows computer, which matches the current collectors and local data.

## Delivery sequence and completion criteria

### 1. Data contract and design foundation

Confirm field semantics against fixture logs, specify API responses and coverage states, and establish dark-theme tokens. In Figma, produce an annotated Overview, Explore, Conversation detail, Limits, and Connections flow at desktop size, plus a narrow-screen adaptation.

Complete when every displayed metric has a defined source, period, scope, and unavailable state, and the Figma prototype supports Overview → filtered usage → conversation detail → Back.

### 2. Interactive prototype

Build the dashboard shell with labeled sample fixtures covering both providers, mixed effort, unpriced models, stale limits, and missing logs. Connect filters, chart selection, sorting, search, detail drawers, and keyboard navigation.

Complete when the user can explain an estimated total, find a conversation, and return to the same filtered view without losing context. Sample data stays visibly labeled.

### 3. Local data integration

Add the API, shared polling service, log index, and aggregate queries. Wire real data without reading or displaying conversation content. Preserve existing tray behavior and Python tests.

Complete when web and terminal totals match the shared service's corrected fixture expectations, both providers operate independently, multiple tabs/processes share provider refreshes, and restarts/file updates do not duplicate usage. Existing parser output is a compatibility check, not the oracle for documented accounting defects.

### 4. Reliability and Windows delivery

Add loading/recovery states, pricing/fee settings, scoped exports, responsive behavior, and packaged frontend assets. Include rate sources and coverage in exports. Verify actual Windows launch and tray-to-dashboard behavior.

Complete when missing credentials, cooldown, stale snapshots, mixed-priced data, large histories, and timezone boundaries are handled visibly. Check that credentials and prompt content never enter API payloads or exports. Agree a representative local-history fixture, then measure a target of under two seconds for indexed overview/filter queries on that machine, without blocking on live provider requests.

## Verification plan

- Reuse existing adapter/parser/accounting tests and add meaningful contract tests for API aggregation, filters, pagination, unknown values, and day/month boundaries.
- Test ingestion idempotency with repeated cumulative Codex counters, streamed Claude updates, model/effort changes, and a changed file after restart.
- Run browser workflows for filter → chart selection → detail → Back, independent provider failures, and keyboard-only navigation.
- Check layouts at desktop, narrow laptop, and phone widths; verify contrast, focus, chart alternatives, and reduced motion.
- Check real Windows provider limits against provider displays when available. Local token totals should match report fixtures; they need not equal provider-wide activity.

## Deferred until the core workflow works

Cross-device/cloud synchronization, multi-account login management, prompt-text search, automatic session reopening, forecasts, and threshold notifications. Each needs data or behavior beyond the existing Windows companion. Historical quota charts begin only after opt-in snapshot collection and should show their actual coverage start date.
