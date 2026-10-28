# Plan A: missing Codex app usage and accounting audit

Status: **A1–A3 complete for the verified accounting/freshness scope**, October 26, 2026. Source, browser, packaged and real laptop acceptance passed for **0.14.2**; the updated tray is installed and running. Existing unavailable-source/ambiguous-baseline qualifications remain. No commit or push performed.

## Goal

Find why the portfolio research skill creation in this laptop's **Codex desktop app** is absent from the dashboard. Correct the demonstrated failure and check whether the apparently excessive tokens/value share the same cause. A skill file is an output artifact; usage belongs to the model activity that created it. Do not estimate tokens from the skill's file size or count a skill as one request.

Follow [AGENTS.md](../AGENTS.md), the [refinement plan](project-refinement-plan.md), [S11 index rules](s11-local-index.md), [S12 API rules](s12-local-api.md) and [S13 runtime rules](s13-runtime-integration.md).

## Evidence collected

- Working source tree: clean `main` at `4ba7bb3`. The running local service identifies itself as **0.14.1**; this report is not explained by an older running version.
- One read-only service check reported usage revision **82**, no pending settings and no active indexing. Its last import succeeded, while dataset freshness remained **stale**. Job success therefore does not establish complete source coverage.
- Source health: Codex read **165 files** from one readable root; Claude read **23 files**. Codex reports one missing root, 24 retained missing files, one invalid-counter metadata issue, 937 counter-reset issues and 62 cache-exceeds-input issues. Claude reports two retained missing files. These are diagnostic counts, **not counts of lost requests or known missing tokens**. Some may be historical or harmless retention effects; trace the affected session before attributing the bug.
- `usage_jobs.py` already imports at startup and schedules scans at a minimum **300-second interval**. Do not add a second scanner.
- `dashboard/local-session.js` intentionally freezes report context. `local-app.js` distinguishes **Refresh view** from **Rescan local logs**; an open view does not automatically adopt every background publication.
- Default Codex roots are `.codex/sessions` and `.codex/archived_sessions`, or the corresponding `CODEX_HOME` roots. Discovery recursively reads JSONL files. `extract_codex()` expects token-count events with cumulative/last-usage counters and model/session context.
- Canonical tokens already distinguish uncached input from cache reads; output includes reasoning. The audit must verify how real desktop observations reach those fields.

The above was the initial planning evidence. The investigation below identifies the session and defect. No real conversation text, credentials or raw source lines were retained.

## A1 — Locate and reproduce the failure

Target effort: roughly one third of Plan A; diagnosis may change this allocation.

1. Identify the portfolio skill creation's local desktop session from user-selected/recent session metadata and its time window. Confirm the app's effective history root against saved approved roots, including custom `CODEX_HOME` or app profile differences. Keep unrelated home folders and skill contents outside collection.
2. Trace this session through: file discovery → extracted counter observations → reconciled events → published SQLite revision → API result → dashboard filters and frozen context. Inspect only allowlisted metadata/counters; never export prompts, responses or raw lines.
3. Compare the existing view with a fresh query, then an explicitly requested rescan. Check provider, project, day, search and timezone boundaries separately. A projectless skill-creation chat must still appear in overall Codex usage, with an honest unknown-project label if no project is recorded.
4. Determine whether counter resets/cache exclusions affect this session. Inspect the actual counter scope, resets, compaction and parent/child evidence; do not assume all reset warnings indicate duplicates or all excluded intervals are recoverable.
5. Reproduce the observed failure with a minimal synthetic fixture before modifying accounting. If no local counters exist, report the coverage limitation and identify a supported source rather than fabricate usage or scrape private content.

Deliverable: a short diagnosis naming the failing stage, a safe fixture, expected exact counters and the smallest proposed fix. A successful rescan by itself is not evidence of an accounting fix.

## A2 — Fix the demonstrated path and freshness feedback

Target effort: roughly one third.

- If discovery/root configuration is responsible, correct approved-root handling and expose unavailable coverage. Do not silently import an additional account/profile or arbitrary folder.
- If desktop event shape or counter scope changed, extend extraction/reconciliation only with evidence. Preserve cumulative-to-delta rules, fork baselines, duplicate reconciliation and nullable unknown counters.
- If the data is indexed but hidden by a captured view, expose **new usage available**, **last successful scan**, **view captured at**, and distinct **Update view** / **Rescan logs** actions. Check status with a bounded lightweight timer while visible; do not reread full histories from the browser or trigger provider polling. Stop checks when hidden/unmounted.
- Preserve the five-minute owner-controlled import schedule initially. Decide whether faster scanning is necessary only after correctness and timing measurements; a faster scan does not repair frozen views or absent source counters.
- Refresh Overview, charts, lists and detail coherently under one new context. Retain filters, and preserve the old result with clear failure feedback when refresh fails. Keep pagination/Back bound to their original contexts until an explicit coherent refresh.
- Keep essential stale/excluded/unpriced qualifications visible even when the detailed orange report is collapsed. Distinguish retained historical files from current unreadable evidence and an outdated browser snapshot.
- Audit applied model/rate/category selection alongside tokens. Unknown models remain unpriced; large totals must not be reduced by discarding legitimate cached work.

Likely source areas: `usage_config.py`, `usage_ingestion.py`, `usage_observations.py`, `usage_reconciliation.py`, `usage_index.py`, `usage_jobs.py`, `usage_api_query.py`, and production `local-*` modules. Touch only the demonstrated path and necessary feedback.

## A3 — Verification and release handoff

Target effort: roughly one third.

- A synthetic desktop skill-creation session appears exactly once in Codex, Both, its local day and conversation detail; unknown project or unknown price does not hide token usage.
- Append new usage after opening a view: background publication is detectable; explicit update shows the new usage everywhere together. An unchanged rescan adds zero tokens. Exercise failed import, missing root, restart and interrupted writes without erasing accepted history.
- Required invariants: complete `100, 200` plus partial `200` totals **200** in every supported order; reset `100, 200, 50, 100` retains **250**, excluding the ambiguous transition.
- Cache/reasoning fixture: raw input 1,000 including 800 cached, output 100 including 30 reasoning becomes uncached input 200, cached 800, output 100, total **1,100**. Neither cached nor reasoning is added twice. Add changed-model/fork/reset fixtures only where the diagnosis establishes their semantics.
- Reconcile exact summary, daily chart, provider, list and detail totals. Test Los Angeles midnight/DST, filters, old/fresh contexts, partial/unpriced values and pending/failed work.
- Run focused Python/Node checks, relevant full suites and `git diff --check`. If shipping an executable, use `windows/build.ps1` and actual packaged release harnesses. Verify the installed app identity separately from build success.
- Validate the original portfolio session with a read-only before/after counter comparison and a real dashboard interaction. If it has no local counters, the gate is an accurate limitation with supporting metadata, not an invented total.

## Completion gate and dependency

Complete only when the reported session is accounted for exactly once or its unavailable source is demonstrated, supported fixtures pass, and stale/new-publication feedback is verified. Record exact checks, changed files and unresolved scope in the refinement ledger. Plan B's calculator/UI work follows this gate so it cannot conceal an accounting defect.

## A1–A3 implementation evidence — October 26, 2026

### Confirmed diagnosis and change

- Located the user-confirmed local chat **Plan portfolio research skills** using app metadata, then inspected only its token/session metadata and the three child files contributing to its indexed conversation. The parent file was discovered and had 82 indexed observations; missing-root warnings were not the cause of this session's accounting failure.
- Each child rollout starts with its own fork `session_meta`, followed by a replayed parent header. The old extractor overwrote the outer identity, project and fork boundary with inherited metadata. Four independent counters were then reconciled as one parent conversation, producing false resets, inflated values and excluded intervals.
- The extractor now preserves the outer fork header's identity, project, creation boundary and source reference across replayed ancestor headers. Ordinary non-fork extraction is unchanged. The parser cache identity advances from `observations-v1:project-context-2` to `observations-v1:fork-origin-3`, forcing a normal re-extraction of unchanged available files on the next import. No database rebuild or new schema is needed.
- For these four selected files, the stored legacy merge yielded **65,602,987 tokens**, 93 accepted events, 36 reset issues and two cache-exceeds-input issues. Read-only extraction with the fix yields **18,872,881 accepted tokens** across four conversations and 127 events, with no collision-induced reset/cache issues. The parent alone accounts for **13,524,013**. These are scoped file comparisons, not account-wide totals or a claim of complete billed usage.
- The existing conservative fork baseline is preserved: three child first intervals remain qualified as unavailable baselines. Their skipped contribution is not invented. The parent's initial zero-origin assumption remains labeled. No price/rate/fee changes were made.
- Added a status-only observer every 30 seconds while visible. It pauses while hidden, discards obsolete replies and stops on disposal. A newer publication exposes **Update view**, while scan and capture clocks remain separate. Updating captures all widgets coherently with existing filters; status checks cannot trigger an import/provider poll or replace usage totals/drafts. Essential accounting-exclusion warnings remain visible above closed Data details.

### Verification

- New focused regression: **3 Python tests**, initially all failing under the old extractor, now passing. Includes outer metadata/provenance/privacy, nested replay headers, all 24 parent/children/copy file orders, old-cache reparsing without changed bytes, independent conversation/detail/daily totals, append, idempotence and failed-read retention.
- Full Windows build: **419 Python tests / 77.342 s**, then successful application/installer packaging, **19/19** existing offline executable checks and isolated installer acceptance (exact payload, GUI subsystem, Start menu/startup, repeat install and preserved synthetic settings/index).
- Frontend: **107 tests / 3730.128 ms**, including four new freshness tests and the production local HTTP integration. Status failures, nonoverlapping checks, hidden/disposed/obsolete replies, unchanged totals/drafts and coherent filtered refresh are covered.
- Independent probes printed **200/200**, **200/200**, **250/250**, all `matches_expected=true`.
- New actual-executable regression `windows/tests/packaged_codex_fork_smoke.py`: seeded old-parser cache → automatic reparse → **350 tokens / USD0.0007**, separate parent/child/detail → append **450** → restart **450** → terminal agreement/privacy, all pass. The Windows CI workflow now includes this gate; hosted CI has not been run for this change.
- Existing packaged real launcher: **2,840,000 / USD18.42**, bundled freshness module, authentication/resume, offline limits, detail and owner reuse pass. Full packaged recovery harness passes schema-2 upgrade/backup/restore, interrupted jobs/restart, invalid settings, access controls, safe diagnostics and terminal fallback.
- Fixture performance: 40 files / 4,000 accepted events / 4,000,000 tokens / USD8. Overview HTTP bundles **1.271989 / 0.831680 / 0.750468 s**; Explore **0.586452 / 0.549116 / 0.517925 s**, below the two-second fixture target. These are local machine measurements, not a general performance guarantee.
- Actual production-handler browser check with synthetic parent/child logs: separate **300 + 50** rows; after appending, a **new usage available** notice preserves the filtered **300** snapshot; Update view gives **400**, and detail/Escape Back agree while preserving Codex/search filters. Data details stays closed. At a 390px viewport, document/client widths both **375px**, with local table/navigation scrolling; the freshness notice is readable. No native taskbar playback is claimed.
- Early test attempts: restricted loopback sockets caused sandbox-only HTTP failures; an elevated run without isolated LOCALAPPDATA encountered the existing real tray's lock in three mocked CLI tests. The final passing build uses workspace-local TEMP/TMP, LOCALAPPDATA and provider roots. The real owner/settings/history were not altered by these test runs.

### Release and remaining acceptance

- Tested app SHA256: `aaab69138db7b9212eb6e2eb78b2208ca80faec4a11dacc134c1d88056693b4d`.
- Tested installer SHA256: `287cf521d63f85264950fd264fa2a7d5a9ad8748c26fdd0c69df8e818177c2c3`.
- `windows/dist` contains only **Usage_Dashboard.exe**, the tested 0.14.2 installer. The previous installer and portable build outputs are preserved under ignored `windows/build/a1-release-0.14.2`; the normal build script's output naming is unchanged.
- Staged the exact tested payload with the existing installer's `--quiet --no-start`; installed payload hash matches. After the user confirmed the old tray was closed, launched the installed 0.14.2 executable. The running API confirms 0.14.2, system-detected America/Los_Angeles, and normal owner-controlled import at revision **88**. All four selected files now use `observations-v1:fork-origin-3`.
- Real post-update acceptance: parent **13,524,013** tokens / 80 accepted events; three children **1,334,002 / 2,428,696 / 1,586,170** tokens, totaling **18,872,881** / 127 events. Read-only current-source reconciliation matches the live SQLite publication and API Overview/list/detail for every conversation. No collision-induced reset/cache issue remains in this selected group; the three unknown fork baselines and initial-origin assumption remain visible. Dataset freshness is still stale because of unrelated retained/missing source evidence.
- Opened the real dashboard through the native `--dashboard` handoff, reusing the running owner. In the default Vivaldi browser, searched the selected conversation's metadata identity: the parent displays **13.52M / USD2.12**. Detail shows uncached input **196,308**, cache reads **13,287,808**, output **39,897** and reasoning **13,710** as a subset of output. Escape Back preserves the filtered list and total. Scan/capture clocks use PDT and detailed data qualifications remain closed. Left this real filtered dashboard open for the user; no unrelated browser tabs were closed. Initial native accessibility clicks on occluded/offscreen targets did not navigate; raising the window and using freshly observed visible controls completed the check.
- Existing missing/retained source warnings and genuinely ambiguous counter intervals remain qualified. No raw history export, credential change, account-matching claim, credit calculator, macOS verification or source-history deletion. Concurrent Plan B research documents/ledger edits are preserved.
- Plan A's requested missing-session accounting and freshness gate is complete with source, packaged and real acceptance. Full account coverage, recovery of absent source bytes, unknown first intervals, hosted CI, clean-machine distribution and macOS remain outside this acceptance. Plan B still needs its unit/default decision before calculator/UI implementation.
