# Usage Tray / Usage Hub: engineering refinement plan

Status: implementation backlog. This document does not implement its fixes or authorize executing every session automatically.

Historical planning baseline: local working tree based on Git `f93f87e`, with then-uncommitted Windows changes and documentation. Prepared from the October 23, 2026 review and subsequent refinement discussion. S00 captured the implementation baseline at clean commit `810b3a8`; see [the baseline and handoff](s00-baseline.md). Windows is the primary runtime target; macOS observations are source review only.

## 1. Purpose and success criteria

Make the existing local usage tool dependable before expanding its interface. Its primary question is: **What would my recorded Codex and Claude activity cost at configured API token prices, compared with my subscriptions?**

The user's configured monthly fees are Codex **USD 20** and Claude **USD 20**. These are configuration values, not provider API prices. The comparison is calendar-month-to-date against full monthly fees, not an actual bill or a claim of realized savings.

Core refinement is complete when:

- Accepted usage is independent of source-file ordering, repeated imports, and supported overlapping copies.
- Reset/fork/stream cases have explicit, tested accounting outcomes.
- Unknown prices, unknown counters, excluded intervals, and missing local sources remain visible and distinct.
- All consumers use the same token facts, valuation policy, period boundaries, and summary result.
- Settings survive restart; provider failures preserve useful previous state; errors identify a safe category and next step.
- The packaged Windows application passes the relevant offline and lifecycle checks.

Interface redesign is a later session. The terminal remains available, and a future dashboard opens explicitly. Building a database, API, or web interface is an optional integration track, not a prerequisite for correcting the current tool.

## 2. Documents and decision ownership

- [AGENTS.md](../AGENTS.md): working instructions for agents implementing this refinement.
- [Project evaluation](project-evaluation-2026-10-23.md): evidence, confirmed defects, and review limitations.
- [Usage hub integration contract](usage-hub-integration-plan.md): detailed proposed database/API/UI semantics for the optional hub track.
- [Original hub plan](usage-hub-plan.md): product/design background; superseded by the integration contract where they differ.
- [Accounting probes](review_accounting_probes.py): isolated reproductions; currently diagnostic scripts rather than passing regression gates.

This document owns work order, session scope, and completion evidence. The integration contract owns detailed hub DTO/schema/query semantics. Preserve the shared accounting invariants below across both documents. Record substantive deviations with rationale in the decision log before dependent work diverges. Current user instructions take precedence; do not repeatedly ask about already-established preferences or routine reversible implementation choices.

Role labels such as collector, backend, and release describe responsibilities. One developer may perform all of them; no separate team is assumed.

## 3. Factor assessment and priorities

Scores are approximate engineering-maturity judgments, not measured accuracy, test coverage, or percentage complete. They assess the current Windows implementation. The weighted baseline is approximately **60/100**, excluding expression/presentation. Re-score only with new implementation evidence; better documentation alone does not prove a higher runtime score.

### F1 — Foundation: 75/100; weight 15%; priority P2

Keep Python, the existing adapters, token concepts, tray entry point, and packaging approach. Improve configuration ownership, version identity, module responsibilities, and dependency boundaries. Avoid a framework rewrite or a module split that only moves code without clarifying behavior.

Main sessions: S00, S05, S06, S09. Evidence of improvement: a headless service import, one configuration source, reproducible commands, identifiable builds.

### F2 — Data integrity: 45/100; weight 25%; priority P0

Fix overlapping-source overcounting and repeated counters after resets. Preserve source evidence, derive deltas after reconciliation, and distinguish unknown metadata from observed zero. Partial local coverage must never imply complete account coverage.

Main sessions: S01–S03. Evidence: invariant fixtures, file-order permutations, idempotent results, and explicit exclusions.

### F3 — Pricing and estimated value: 65/100; weight 15%; priority P1

Introduce precise monetary calculations and versioned provenance; qualify request-tier assumptions; preserve unpriced states; make fee comparisons signed and scoped correctly.

Main sessions: S04–S06. Evidence: exact synthetic estimates, rate-version isolation, and consistent comparisons across consumers.

### F4 — Architecture and maintainability: 55/100; weight 10%; priority P1

Separate source observation, reconciliation, valuation, aggregation, presentation, and orchestration by responsibility. Expose one shared result to existing reports and future integrations. Extract small seams while preserving behavior, rather than launching a broad rewrite.

Main sessions: S01, S05, S07; optional S11–S13. Evidence: shared typed contracts and calculations, GUI-independent imports, and explicit process ownership when a service exists.

### F5 — Reliability and recovery: 60/100; weight 10%; priority P1

Retain independent provider refresh/backoff. Add safe handling for active log writes, interruption, repeated launches, settings corruption, and stale data. Do not substitute empty results for failed computation.

Main sessions: S03, S06, S07, S09. Evidence: controlled failure/recovery fixtures and packaged lifecycle checks.

### F6 — Testing and verification: 55/100; weight 10%; priority P0/P1

The previous verification passed 57 existing tests, while separate probes still exposed two accounting failures. Promote those cases into meaningful assertions and test invariants across layers. The test count itself is not a success metric.

Main sessions: every behavior-changing session, especially S00–S05 and S09. Evidence: expected outcomes independent of the implementation, regression coverage, and executable release gates.

### F7 — Privacy and security: 70/100; weight 5%; priority P1

Preserve local credential handling, redirect rejection, and sanitized errors. Keep transcript content out of persisted/exported records. Treat paths, IDs, model names, and other source metadata as untrusted display text. Extend access controls only when the local API is introduced.

Main sessions: S08; optional S11–S13. Evidence: privacy sentinels, safe rendering, redacted diagnostics, and API boundary tests when applicable. This score is not a comprehensive security certification.

### F8 — Packaging and operations: 65/100; weight 5%; priority P2

Make app/build/rate identity visible, settings discoverable, startup predictable, and packaged checks representative of actual usage. Bound generated artifacts through a documented retention policy.

Main sessions: S06, S07, S09. Evidence: executable smoke checks, version output, clean restart, and tested recovery.

### F9 — Product scope and requirements: 80/100; weight 5%; priority P2

Keep the value question primary and live capacity separate. Preserve local-only scope, terminal access, explicit dashboard launch, and incremental implementation. Do not count proposed features as existing capabilities.

Main sessions: S00 and scope checks throughout; optional S13. Evidence: each shipped metric has a source, scope, time range, and unavailable state.

### F10 — Expression and interaction: provisional 40/100; unweighted; deferred

Later improve information hierarchy, explanation of cached tokens, summary length, and navigation. Begin with domain-correct summaries before changing visual layout. Do not make output styling the first implementation task.

Main session: S10; optional S13. Evidence: coherent one-screen summary and drill-down reconciliation, not aesthetic preference alone.

Priority definitions: **P0** blocks trusting affected accounting; **P1** establishes dependable calculation/recovery; **P2** improves maintenance and delivery after prerequisites; **deferred** is outside the current core path. These are project priorities, not externally assigned incident severities.

## 4. Invariants that every session must preserve

1. Local usage may cover multiple unmatched accounts; live limits describe the active CLI account. Keep these scopes separate.
2. Record uncached input, output, cache reads, 5-minute writes, and 1-hour writes as separate nonnegative categories. Total is their sum. Reasoning is nullable and already included in output.
3. Preserve explicit effort values and their source. Do not infer effort from thinking budgets or apply an effort-based price multiplier.
4. Reconcile copied/overlapping histories before deriving canonical usage. Neither file position nor a cumulative numeric tuple is sufficient global event identity.
5. Unknown rates produce unpriced usage; all-unpriced and empty results have different unavailable states. A legitimate configured zero rate remains a priced zero.
6. Ingestion completeness, price coverage, counter quality, and tier assumptions are separate dimensions. No single percentage represents all of them.
7. Estimate each accepted event, then aggregate. An aggregate delta does not prove request context size; keep tier evidence or a visible compatibility assumption.
8. Compare full configured fees only for unfiltered calendar-month-to-date, optionally restricted by provider. Do not silently omit unavailable providers from a Both comparison.
9. Use one captured time context per result. Shared-service queries use UTC `[start, end)` and named display-zone boundaries; document the existing inclusive-end behavior during migration.
10. Extract allowlisted metadata from logs. Parsing reads source lines, but prompts, responses, credentials, and raw payloads must not enter saved DTOs, databases, diagnostics, or exports.
11. Preserve existing local modifications and useful behavior. No automatic reset, stash, source deletion, credential modification, or remote publication as a consequence of reading this plan.

## 5. Session protocol and dependency order

A session is a reviewable unit of work, not a fixed duration or a requirement to start a new chat. Split a session if its change cannot be understood or verified coherently. Reading this plan is not an instruction to execute all sessions.

Core dependency path:

```text
S00 Baseline
  -> S01 Observation contracts
  -> S02 Reconciliation fixes
  -> S03 Quality / source recovery / time
  -> S04 Precise valuation
  -> S05 Shared summaries
  -> S06 Persistent configuration
  -> S07 Runtime reliability
  -> S08 Privacy and diagnostics verification
  -> S09 Core Windows release gate

After core correctness: S10 Expression and interaction, when requested
Optional hub track: S11 Index -> S12 API -> S13 Dashboard -> S14 Hub release gate
```

Security and regression checks apply throughout; S08 is a focused verification session, not permission to postpone obvious fixes. Documentation/design exploration may proceed independently when it does not depend on unresolved accounting decisions. Do not introduce database/API infrastructure just to finish a core session.

Each session must record its starting state, intended change, touched files, tests/commands with outcomes, known limitations, and next ready session. Mark a session complete only when its gate is met. Distinguish `not_started`, `in_progress`, `complete`, and `blocked`; use blocked only for a specific dependency that cannot currently be resolved. Do not turn a passing diagnostic script's exit code into evidence that its printed comparisons passed.

## 6. Core implementation sessions

### S00 — Capture the baseline and establish the work ledger

Factors: F1, F6, F9. Priority: P0 support. Dependencies: none.

- Inspect Git status, applicable instructions, and the current files; preserve user edits. Record the actual base and changed files instead of assuming this document's baseline is still current.
- Run the existing test suite with the project interpreter and capture a concise outcome. Re-run the accounting probes and inspect each `matches_expected` value.
- Inventory current public CLI options, period semantics, report formats, provider behavior, and packaged launch behavior from source and available evidence.
- Record decisions for conservative reset/overlap handling, uncertain context tiers, and configuration location. Use the agreed defaults where sufficient; identify unresolved material ambiguities without stopping unrelated work.
- Add a progress entry using section 10. The historical 57-test result is context, not proof of a fresh run.

Starting points: `windows/tests/`, `windows/usage_tray.py`, and the review/probe documents.

Gate: baseline commands and known failures are reproducible; the next session has explicit invariants and scope. The two known defects remain open until S02.

### S01 — Introduce observation and canonical-event contracts

Factors: F2, F4. Priority: P0. Dependencies: S00.

- Define provider observations carrying conversation identity, available message/request/turn IDs, counters, time, sequence/source position, model/effort context, and quality/provenance fields.
- Keep raw source observations distinct from accepted canonical events. Preserve enough metadata to reconcile copies, forks, and resets without storing source text.
- Represent weak/missing identity explicitly. Preserve absence/invalidity indicators before normalization can turn a counter into zero.
- Build a fixture-friendly reconciliation seam. Reuse `Record` as a compatibility projection if appropriate; do not change every caller at once or create a database in this session.
- Document identity/epoch rules and conflict handling alongside focused tests. Stable IDs must not depend on file enumeration order.

Starting points: `windows/usage_reports.py` (`Record`, readers, normalization helpers); proposed small modules only as responsibilities move.

Checks: observation extraction retains required evidence; private content is absent from projected fields; ordinary existing fixtures retain intended token categories and metadata.

Gate: observations can be reconciled independently of GUI, pricing, and formatting, with an explicit source-to-event mapping policy.

### S02 — Fix overlapping histories and reset epochs together

Factors: F2, F6. Priority: P0. Dependencies: S01.

- Convert both known reproductions into regression assertions before fixing them. Test complete-first and truncated-first order, including reversed root/file enumeration where practical.
- Reconcile a conversation's available observations before deriving deltas. Resolve identical/overlapping observations using sequence, timestamps, IDs, context, and fork evidence; do not simply take the largest per-file sum.
- Introduce coherent reset epochs so repeated numeric totals after a reset cannot collide with earlier events. Exclude and flag the ambiguous reset transition while retaining supported subsequent increments.
- Preserve fork baselines without counting inherited work as new child usage. Keep model/effort attribution aligned with the contributing event context.
- Preserve Claude streamed-update merging and weaker last-usage fallback behavior, with explicit uncertainty where identity is insufficient. Conflicting evidence must produce a documented exclusion or qualified result rather than a silent arbitrary winner.

Required fixture outcomes:

- Complete counters `100, 200` plus a partial copy containing `200` yield **200**, regardless of enumeration order or reimport.
- Counters `100, 200, 50, 100` retain **250**, excluding the ambiguous reset transition and retaining the final valid 50-token increment.
- Exact copies, zero-delta notifications, forks, equal timestamps, and repeated post-reset values have documented deterministic outcomes.

Gate: the new regressions pass, the existing suite has no unexplained regression, and the diagnostic comparisons match their expectations. Do not claim these synthetic cases certify all live histories.

### S03 — Make source quality, recovery, and time explicit

Factors: F2, F5, F6. Priority: P1. Dependencies: S02.

- Replace ambiguous warning-only interpretation with structured issue codes/counts while retaining readable messages for existing consumers.
- Distinguish absent counters, malformed complete lines, an incomplete actively appended final line, invalid timestamps, missing IDs, skipped intervals, and unavailable roots. Unknown skipped token amounts stay unknown.
- Read a consistent file generation/prefix; detect truncation/replacement and avoid mixing generations. Do not silently turn a failed scan into a successful empty result.
- Stop relying on modification time as proof of event-time relevance for authoritative backfills. Preserve baselines needed to calculate in-range deltas even when earlier observations are out of range.
- Define one range/timezone context and adapt legacy inclusive-end behavior deliberately. Use named-zone local day/month boundaries and trailing 168 hours for Last 7 days; preserve provider-specific session semantics separately.
- Before persistence exists, expose a failed/partial scan honestly. When a retained committed dataset exists, keep it queryable and explicitly stale on import failure.

Checks: midnight, month change, DST transitions, exact end boundary, partial final line, replacement/truncation, unreadable source, and an old-mtime file containing relevant event timestamps.

Gate: callers can distinguish empty, partial, failed, and retained-stale data; boundary fixtures pass; no event is silently shifted between periods by inconsistent clocks.

### S04 — Make valuation precise, versioned, and explainable

Factors: F3, F6. Priority: P1. Dependencies: S02, S03.

- Use exact decimal rates/money within the shared valuation path. Preserve integer token counts; define bounds, scale, and rounding policy consistent with the hub contract.
- Retain exact model lookup and documented dated-snapshot mapping. Never assign a convenient price to an unknown model.
- Attach rate source, checked date, catalog/override version, computation policy, and selected tier/assumptions to each valuation.
- Separate supported request-context evidence from compatibility tier estimates. Do not infer one request's context from a monthly/group total or an ambiguous multi-request delta.
- Define `complete`, `partial`, `unpriced`, and `empty` aggregate states, separately from ingestion quality. Repricing must leave canonical token facts unchanged.
- Return signed monthly fee differences with explicit qualifications. Use one $20/$20 configuration source after S06; until then, isolate temporary compatibility defaults in one place.

Checks: synthetic category arithmetic; unknown-only and mixed models; zero rates; tiny amounts; large counts; threshold boundaries; missing context evidence; selected-provider comparisons; no-record and filtered-comparison states.

Reference expectations: the integration fixture yields Codex **18.42 USD**, Claude **0.471 USD**, Both **18.891 USD**. Against full 20/20 fees, the signed differences are **-1.58**, **-19.529**, and **-21.109 USD**. These are synthetic expectations, not current live usage or price verification.

Gate: exact expectations pass; existing float compatibility differences are explained within the agreed quantization bounds; unpriced usage cannot appear as a priced zero or unconditional savings.

### S05 — Extract one headless report/query service

Factors: F1, F3, F4. Priority: P1. Dependencies: S03, S04.

- Define a typed result containing scope, captured range/timezone, generated time, tokens, value states, issues, provenance, groups, and comparison amounts.
- Make pricing and aggregation presentation-independent. Existing text/HTML renderers format this result rather than recomputing competing totals or consuming preformatted comparison strings.
- Keep provider polling separate from usage queries. Generating a local report must not require importing tray GUI dependencies or making a provider request.
- Provide exact stable sorting and consistent full-result aggregates. Define how conversation/project/model/effort breakdowns derive from the same accepted events.
- Preserve CLI/report entry points with compatibility adapters. Document intentional accounting corrections instead of forcing agreement with a known-buggy legacy result.

Checks: shared category/value totals reconcile across provider/group/detail views; headless imports work; text/HTML consumers share exact underlying results; no network call occurs for offline fixture reports.

Gate: one authoritative result drives current consumers without duplicate valuation/summary implementations. Output styling can remain unchanged until S10.

### S06 — Persist validated configuration and identity

Factors: F1, F3, F5, F8. Priority: P1/P2. Dependencies: S05.

- Choose a documented per-user local application-data location for configuration, separate from source code, generated build output, and credentials.
- Persist fees, approved log roots, timezone, rate overrides/catalog selection, and report preference actually supported by the application. Seed fees at $20 each; define CLI override precedence and whether overrides persist.
- Validate configuration atomically: finite nonnegative fees/rates, supported fields/timezones, explicit root semantics, and configuration schema version. A malformed file must produce recoverable guidance rather than silent replacement or data loss.
- Add app/build, parser/reconciliation, and pricing identities to structured results and an accessible version/diagnostic command or view.
- Preserve defaults/legacy arguments through a documented migration. Do not introduce unsupported appearance toggles or billing-cycle calculations.

Checks: round-trip persistence, CLI precedence, invalid/partial files, interrupted atomic write, zero/missing fee semantics, timezone availability, and legacy startup.

Gate: settings survive restart, one source owns default fees, versions are identifiable, and failure preserves the last usable configuration or offers a clear first-run state.

### S07 — Separate polling from UI and improve runtime recovery

Factors: F4, F5, F8. Priority: P1. Dependencies: S05, S06.

- Move provider state/scheduling into a GUI-independent component. Retain independent provider execution, five-minute minimum success interval, failure backoff, and previous successful snapshots.
- Keep scheduling deadlines monotonic in-process. Derive wall-clock retry timestamps for display; never persist a monotonic value as UTC.
- Distinguish login-required, network error, cooldown, blocked usage, unsupported response, and unexpected local failures. Replace broad permission-only report errors with safe categorized outcomes.
- Redraw the tray on meaningful state changes instead of every one-second worker wake where unnecessary. Ensure refresh triggers reach both providers without bypassing locks/backoff.
- Handle repeated launches predictably, with one polling owner for one installation. Choose a lightweight mechanism suited to the current app; do not require an HTTP server solely to establish ownership.
- Define shutdown/restart behavior and cleanup only app-owned children/resources. Bound report artifact retention with explicit policy; do not remove source histories or live user data.

Checks: one provider hangs/fails while the other succeeds; repeated refresh during cooldown; same-provider concurrency; two app launches; clock change; report/open failure; Quit/restart.

Gate: repeated actions do not multiply provider requests, stale state remains labeled, and the app shuts down without orphaning its owned provider processes.

### S08 — Verify privacy, safe rendering, and diagnostics

Factors: F7, F5, F6. Priority: P1. Dependencies: S05–S07; apply relevant safeguards in earlier sessions too.

- Enforce metadata allowlists at extraction and serialization boundaries. Test that sentinel transcript/credential values cannot enter summaries, saved reports, diagnostics, or future persistence DTOs.
- Escape HTML and neutralize terminal control sequences in untrusted metadata without changing internal identity. Keep full IDs/paths available only through intentional supported views/exports.
- Preserve credential redirect protections and sanitized provider errors. Do not add credential refresh/writes merely to make failures disappear.
- Provide redacted local diagnostics containing operation/build IDs, safe categories, phases, and counts. Raw provider payloads and source lines are not diagnostic logs.
- Document current local artifact locations, retention behavior, and what a user-selected diagnostic export includes. Do not claim a full security audit from these checks.

Gate: privacy/rendering fixtures pass; existing provider safeguards remain tested; diagnostics can explain a failure without exposing protected source content or secrets.

### S09 — Validate the refined core as a Windows release

Factors: F1, F6, F8. Priority: P2 release gate. Dependencies: S00–S08 gates satisfied.

- Run the complete relevant suite once after final source changes, then build with the existing Windows script. Pin any newly required dependencies at implementation time; reuse the current packaging approach unless evidence requires change.
- Exercise the packaged executable with offline/demo fixtures: terminal report path, saved report generation, version identity, settings load/restart, and GUI-independent commands. A successful build alone is insufficient.
- Check supported Python/runtime versions in CI. Add a bounded packaged smoke check rather than assuming source tests prove frozen-runtime behavior.
- Verify named timezone data on a clean Windows runtime if named-zone handling was introduced. Keep local resources bundled; do not rely on a development environment or CDN.
- After fixture gates pass, perform a sanitized read-only local-history check: observed model keys, known/unpriced coverage, structured issues, category sums, and provider/detail reconciliation. Do not export transcript content or call this complete account verification.
- Measure representative scan time/history size and record the machine and scope. Add indexing only through S11 when justified or required for the explicitly requested hub.

Gate: core fixtures, executable smoke checks, version/settings behavior, and release notes all agree. Remaining unsupported shapes/assumptions are documented. This completes core engineering refinement without claiming the future hub is implemented.

## 7. Deferred expression session

### S10 — Refine explanations and interaction after correctness

Factors: F10, F9. Priority: deferred. Dependencies: S05, S06 and stable core gates. Start when interface refinement is requested.

- Make the default terminal view approximately 20–30 lines at a normal 80-column width: period/scope, API-equivalent value or priced subtotal, provider fees/differences, quality/freshness, and cache-read explanation.
- Keep full audit details available, but show one grouping at a time. Sort by contribution using exact values; label partially priced rankings honestly.
- Prefer compact summaries and a pager/detail modes before choosing a full terminal UI. Measure whether in-window navigation is needed.
- Make output and cached-context distinctions clear. Reasoning stays labeled as included in output; no-record usage stays distinct from zero account usage.
- Review representative normal, narrow, long-path, Unicode, empty, mixed-priced, stale, and error states. A future web interface consumes the same underlying result.

Gate: a user can identify the selected scope, value, comparison, and main limitation without reading the full diagnostic export; details reconcile to the summary. Do not count this session as complete from static screenshots alone.

## 8. Optional usage hub integration sessions

These sessions remain proposed work. Follow the detailed [integration contract](usage-hub-integration-plan.md); confirm any already-started database implementation before introducing a competing one. No remote database, external Figma edits, deployments, or account synchronization are implied by this plan.

### S11 — Add a recoverable local index

Factors: F2, F4, F5, F7. Dependencies: core contracts/correctness gates through S09; hub integration explicitly in scope.

- Map observation, canonical event, valuation, issue, settings, and revision responsibilities to the chosen schema. SQLite remains the recommended local default where no existing database constrains the design.
- Reparse changed files and reconcile the whole affected conversation, including unchanged overlapping sources. Stage work and atomically publish events/provenance/revision.
- Preserve prior accepted contributions on failed reads and distinguish disable/remove/rebuild operations. Keep real/demo namespaces separate.
- Serialize writers, use consistent reads, enforce foreign keys, version migrations, and test database-consistent backup/recovery. Retain metadata needed to rebuild advertised history.
- Keep exact decimal aggregation/sorting correct; SQLite decimal text must not be summed or ordered as authoritative numeric SQL without a proven representation.

Gate: repeated import, restart, copies, truncation, interrupted writes, repricing, migration failure, and source disappearance have tested outcomes; indexed results equal the corrected shared service for the same query.

### S12 — Implement the versioned local API and job lifecycle

Factors: F4, F5, F7. Dependencies: S11 and stable machine-readable DTO/schema fixtures.

- Implement the first-release `/api/v1` subset from the integration contract, with integer-string counters, decimal-string money, bounded input, and safe error codes.
- Freeze resolved range, dataset, normalized filters, usage/pricing/configuration versions in query contexts. Preserve them across facets/pages/details; refresh related widgets together after a revision conflict.
- Add stable cursor semantics, consistent full-result summaries, and operation status for reindex/repricing. Persisted settings and active computed results are distinct states.
- Share one process owner/writer/provider scheduler across tray, tabs, and repeated launches. Route reads consume cached provider state and never initiate network polling implicitly.
- Implement same-origin loopback authentication/bootstrap, Host/Origin checks, read authorization, and anti-CSRF mutation protection. Keep credentials and durable secrets out of client bundles/browser storage/URLs.

Gate: contract, filter, pagination, time-drift, version-conflict, jobs, concurrent-launch, and hostile-origin tests pass. Usage remains queryable when a provider is offline.

### S13 — Integrate the reviewed dashboard flow

Factors: F9, F10. Dependencies: S12; relevant design/flow reviewed. Full visual refinement remains a separate user-directed activity.

- Deliver the thin month/provider → summary → conversation → Back flow before expanding every screen. Preserve query state, cursor, and list position.
- Use shared query data, discard obsolete responses, and show price coverage/assumptions near the headline. Every enabled control must have a supported action or explicit preview limitation.
- Keep live Limits separate from report periods and account scope. Settings use draft/Save/Cancel with persistence/conflict outcomes.
- Support keyboard/focus and narrow desktop behavior. Extra themes, rich Projects screens, arbitrary ranges, and full phone flows remain later work unless specifically included.
- Add an explicit tray action for the dashboard while preserving terminal access. Reinspect Figma nodes before editing; inherited node IDs are not current verification.

Gate: fixture and controlled local-data flows reconcile through detail; Back and refresh recover coherently; no browser-side authoritative valuation or automatic demo substitution exists.

### S14 — Validate packaged hub delivery

Factors: F5, F6, F7, F8. Dependencies: S11–S13.

- Package local frontend assets, API runtime, timezone data, migrations, and configuration discovery. Verify an offline launch without development servers or network-hosted assets.
- Exercise first launch, second launch reuse, explicit dashboard open, terminal output, multiple tabs, browser close, app Quit, interrupted jobs, and restart recovery.
- Test local session/bootstrap boundaries and safe diagnostics in the packaged runtime, not only the development server.
- Measure Overview/Explore query time on a documented fixture/machine; the initial integration target is under two seconds without waiting on live provider calls. Report findings rather than a universal guarantee.

Gate: the hub's executable, contract, privacy checks, migration recovery, and end-to-end flow agree. Preserve a working core path if optional integration fails.

## 9. Verification commands and evidence rules

Run from the repository root in PowerShell. Use the existing project interpreter when present. The workspace-local temporary directory avoids the fixture-write permissions issue observed with the sandbox's default temporary directory.

```powershell
$refinementTemp = Join-Path $PWD 'windows\build\refinement-temp'
New-Item -ItemType Directory -Path $refinementTemp -Force | Out-Null
$env:TEMP = $refinementTemp
$env:TMP = $refinementTemp
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -v
```

Run focused tests while developing; run the relevant full suite after the coherent change is ready. Existing commands, before any module renaming, include:

```powershell
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -p test_reports.py -v
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -p test_usage.py -v
.\windows\.venv\Scripts\python.exe docs/review_accounting_probes.py
git diff --check
```

For the probes, inspect every printed comparison. The current script exits successfully even when `matches_expected` is false. S02 must add assertions in the normal regression suite; do not merely change expected values to match incorrect output.

Run packaging only when relevant behavior/dependencies change or at a release gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build.ps1
```

The expected build artifact is `windows/dist/UsageTray.exe`; generated artifacts are not source evidence. If the environment is missing, follow `windows/README.md` rather than silently testing an unrelated interpreter. Record an unavailable check honestly. On Windows, validate resolved targets before any recursive cleanup/move, and keep file operations within the intended workspace/application-owned location.

## 10. Progress ledger and handoff template

Current main-branch core status: **S00 complete; S01–S14 not_started here**. October 24 commit follow-up found S01-S07 recorded complete in the isolated `codex/s01-observation-contracts` branch through `461c3a3`; those commits are not merged here. Preserve that work and verify combined integration rather than restarting those sessions. Dashboard and pre-S08/database preparation are tracked separately below and do not complete core/hub gates.

Create one entry per session and update it when work changes:

```markdown
### Session Sxx — Name
Status: not_started | in_progress | complete | blocked
Scope and factors:
Starting commit / relevant local changes:
Decisions and rationale:
Files changed:
Checks run and actual outcomes:
Acceptance gate evidence:
Remaining issues / explicit limitations:
Next session ready / unresolved dependency:
```

Decisions requiring an entry when implemented: canonical observation/epoch identity; partial-source policy; tier uncertainty; money representation/rounding; configuration location/precedence; period compatibility; runtime ownership; and, only on the optional track, database placement/schema/authentication/migrations.

Do not include raw source lines, transcript text, credentials, or identifying user-history examples in the ledger. Use synthetic fixtures and sanitized summaries.

### Publication verification — existing Windows updates and Figma handoff

- Scope: publish previously completed local terminal-report, monthly comparison, model-rate, packaging, and Figma documentation changes. This is not completion of S00–S14.
- Starting commit: `0dde414`, with the Windows changes and Figma documentation still local.
- Files: `windows/usage_reports.py`, `windows/usage_tray.py`, `windows/tests/test_reports.py`, `windows/build.ps1`, `windows/README.md`, `docs/usage-hub-integration-plan.md`, `docs/usage-hub-figma-test-report.md`, and this ledger.
- Checks: the full `unittest discover -s windows/tests` suite passed all 57 tests using workspace-local TEMP/TMP. Documentation links, JSON examples, code fences, whitespace, and `git diff --check` passed.
- Packaging: `powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build.ps1` succeeded using installed dependencies with `PIP_NO_INDEX=1`. The packaged executable's hidden offline `--report month --demo --output ...` smoke check passed: 108,000 tokens, USD 0.2658 estimated API value, and the month-to-date comparison. Generated binaries remain outside the source commit.
- Limits: the independent accounting probes still produce 300 instead of 200 for truncated-first overlap and 200 instead of 250 for the reset case. These remain open S02 gates. The Figma report is carried forward from its authoring work; this publication check did not repeat its Figma inspection/playback.
- Next: S00 baseline/decision capture, then S01/S02 reconciliation; no refinement-session gate is marked complete by publication alone.

### Figma workflow integration — October 23, 2026

- Scope: apply the installed Figma skills to the existing repository instructions and check compatibility with the core plan. This is a workflow update, not implementation of the dashboard or completion of S00-S14.
- Starting state: clean working tree at `810b3a8`; no database schema, API, or browser frontend was found in the tracked project inventory.
- Decision: keep one repository-wide `AGENTS.md`; reference installed skills instead of copying their API guidance. Core/session gates and the integration contract remain authoritative for accounting and data semantics. Figma remains the visual/interaction reference, including the confirmed token-format and chart-axis rules.
- Files changed: `AGENTS.md` and this ledger. Python, tray behavior, packaging, and the Figma design were not changed.
- Checks: `windows/.venv/Scripts/python.exe -m unittest discover -s windows/tests` passed all 57 tests with workspace-local TEMP/TMP (`windows/build/refinement-temp`). `docs/review_accounting_probes.py` still reported overlap truncated-first **300 vs expected 200**, complete-first **200 vs expected 200**, and reset **200 vs expected 250**. Its successful exit is not a passing accounting gate.
- Figma reference check: the connected plugin returned current metadata for page `0:1` in file `6Axot2OcYiKcSfGYcLh3Jh`, confirming Overview `2:43` with the current token labels and labeled chart axes. This was a read-only structure check, not design implementation or presentation playback.
- Verification: local Markdown links and `git diff --check` passed after the documentation edits. No runtime implementation or new API was tested by this update.
- Remaining limits / next dependency: the two S02 defects remain open. S00 baseline/decision capture is the next core implementation session, followed by S01/S02; optional real-data hub integration still follows the later gates and inspection of any separately developed database.

### Session S00 — Capture the baseline and establish the work ledger

- Status: **complete**. Scope: F1/F6/F9 baseline and implementation decisions; no application behavior changes.
- Starting commit / local changes: `810b3a8`, `main...origin/main`, clean working tree. Repository-wide AGENTS.md read; Windows source, tests, build, and CLI inventoried.
- Decisions and rationale: [S00 baseline and handoff](s00-baseline.md) records D00-1 conservative observation-first overlap/reset handling, D00-2 visible request-tier assumptions, D00-3 per-user settings location and invocation-only override precedence, and D00-4 compatibility/session boundaries. Concrete identity algorithms remain S01/S02 work.
- Files changed: `docs/s00-baseline.md` and this plan. Generated demo/temp artifacts remain ignored.
- Concurrent changes: separate Figma workflow additions appeared in `AGENTS.md` and this ledger after S00's initial clean-status check. Updated instructions were read and those additions preserved; they are not S00-authored work.
- Checks: project Python 3.14.5; fresh full suite passed **57 tests in 7.527 seconds**. Probes reproduced truncated-first overlap **300 vs expected 200**, complete-first **200 vs 200**, and reset **200 vs expected 250**. Inspected every comparison rather than trusting exit zero. `--help` inventory matched source.
- Packaged check: existing executable's hidden offline month-demo saved report exited 0 and contained DEMO, 108,000 tokens, USD 0.2658, and the monthly comparison. Source was unchanged, so no rebuild was run. Interactive launch behavior remains source/test evidence rather than a fresh manual check.
- Acceptance gate: actual baseline and known failures reproduced; public options/periods/providers/packaged branches recorded; next-session invariants and scope explicit. Changed documentation links/fences/whitespace and `git diff --check` passed.
- Limitations: both accounting defects remain open; no real-log/account, macOS, CI, price-verification, or interactive lifecycle checks were run. S00 completion does not raise runtime maturity scores.
- Next ready: **S01 observation/canonical-event contracts**. S02 requires that seam and regression assertions before fixing deltas. No unresolved S00 decision blocks S01.

### Dashboard development slice — October 23, 2026

- Status: **in_progress** for dashboard integration; no S01-S14 gate is completed by this preview. See the [implementation and core handoff](dashboard-implementation.md).
- Starting state: clean commit `854ac73`, S00 complete. Concurrent S01 record/observation contracts and reader changes appeared during work and were preserved. A provisional accounting fix was withdrawn to avoid competing with that core session; the two S02 invariants remain open.
- Scope/decision: implement the reviewed Figma first slice as an explicit demo-only local development preview while core refinement continues. This permits UI/adapter verification without treating unfinished core results as trusted real data. No database or migrations were introduced; existing database work still needs inspection before integration. This development-scope deviation does not waive S11-S14 dependencies or release gates.
- Files: new `windows/dashboard/` UI/assets/formatter tests; `windows/usage_hub.py`, `usage_value.py`, `dashboard_main.py`, `tests/test_hub.py`, and `tests/packaged_dashboard_smoke.py`; changes to `usage_tray.py`, `requirements.txt`, `build.ps1`, `windows/README.md`, this ledger, and the linked handoff. Changes in `usage_reports.py`, `usage_records.py`, `usage_observations.py`, and `test_observations.py` belong to the concurrent core work, not this slice.
- Evidence: demo totals reconcile to Figma (8,920,000 tokens / USD 49.506 / 12 conversations / four projects); Python query/HTTP tests and Node formatter/axis tests pass. Actual browser interactions cover provider selection, metric/day drill-down, detail/Back, pagination, no-match search/recovery, and help/keyboard shortcuts. Narrow-width and original local SVG/font checks were performed.
- Packaging: the existing Windows build script succeeded with bundled dashboard assets and timezone data. Executable smoke checks passed for demo API totals, named timezone, local assets/fonts, and the preserved offline terminal month-demo report. Build and smoke success do not certify interactive packaged lifecycle or real-data accounting.
- Limitations/next: real-data CLI launch remains gated; Settings is read-only; Limits is sample data in demo mode. Exact preview valuation still needs S04/S05 consolidation into the authoritative core service. Persistent index/API, database handoff, full runtime ownership, and S09/S14 release gates remain outstanding. Detailed check counts and final verification outcomes are recorded in the handoff.
- Commit isolation: the staged dashboard snapshot passed 66 Python tests and two Node tests against the committed core baseline, plus JavaScript syntax and staged whitespace checks. Concurrent core files were excluded from the dashboard commit. The earlier 80-test working-tree run includes those separate core tests; neither result completes a core gate.

### Pre-S08 privacy regression preparation — October 24, 2026

- Status: preparation **complete**; S08 remains **not_started**, dependent on S05-S07. Scope: independent synthetic privacy fixtures and repair handoff while another agent owns S04. This does not certify the pending earlier gates.
- Starting commit / concurrency: `0f4ce44`. Existing edits in `usage_reports.py` and untracked observation/record modules and tests belong to other core work and were preserved/excluded. No production file, pricing, Figma, schema, credential, or scheduler changes.
- Files: `windows/tests/privacy_cases.py`, `windows/tests/test_privacy.py`, `docs/review_privacy_probes.py`, this ledger, and the [pre-S08 handoff](pre-s08-privacy-handoff.md).
- Findings: legacy Codex and Claude readers stringify nested invalid metadata into public outputs; live Codex limit labels retain terminal controls. Typed metadata projection and live-display sanitization are deferred to the owning core/runtime boundaries. Existing HTML escaping, normal-content exclusion, report terminal sanitization, and fixed preview diagnostics gained executable boundary evidence.
- Evidence: focused run executed eight tests (five passes, three explicit expected failures). Full working-tree run executed 88 tests in 9.004 seconds (85 passes, three expected failures). Loopback tests passed outside the network-restricted sandbox. The independent privacy probe exited **1**, correctly identifying all three unresolved cases; expected failures are open defects, not S08 acceptance evidence. No packaging run was needed for test/documentation-only changes.
- Commit isolation: the staged snapshot ran 74 Python tests in 8.446 seconds (71 passes, three expected failures) against the committed core, excluding concurrent edits; the strict probe reproduced all three gaps with exit 1. Both Node formatter/axis tests, staged whitespace, and changed-document links/fences passed.
- Next dependency: finish S04, then S05-S07; resolve the three findings and remove expected-failure annotations before completing S08. Remaining paths and release limits are explicit in the handoff. No core session gate was advanced by this preparation.

### Local database mapping preparation — October 24, 2026

- Status: preparation **complete**; S11 implementation remains **not_started** and gated by the core through S09. Starting commit: `446e2e0`. User confirmed local-first scope and authorized commit/push of this handoff.
- Discovery: bounded schema/configuration filename searches across this checkout, local branches/worktrees, nearby development folders/saved local project locations, and the application-data location found no Usage Hub database. A separate planner's schema was not reused. No database contents, credentials, or real histories were read.
- Branch distinction: S01-S03 commits through `b9495f0` exist in `codex/s01-observation-contracts`, where S04 is active; they are not merged here. Existing shared-checkout core edits remain preserved and excluded. This entry does not certify or merge the other branch's gates.
- Decision: plan a per-user local SQLite adapter at S11, retain S06 settings-file authority, and map database settings as versioned projections. Physical DDL/migrations and final S04 numeric adapters remain pending. No runtime/database/package changes or duplicate configuration defaults were introduced.
- Files: [database mapping handoff](usage-hub-database-handoff.md), [synthetic fixture](fixtures/usage-hub-database-alignment.json), a cross-reference in the integration contract, and this ledger. Mapping covers entity/key ownership, exact numerics, import/repricing/publication, frozen reads, source retention, migration/backup recovery, privacy gates, and current preview discrepancies.
- Checks: independent project-Python JSON/Decimal/zoneinfo validation passed for duplicate keys, integer/decimal wire types, bounded fixture counts, category/total arithmetic, reasoning subset/coverage, half-even event values, provider/full summaries, signed full-fee differences, frozen UTC/local-day buckets, exact ordering, IDs and source references. Changed-document local links, fences, whitespace, and `git diff --check` passed. No database, API, migration, reconciliation, application-suite, or packaged-runtime check is claimed by this documentation/fixture-only preparation.
- Next dependency: finish and integrate the core branch with combined validation, then S11 actual schema/adapter implementation and its persisted-fixture gates; S12/S13 consume that result. No core or hub gate advanced from example validation.

### Automatic collection scope clarification — October 24, 2026

- Scope: user requests automatic account usage collection if feasible, otherwise local recorded usage; ordinary conversations remain excluded. Added the policy and fallback to the [database handoff](usage-hub-database-handoff.md#automatic-collection-scope--october-24-clarification).
- Evidence: official app-server documentation describes `account/usage/read`; installed `codex-cli 0.163.0` generated a protocol schema declaring it without the experimental flag. Generation used an isolated temporary `CODEX_HOME`, without opening real histories or credentials. Initial version/help commands emitted sandbox temp-directory permission warnings; isolated schema generation succeeded.
- Limits: no authenticated account response or product-scope check, no production/scheduler/database change, no persistent automation, and no core gate advanced. Local detailed usage remains authoritative; account snapshots must stay separate and fall back without blocking offline views. Ordinary-chat exclusion must be established before enabling account token activity. Next dependency remains the existing core/runtime/index integration gates.
- Validation: documentation-only clarification; whitespace and local-link checks recorded after editing. No application-suite or packaging run is required or claimed.

### S05 dashboard integration review and interaction repairs — October 24, 2026

- Status: independent review/repair **complete**; no core or real-data hub gate advanced. Pinned completed S05 at `97b6070`, S04 at `15219d5`; the other agent owns S06. No changes to its worktree, shared core edits, configuration, database, Figma or account access.
- Files: [S05 dashboard handoff](s05-dashboard-integration-review.md), links/status updates in dashboard/database handoffs and this ledger, `windows/dashboard/app.js`, `windows/dashboard/tests/interaction.test.mjs`, and the Node command in `windows/README.md`. Earlier automatic-collection clarification remains in the working tree.
- Review decisions: replace preview valuation/aggregation/comparison with the core's authoritative result; retain full canonical IDs and frozen inputs; explicitly adapt multi-project membership, provider-scoped project groups, 200-character model-inclusive search, reasoning coverage, independent quality dimensions, exact numeric bounds/serialization and money display. S05 supplies no persisted dataset/revision, API query token/cursor, self-excluding facets or restart recovery; these remain integration work.
- Repairs: pending searches could restore cleared filters or run after leaving Explore; global `/` navigated behind an open shortcut dialog. Cancel pending timers on navigation/history/rescan and let the native modal own keyboard handling. Three new handler/timer simulation regressions failed before the repair and passed afterward; with existing formatter/axis tests, **five Node tests passed**. `node --check windows/dashboard/app.js` passed.
- Core review evidence: exported committed `97b6070` into ignored `windows/build/s05-dashboard-review/snapshot` without copying active S06 edits. The project interpreter ran its **24 service tests in 3.027 seconds**, all passing. This is focused committed-contract evidence, not combined integration or a fresh S05 release certification.
- Current-checkout checks: focused **9 hub tests in 5.179 seconds** passed; full **88 Python tests in 15.434 seconds** completed with **85 passes and the same three expected privacy failures**. This includes concurrent observation tests; it is not an isolated main-baseline certification. Loopback HTTP checks ran outside the socket-restricted sandbox. Privacy defects remain open.
- Actual browser evidence: reproduced clear-search and modal defects before editing; after reload, pending clear remained empty, `/` stayed within the dialog, Escape closed it with focus returning to its opener. Claude selection yielded **3.02M / USD 20.766**; token-axis labels ran **0–2.5M**, with the largest matched daily column **1.9M**. Keyboard Enter opened that day: **two conversations / USD 14.750**, whose rows reconcile **830,000 + 1,070,000** tokens and **6.300 + 8.450 USD**. Detail matched its row; Back retained provider/metric/day and focused main content. At **390 × 844**, page width stayed within the viewport and the wide table scrolled internally. The viewport was reset; browser error/warning inspection was empty. A synthetic screenshot is saved outside the repo in the chat artifact directory.
- Final documentation checks: `git diff --check` passed; five changed documents had **33 existing local link targets** and balanced code fences. Generated snapshot/test files remain ignored and outside source deliverables.
- Limits/next: no new real-history/account, persistence, v1 API, packaged build/lifecycle, native Figma playback or full accessibility certification. Error recovery beyond the existing tests was not newly fault-injected in the browser. Complete S06-S09 and combined integration before S11-S13 adapters. The preview remains demo-only; terminal/tray behavior and other-agent edits are preserved.

### Dashboard exact display and failure recovery — October 24, 2026

- Status: independent demo-preview slice **complete** while the other agent owns S07. Starting main `70dde1f`, retaining the previous uncommitted dashboard review/interaction repairs and shared core edits. Separate core S06 is committed at `6a29b00`; no core branch, settings, provider, process owner, database, account or Figma changes here. No session gate advances.
- Overlap guard: [resilience handoff and coverage inventory](dashboard-resilience-handoff.md) distinguishes the prior ordinary interaction review from these new failure paths, lists owned files and future dependencies, and provides reproduction commands. Existing three interaction tests are retained and share the new harness. Read both dashboard reviews before assigning further frontend work; reuse completed checks rather than treating them as a new session.
- Changed files: `windows/dashboard/app.js`, `format.js`, initial `index.html` badge, `tests/format.test.mjs`, retained `tests/interaction.test.mjs`, new `tests/dashboard-harness.mjs`, `tests/recovery.test.mjs`, test-only `windows/tests/dashboard_fault_server.py`, this ledger, dashboard/S05 handoff cross-references and Windows README test guidance.
- Changes: BigInt decimal-string USD display with half-even rounding and signed comparisons, including full-bound carry, tiny differences and legacy exponent fee strings; visible loading, previous-result/filter/URL restoration with explicit GET Retry, one fresh-revision retry, last-result preservation when rescan succeeds but query fails, duplicate pending-rescan guard, superseded/modal-safe focus and neutral initial failure labels. Approximate chart geometry/ticks remain separate from exact labels and do not calculate accounting.
- Test evidence: initial eight recovery cases produced **two passes / six failures** against the unfixed app. Final Node suite: **20 passed** (five retained, fifteen new). While adding legacy exponent compatibility, one intermediate run failed on duplicate local declarations; renamed the display variables and reran all 20 successfully. App/formatter syntax and Python fault-driver AST parse passed. Current working-tree Python suite: **88 in 10.802 seconds, 85 passes / three existing expected privacy failures**, with workspace-local TEMP/TMP and loopback access. This includes shared concurrent observation edits, not an isolated/main-plus-S06 integration certification. The final subsequent source adjustment only expanded the JS formatter compatibility/sign assertions; the Node suite was rerun for it.
- Actual browser evidence: synthetic 503 restored matching old filters/results, keyboard Retry applied the failed provider; initial 503 displayed unavailable/neutral preview state and GET Retry recovered; held request hid old rows and completion preserved native modal Close focus; two 409s stopped after one retry, leaving a third queued action untouched; a released older request did not overwrite newer Settings or focus; failed detail then keyboard Retry/Back retained Claude parent context. Banner screenshot was visually inspected; browser warning/error inspection returned none. No broad repeat of ordinary chart/day/narrow-layout checks is claimed.
- Limits/next: test driver is opt-in, demo-only, outside application entry points and packaging; control artifacts stay ignored. No fresh executable build, packaged lifecycle, real history/account, core privacy certification, complete accessibility audit, v1 API or persistence validation. All three expected privacy failures remain open. Keep S07 ownership with the other agent, then S08/S09; S11-S14 and combined branch validation remain prerequisites for real data. No commit or push requested/performed in this slice.
- Evidence-driven scope extension: the held-query browser case printed a server `ConnectionAbortedError`, followed by an attempted second reply. Updated only `windows/usage_hub.py` response writes to close quietly on broken-pipe/reset/aborted sockets; API contracts/security/provider runtime stay unchanged. Added one `windows/tests/test_hub.py` test with six controlled header/body failure combinations. Corrected a missing request-line field in its initial setup, then confirmed all six real write failures before fixing production behavior. Focused **10 hub tests passed in 2.827 seconds**; final full suite **89 in 13.664 seconds, 86 passes / the same three expected privacy failures**. Repeated only the actual browser cancellation case against the corrected server; Settings/focus/busy stayed correct and server output contained no traceback. Browser tabs/test servers stopped. Five documentation files have **38 existing local file link targets**, balanced fences and passing whitespace checks.

### Dashboard commit and completed S07 handoff — October 24, 2026

- Scope: user requested a local commit of the completed dashboard work and the next independent session. Included the previous dashboard review/interaction repairs, exact formatting/recovery slice and their documentation; preserved the separate `usage_reports.py`, observation/record modules and observation tests without staging them. No push or core-branch merge authorized/performed.
- Commit isolation: exported the exact staged index to ignored `windows/build/dashboard-commit-verify/snapshot`, excluding all untracked/shared core edits. It passed **20 Node tests** and **75 Python tests in 16.211 seconds: 72 passes / the same three expected privacy failures**. Loopback tests used the project interpreter, workspace-local TEMP/TMP and required socket access. This differs from the prior mixed-checkout 89-test run; no integration or privacy certification is inferred. Six changed Markdown documents have **45 existing local file link targets**, balanced fences and passing whitespace checks; staged `git diff --check` passed. No source changed after snapshot validation; only this documentation entry was added.
- S07 evidence review: committed `461c3a3` on the isolated refinement branch records S00-S07 complete, 226 full tests/build and 23 packaged scenarios, with native tray playback and remaining privacy/release limits explicitly unverified. Those results were read, not rerun here. Main still does not contain those core commits.
- Next independent session: **S08 privacy, safe rendering and diagnostic verification against committed S07**. Reuse the existing pre-S08 sentinels/probe and new dashboard coverage inventory; first determine which legacy privacy findings reproduce on the refined core, then fix only confirmed gaps and review expected-failure markers. Verify allowlisted metadata and sanitized text/HTML/service/runtime diagnostics without duplicating the ordinary dashboard interaction review. S09 follows a passing S08 gate; real-data index/API/dashboard integration remains S11-S14.

## 11. Completion and reassessment

- **Core complete:** S00–S09 gates pass; terminal functionality remains available; known accounting defects have regression coverage and correct outcomes.
- **Expression complete:** S10's usability and reconciliation checks pass after interface work is requested.
- **Hub complete:** the explicitly scoped S11–S14 gates pass; plans/Figma alone do not count as runtime integration.
- **Factor reassessment:** revisit F1–F10 using linked tests, runtime checks, and remaining limitations. Keep weights stable or explain a scope-driven change. Do not raise the score just to hit a target number.

Recommended next core implementation unit: **S08 privacy, rendering and diagnostic verification against committed S07**, then S09. S01-S07 already have commits in the isolated refinement branch; their integration into this branch needs combined validation. Independent dashboard resilience work is complete for the demo preview; consult its coverage inventory before more frontend work. Local database mapping and dashboard preparation do not complete S11, which still requires the core gates through S09.
