# Dashboard and refined core branch integration

Prepared October 24, 2026. Status: preflight complete; integration execution authorized by the user after this plan. This is a compatibility session, not a repeat of S08 or a claim of release readiness.

## Pinned inputs and ownership

- Dashboard/main: `963275c`, including the completed interaction and recovery work.
- Refined core: `e0bcd79`, S01-S08 on `codex/s01-observation-contracts`; application version 0.8.0.
- Common ancestor: `854ac73`.
- Agent 1 retains S09 release ownership. This session owns the isolated combined checkout, merge resolutions, compatibility repairs and combined evidence. Later core commits are reviewed and incorporated at explicit checkpoints; no background monitor or automatic publication is created.
- Preserve the original checkout's existing `windows/usage_reports.py`, untracked `usage_observations.py`, `usage_records.py` and `tests/test_observations.py`. Do not use these incomplete working files as integration inputs. Do not modify Agent 1's worktree.

Read the [refinement plan](project-refinement-plan.md), [integration contract](usage-hub-integration-plan.md), [dashboard coverage inventory](dashboard-resilience-handoff.md) and [S05 adapter review](s05-dashboard-integration-review.md). The S08 contract is present on the core branch at `docs/s08-privacy-diagnostics.md` and becomes available after combining the branches.

## S08 completion review

S08's committed ledger records 17 focused privacy tests, a 243-test full suite/build and 32 synthetic packaged cases. It covers allowlisted extraction, default reduced report metadata, explicit full-metadata exports, inert terminal/HTML display, provider snapshot projection, strict atomic diagnostic exports and preserved credential/redirect protections. These reported full/build/packaged results were inspected, not rerun during preflight.

Independent preflight exported only committed `e0bcd79` to ignored `windows/build/s08-integration-preflight/core-e0bcd79` and ran its **17 privacy tests: all passed in 18.821 seconds**, using the existing project Python and workspace-local TEMP/TMP. No real histories, credentials or provider requests were used. Source export is a test snapshot, not a merged checkout.

The main branch's old strict privacy probe cannot yet run unchanged across both branches. It first failed in the preview valuation adapter with `decimal.InvalidOperation`; a narrowed core-only check also exposed its empty-provider legacy Report construction when malformed metadata yields no records. With only that temporary probe's output function scoped to records/notices and nonempty reports, all three historical case checks passed. This is limited preflight evidence, not a pass of the unchanged strict probe or the preview boundary. Port the fixture correctly during integration, retain its assertions and remove expected-failure markers only after the complete cases pass.

## Confirmed integration work, including S08 follow-through

1. **Combine committed snapshots in an isolated worktree.** Both branches changed `docs/project-refinement-plan.md`, `windows/README.md`, `windows/build.ps1`, `windows/requirements.txt`, `windows/tests/test_privacy.py` and `windows/usage_tray.py`. This is a shared-change inventory, not a claim that every file has a textual conflict. Preserve both histories and all core AGENTS rules.
2. **Preserve both privacy suites.** The two independently added `test_privacy.py` files have distinct coverage. Retain S08's tests, move the preview-specific tests to a clearly named module, and port shared pre-S08 fixtures to the refined query/record contracts. Keep HTTP fixed-error/no-request-log checks and sentinel coverage. Update the strict probe without weakening exposure assertions or accepting unexplained skips/expected failures.
3. **Repair the reproduced valuation incompatibility.** Combining committed core modules with committed preview modules makes a demo query fail with `InvalidOperation`. The refined `gpt-5.4` price has optional write rates `None`; the preview unconditionally converts every rate through `Decimal(str(rate))`. Use the authoritative core valuation policy for the compatibility seam, including unused missing rates, used missing rates, explicit zero, unknown models and event tier/context evidence. Never coerce missing rates to zero or restore duplicate pricing defaults. Real-data service/index/API adoption remains gated.
4. **Preserve S08 at the launcher boundary.** Merge the explicit demo dashboard flags with S06 configuration, S07 ownership and S08 diagnostic/metadata guards. Dashboard launch must remain deliberate and demo-only; offline reports and diagnostics must remain GUI/polling independent. Reject incompatible command combinations explicitly; do not quietly ignore report/export/settings flags.
5. **Cover the added dashboard privacy boundary.** Reuse synthetic sentinels through preview summary/detail responses and targeted rendered text/attribute sinks. Check hostile labels, control/bidi text and canonical identity separately; do not replace internal identities with display digests. S08's reduced report display does not authorize changing the dashboard's intentional detail metadata or invent a new privacy preference. Fixed HTTP errors and cancellation must not expose exceptions, cookies, query text or source payloads. Native browser checks are needed only for changed/uncovered sinks; existing ordinary provider/chart/Back/recovery checks are not a new review session.
6. **Combine packaging instructions and assets.** Keep refined build/version/dependency behavior and local dashboard/font/timezone assets. Reuse the packaged dashboard smoke check after an isolated combined build. A build alone does not complete S09 or certify native tray playback.

## Execution and acceptance

1. Create/reuse a suitable managed integration worktree from `963275c`, with a `codex/` branch. Merge the pinned S08 commit there. Keep the source checkout and Agent 1's working files untouched.
2. Resolve overlaps by responsibility: core service/config/runtime/privacy authoritative; dashboard remains an explicit demo adapter. Record any necessary scope deviation before broadening changes.
3. Run focused privacy, preview/service/valuation/config/CLI checks for touched behavior. Reproduce each compatibility failure before repairing it. Run the strict privacy probe and inspect accounting probe comparisons, not just their exit codes.
4. Run the combined relevant Python suite and retained Node suite after final source changes, with the project interpreter and isolated temporary/application-data directories. Check syntax, local documentation links, conflict markers and `git diff --check`.
5. Build using `windows/build.ps1` if packaging/launch behavior changes, then exercise bounded synthetic executable checks for both the preserved terminal/report path and demo dashboard assets/query. Record build/run outcomes separately.
6. Update this plan and the refinement ledger with exact input commits, resolved conflicts, changed files, actual checks, unrun checks and the next owner/dependency. Keep completed historic entries as history; add current follow-ups instead of relabeling old evidence.
7. Inspect later committed core changes at the closing checkpoint. Incorporate only completed, relevant commits with their own compatibility validation; do not copy active uncommitted work or claim indefinite future incorporation is already done.

Acceptance: both branches' behavior is preserved in one isolated checkout; confirmed incompatibilities have regressions and repairs; both privacy suites survive; the strict privacy probe has no unresolved exposure; retained accounting comparisons agree; exact values and demo labeling remain honest. No merge into main, push, live provider call, deployment, Figma change or automatic monitor is included.

## Remaining dependencies

- **S08:** independently verified focused core gate; this session validates its additional dashboard/merge boundaries. It does not reopen the completed core session without new defect evidence.
- **S09 / Agent 1:** native tray/menu lifecycle, clean-runtime/CI/version support, scoped read-only local-history/performance and final release evidence remain separate. Inspect its actual completion evidence when available.
- **S11-S14:** persistent snapshots/index, explicit API DTOs and frozen query revisions/jobs, real-data dashboard integration and hub release remain gated. This session neither creates a competing database nor enables real dashboard collection.
- No full security/anonymization/accessibility certification, live account coverage or exhaustive browser/terminal policy verification is implied.

## Execution checkpoint before S09 incorporation

The isolated `codex/dashboard-core-integration` checkout combines the pinned S08 and dashboard inputs. Four textual conflicts were resolved: ledger (both histories retained), build (dashboard assets plus full tzdata collection), privacy tests (S08 module plus renamed preview module), and tray (refined runtime/config/privacy with explicit demo launch). The preview delegates event valuation, summaries and fee comparisons to the core. Seven integration tests, ten HTTP/query tests, eight preserved preview privacy tests, 22 Node tests and all three strict privacy probes pass; accounting comparisons are 200/200, 200/200 and 250/250.

Full/build attempts are not yet accepted: the first 267-test run caught a partially written synthetic PID marker; the producer now publishes atomically. The next 268-test run encountered two three-second synthetic process startup timeouts. The focused 19 runtime tests passed in 9.905 seconds, but that does not replace a clean combined run. Production containment/cleanup assertions remain unchanged.

During execution, Agent 1 committed `fee6e23` with S09 release/CI tooling and a ten-second crash-fixture startup allowance. Its committed handoff says validation is still in progress; do not call S09 complete. Incorporate this available commit at the closing checkpoint, resolve overlapping build/ledger documentation, then rerun combined acceptance. The ownership fixture also hit its three-second startup allowance here; align that startup wait with S09's bounded ten-second policy, retaining the cleanup deadlines.
