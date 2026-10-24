# Usage Tray for Windows — Codex + Claude

A Windows system-tray companion showing subscription usage remaining, reset times, and **local token/cost reports for both Codex and Claude**. Inspired by this repository's macOS app; the Swift app is unchanged. Supports the active account in each CLI for live limits. Reports analyze local logs across accounts; multi-account sign-in and automatic end-of-session notifications are not implemented.

## Run on Windows

Requires Windows 10/11, Python 3.11+ with pip, and your providers' CLIs. No administrator access is needed.

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

To use only one provider, add `--provider codex` or `--provider claude`. A missing provider login does not stop the other provider.

## Local dashboard development preview

The reviewed Figma dashboard now runs locally with explicit sample data. From the repository root:

```powershell
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --dashboard --demo
```

This opens the browser at `http://127.0.0.1:8765/`. Stop the source-mode server with Ctrl+C. Use `--no-browser` to serve without opening a tab, or `--dashboard-port 8766` if the default port is occupied. A demo tray also has **Open dashboard preview (sample data)…**; Quit stops its owned dashboard server. The packaged `UsageTray.exe --dashboard --demo` keeps a tray owner so you can quit it normally.

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

Right-click the tray icon and choose **This month: API value & plan savings…**, **Current session estimated API value…**, **Today's estimated API value…**, or **Last 7 days estimated API value…**. By default, a text report opens in a PowerShell window that stays open until you close it. No browser is needed. It shows totals and breakdowns by provider, model and effort, project, conversation, and day. To use the full HTML report instead, start the tray with `--report-format html`. The HTML report includes:

- Total recorded tokens and estimated API-equivalent USD value.
- Uncached input, cache reads, cache writes, and output (including reasoning).
- Breakdowns by provider, **model + effort**, effort, model, project, conversation, and day.
- Recorded effort and reasoning-token subtotals, plus an expandable turn/usage-event history showing the setting's source.
- Price assumptions, unpriced models, and missing or incomplete log coverage.

For the session report, a recent provider reset time anchors the current five-hour quota window when available. Otherwise the report explicitly uses the last five hours. This is a quota session; separate conversation IDs appear in the conversation breakdown. Today uses your local midnight; the weekly report covers the last seven days. Reports are generated on demand, without uploading logs. They include all accounts whose activity is present in the configured local log folders, and cannot attribute usage to the currently signed-in account reliably.

Codex records come from `%USERPROFILE%\.codex\sessions` and `archived_sessions` (or `CODEX_HOME`). Claude Code records come from `%USERPROFILE%\.claude\projects` (or `CLAUDE_CONFIG_DIR`). Completed responses and recorded counters are counted; ongoing responses may not appear until their CLI writes usage. Repeated cumulative Codex counters and streamed Claude message updates are deduplicated. Cached Codex input is a subset of input, and reasoning is a subset of output: neither is counted twice. Claude cache writes distinguish 5-minute and 1-hour prices when the logs provide those details; legacy writes without TTL details are labeled as an estimate at the 5-minute rate.

**Dollar values estimate what your recorded tokens would cost at API token prices, not an actual bill or a conversion of your quota percentage.** The month-to-date report compares that estimated API value with your full monthly plan fees: **$20 for Codex and $20 for Claude** by default. Estimated savings so far = estimated API value minus the monthly fee. If value is below the fee, the report shows how far below rather than claiming savings. Unpriced models make the comparison incomplete; missing local usage records leave the comparison unavailable. The period starts on the first day of the calendar month, not your subscription renewal date, and does not project future usage. Use `--codex-plan-usd 20 --claude-plan-usd 20` to change the comparison prices when starting the tray or generating a report. Browser chat, cloud/remote tasks, other devices, and missing local logs cannot be counted. Counts can therefore differ from provider-wide usage. Unknown models remain in token totals but are marked unpriced, making the dollar subtotal explicitly incomplete. Bundled rates and their source are listed in the report. Discounts, priority/flex pricing, tools, taxes, and unrecorded billing adjustments are excluded. The GPT-5.4 long-context price tier is applied when the recorded request input exceeds 272,000 tokens.

Reports are saved under `%LOCALAPPDATA%\UsageTray\Reports`. They contain local project names and conversation IDs, so review before sharing. Delete files there when no longer needed.

You can also generate reports without starting the tray, without API access, and without the tray dependencies:

```powershell
.\.venv\Scripts\python.exe usage_tray.py --report session --open-report
.\.venv\Scripts\python.exe usage_tray.py --report today
.\.venv\Scripts\python.exe usage_tray.py --report month
.\.venv\Scripts\python.exe usage_tray.py --report today --report-format html --output .\today.html
.\.venv\Scripts\python.exe usage_tray.py --report week --provider codex --open-report
.\.venv\Scripts\python.exe usage_tray.py --report session --demo --output .\demo.txt
```

Offline commands do not fetch a provider reset time, so `--report session` uses the last five hours. `--demo` uses clearly labeled samples and reads no logs. For updated or new models, copy `prices.example.json` to `%LOCALAPPDATA%\UsageTray\prices.json` and edit exact model rates in **USD per million tokens**. The app loads that file at startup; `--prices .\my-prices.json` selects another file. Each model requires `input`, `output`, and `cached`; Claude cache writes also use `write5m` and `write1h`. Restart the tray after changing prices.

### Effort changes within a conversation

Effort is tracked per recorded turn/message, not once per conversation. For example, a GPT-5.4 conversation that switches **medium → high → ultra** produces three separate model-and-effort buckets. Every subsequent token increment is associated with the recorded turn context active when that increment was logged. `xhigh`, `max`, and `ultra` remain distinct wire labels; the app does not map them to each other. Custom recorded effort names are preserved as well.

For Codex, effort comes from [`turn_context.effort`](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs), with an explicit collaboration-mode setting as a fallback when the top-level field is absent. The next context resets the association: if it omits effort, new usage is **unknown**, rather than inheriting the previous turn's setting. The report also shows recorded turn IDs and metadata sources in **Turn and usage-event history**. Multiple usage increments can belong to the same turn.

For Claude, only explicit effort metadata attached to the logged request, message, or user turn is used (such as `effort`, `effortValue`, or `output_config.effort`). Tool-result messages remain in the current turn; a new user prompt resets the association. Some Claude Code versions do **not** persist the effective request effort in their transcript. Those records stay **unknown**, and the report states how many records/tokens lack effort. Current settings files, thinking budgets, and prompt text cannot reliably reconstruct historical effort and are not used to guess it. Existing logs with no effort metadata cannot be retroactively labeled accurately.

The **Reasoning (subset)** column uses a separate numeric usage counter when recorded. Missing or inconsistent counters remain unavailable. Reasoning tokens are already part of output tokens, so this column is informational and is never added to totals or charged twice. Effort itself does not receive an invented price multiplier: API-equivalent value remains the actual token counts multiplied by model rates. Higher effort can consume more output/reasoning tokens; the report captures those recorded differences.

## Build an executable on Windows

From PowerShell in this folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
.\dist\UsageTray.exe
```

The script installs pinned dependencies, runs tests, and bundles Python into `dist\UsageTray.exe`. Codex/Claude CLIs remain separate prerequisites. The executable is unsigned; signing and distribution are separate release steps. No startup registration is changed automatically. To launch at login, optionally place a shortcut to your built executable in the folder opened by `Win+R` → `shell:startup`.

Alternatively, push the changes to GitHub and run **Actions → Build Windows Usage Tray → Run workflow**. The workflow uses a Windows runner, runs the tests, and uploads an artifact named `UsageTray-Windows` containing the executable. It also runs when changes to `windows/` are pushed or proposed in a pull request. The workflow has been added but has not been run from this Linux development environment.

Windows packaging and native tray behavior must be checked on Windows. A Linux test run validates adapters and protocol behavior, not a Windows executable. Before distribution, run the app on Windows with both real accounts, check remaining percentages against each provider's usage page, confirm reset times, test expired/missing logins, and quit/relaunch it.

### Current-model price coverage

The bundled rates include GPT-6.1 Sol (input $2, output $10, cached input $0.10 per million tokens; higher context tier above 272,000 input tokens) and Claude Opus 5.5 (input $4, output $20, cache reads $0.20, 5-minute cache writes $5, 1-hour cache writes $8 per million tokens). Sources: https://developers.openai.com/api/docs/models/gpt-6.1-sol and https://platform.claude.com/docs/en/models/opus-5-5/overview, checked October 23, 2026.

Models without a configured public API rate, including `codex-auto-review`, retain their token counts and appear as **unpriced**, never as a zero-dollar API estimate. Partial comparisons show only the priced subtotal minus the plan fee. Text reports list the rates used and their sources. Standard API-equivalent estimates exclude service-tier premiums.
