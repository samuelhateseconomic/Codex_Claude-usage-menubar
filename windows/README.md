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

## Session token and dollar-value reports

Right-click the tray icon and choose **Current session token & cost report…**, **Today's token & cost report…**, or **Last 7 days token & cost report…**. An HTML report opens in your browser showing:

- Total recorded tokens and estimated API-equivalent USD value.
- Uncached input, cache reads, cache writes, and output (including reasoning).
- Breakdowns by provider, model, project, conversation, and day.
- Price assumptions, unpriced models, and missing or incomplete log coverage.

For the session report, a recent provider reset time anchors the current five-hour quota window when available. Otherwise the report explicitly uses the last five hours. This is a quota session; separate conversation IDs appear in the conversation breakdown. Today uses your local midnight; the weekly report covers the last seven days. Reports are generated on demand, without uploading logs. They include all accounts whose activity is present in the configured local log folders, and cannot attribute usage to the currently signed-in account reliably.

Codex records come from `%USERPROFILE%\.codex\sessions` and `archived_sessions` (or `CODEX_HOME`). Claude Code records come from `%USERPROFILE%\.claude\projects` (or `CLAUDE_CONFIG_DIR`). Completed responses and recorded counters are counted; ongoing responses may not appear until their CLI writes usage. Repeated cumulative Codex counters and streamed Claude message updates are deduplicated. Cached Codex input is a subset of input, and reasoning is a subset of output: neither is counted twice. Claude cache writes distinguish 5-minute and 1-hour prices when the logs provide those details; legacy writes without TTL details are labeled as an estimate at the 5-minute rate.

**Dollar values are estimates at standard API list prices, not subscription charges or a conversion of your quota percentage.** Browser chat, cloud/remote tasks, other devices, and missing local logs cannot be counted. Counts can therefore differ from provider-wide usage. Unknown models remain in token totals but are marked unpriced, making the dollar subtotal explicitly incomplete. Bundled rates and their source are listed in the report. Discounts, priority/flex pricing, tools, taxes, and unrecorded billing adjustments are excluded. The GPT-5.4 long-context price tier is applied when the recorded request input exceeds 272,000 tokens.

Reports are saved under `%LOCALAPPDATA%\UsageTray\Reports`. They contain local project names and conversation IDs, so review before sharing. Delete files there when no longer needed.

You can also generate reports without starting the tray, without API access, and without the tray dependencies:

```powershell
.\.venv\Scripts\python.exe usage_tray.py --report session --open-report
.\.venv\Scripts\python.exe usage_tray.py --report today --output .\today.html
.\.venv\Scripts\python.exe usage_tray.py --report week --provider codex --open-report
.\.venv\Scripts\python.exe usage_tray.py --report session --demo --output .\demo.html
```

Offline commands do not fetch a provider reset time, so `--report session` uses the last five hours. `--demo` uses clearly labeled samples and reads no logs. For updated or new models, copy `prices.example.json` to `%LOCALAPPDATA%\UsageTray\prices.json` and edit exact model rates in **USD per million tokens**. The app loads that file at startup; `--prices .\my-prices.json` selects another file. Each model requires `input`, `output`, and `cached`; Claude cache writes also use `write5m` and `write1h`. Restart the tray after changing prices.

## Build an executable on Windows

From PowerShell in this folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
.\dist\UsageTray.exe
```

The script installs pinned dependencies, runs tests, and bundles Python into `dist\UsageTray.exe`. Codex/Claude CLIs remain separate prerequisites. The executable is unsigned; signing and distribution are separate release steps. No startup registration is changed automatically. To launch at login, optionally place a shortcut to your built executable in the folder opened by `Win+R` → `shell:startup`.

Alternatively, push the changes to GitHub and run **Actions → Build Windows Usage Tray → Run workflow**. The workflow uses a Windows runner, runs the tests, and uploads an artifact named `UsageTray-Windows` containing the executable. It also runs when changes to `windows/` are pushed or proposed in a pull request. The workflow has been added but has not been run from this Linux development environment.

Windows packaging and native tray behavior must be checked on Windows. A Linux test run validates adapters and protocol behavior, not a Windows executable. Before distribution, run the app on Windows with both real accounts, check remaining percentages against each provider's usage page, confirm reset times, test expired/missing logins, and quit/relaunch it.
