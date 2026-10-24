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

Copied and overlapping histories are reconciled before Codex cumulative deltas are calculated. Counter resets exclude the ambiguous transition and preserve later valid increments in a new epoch. Fork history seeds a baseline without charging inherited work; if that baseline is unavailable, the first observed child interval is excluded. Same-time observations need source ordering evidence. Missing/invalid counters and unresolved ordering break the baseline; counting resumes after a complete point re-establishes it. Report notes identify assumptions and exclusions; excluded token amounts are unknown, not zero.

Claude streamed updates retain category maxima for supported message/request identity. Detailed cache-write TTL evidence resolves earlier legacy aggregate writes rather than counting both representations. Conflicting metadata is qualified as unknown or excluded; a conflicting model remains unpriced. Mixed Codex last-only and cumulative measurement modes are conservatively excluded from last-only additions to prevent double charging. These policies do not establish complete account coverage. See the [S02 reconciliation policy](../docs/s02-reconciliation.md) for supported cases and limits.

Source scans distinguish **empty, complete, partial, and failed** local data and list issue counts. Complete means no known ingestion gaps in the scanned files, not full account coverage. Active incomplete final records are deferred; complete JSON at EOF is supported without a final newline. Files are verified as one prefix with a bounded retry for mutation, truncation or replacement. Records after a malformed complete line are conservatively deferred because context may be missing. Rescan after source recovery; the current offline path does not retain a committed history database. Modification time never excludes otherwise relevant history. See [S03 source quality and time](../docs/s03-source-quality-and-time.md).

Report boundaries and daily groups use **America/Los_Angeles** by default, with offline bundled IANA timezone data. Use `--timezone UTC` or another IANA name to change report dates and calendar boundaries. This replaces the older host-local day/month interpretation. Ranges include their start and exclude their captured end; Last 7 days remains a trailing 168 hours, including across daylight-saving changes. Live-limit reset display retains its existing host-local behavior.

**Dollar values estimate what your recorded tokens would cost at API token prices, not an actual bill or a conversion of your quota percentage.** The month-to-date report compares that estimated API value with your full monthly plan fees: **$20 for Codex and $20 for Claude** by default. Estimated savings so far = estimated API value minus the monthly fee. If value is below the fee, the report shows how far below rather than claiming savings. Unpriced models make the comparison incomplete; missing local usage records leave the comparison unavailable. The period starts on the first day of the calendar month, not your subscription renewal date, and does not project future usage. Use `--codex-plan-usd 20 --claude-plan-usd 20` to change the comparison prices when starting the tray or generating a report. Browser chat, cloud/remote tasks, other devices, and missing local logs cannot be counted. Counts can therefore differ from provider-wide usage. Unknown models remain in token totals but are marked unpriced, making the dollar subtotal explicitly incomplete. Bundled rates and their source are listed in the report. Discounts, priority/flex pricing, tools, taxes, and unrecorded billing adjustments are excluded. The GPT-5.4 long-context price tier is applied when the recorded request input exceeds 272,000 tokens.

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
