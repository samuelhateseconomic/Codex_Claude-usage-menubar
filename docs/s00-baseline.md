# S00 baseline and implementation handoff

Status: **complete**. Captured October 23, 2026 (America/Los_Angeles).

This session establishes a reproducible starting point for the [refinement plan](project-refinement-plan.md). It changes documentation only. The accounting defects below remain open; a passing existing suite does not certify accounting correctness.

## Repository and verification environment

- Starting commit: `810b3a8` on `main`, tracking `origin/main`. `git status --short --branch` showed no local changes at session start.
- Repository-wide instructions: [AGENTS.md](../AGENTS.md). No additional Windows-specific AGENTS.md was found in the source inventory.
- During the session, separate Figma workflow additions appeared in AGENTS.md and the refinement ledger. They were read and preserved; they are not S00-authored changes. The clean starting-state observation above predates those additions.
- Primary runtime: Windows Python. Project interpreter: `windows/.venv/Scripts/python.exe`, reporting Python **3.14.5**. CI currently selects Python **3.12**; this session did not run CI or verify Python 3.11.
- Pinned runtime dependencies: pystray **0.19.5**, Pillow **11.3.0**. The build script selects PyInstaller **6.16.0**.
- Fixture temporary directory: `windows/build/s00-temp`, excluded from source delivery. No real usage histories were scanned or exported, and no live provider request was made.
- Source references: [entry point](../windows/usage_tray.py), [reports and readers](../windows/usage_reports.py), [provider adapters](../windows/usage_core.py), [Windows instructions](../windows/README.md), and [build script](../windows/build.ps1).

## Executed checks and actual results

Commands ran from the repository root using PowerShell:

```powershell
$s00Temp = Join-Path $PWD 'windows\build\s00-temp'
New-Item -ItemType Directory -Path $s00Temp -Force | Out-Null
$env:TEMP = $s00Temp
$env:TMP = $s00Temp
.\windows\.venv\Scripts\python.exe --version
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -v
.\windows\.venv\Scripts\python.exe docs/review_accounting_probes.py
.\windows\.venv\Scripts\python.exe windows/usage_tray.py --help
```

- Existing suite: **57 tests passed**, no skips reported, in **7.527 seconds**. Includes offline CLI/report fixtures, text-popup invocation mocks, provider isolation/backoff, credential safeguards, and bounded local protocol subprocess tests.
- Overlap, truncated copy first: expected **200**, observed **300**, `matches_expected=false`; no ingestion notice.
- Overlap, complete copy first: expected **200**, observed **200**, `matches_expected=true`.
- Reset sequence `100, 200, 50, 100`: expected **250**, observed **200**, `matches_expected=false`; reset exclusion notice present.
- The probe process exited zero despite the failed comparisons. These results were inspected individually. S02 must promote the cases into ordinary assertions before fixing them.
- `--help` succeeded and matched the CLI inventory below.

The existing packaged executable was also exercised, without rebuilding unchanged application source:

```powershell
$s00Report = Join-Path $s00Temp 'packaged-month-demo.txt'
$s00Process = Start-Process -FilePath (Join-Path $PWD 'windows\dist\UsageTray.exe') -ArgumentList @('--report','month','--demo','--output',$s00Report) -WindowStyle Hidden -Wait -PassThru
$s00Process.ExitCode
```

Outcome: exit **0**, report created; inspected markers confirmed **DEMO**, **108,000** tokens, **USD 0.2658**, and the month-to-date comparison. The existing artifact is 17,266,588 bytes and came from the prior publication build. This check validates saved demo output from that artifact; it does not establish reproducible build identity, real-account accuracy, or interactive tray/terminal behavior.

Documentation validation for this session checked changed Markdown's local links, balanced code fences, and trailing whitespace. `git diff --check` passed. No dependency or packaging inputs changed, so no fresh build was required.

## Current public interface and compatibility inventory

The following describes current behavior, including limitations to migrate deliberately in later sessions.

### CLI arguments

- `-h` / `--help`: print help and exit.
- `--provider {both,codex,claude}`: select providers; default `both`.
- `--demo`: labeled synthetic data. Avoids usage-log and credential reads/provider polling; startup still loads a configured price file if present.
- `--once`: one JSON live-limit snapshot per selected provider, without a tray. Reports provider errors separately and exits nonzero if one fails. Demo mode returns sample snapshots. Real providers are queried sequentially in this CLI mode; independent worker execution applies to the tray.
- `--report {session,today,week,month}`: query local logs without live provider polling or GUI imports. Month also compares configured fees.
- `--report-format {text,html}`: default text for CLI and tray reports. The lower-level `save_report()` helper still defaults to HTML; preserve explicit format passing during extraction.
- `--output PATH`: save a report at a chosen destination; requires `--report`.
- `--open-report`: open the saved report; requires `--report`. Text opens a PowerShell terminal on Windows; HTML opens via the default handler/browser.
- `--prices PATH`: exact-model custom USD-per-million rate JSON. Overrides bundled matching entries; dated model suffixes can inherit known base-model prices. Unknown models remain unpriced.
- `--codex-plan-usd NUMBER` and `--claude-plan-usd NUMBER`: invocation-only fees, each defaulting to **20**. Finite nonnegative numbers are accepted, including zero. These values do not yet persist.
- `--once` and `--report` are mutually exclusive. Without either, startup enters tray mode. There is no current settings/version/root/timezone CLI option or implemented local HTTP API.

### Periods, accounting, and value

- One `now` value is captured by `collect_report()`. Current final filtering is **inclusive** at both ends: `start <= timestamp <= now`.
- Today begins at host-local midnight; month begins at the host-local first day at midnight. No explicit named timezone is persisted yet.
- Week is a trailing **168 hours**. Session uses a supplied provider's qualifying five-hour reset boundary, otherwise trailing five hours. Offline CLI reports do not fetch a reset boundary. Tray reports use snapshots already held in memory.
- File discovery skips symlink files and uses file modification time as a prefilter. Readers calculate baselines from the eligible files before final event-time filtering. Old-mtime backfills and incomplete reads remain S03 risks.
- Codex roots: `CODEX_HOME/sessions` and `CODEX_HOME/archived_sessions`, otherwise the corresponding home `.codex` directories. Claude root: `CLAUDE_CONFIG_DIR/projects`, otherwise home `.claude/projects`.
- Usage includes available local activity across unmatched accounts. Live limits refer to the active CLI account. Neither local report completeness nor account matching is established.
- Token total is uncached input + output + cache reads + 5-minute writes + 1-hour writes. Codex cached input is removed from total input before projection. Nullable reasoning is included in output, never added again. Explicit effort/source values are preserved.
- Current Codex reader derives deltas within each file, then deduplicates using session/cumulative counters; this causes the defects above. Last-usage-only events use weaker timestamp/counter identity. Pre-creation fork history seeds counters but is excluded from child usage.
- Claude streamed usage merges category maxima for session/message/request identity; missing message IDs are skipped. Legacy cache writes without TTL assume the five-minute price and emit a notice.
- Valuation uses binary floats per record, then sums priced values. Tier selection currently uses that record's input + cache-read count. This is not always proven per-request context.
- Empty, all-unpriced, mixed-priced, and priced-zero values already have distinct report handling. Month compares full selected-provider fees, not prorated fees. Current labels include “Estimated savings so far”; S04 will use signed, qualified differences consistently.

### Reports and packaged launch

- Source CLI text with stdout and no output/open flag prints directly. Explicit output saves without opening unless `--open-report` is supplied.
- The windowed packaged executable has no stdout; a report without `--output` saves and opens automatically. An explicit output destination suppresses automatic opening. Source inspection establishes these branches; this session exercised only the packaged saved-output branch.
- Text opening uses `powershell.exe -NoLogo -NoProfile -NoExit`, a literal-path read, a path passed through an environment variable, and `CREATE_NEW_CONSOLE`. It is a static report, not an interactive terminal UI.
- Saved default reports use unique files under `%LOCALAPPDATA%/UsageTray/Reports`; fallback is `~/.local/share/UsageTray/Reports`. No automatic retention policy exists yet.
- Reports include provider/model-and-effort/project/conversation/day breakdowns, assumptions, and unpriced notices. HTML is optional. Output hierarchy is deferred to S10.
- Build uses one-file, windowed PyInstaller packaging. Launch with no mode starts the tray; startup registration is not automatic. No single-instance owner is currently enforced. CI builds/uploads the executable but has no packaged runtime smoke step yet.

### Provider behavior

- Tray providers run independently with per-provider fetch locks. Successful polls schedule at least **300 seconds** before the next check; failures back off through 300/600/1200/2400 seconds, subject to a larger provider retry delay. Refresh does not bypass the deadline. Last successful snapshots remain visible and labeled stale after failures.
- Codex launches a bounded local `app-server`, initializes it, checks subscription account type, reads rate limits, and terminates its owned child. The adapter leaves authentication to the CLI and does not read Codex credential files.
- Claude reads existing CLI OAuth credentials and queries its usage endpoint. Expired credentials require renewal through Claude Code; the app does not refresh/write them. Redirects are rejected and provider body text is not exposed in errors. Rate-limit retry hints are respected.
- Current polling lives in the tray module and redraws on worker wakes. CLI queries remain usable without GUI imports. Runtime extraction, launch ownership, and shutdown verification belong to S07.

## Decisions carried into implementation

### D00-1: Conservative reconciliation and reset policy

Reconcile observations across all available copies of a conversation **before** deriving canonical deltas. Preserve provider IDs, timestamp, sequence/context evidence, fork baseline, and source provenance. File enumeration and cumulative values alone cannot define event identity.

Identical observations with supporting identity/time/context evidence may merge. A reset starts a distinct epoch: exclude and flag the ambiguous transition, retain valid subsequent increments, and never deduplicate a later epoch against an earlier equal numeric counter. For `100, 200, 50, 100`, accepted increments are `100 + 100 + 50 = 250`; the reset transition's unknown work is not fabricated.

For contradictory evidence without a defensible ordering/identity, retain an issue and exclude the disputed contribution. Do not select the largest per-file sum or an arbitrary first winner. A partial source alone cannot prove that missing earlier work never existed. The concrete deterministic identity/epoch algorithm remains S01/S02 work, with fixture expectations controlling acceptance.

### D00-2: Request-context uncertainty

Keep current tier behavior only as a clearly identified compatibility assumption where request context is unavailable. S01 observations must retain available request-context evidence separately from cumulative/delta counters. S04 must report applied tier/provenance/assumptions alongside value and must not present an aggregate-derived tier as proven request context. Unknown prices remain unpriced; no new effort multiplier or rate is introduced by this decision.

### D00-3: Configuration location and precedence

Use `%LOCALAPPDATA%/UsageTray/settings.json` for S06's per-user validated settings, with `~/.local/share/UsageTray/settings.json` as the existing non-Windows location convention. Keep settings separate from credentials, logs, reports, and build output. Seed fees at Codex **USD 20/month** and Claude **USD 20/month** through one owner.

Precedence will be application defaults, then validated persisted settings, then explicit CLI invocation overrides. CLI overrides will not persist implicitly. Preserve existing automatic `prices.json` discovery and explicit `--prices` selection through a documented migration; a settings reference may select a catalog, but must not create competing fee/rate owners. Atomic validation/recovery, schema, and migration tests belong to S06; no settings file is created in S00.

### D00-4: Compatibility and scope

Preserve Python, existing adapters, terminal defaults, optional HTML, and offline reports. S03 introduces named-zone UTC `[start,end)` query semantics with explicit legacy-boundary migration tests. S04 introduces exact decimal valuation. S05 provides the authoritative summary. Existing behavior is a compatibility reference, not an oracle for documented bugs.

The optional database/API/dashboard track is not started. No existing database implementation was identified in the Windows source inventory. Database placement, migrations, local API authentication, and UI choices remain on that track. No unresolved decision blocks S01; exact ambiguous-evidence cases must be settled through its contracts and fixtures before S02 emits accepted deltas.

## Next session and acceptance boundary

S00's gate is met: the clean starting commit, commands, fresh test result, known probe failures, public behavior, and implementation decisions are recorded. Application correctness has not improved merely because this baseline is documented.

**S01 is ready:** introduce metadata-only observations and canonical-event contracts plus a GUI/pricing-independent reconciliation seam. Specify weak identities, missing/invalid fields, provenance, epoch/fork evidence, and source-to-event mappings; retain `Record` as a compatibility projection where useful. Add focused extraction/privacy fixtures without attempting the entire reconciliation fix prematurely.

**S02 remains required:** assert both overlap file orders, reset-to-repeated values, copies/idempotence, fork baselines, zero deltas, and ambiguous conflicts. Both known defects remain open until its gate passes.

Unrun checks: fresh packaging build, interactive tray/terminal click-through, real-account quota comparison, real-history scan, macOS runtime, fresh price verification, and CI. None is needed to complete S00's baseline gate, and none is implied by the offline demo result.
