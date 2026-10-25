# Usage Tray / Usage Hub for Windows — 0.13.0

Codex + Claude usage estimates, live limits, terminal reports, and an optional local dashboard. [Project overview and macOS setup](../README.md).

## Install without a terminal

Download and extract a successful [Windows build artifact](https://github.com/samuelhateseconomic/Codex_Claude-usage-menubar/actions/workflows/windows-usage-tray.yml), then double-click **UsageTraySetup.exe**. Source builds place it in `windows/dist`. It installs the app for your Windows account, adds Start menu and sign-in shortcuts, and starts the background tray with live checks enabled. No administrator access, separate Python install, terminal or browser is required. Provider CLI sign-ins remain necessary for live limits.

Open the dashboard from the tray when needed. Closing its browser tab leaves monitoring running; **Quit** stops it until the next launch/sign-in. If an older owner is already running, Quit it and reopen **Usage Tray** from the Start menu to use the new installation.

Installed binaries live in `%LOCALAPPDATA%\Programs\UsageTray\versions`; upgrades retain old binaries rather than overwriting a running app. Settings/history remain in `%LOCALAPPDATA%\UsageTray`. To disable sign-in startup, remove **Usage Tray.lnk** from the folder opened by `Win+R` → `shell:startup`. To remove the installation, Quit it, remove its Start menu/startup shortcuts, and remove the app's Programs folder; settings/history are separate.

The installer and executable are unsigned. Windows may require approval for a downloaded build. [Windows startup folders](https://support.microsoft.com/en-gb/windows/experience/startup-boot/configure-startup-applications-in-windows).

## Run on Windows

Requires Windows 10/11; source setup needs Python 3.11–3.14 with pip. Use the current `main` branch.

Run these commands from this `windows` folder, reusing `.venv` if present:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe usage_tray.py
```

For live limits, install/sign in through [Codex CLI](https://github.com/openai/codex) (`codex login`) and [Claude Code](https://code.claude.com/docs/en/setup) (`/login`). API-key accounts do not provide subscription limits. Claude needs Windows-native credentials; WSL/Keychain credentials are not imported. Renew expired credentials through the CLI.

Find the icon under **Show hidden icons**. Right-click for limits, reports, dashboard, or Quit. `--provider codex` or `--provider claude` selects one provider. Checks run independently every five minutes with cooldown/backoff; failures retain labeled last-successful readings. Local usage can span unmatched accounts; live limits describe the active CLI account.

## Explicit local usage dashboard

```powershell
.\.venv\Scripts\python.exe usage_tray.py --dashboard --dashboard-port 0
# Packaged equivalent:
.\dist\UsageTray.exe --dashboard --dashboard-port 0
```

Or choose **Open usage dashboard...** from the ordinary live tray to share its cached limits. Standalone dashboard launch imports local metadata without polling providers. Normal tray startup opens no browser.

- **Overview:** provider/period selection, daily token/value charts, and qualified plan comparisons.
- **Explore:** metadata search, project/model/effort filters, conversation details, and Back with retained page/filter state.
- **Settings & data:** save fees and timezone; pending computation and concurrent edits are labeled.

Repeated launches reuse one owner's mode and port. Close browser tabs freely; tray **Quit** stops the packaged service, while Ctrl+C stops the source dashboard. Quit/relaunch to change modes or load updates. Launch through the application to authenticate; a plain loopback URL grants no private access. `--no-browser` suppresses browser launch.

`--dashboard --demo` explicitly selects isolated samples with read-only Settings. Real connection failures never substitute demo data. [Runtime/API details](../docs/s13-runtime-integration.md).

## Estimated API value and plan comparison

Default fees are **Codex USD 20/month + Claude USD 20/month**. Eligible unfiltered calendar-month-to-date usage, optionally by provider, is compared against full monthly fees: **estimated API value minus fee**. This is a hypothetical comparison, not a bill or realized savings. Missing sources and partial pricing qualify or prevent comparisons.

Reports reconcile supported copied histories, resets, forks, and streamed updates. Total tokens include uncached input, output, cache reads, and both cache-write durations. Reasoning is a nullable subset of output. Effort uses explicit metadata without a price multiplier. Unknown models remain unpriced.

```powershell
.\.venv\Scripts\python.exe usage_tray.py --report month --report-format text
.\.venv\Scripts\python.exe usage_tray.py --report month --report-format text --details model
.\.venv\Scripts\python.exe usage_tray.py --report month --report-format text --details conversation --page-size 10 --page 2
.\.venv\Scripts\python.exe usage_tray.py --report month --report-format text --audit
.\.venv\Scripts\python.exe usage_tray.py --report month --report-format html --output .\report.html
.\dist\UsageTray.exe --report month --report-format text --open-report
```

Periods: `session`, `today`, `week`, `month`. Offline session uses the last five hours; week means the last seven days. Reports do not poll providers or require a running dashboard. Detail pages retain full matched headlines; `--audit` shows exact counters, rates, and notes. More: [terminal views](../docs/s10-terminal-views.md), [accounting](../docs/s04-exact-valuation.md).

### Persistent settings and version diagnostics

Settings: `%LOCALAPPDATA%\UsageTray\settings.json`. Save fees/timezone through the dashboard, or quit the active owner before saving from CLI:

```powershell
.\.venv\Scripts\python.exe usage_tray.py --save-settings --codex-plan-usd 20 --claude-plan-usd 20 --timezone America/Los_Angeles --report-format text
.\.venv\Scripts\python.exe usage_tray.py --diagnostics
.\dist\UsageTray.exe --version --output .\version.json
.\dist\UsageTray.exe --diagnostics --output .\diagnostics.json
```

CLI overrides are temporary unless `--save-settings` is explicit. `--config PATH` selects another file. Roots, rate overrides, and report preferences use native configuration; browser saves preserve them. Malformed settings remain untouched with recovery guidance. [Schema example](settings.example.json) · [Configuration/recovery](../docs/s06-persistent-configuration.md).

### Current-model price coverage

Bundled rates are a versioned snapshot, not an automatic price feed. Reports identify applied rates, sources, unpriced models, and tier assumptions. Valuation uses exact decimal rates with per-event half-even rounding to 12 USD decimal places.

For custom **USD-per-million-token** rates, use [prices.example.json](prices.example.json) with `--prices PATH`. Persist validated overrides with `--save-settings`; saved settings supersede automatic legacy `prices.json`. [Pricing policy and provenance](../docs/s04-exact-valuation.md).

## Data and privacy

Local sources normally come from `.codex/sessions`, `.codex/archived_sessions`, and `.claude/projects`, with environment/saved-root overrides. Browser/cloud activity and other devices may be absent.

Under `%LOCALAPPDATA%\UsageTray`, `usage-hub.sqlite3` holds allowlisted metadata, valuations, jobs, and cached provider state. Interrupted imports retain the previous committed publication. The dashboard uses an authenticated loopback API and bundled assets; offline views require no provider polling.

The index/reports exclude prompts, responses, and credentials. Project names and conversation IDs remain sensitive. Text/HTML shorten path/ID labels by default; `--include-metadata` explicitly includes full metadata. Dashboard details expose conversation metadata. Diagnostics are sanitized, explicit exports; `--show-settings` includes configured paths.

Automatic reports in `Reports\Generated` are limited to 100 files and 30 days after successful saves. Source histories and explicit exports elsewhere are untouched. [Privacy/diagnostics](../docs/s08-privacy-diagnostics.md) · [Index/recovery](../docs/s11-local-index.md) · [API contract](../docs/s12-local-api.md).

## Build an executable on Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
.\dist\UsageTray.exe
```

Build runs the Python suite, packages the windowed app/local assets/timezone data, and performs 18 offline executable checks. It also creates **dist/UsageTraySetup.exe** and tests installation in isolated user folders, including exact payload identity, valid Start menu/startup shortcuts, repeat install and preserved settings/index. CI artifacts include both executables. Provider CLIs remain separate; Node.js is needed only for frontend tests. Portable app launches do not register startup; explicit setup does.

### Repeat release checks

From this `windows` folder:

```powershell
$refinementTemp = Join-Path $PWD 'build\refinement-temp'
New-Item -ItemType Directory -Path $refinementTemp -Force | Out-Null
$env:TEMP = $refinementTemp
$env:TMP = $refinementTemp
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test dashboard/tests/*.test.mjs
.\.venv\Scripts\python.exe tools/release_smoke.py --exe dist/UsageTray.exe
.\.venv\Scripts\python.exe tools/installer_smoke.py --setup dist/UsageTraySetup.exe --app dist/UsageTray.exe
.\.venv\Scripts\python.exe tests/packaged_hub_release.py --exe dist/UsageTray.exe --measurements build/hub-release-measurements.json
```

Recorded 0.13.0 CI passed **378 Python / 79 frontend / 18 core executable checks** per Python 3.11–3.14 job, plus packaged migration, authentication, interruption/restart, and restore checks. Native tray/report/Quit sign-off, clean-machine/disconnected delivery, signing, and macOS remain unverified. [S14 evidence and full acceptance commands](../docs/s14-hub-release.md).
