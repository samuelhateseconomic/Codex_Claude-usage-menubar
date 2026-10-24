# S09 — Windows core release validation

Release candidate: **0.9.0** on `codex/s01-observation-contracts`, after S00–S08. Status: **core release gate complete**. Main/original-checkout integration and distribution are separate actions.

## Changes and release scope

The refined core preserves local terminal/text and HTML reports, the tray, independent live-provider checks and the Python/PyInstaller packaging approach. Prior sessions establish observation-first reconciliation, exact event valuation, qualified signed plan comparisons, one headless summary, validated settings, runtime ownership/recovery and safe metadata/diagnostic projections. This release does not add the optional database, API, dashboard, account matching or a terminal redesign. Estimates use recorded local tokens and the versioned bundled/explicit rates; they are not actual bills or realized savings.

`--version` and `--diagnostics` now include `python_version` alongside app/build/computation identities. The application version is 0.9.0. Existing settings schema 1 and operation diagnostic schema 1 are unchanged; there is no data migration.

The build reuses the project `.venv`. When absent, it uses PATH-selected `python` to create the environment, so CI's selected Python is respected. Dependency pins remain unchanged. Windows CI targets the documented Python 3.11–3.14 range, with separate test/build/smoke jobs and uniquely named artifacts. A matrix configuration alone is not a passed remote run.

## Repeatable executable gate

From the repository root, use the project interpreter and workspace-local TEMP/TMP as in [the refinement plan](project-refinement-plan.md#9-verification-commands-and-evidence-rules):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build.ps1
# Repeat only the executable gate when needed:
.\windows\.venv\Scripts\python.exe windows/tools/release_smoke.py --exe windows/dist/UsageTray.exe
```

The build first runs the relevant full suite, packages a windowed one-file executable including tzdata, then runs 14 executable cases: version/hash/runtime identity; named-zone fallback with an empty host zone search path; demo text/HTML; settings save and restart; exact synthetic accounting; ephemeral override; offline access while an owner holds the runtime lock; empty/unpriced/legitimate-zero distinctions; partial-source diagnostics; corrupt settings recovery and version availability during recovery. Synthetic 2,905,000 tokens produce USD 18.8910; a persisted USD 30.000000000001/0 plan configuration displays a signed -USD 11.11 difference. Each case has a 30-second process wait plus bounded owned-tree teardown. All children use scoped Job Objects, hidden launch, isolated temp/application data and synthetic histories. No `--open-report`, live `--once`, credential access or provider request is part of this automatic gate. Fixtures are removed only from the tool's own newly allocated temporary directory.

The executable's hash must match its own reported build identity and the frozen Python major/minor must match the project build interpreter. Version mismatch or a failed acceptance assertion fails the build before artifact upload. This gate does not prove native menu interaction, clean physical-machine installation, signatures or live protocol compatibility.

## Read-only local-history check

Only after fixtures pass, explicitly run:

```powershell
.\windows\.venv\Scripts\python.exe windows/tools/local_history_audit.py --read-local-history
```

The auditor reads environment-default local JSONL roots using the existing core. It does not load saved settings, poll providers or access credential files. Output is an explicit projection of counts, category token integer strings, coverage, bounded display-safe model labels (200 labels, 200 characters each, with truncation disclosed), structured issue counts, machine/runtime category and scan/query time. It excludes paths, prompts/responses, conversation/event/turn identifiers, arbitrary notices and raw exceptions. It is a separate developer report, not the token-free operation diagnostic schema. Do not serialize its internal `UsageResult` graph.

It checks category sums, reasoning as an output subset, exact valued-detail/total equality and complete membership plus category/value reconciliation for every provider/model/effort/project/conversation/day grouping. `passed` means these consistency checks passed, not that source coverage is complete or rates are current. Pricing and ingestion/counter/tier quality remain separate. Missing roots are not zeros, excluded amounts stay unknown and model metadata cannot reconstruct absent history. Inventory enumeration/size precedes the query; active writes can change between them. The measurement is not a persistent revision, all-history benchmark or proof of complete account coverage. There is no index or telemetry upload.

## Validation evidence

Final local full suite: **247 tests passed in 47.157 seconds** on Windows 11 / project Python 3.14.5. The final package built successfully and passed all **14 automatic executable smoke checks**. Executable SHA-256: `51809bc976408f569c022e5e96991003c43cafb0c4df15cbc0c2ceb7bde30a3c`. A repeated full suite missed a 3-second crash-fixture startup marker; the fixture now allows up to 10 seconds or detects early parent exit, while retaining its 3-second process-cleanup assertions. Focused 19 runtime tests passed in 7.769 seconds after that adjustment. The initial four-runtime CI run reached all suites and exposed an inherited test spelling comparison between short `RUNNER~1` TEMP paths and resolved long paths. The test now verifies file identity using `samefile`; **35 report tests passed in 8.135 seconds**. No application/packaged code changed for that test fix. The final local post-correction full suite passed **247 tests in 67.494 seconds**; the correction changed only a test assertion and documentation, so the previously verified production executable remains applicable.

A corrected read-only history run measured **153 files / 199,834,592 observed bytes**, **3,698 in-range records / 48 conversations** in **5.236890 seconds** on Windows 11 AMD64 / Python 3.14.5 / 22 logical CPUs / America/Los_Angeles. All nine consistency checks passed. Available model keys were `gpt-6.1-sol`, `claude-opus-5-5` (priced) and `codex-auto-review` (unpriced). Codex source quality is partial, with an absent root and invalid counter metadata; reset/counter exclusions and tier assumptions remain explicit. Claude source quality is complete for available files. Histories changed between scans; these are single-sample counts, not a stable benchmark. No raw history or audit output is committed. See the [session ledger](project-refinement-plan.md#10-progress-ledger-and-handoff-template) for separate issue counts and exact command outcomes.

Inspected mandatory accounting probes remain **200/200**, **200/200**, **250/250**, all matching expected values. The Windows computer-use inventory exposes no taskbar/tray surface here; native menu interaction is unverified, and terminal UI automation is excluded by the installed computer-use skill. Three scoped actual-executable process checks passed: two demo tray launches acquired ownership, remained alive and released the lock after fixture-owned teardown, allowing restart; explicit demo text reporting created an owned PowerShell process and the correct saved report using a path with spaces, an apostrophe and brackets. These checks observed only owned Job Object PIDs/process images and file content. No UI Automation, menu invocation or terminal input was used. The viewer and tray test processes were closed only within their fixture-owned jobs. This is process-level evidence, not native interaction/playback.

## Remote Windows evidence

[GitHub Actions run 40121222830](https://github.com/samuelhateseconomic/Codex_Claude-usage-menubar/actions/runs/40121222830), source/tool revision `50f5ab57dfd2026f14b5cb6a7e7658fc1c30563d`, passed all four jobs. Logs verify the actual packaged Python versions, all 247 source tests, successful PyInstaller builds, all 14 executable checks and artifact upload for each runtime:

- Python **3.11.9**: suite **11.817 seconds**, artifact `UsageTray-Windows-Python-3.11`.
- Python **3.12.10**: suite **14.123 seconds**, artifact `UsageTray-Windows-Python-3.12`.
- Python **3.13.16**: suite **14.163 seconds**, artifact `UsageTray-Windows-Python-3.13`.
- Python **3.14.9**: suite **13.119 seconds**, artifact `UsageTray-Windows-Python-3.14`.

The hosted Windows image reports OS build 26100; fresh per-job virtual environments and the empty-host-timezone smoke setting verify local tzdata fallback across the supported runtime range. Artifact names/availability were inspected; no artifact download or end-user installation is claimed. The local Windows 11 build above uses Python 3.14.5 and has its own executable fingerprint; distinct builds can have different hashes. Existing optional pystray GTK and hosted-action Node notices are nonblocking. Final evidence updates are documentation-only; they do not change the tested application/tool tree.

Core release acceptance is complete on the isolated branch, with the limitations below. S10 remains the next requested-only terminal expression/interaction session. No later hub gate is implied.

## Release and operation limits

The executable is unsigned; no installer, signing, startup registration or distribution was performed. The original checkout and main branch remain separate. Native tray/menu interaction and terminal-viewer playback require their own evidence; source simulations and process launches are labeled separately. Live quota/account validation, other operating systems, browser policy enforcement, refreshed rates, complete account coverage, and a full security certification are outside this release gate. Retained S06–S08 durability, HTTP cancellation and local-filesystem assumptions remain documented in their contracts.

The next core follow-up is S10 expression/interaction only when requested. Optional hub work remains S11–S14 with its own dependencies; a passed core release does not implement that track.
