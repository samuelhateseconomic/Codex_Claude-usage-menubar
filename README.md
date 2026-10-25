<p align="center">
  <img src="assets/icon.png" width="128" alt="Usage Tray icon">
</p>

<h1 align="center">Usage Tray / Usage Hub</h1>

<p align="center">
  <b>See your usage. Estimate its value.</b><br>
  Codex and Claude limits, token reports, and a local dashboard on Windows.<br>
  Original Claude menu-bar app included for macOS.
</p>

<p align="center">
  <a href="#getting-started">⬇️ <b>Download / setup</b></a> ·
  <a href="#features">Features</a> ·
  <a href="#build-from-source">Build from source</a> ·
  <a href="#how-it-works">How it works</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows_version-0.13.0-e8775a" alt="Windows version 0.13.0">
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D4" alt="Windows 10/11">
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white" alt="Python 3.11–3.14">
  <img src="https://img.shields.io/badge/macOS-13%2B-000000?logo=apple&logoColor=white" alt="macOS 13+">
  <img src="https://img.shields.io/badge/Swift-6-F05138?logo=swift&logoColor=white" alt="Swift 6">
</p>

<hr>

> [!WARNING]
> **Unsigned builds.** Windows has no signed installer. The macOS app is not Developer ID signed or notarized; first launch may require **Open** or approval under **Privacy & Security**.

> [!NOTE]
> Unofficial; unaffiliated with OpenAI or Anthropic. API-equivalent value is an estimate, not a bill or realized savings. Provider usage interfaces may change.

## Features

- **Live tray limits.** Remaining Codex/Claude capacity and reset times, with independent refresh, backoff, and stale-state labels.
- **Local dashboard.** Daily token/value charts, provider/date filters, searchable projects and conversations, detail/Back navigation, and saved fee/timezone settings.
- **Terminal reports.** Compact summaries, ranked details, full audit output, and optional HTML. Normal tray startup opens no browser.
- **Reliable accounting.** Reconciles supported duplicate histories, resets, forks, and streamed updates. Unknown models stay unpriced; reasoning is included in output once.
- **Persistent local service.** Shared settings, recoverable SQLite storage, and authenticated browser access. Version 0.13.0 improves query reuse and honors saved report formats in explicit dashboard/API tray launches.
- **Original macOS app.** Multiple Claude accounts, menu-bar styles, weekly reports, Keychain login, and launch at login. Windows Codex/Usage Hub features have not been ported to Mac.

## Getting started

### Windows

Use the [validated Windows build artifacts](https://github.com/samuelhateseconomic/Codex_Claude-usage-menubar/actions/runs/40141823025) or build below. Run **UsageTray.exe** and find it under **Show hidden icons**.

For live limits, sign in through Codex CLI (`codex login`) and Windows-native Claude Code (`/login`). Right-click the tray for reports, **Open usage dashboard...**, or **Quit**.

```powershell
# From the windows folder after building:
.\dist\UsageTray.exe --dashboard --dashboard-port 0
.\dist\UsageTray.exe --report month --report-format text --open-report
```

Standalone dashboard mode does not poll providers. Closing the browser leaves the tray running; **Quit** stops it. Quit/relaunch after updates or mode changes. [Full Windows guide](windows/README.md).

### macOS

1. Build below, then open **ClaudeUsageBar.app** from Applications.
2. Choose **Sign in with Claude**. For another account, sign out of claude.ai or use a private browser window, then **Add Another Account**.
3. Use **Accounts → Manage Accounts...**, **Menu Bar Style**, **Weekly Reports → This Week So Far**, and **Launch at Login** from the menu bar.

## Build from source

The current Windows version is included on `main`.

```bash
git clone https://github.com/samuelhateseconomic/Codex_Claude-usage-menubar.git
cd Codex_Claude-usage-menubar
```

Already have this repository on `main`? Check `git status`, preserve local edits, then `git pull --ff-only`.

**Windows:** Python 3.11–3.14 with pip. From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build.ps1
.\windows\dist\UsageTray.exe
```

For source-only setup and launch, see the [Windows guide](windows/README.md#run-on-windows).

**macOS:** macOS 13+ and compatible Xcode command-line tools:

```bash
xcode-select --install  # Skip if already installed.
./build.sh
open /Applications/ClaudeUsageBar.app
```

The Mac build creates Apple silicon/Intel binaries and **replaces any existing `/Applications/ClaudeUsageBar.app`**. Add `--zip` to produce a versioned ZIP.

## How it works

- **Value:** configured token rates applied per accepted event. Default fees are **USD 20/month per provider**. Eligible unfiltered month-to-date comparisons show estimated value minus the full monthly fee, with coverage qualifications.
- **Scope:** local usage spans unmatched accounts; live limits describe the active CLI account. Browser/cloud activity and other devices may be absent.
- **Windows data:** settings and metadata stay under `%LOCALAPPDATA%\UsageTray`. The index/reports exclude prompts and responses; project names and IDs can still be sensitive. Dashboard assets and its authenticated API run locally.
- **Mac data:** logins use Keychain; reports live in `~/Library/Application Support/ClaudeUsageBar/Reports`, with about four weeks retained.

Recorded Windows acceptance: **378 Python tests, 79 frontend tests, and 18 executable checks** per Python 3.11–3.14 CI job, plus packaged recovery checks. Native tray/report/Quit sign-off, clean-machine delivery, signing, and Mac verification remain pending. [Release evidence](docs/s14-hub-release.md).

[Contributing instructions](AGENTS.md) · [Refinement plan](docs/project-refinement-plan.md) · [Original Claude Usage Bar](https://github.com/jiachengw-sf/claude-usage-menubar)
