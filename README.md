# Claude Usage Bar

A small macOS menu bar app that shows how much of your Claude plan limits you have left: the 5-hour session limit and the weekly limit, for one or more accounts at once.

## Features

- **Live limits in the menu bar** for every signed-in account, color-coded green / orange / red. Four menu bar styles: names and percentages, initials only, a single icon for the lowest account, or one account's session + week side by side.
- **Multiple accounts.** Sign each account in once from the menu; the app keeps its own login and renews it, so it stays live through restarts, sleep and Claude Code logouts. It can also read existing Claude Code logins (including ones from separate `CLAUDE_CONFIG_DIR` folders).
- **Weekly reports.** When an account's weekly limit resets, the app writes an HTML report and sends a notification: limit used vs. last week, every 5-hour session, which sessions hit the limit, Claude Code activity by day / project / model, and an estimate of how much went to chat or Cowork versus Claude Code.
- **Starts with your Mac** and keeps only the last 4 weeks of reports and history.
- **Open Claude** from the menu (⌘O), so the Claude app's own menu bar icon can be hidden.

## Install

Requires macOS 13+ and the Xcode command line tools (`xcode-select --install`).

```bash
git clone https://github.com/jiachengw-sf/claude-usage-menubar.git
cd claude-usage-menubar
./build.sh
open /Applications/ClaudeUsageBar.app
```

`build.sh` compiles the app, signs it ad hoc and installs it to `/Applications`. Then click the menu bar item → **Accounts → Sign In to an Account…** and approve in the browser. Repeat for each account (sign out of claude.ai in the browser first if it opens the wrong one).

## How it works

- Limits come from the same endpoint Claude Code's `/usage` uses (`api.anthropic.com/api/oauth/usage`), polled every 5 minutes with backoff when rate-limited.
- Sign-in uses the same OAuth flow as Claude Code (PKCE with a localhost redirect). Tokens are stored in your login keychain under `ClaudeUsageBar-login` and never leave your Mac except to Anthropic.
- Report breakdowns read Claude Code's local session files (`~/.claude*/projects`). Chat and Cowork don't save usage locally, so their share is estimated from the limit used beyond your Claude Code work, calibrated on your own history (including the Claude desktop app's `plan-usage-history.json` when present).
- Data lives in `~/Library/Application Support/ClaudeUsageBar/Reports` and the app's preferences; a status log is written to `~/Library/Logs/ClaudeUsageBar.log`.

## Notes

This is an unofficial personal tool, not affiliated with Anthropic. It relies on undocumented endpoints that may change. The "API-equivalent cost" figures use list prices for comparison only; on a subscription you aren't charged per token.
