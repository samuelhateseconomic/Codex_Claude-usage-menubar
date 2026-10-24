# Usage Tray for Windows — Codex + Claude

A Windows system-tray companion showing subscription usage remaining, reset times, and **local token/cost reports for both Codex and Claude**. Inspired by this repository's macOS app; the Swift app is unchanged. Supports the active account in each CLI for live limits. Reports analyze local logs across accounts; multi-account sign-in and automatic end-of-session notifications are not implemented.

## Run on Windows

Requires Windows 10/11, Python 3.11–3.14 with pip, and your providers' CLIs. No administrator access is needed.

1. Install the [Codex CLI](https://github.com/openai/codex), for example `npm install -g @openai/codex` with Node.js installed, and run `codex login` with your ChatGPT account. API-key accounts do not provide these subscription limits.
2. Install [Claude Code](https://code.claude.com/docs/en/setup), start `claude`, and use `/login` with your Claude subscription. Launch Claude Code periodically so it can renew its login.
3. Open PowerShell in this repository's `windows` folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe usage_tray.py
```

The icon appears in the system tray, possibly under **Show hidden icons**. Right-click it to see both providers' limits. The top bar represents Codex and the bottom represents Claude when both are selected. Green, amber, and red indicate the lowest remaining window; gray indicates missing or stale data. The tooltip and menu label demo mode explicitly.

Each provider refreshes independently every five minutes. Failures back off; Claude's `Retry-After` is respected. The Refresh menu wakes the checker but does not bypass its polling or backoff interval. Failed polls retain the last successful reading with an explicit stale-data warning. Reset dates are displayed in your local time zone.

The tray redraws on state/report changes rather than every second. Both providers receive Refresh independently, and repeated clicks preserve cooldown/backoff. Login, network, unsupported-response, blocked-usage and unexpected local states are identified separately; a blocked Codex status remains blocked even when a percentage shows remaining capacity.

One tray or real `--once` process owns the local application-data `runtime.lock` file. A duplicate launch exits 3 without starting another poller; use the existing tray or Quit before restarting. Offline reports and diagnostics still work while it runs. Quit cancels Codex RPC waits and cleans up only the app-owned Codex process tree; report viewers already opened for you can stay open. A new process starts a new in-memory polling schedule. See [S07 runtime/recovery](../docs/s07-runtime-recovery.md) for ownership, timing and shutdown limits.

To use only one provider, add `--provider codex` or `--provider claude`. A missing provider login does not stop the other provider.

## Local dashboard development preview

The integrated preview uses the refined core's valuation, summary and fee policies, and the effective saved settings/temporary fee and timezone overrides. Settings remains read-only in the browser. Unknown fees display Unavailable; zero fees remain USD 0.00. Dashboard launch rejects report/export/settings commands and source-root options instead of ignoring them. S08's reduced report metadata and opt-in full report exports remain unchanged. The dashboard's intentional conversation detail view preserves exact metadata identities while showing controls as visible escapes. See the [integration evidence and remaining release gates](../docs/branch-integration-plan.md).

The reviewed Figma dashboard now runs locally with explicit sample data. From the repository root:

```powershell
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --dashboard --demo
```

This opens the browser at `http://127.0.0.1:8765/`. Stop the source-mode server with Ctrl+C. Use `--no-browser` to serve without opening a tab, or `--dashboard-port 8766` if the default port is occupied. A demo tray also has **Open dashboard demo preview...**; Quit stops its owned dashboard server. The packaged `UsageTray.exe --dashboard --demo` keeps a tray owner so you can quit it normally.

The preview supports Codex/Claude/Both, month/today/week, text search, project/model/effort filters, daily token/value charts with labeled axes, conversation details, preserved Back state, two-page sample results, and keyboard shortcuts. It uses local bundled UI assets, Geist fonts, and named timezone data; no frontend build server or CDN is required. Settings are explicitly read-only, and Limits uses sample readings in demo mode.

**Real-data dashboard launch is gated:** `--dashboard` currently requires `--demo`. Core accounting/shared-service gates and the existing database handoff must be completed before enabling real history. The preview neither replaces the terminal nor silently falls back to demo data. Existing real terminal reports and provider limits retain their current behavior and known refinement limitations. See the [implementation handoff](../docs/dashboard-implementation.md).

Run the dashboard checks from the repository root:

```powershell
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -p test_hub.py -v
node --test windows/dashboard/tests/*.test.mjs
.\windows\.venv\Scripts\python.exe windows/tests/packaged_dashboard_smoke.py --exe windows/dist/UsageTray.exe
```

Node is needed only for formatter and controlled handler/recovery tests, not for running the dashboard. The HTTP tests need local loopback access. Packaging uses the normal `windows/build.ps1`, including dashboard assets and `tzdata`. Before repeating interaction work, read the [completed coverage inventory and synthetic browser fault driver instructions](../docs/dashboard-resilience-handoff.md); ordinary navigation and request-failure evidence are recorded separately there.

## Diagnose and test

```powershell
# No login, network calls, or credential reads; sample data is labeled DEMO.
.\.venv\Scripts\python.exe usage_tray.py --demo
# JSON output without GUI dependencies (also works on Linux for development).
.\.venv\Scripts\python.exe usage_tray.py --once --demo
# Real usage: exits nonzero if a selected provider fails.
.\.venv\Scripts\python.exe usage_tray.py --once
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For Codex, the app launches `codex app-server` over local stdin/stdout, initializes it, reads `account/read` and `account/rateLimits/read`, then shuts down that child process. Codex manages its own authentication and refresh. The app does not read Codex token files, send prompts, run agents, or approve tool requests. If a CLI version no longer supports these methods, update it or report the incompatibility. See the upstream [app-server protocol schema](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/json/v2/GetAccountRateLimitsResponse.json).

For Claude, the app reads `%USERPROFILE%\.claude\.credentials.json` (or `CLAUDE_CONFIG_DIR\.credentials.json`) and requests `https://api.anthropic.com/api/oauth/usage`, matching the Swift app's bearer-auth and beta header. This is an undocumented Anthropic endpoint and may change. The app never writes, refreshes, or copies Claude credentials, avoiding refresh-token races with Claude Code. Expired logins require renewing through Claude Code. A Windows-native Claude Code login is required: WSL-only credentials and macOS Keychain entries are not automatically imported. If Claude Code uses a different credential store, this adapter will need an update.

Credentials are used locally and sent only by the provider's normal authentication route. Claude redirects are rejected to prevent forwarding bearer tokens. No credentials, raw server error bodies, or conversation text are logged or copied into reports. Live limit snapshots exist only in memory. Reports read existing local CLI logs and save token aggregates, model names, project names, and conversation IDs locally. The app respects existing proxy and TLS settings.

## Estimated API value and plan comparison

Right-click the tray icon and choose **This month: API value & plan comparison…**, **Current session estimated API value…**, **Today's estimated API value…**, or **Last 7 days estimated API value…**. By default, a text report opens in a PowerShell window that stays open until you close it. No browser is needed. It shows a compact summary of value, plan comparisons, tokens and coverage. Use the CLI detail/audit options below for deeper inspection. To use the full HTML report instead, start the tray with `--report-format html`. The HTML report includes:

- Total recorded tokens and estimated API-equivalent USD value.
- Uncached input, cache reads, cache writes, and output (including reasoning).
- Breakdowns by provider, **model + effort**, effort, model, project, conversation, and day.
- Recorded effort and reasoning-token subtotals, plus an expandable turn/usage-event history showing the setting's source.
- Price assumptions, unpriced models, and missing or incomplete log coverage.

For the session report, a recent provider reset time anchors the current five-hour quota window when available. Otherwise the report explicitly uses the last five hours. This is a quota session; separate conversation IDs appear in the conversation breakdown. Today uses your local midnight; the weekly report covers the last seven days. Reports are generated on demand, without uploading logs. They include all accounts whose activity is present in the configured local log folders, and cannot attribute usage to the currently signed-in account reliably.

Codex records come from `%USERPROFILE%\.codex\sessions` and `archived_sessions` (or `CODEX_HOME`). Claude Code records come from `%USERPROFILE%\.claude\projects` (or `CLAUDE_CONFIG_DIR`). Completed responses and recorded counters are counted; ongoing responses may not appear until their CLI writes usage. Repeated cumulative Codex counters and streamed Claude message updates are deduplicated. Cached Codex input is a subset of input, and reasoning is a subset of output: neither is counted twice. Claude cache writes distinguish 5-minute and 1-hour prices when the logs provide those details; legacy writes without TTL details are labeled as an estimate at the 5-minute rate.

Copied and overlapping histories are reconciled before Codex cumulative deltas are calculated. Counter resets exclude the ambiguous transition and preserve later valid increments in a new epoch. Fork history seeds a baseline without charging inherited work; if that baseline is unavailable, the first observed child interval is excluded. Same-time observations need source ordering evidence. Missing/invalid counters and unresolved ordering break the baseline; counting resumes after a complete point re-establishes it. Report notes identify assumptions and exclusions; excluded token amounts are unknown, not zero.

Claude streamed updates retain category maxima for supported message/request identity. Detailed cache-write TTL evidence resolves earlier legacy aggregate writes rather than counting both representations. Conflicting metadata is qualified as unknown or excluded; a conflicting model remains unpriced. Mixed Codex last-only and cumulative measurement modes are conservatively excluded from last-only additions to prevent double charging. These policies do not establish complete account coverage. See the [S02 reconciliation policy](../docs/s02-reconciliation.md) for supported cases and limits.

Source scans distinguish **empty, complete, partial, and failed** local data and list issue counts. Complete means no known ingestion gaps in the scanned files, not full account coverage. Active incomplete final records are deferred; complete JSON at EOF is supported without a final newline. Files are verified as one prefix with a bounded retry for mutation, truncation or replacement. Records after a malformed complete line are conservatively deferred because context may be missing. Rescan after source recovery; the current offline path does not retain a committed history database. Modification time never excludes otherwise relevant history. See [S03 source quality and time](../docs/s03-source-quality-and-time.md).

Report boundaries and daily groups use **America/Los_Angeles** by default, with offline bundled IANA timezone data. Use `--timezone UTC` or another IANA name to change report dates and calendar boundaries. This replaces the older host-local day/month interpretation. Ranges include their start and exclude their captured end; Last 7 days remains a trailing 168 hours, including across daylight-saving changes. Live-limit reset display retains its existing host-local behavior.

**Dollar values estimate what your recorded tokens would cost at API token prices, not an actual bill or a conversion of your quota percentage.** The month-to-date report compares that estimated API value with your full monthly plan fees: **$20 for Codex and $20 for Claude** by default. The signed comparison is **estimated API value minus the full monthly fee**; positive and negative amounts are qualified estimates, not realized savings. Only unfiltered calendar-month-to-date (optionally by provider) is comparable. Unpriced models make the comparison incomplete; missing local usage records leave the comparison unavailable. The period starts on the first day of the calendar month, not your subscription renewal date, and does not project future usage. Use `--codex-plan-usd 20 --claude-plan-usd 20` to change the comparison prices when starting the tray or generating a report. Browser chat, cloud/remote tasks, other devices, and missing local logs cannot be counted. Counts can therefore differ from provider-wide usage. Unknown models remain in token totals but are marked unpriced, making the dollar subtotal explicitly incomplete. Bundled rates and their source are listed in the report. Discounts, priority/flex pricing, tools, taxes, and unrecorded billing adjustments are excluded. Tiered models use recorded request-context evidence when available. Otherwise the existing event-input tier policy is retained and labeled as an assumption; neither cumulative/group totals nor model context capacity prove a request size.

Pricing uses exact Decimal rates and money, with half-even rounding once per event to 12 fractional USD digits and exact summation. Reports distinguish empty, all-unpriced, partially priced, and completely rate-covered results, with independent source-quality and tier/TTL qualifications. Catalog, override and computation versions identify the applied pricing snapshot; bundled checked dates are retained rather than silently refreshed. See [S04 exact valuation](../docs/s04-exact-valuation.md) for precision/bounds, provenance, compatibility changes and verification.

CLI and tray reports now use one immutable headless query result for totals, groups, event details, source quality and signed fee comparisons. Text and HTML format the same result. Metadata filters and exact stable ranking are available to Python consumers without importing provider adapters or GUI packages; no database or API is required. See [S05 shared query service](../docs/s05-headless-query-service.md) for the contract, compatibility adapters and limits.

Reports are saved under `%LOCALAPPDATA%\UsageTray\Reports`. They contain local project names and conversation IDs, so review before sharing. Delete files there when no longer needed.

You can also generate reports without starting the tray, without API access, and without the tray dependencies:

```powershell
.\.venv\Scripts\python.exe usage_tray.py --report session --open-report
.\.venv\Scripts\python.exe usage_tray.py --report today
.\.venv\Scripts\python.exe usage_tray.py --report today --timezone UTC
.\.venv\Scripts\python.exe usage_tray.py --report month
.\.venv\Scripts\python.exe usage_tray.py --report today --report-format html --output .\today.html
.\.venv\Scripts\python.exe usage_tray.py --report week --provider codex --open-report
.\.venv\Scripts\python.exe usage_tray.py --report session --demo --output .\demo.txt
```

### Compact terminal views

The CLI and tray text default is a roughly 20–30-line summary at 80 columns, with API-equivalent value, qualified signed plan differences, token categories, and separate source/counter/pricing/assumption states. Thousands remain exact comma-separated integers; millions/billions use M/B with up to two decimal places, matching the dashboard. `--audit` retains exact counts, all legacy groupings, rates and detailed notes. HTML remains the explicit full report.

```powershell
.\.venv\Scripts\python.exe usage_tray.py --report month
.\.venv\Scripts\python.exe usage_tray.py --report month --details model
.\.venv\Scripts\python.exe usage_tray.py --report month --details conversation --page-size 10 --page 2
.\.venv\Scripts\python.exe usage_tray.py --report month --details project --width 60
.\.venv\Scripts\python.exe usage_tray.py --report month --audit --output .\audit.txt
```

`--details` selects one provider, model, model_effort, effort, project, conversation or day grouping. Pages rank exact priced contribution, then unpriced groups; partial values stay labeled as priced subtotals. The headline always covers the full matched result. Omit `--details` to return to the summary. Each CLI invocation captures a fresh scan; pagination across separate commands is not a persisted frozen query. Page size is 1–50 and width 40–160. Terminal options require text format; if HTML is saved as your preference, add `--report-format text`. Full path/ID metadata still requires explicit `--include-metadata`; reduced labels are not anonymization. View/paging/width choices do not become saved settings. See [S10 terminal views](../docs/s10-terminal-views.md).

Offline commands do not fetch a provider reset time, so `--report session` uses the last five hours. `--demo` uses clearly labeled samples and reads no logs. For updated or new models, copy [prices.example.json](prices.example.json) to `%LOCALAPPDATA%\UsageTray\prices.json` and edit exact model rates in **USD per million tokens**. Before persistent settings are initialized, the app loads that file at startup; `--prices .\my-prices.json` selects another file. See persistent settings below for migration and precedence. Each model requires `input`, `output`, and `cached`; Claude cache writes also use `write5m` and `write1h`. Omitted write rates stay unconfigured: events using them are unpriced until configured. Explicit zero rates are allowed. JSON numbers and decimal strings support up to 12 fractional digits, bounded to USD 1,000,000,000 per million; fees share that bound/scale. Restart the tray after changing prices.

### Persistent settings and version diagnostics

Settings live in `%LOCALAPPDATA%\UsageTray\settings.json` (or `~/.local/share/UsageTray` without LOCALAPPDATA). Ordinary startup uses defaults when absent and does not create a file. Save your choices explicitly; restart an existing tray to load them:

```powershell
.\.venv\Scripts\python.exe usage_tray.py --save-settings --codex-plan-usd 20 --claude-plan-usd 20 --timezone America/Los_Angeles --report-format text
.\.venv\Scripts\python.exe usage_tray.py --show-settings
.\.venv\Scripts\python.exe usage_tray.py --diagnostics
.\dist\UsageTray.exe --version --output .\version.json
.\dist\UsageTray.exe --diagnostics --output .\diagnostics.json
```

Explicit CLI values override saved values for that run; only `--save-settings` persists them. `--config PATH` selects a separate file. Repeated `--codex-root` / `--claude-root` flags replace that provider's log-directory list with absolute paths. In JSON, null roots retain environment defaults and an empty list disables discovery; null fees mean unknown, while zero is a known zero fee. Saved settings include exact rates, timezone and the existing text/HTML preference. [settings.example.json](settings.example.json) is the complete schema template.

The legacy automatic `prices.json` remains active until settings are first saved; that save copies validated rates into settings without modifying the legacy file. Afterward edit `rate_overrides` in settings or use `--prices PATH`, which replaces custom overrides for a run and persists them only with `--save-settings`. Invalid or partial settings stop startup with recovery guidance and remain untouched. `--version` works independently for diagnosis; JSON commands in the windowed executable use `--output` without opening a browser. `--show-settings` includes configured paths; `--diagnostics` includes only root modes/counts plus computation/configuration identities. See [S06 configuration and recovery](../docs/s06-persistent-configuration.md) for schema, migration, precision, atomic-write and build-identity limits.

### Generated reports and recovery

Automatic saved reports now go to `%LOCALAPPDATA%\UsageTray\Reports\Generated`. After each successful automatic save, the app keeps at most 100 generated reports and removes generated reports older than 30 days. The new report is protected; a cleanup permission/IO failure leaves it available and produces a safe warning. Keep manually managed files outside this reserved folder. Old reports directly under Reports and explicit `--output` exports elsewhere are untouched; source histories are never cleanup targets. This bounds count/age, not total disk bytes. Terminal output without a saved file needs no cleanup.

Report failures identify permissions, disk space, file IO, unsupported data/calculation, unexpected local problems or opening the viewer. If opening fails, the saved file remains available. Native viewer launch/interaction and unusual long-running IO still need the release checks documented in [the S07 contract](../docs/s07-runtime-recovery.md).

### Metadata privacy and local diagnostics

Reports now use project-path basenames and abbreviated ID digests by default. These are display labels, not anonymization; counts and internal identities stay exact. Add `--include-metadata` to a report command for full project paths and conversation IDs (plus turn IDs in HTML history). Full metadata remains intentional and should be reviewed before sharing. Terminal controls, bidi/format characters and embedded newlines are rendered as visible escapes; HTML text is escaped and embedded active content is restricted.

```powershell
.\.venv\Scripts\python.exe .\usage_tray.py --report month --include-metadata --output .\private-report.txt
.\.venv\Scripts\python.exe .\usage_tray.py --diagnostics --output .\configuration-check.json
.\.venv\Scripts\python.exe .\usage_tray.py --report month --diagnostic-output .\report-operation.json
.\.venv\Scripts\python.exe .\usage_tray.py --once --demo --diagnostic-output .\demo-check.json
```

`--diagnostics` checks configuration/build identities offline, including a safe settings failure result (exit 2). The explicit `--diagnostic-output` option records a report/one-shot operation's ID, build, phase, category, static recovery action and aggregate counts, even on handled failure. It excludes transcripts, credentials, raw exceptions/payloads, paths and record identifiers. It is not a log of the running tray. Real `--once` still polls providers; demo avoids credential/network access. Partial source coverage is labeled `partial` even if report generation succeeds. No diagnostic file is written automatically, uploaded or pruned; manage the selected export yourself. `--show-settings` intentionally includes configured roots and is not a redacted diagnostic export. See [the S08 contract](../docs/s08-privacy-diagnostics.md) for schema, artifact locations, retention and verification limits.

### Effort changes within a conversation

Effort is tracked per recorded turn/message, not once per conversation. For example, a GPT-5.4 conversation that switches **medium → high → ultra** produces three separate model-and-effort buckets. Every subsequent token increment is associated with the recorded turn context active when that increment was logged. `xhigh`, `max`, and `ultra` remain distinct wire labels; the app does not map them to each other. Custom recorded effort names are preserved as well.

For Codex, effort comes from [`turn_context.effort`](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs), with an explicit collaboration-mode setting as a fallback when the top-level field is absent. The next context resets the association: if it omits effort, new usage is **unknown**, rather than inheriting the previous turn's setting. The HTML report shows metadata sources and abbreviated turn labels in **Turn and usage-event history**; `--include-metadata` explicitly includes full turn IDs. Multiple usage increments can belong to the same turn.

For Claude, only explicit effort metadata attached to the logged request, message, or user turn is used (such as `effort`, `effortValue`, or `output_config.effort`). Tool-result messages remain in the current turn; a new user prompt resets the association. Some Claude Code versions do **not** persist the effective request effort in their transcript. Those records stay **unknown**, and the report states how many records/tokens lack effort. Current settings files, thinking budgets, and prompt text cannot reliably reconstruct historical effort and are not used to guess it. Existing logs with no effort metadata cannot be retroactively labeled accurately.

The **Reasoning (subset)** column uses a separate numeric usage counter when recorded. Missing or inconsistent counters remain unavailable. Reasoning tokens are already part of output tokens, so this column is informational and is never added to totals or charged twice. Effort itself does not receive an invented price multiplier: API-equivalent value remains the actual token counts multiplied by model rates. Higher effort can consume more output/reasoning tokens; the report captures those recorded differences.

## Build an executable on Windows

From PowerShell in this folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
.\dist\UsageTray.exe
```

The script installs pinned dependencies, runs the full suite, bundles Python and local named-timezone data into `dist\UsageTray.exe`, then runs 18 bounded offline executable checks. A failed smoke check fails the build. Existing `.venv` environments are reused; a missing environment uses the `python` selected on PATH (including `actions/setup-python` in CI). Codex/Claude CLIs remain separate prerequisites. The executable is unsigned; signing and distribution are separate release steps. No startup registration is changed automatically. To launch at login, optionally place a shortcut to your built executable in the folder opened by `Win+R` → `shell:startup`.

Alternatively, push the changes to GitHub and run **Actions → Build Windows Usage Tray → Run workflow**. The workflow has Windows jobs for Python 3.11, 3.12, 3.13 and 3.14; each tests, builds and smoke-tests its own executable and uploads `UsageTray-Windows-Python-<version>`. It also runs when changes to `windows/` are pushed or proposed in a pull request. A configured matrix is not evidence that remote jobs passed; see the [Windows release record](../docs/s09-windows-release.md) for actual results and limits.

Native tray/menu and terminal-viewer interaction remain separate from hidden executable acceptance. A Linux test run validates adapters and protocol behavior, not a Windows executable. Before distribution, run the app on Windows with both real accounts, check remaining percentages against each provider's usage page, confirm reset times, test expired/missing logins, and quit/relaunch it.

### Current-model price coverage

The bundled rates include GPT-6.1 Sol (input $2, output $10, cached input $0.10 per million tokens; higher context tier above 272,000 input tokens) and Claude Opus 5.5 (input $4, output $20, cache reads $0.20, 5-minute cache writes $5, 1-hour cache writes $8 per million tokens). Sources: https://developers.openai.com/api/docs/models/gpt-6.1-sol and https://platform.claude.com/docs/en/models/opus-5-5/overview, checked October 23, 2026.

Models without a configured public API rate, including `codex-auto-review`, retain their token counts and appear as **unpriced**, never as a zero-dollar API estimate. Partial comparisons show only the priced subtotal minus the plan fee. Text reports list the rates used and their sources. Standard API-equivalent estimates exclude service-tier premiums.

### Repeat release checks

From this `windows` folder, after building:

```powershell
.\.venv\Scripts\python.exe tools/release_smoke.py --exe dist/UsageTray.exe
# Explicit read-only check of real environment-default histories; no provider polling.
.\.venv\Scripts\python.exe tools/local_history_audit.py --read-local-history
# Explicit terminal report launch from the packaged app.
.\dist\UsageTray.exe --report month --open-report
```

The audit prints allowlisted counts, bounded display-safe model labels, coverage states, structured issue counts, inventory bytes and measured scan/query time. It checks exact category/value reconciliation through provider, conversation and all other groupings. It does not export paths, transcript text, identifiers, arbitrary notices or raw errors. Its inventory is measured separately from the query, so active writes can change file counts/bytes between them. A passing reconciliation check can accompany failed/partial source coverage; inspect the provider states. It deliberately uses environment-default roots and bundled rates, without loading saved configuration. This is a developer release check, not account verification or an alternative report/diagnostic format. See the [S09 record](../docs/s09-windows-release.md).


The optional headless local index is documented in [S11](../docs/s11-local-index.md). It supports explicit metadata-only import, recoverable SQLite publication and offline shared-service queries. It is not yet connected to the tray/dashboard preview; production API and real-data dashboard integration follow S12/S13.


The explicit production local API is documented in [S12](../docs/s12-local-api.md), with [OpenAPI](../docs/api/usage-hub-v1.openapi.json), [response schema](../docs/api/usage-hub-v1.schema.json) and [synthetic examples](../docs/api/usage-hub-v1.fixtures.json). Run `windows/usage_api_main.py` with the project interpreter; it uses the recoverable index and does not poll providers unless `--live-limits` is explicit. `--open` opens the authenticated service status page; the reviewed dashboard remains the labeled preview until S13.
