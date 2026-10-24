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

Current status in this isolated worktree: **S00–S08 complete; S09–S14 not_started**. S01–S08 have not been integrated into the separate original checkout. Earlier reviews, tests, pricing fixes, and documentation are baseline evidence; they do not automatically complete the broader session gates. Some tasks may already be satisfied when implementation begins; verify and record that evidence rather than repeating work unnecessarily.

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

### Session S01 — Observation and canonical-event contracts

- Status: **complete in the isolated S01 worktree**. Scope: F2/F4 metadata evidence, compatible shared records, canonical acceptance contract, and independent reconciliation input; no accounting correction or UI expansion.
- Starting commit: `854ac73` after committing S00 and existing workflow documentation. Concurrent changes later modified the same shared reader and introduced a different observation/reconciliation contract. Those edits were preserved. S01 was reconstructed against the committed base in an isolated snapshot, then continued in the managed `s01-observation-contracts` worktree.
- Decisions/rationale: [S01 contract and mapping policy](s01-observation-contracts.md) separates unknown/invalid/zero counters, source-local observations from global events, provider IDs from weak source surrogates, and context capacity from request evidence. Canonical IDs include reconciled epoch/event anchors, not copy provenance. Concrete reconciliation is still S02 work.
- Files changed: `windows/usage_records.py`, `windows/usage_observations.py`, `windows/usage_reports.py`, `windows/tests/test_observations.py`, `docs/s01-observation-contracts.md`, and this ledger. Existing `Record`/`Tokens` import names and reader acceptance remain compatible in this worktree. The temporary parallel extraction seam avoids prematurely replacing the known-buggy reader with an unverified algorithm.
- Checks: first shared-checkout focused run passed 13/14 with one import error caused by the competing `reconcile_codex` change; it is not reported as a passing run. Isolated snapshot then passed 14 focused/71 full tests. After final contract additions, managed worktree passed **16 focused** tests and **73 full tests in 6.293 seconds** via the build script.
- Packaging: `powershell -NoProfile -ExecutionPolicy Bypass -File windows/build.ps1` succeeded with `PIP_NO_INDEX=1` and the existing project environment reused through an ignored junction. Fresh executable's hidden offline `--report month --demo --output ...` check exited 0 and verified DEMO, 108,000 tokens, USD 0.2658, and month comparison.
- Probe outcomes: truncated-first overlap still **300 vs expected 200**; complete-first **200 vs 200**; reset still **200 vs expected 250**. No S02 accounting gate is claimed complete. Documentation links/fences/whitespace and `git diff --check` passed.
- Acceptance evidence: pure extraction/grouping imports without GUI/providers/pricing; both providers retain source/ID/context/counter evidence; privacy sentinels are absent from projected serialization; source physical positions survive malformed/blank lines; accepted IDs ignore copy provenance and distinguish epochs; legacy token/metadata fixtures remain passing.
- Limits: original mixed checkout is not validated or integrated by these checks. Verified file generations/recovery, partial-scan quality, exact valuation, and request-context tier policy remain later sessions. No real-log/live-account, interactive lifecycle, macOS, Figma, or CI check was run.
- Next ready: **S02** against this worktree's seam. Shared-checkout integration requires resolving the competing contract and rerunning its combined gates; preserve all concurrent changes meanwhile.

### Session S02 — Overlap reconciliation and reset epochs

- Status: **complete in the isolated refinement worktree**. Scope: F2/F6 correctness; no interface/storage expansion. Started clean at `e23f62f` on `codex/s01-observation-contracts`.
- Implementation: both readers now extract all eligible observations before pure reconciliation and compatible Record projection. Added canonical event/source mappings, explicit accounting issues, source-supported equal-time ordering, reset epochs, conservative gap/fork baselines, metadata qualifications, and labeled last-usage behavior. Claude stream maxima preserve effort and resolve legacy/detailed cache-write representation before aggregation.
- Decisions and limits: [S02 policy and handoff](s02-reconciliation.md) specifies supported equivalence/order evidence, tied/cyclic exclusions, zero-origin assumption, fork handling, mixed last-only exclusions, and metadata conflicts. This is an accounting issue layer; general ingestion completeness/recovery/time remains S03. Unknown excluded work stays null.
- Files changed: `windows/usage_reconciliation.py`, `windows/usage_observations.py`, `windows/usage_reports.py`, `windows/tests/test_reconciliation.py`, `windows/tests/test_observations.py`, `windows/README.md`, `docs/s02-reconciliation.md`, `docs/s01-observation-contracts.md`, and this ledger.
- Regression sequence: two mandatory tests were added/run first and reproduced 300 vs 200 and the lost final reset increment. Final focused suites passed **28 reconciliation** and **16 observation** tests. The provenance-only observation fixture was made non-fork; dedicated tests now enforce missing-fork-baseline exclusions rather than preserving accidental legacy counting.
- Full verification: **101 tests passed in 6.445 seconds** via `windows/build.ps1`; build succeeded on project Python 3.14.5 with installed pinned dependencies and `PIP_NO_INDEX=1`, using workspace-local `windows/build/s02-temp`.
- Independent probes: **200/200**, **200/200**, **250/250**, all `matches_expected=true`; inspected output rather than relying on zero exit.
- Packaged acceptance: fresh executable read controlled synthetic overlapping/reset logs in text and HTML modes; each exited 0 with **250** tokens, rounded **USD 0.0006**, and a reset notice, without demo substitution. Separate demo remained **108,000** tokens / **USD 0.2658**, clearly labeled. No user logs/credentials or live providers were used.
- Gate evidence: copies/root orders/reimports are invariant; reset-to-repeated values and fork baselines retain supported increments; ambiguous ties/conflicts are deterministic and visible; legacy report/provider suites have no unexplained regression. Documentation links/fences/whitespace and `git diff --check` passed.
- Remaining limits: conservative exclusions do not certify full histories; file generation/recovery/mtime filtering, structured scan completeness, named-zone boundaries, and exact versioned valuation remain later gates. No interactive tray/lifecycle, real-account/history, macOS, Figma, or CI check. Original checkout untouched; no merge or remote publication.
- Next ready: **S03 source quality, recovery, and time**, preserving S02 accounting invariants. Shared-checkout integration still needs an explicit owner and combined validation.

### Session S03 — Source quality, recovery, and time

- Status: **complete in the isolated refinement worktree**. Scope: F2/F5/F6 source integrity and range semantics. Started clean at `82f2b5f` on `codex/s01-observation-contracts`; the original checkout was not changed.
- Implementation: added headless structured scan results/codes/counts, verified file-prefix generations and bounded mutation retries, strict decoding, complete-EOF versus incomplete-final-line handling, conservative corruption suffix deferral, and discovery independent of mtime. Reports retain separate scan and accounting issues and display source quality without claiming full account coverage.
- Decisions: [S03 policy and handoff](s03-source-quality-and-time.md) documents prefix verification limits and the absence of a retained committed dataset. A failed fresh scan remains failed; automatic retained-stale publication remains conditional on S11 persistence. Malformed complete metadata defers the following file suffix because identity/context may be missing; excluded amounts stay unknown.
- Time migration: one captured UTC `[start, end)` per provider with named-zone local day/month boundaries, default `America/Los_Angeles`, consistent daily groups/renderers, explicit `--timezone`, trailing 168-hour week, and preserved provider-specific five-hour sessions. Legacy inclusive-end and host-local calendar behavior are deliberately replaced, with compatibility projections retained. Pinned installed `tzdata==2026.2` and bundled it for offline Windows rules.
- Files changed: `windows/usage_ingestion.py`, `windows/usage_time.py`, `windows/usage_reports.py`, `windows/usage_tray.py`, `windows/tests/test_ingestion.py`, `windows/tests/test_time.py`, `windows/tests/test_observations.py`, `windows/tests/test_reports.py`, `windows/requirements.txt`, `windows/build.ps1`, `windows/README.md`, `docs/s03-source-quality-and-time.md`, and this ledger.
- Focused checks: **25 ingestion**, **10 range/CLI**, and existing **35 report** tests passed. Controlled fixtures cover append, physical truncation and same-size mutation, replacement identity mismatch during read, real replacement between scans, repeated instability, unreadable source/root/subfolder, malformed/partial EOF, strict UTF-8/privacy, missing IDs/counters, old-mtime baselines, duplicate roots, midnight/month changes, both DST transitions, exact ends, provider ranges and captured-clock/daily reconciliation.
- Regression correction: independent probes exposed a too-strict first draft that deferred complete JSON without final LF (100/100/200). Corrected EOF compatibility; all final printed comparisons returned **200/200**, **200/200**, **250/250**, `matches_expected=true`. Their successful exit alone is not a passing gate.
- Full/build verification: the initial build passed 134 tests in 10.104 seconds. After final BOM/CRLF compatibility and byte-verification fixtures, the final `windows/build.ps1` passed **136 tests in 7.692 seconds** and rebuilt the executable on project Python 3.14.5 using installed dependencies (`PIP_NO_INDEX=1`, workspace-local TEMP/TMP). Two legacy expectations now use the named zone rather than host-local time. Byte-level mutation with a restored mtime is rejected/retried; UTF-8 BOM plus a blank first physical line retains correct positions.
- Source/document checks: changed Python syntax, three Markdown files with 13 local links, balanced fences/whitespace, and `git diff --check` passed. Generated build/dist/temp files and reused environment remain ignored.
- Packaged acceptance: fresh hidden executable, controlled synthetic roots only, with `PYTHONTZPATH` pointing to an empty directory to force bundled tzdata fallback. Both text/HTML yielded **200 tokens in America/Los_Angeles** and **100 in UTC** for the same today fixture, with end-exclusive labels and partial/corruption counts. Old-mtime data and a complete EOF copy were included; corrupt suffix content/sentinel stayed out of the reports. All four exited 0. Separate month demo exited 0 with **108,000 tokens / USD 0.2658**, labeled DEMO.
- Gate evidence: quality and exclusions remain distinguishable; failed scans do not become empty successes/demo; supported prefixes recover deterministically; S02 invariants and DST/end-boundary accounting are preserved. Existing reader/Record and terminal/tray entry points remain compatible.
- Limits: no durable retained history, global filesystem transaction, large-history benchmark, live provider/user-history, interactive tray lifecycle, macOS, Figma or remote CI checks. Full-file scan memory/performance remains explicit. Source quality is not price coverage; exact money/tier/comparison policy remains S04. No merge, push or external publication.
- Next ready: **S04 exact/versioned/explainable valuation**, preserving accepted events, structured issues and captured range context. Shared-checkout integration still requires combined validation of its separate concurrent work.

### Session S04 — Exact, versioned, explainable valuation

- Status: **complete** in the isolated refinement worktree. Scope: F3/F6; started clean at `b9495f0`. The user additionally authorized committing and pushing after completion; no merge into the separately developed original checkout is included.
- Decisions: [S04 arithmetic/provenance/comparison policy](s04-exact-valuation.md) defines signed-64-bit token/count bounds, rate/fee bounds and scale, 80-digit local arithmetic, half-even quantization once per event to 12 USD fractional digits, exact aggregation, version hashes and immutable catalog snapshots. Retains existing rate amounts/2026-10-23 checked date without a fresh price-verification claim.
- Implementation: pure `usage_valuation.py` supplies event valuations, coverage summaries and structured signed fee comparisons. Reports retain accepted events/context and use one valuation view per render; compatibility `estimate` remains a float projection unused by either renderer. Decimal JSON rates/CLI fees and one temporary USD 20/20 default source replace authoritative float paths.
- Intentional corrections: missing optional cache-write rates stay unconfigured; a used missing category makes the event unpriced, while explicit zero stays priced. Tiered events lacking request context retain the existing per-event counter tier policy with an assumption flag; capacity, aggregate totals and effort never establish context. Legacy TTL qualifications survive report projection. Calendar-month range/filter validation and selected-provider completeness replace unconditional savings labels with signed qualified differences.
- Files: `windows/usage_valuation.py`, `windows/usage_reports.py`, `windows/usage_tray.py`, `windows/tests/test_valuation.py`, `windows/tests/test_reports.py`, `windows/README.md`, `docs/s04-exact-valuation.md`, and this ledger.
- Focused evidence: **27 S04 tests passed in 1.991 seconds**. The exact integration fixture yields **18.42 / 0.471 / 18.891 USD** and differences **-1.58 / -19.529 / -21.109 USD**. Tests cover rounding, large/bounded counts, bad input, caller Decimal context, all value states, missing/zero write prices, provenance, repricing invariance, context/TTL evidence, scope, unavailable providers, JSON/CLI and renderer authority.
- Regression sequence: initial report tests exposed three expected savings/fake-month compatibility mismatches. First focused checks also caught one leftover float-helper call plus an independently corrected hand-transcribed large-number expectation; final focused results pass. Independent accounting probes print **200/200**, **200/200**, **250/250**, all true.
- Full/build: `windows/build.ps1` passed **163 tests in 10.293 seconds** and rebuilt `UsageTray.exe` on project Python 3.14.5 with installed pinned dependencies, `PIP_NO_INDEX=1`, and workspace-local `windows/build/s04-temp`. No runtime dependency changes.
- Packaged acceptance: **10 hidden offline cases passed**, using synthetic roots/rates and an empty `PYTHONTZPATH` to force bundled timezone fallback. Both text/HTML yield **2,905,000 / USD 18.8910**, Codex-only **2,840,000 / USD 18.4200**, Claude-only **65,000 / USD 0.4710**; fee differences display **-1.58 / -19.53 / -21.11** after rounding. Mixed unknown-model usage preserves **2,905,010** tokens and the same priced subtotal in both formats. All-unpriced remains unavailable, explicit zero rates produce complete/zero and **-40.00**, missing Claude write rates prevent a combined comparison, and demo remains **108,000 / USD 0.2658**. All cases exited 0; sentinels/transcript content and prior savings labels were absent.
- Verification/handoff: source syntax, changed Markdown links/fences/whitespace, catalog amount compatibility and `git diff --check` passed. No S05 completion is claimed. Commit/push uses the existing isolated branch; it does not merge the separate main checkout.
- Remaining limits / next dependency: no refreshed prices, real user histories/accounts, live providers, interactive lifecycle, macOS, Figma, remote CI, persistent settings, database or API. S05 is next after this gate: immutable shared headless query/summary service and exact group/query contracts, preserving the S04 authority. Shared-checkout integration requires its own combined validation.

### Session S05 — Shared headless report/query service

- Status: **complete** in the isolated refinement worktree. Scope: F1/F3/F4; started clean at `15219d5`. The earlier instruction to commit/push is applied to this completed session on the same isolated branch; no merge into the separate main checkout is included. Followed the repository-wide AGENTS instructions and read the requested `create-rule` skill; scope is already explicit, so no duplicate rule tree is introduced.
- Decisions: [S05 service contract](s05-headless-query-service.md) owns immutable result/quality contracts, typed metadata filters, full canonical conversation identities, exact stable sorting, compatibility behavior and limits. Core data stays in memory; no optional hub database/API/frontend is introduced.
- Implementation: `usage_service.py` captures/collects offline inputs and supplies one authoritative `UsageResult` containing context, exact total/group/detail summaries, reasoning coverage, source/accounting issues, provenance and structured signed comparisons. CLI/tray call `query_usage`; text/HTML only format its result. Legacy `Report` and entry points adapt through the same service.
- Intentional corrections: manually injected legacy records now obey provider selection and the captured half-open range; six fixture timestamps move from the excluded end to one second inside, retaining numeric expectations. Structured keys prevent joined-label collisions; conversation membership uses full canonical identity instead of a shortened display surrogate. Repeated legacy occurrences remain distinct and cannot claim canonical identity.
- Files: `windows/usage_service.py`, `windows/usage_reports.py`, `windows/usage_tray.py`, `windows/tests/test_service.py`, `windows/tests/test_reports.py`, `windows/README.md`, `AGENTS.md`, `docs/s05-headless-query-service.md`, and this ledger.
- Focused evidence: final **24 S05 tests passed in 1.791 seconds**. Synthetic totals are **2,905,000 tokens / USD 18.891**, with **-1.58 / -19.529 / -21.109 USD** signed differences. All seven group dimensions and event details reconcile, including partial/unpriced states. Tests cover provider/filter/day/drilldown selection, exact ranking beyond binary precision, canonical/legacy identity, full-result totals, immutable snapshots, one captured clock, source/price/accounting separation and renderer non-recomputation. Fresh-process real fixture collection blocks sockets and subprocess launch and imports no provider/tray/GUI modules.
- Regression sequence: initial report run found one remaining terminal field reference and five tests containing exact-end fixtures (six timestamps); corrected adapter reference and fixture placement, preserving the half-open invariant. The first full suite passed **186 tests in 19.254 seconds**. Full-identity review then added the 24th focused regression; build verification records the final suite below.
- Independent probes: printed **200/200**, **200/200**, **250/250**, all `matches_expected: true`; the diagnostic exit code is not the assertion.
- Full/build: `windows/build.ps1` passed the final **187 tests in 26.749 seconds** and rebuilt `UsageTray.exe` on project Python 3.14.5 / PyInstaller 6.16.0, with installed pinned dependencies, `PIP_NO_INDEX=1` and workspace-local TEMP/TMP. No dependency changes. The existing optional pystray GTK SyntaxWarning remains nonblocking.
- Packaged acceptance: **10 hidden offline executable cases passed** using synthetic roots/rates, `CREATE_NO_WINDOW` and an empty `PYTHONTZPATH` to force bundled timezone fallback. Both text/HTML yield **2,905,000 / USD 18.8910**; provider-only results are **2,840,000 / USD 18.4200** and **65,000 / USD 0.4710**, with signed rounded differences **-1.58 / -19.53 / -21.11**. Mixed unknown usage retains **2,905,010** tokens and the qualified priced subtotal; all-unpriced is unavailable, explicit zero is complete/zero with **-40.00**, missing write prices block the combined comparison, and demo is **108,000 / USD 0.2658**. All exited 0, with the synthetic transcript sentinel and prior savings labels absent. Separately parsed the packaged HTML: all **seven** group dimensions reconcile every token category and USD **18.8910** to the headline.
- Verification/handoff: changed Python syntax, **4 Markdown files / 27 local links**, code fences/whitespace, executed demo documentation example and `git diff --check` passed. Generated environment/build/dist/test fixtures remain ignored. S06 is ready; no later session gate is claimed.
- Remaining limits / next dependency: no refreshed pricing, real user histories/accounts, live providers, interactive lifecycle, macOS, Figma, remote CI, persistent settings, database/API or large-history benchmark. S06 is next after this gate. Separate-checkout integration and combined validation are still required; this work does not merge main.


### Session S06 — Persistent validated configuration and identity

- Status: **complete in isolated worktree**. Started from `97b6070`, on the existing `codex/s01-observation-contracts` branch. Read repository `AGENTS.md`, S06 dependencies and the requested `create-rule` skill before implementation. No parallel agents or duplicate rule tree were created; this remains one coherent session.
- Decisions: [S06 configuration contract](s06-persistent-configuration.md) documents schema-v1, exact bounds, root semantics, migration, recovery, CLI precedence and identity limits. Persistence is explicitly opt-in through `--save-settings`; absent files have a clear first-run/default state, and ordinary startup/report/demo/diagnostic commands do not initialize settings. This avoids incidental writes while meeting the restart/persistence gate. Malformed existing files fail closed with recovery guidance, rather than loading an automatic backup or silently resetting defaults. Concurrent writers and runtime ownership remain S07; no broad runtime/UI/storage rewrite was added.
- Changed files: new `windows/usage_config.py`, `windows/usage_identity.py`, `windows/settings.example.json`, `windows/tests/test_config.py`, and `docs/s06-persistent-configuration.md`; updated `windows/usage_tray.py`, `windows/usage_reports.py`, `windows/usage_service.py`, `windows/README.md`, this ledger and `AGENTS.md`. Default root resolution and strict legacy price-file loading now have one shared configuration implementation; existing report helper imports remain compatible. No dependencies, provider adapters, credentials, bundled rates or token accounting changed.
- Implemented: local application-data settings persist both fees (initially USD 20 each), explicit/dynamic/disabled log roots, named timezone, bundled catalog selection, exact-model rate overrides and supported text/HTML preference. Explicit CLI arguments override saved settings only for the run unless saved. Unknown/null fees remain distinct from known zero fees. Legacy automatic `prices.json` remains active until first save, which snapshots validated overrides without modifying it. Explicit alternate configs are isolated from that automatic migration.
- Recovery/identity: validation precedes writes; complete sibling temporary output is flushed/fsynced and atomically replaced. Invalid/partial/future-schema/duplicate JSON, invalid numeric values, unavailable timezones and failed reads produce sanitized guidance and preserve existing files. Handled flush/replace failures preserve the previous valid file. App `0.6.0`, captured source/executable hash and settings identity augment parser/reconciliation/query/valuation/pricing identities in structured results and both renderers. `--version` bypasses corrupt configuration; `--diagnostics` reports effective-versus-saved state and root modes/counts without root paths, logs, credential reads or provider polling. Windowed JSON commands support explicit `--output`.
- Development evidence: the initial valuation compatibility run passed **27 tests in 3.434 seconds**. An initial full run of **207 tests in 43.211 seconds** found one compatibility failure: explicit invalid timezone overrides lost the existing `Unknown report timezone` guidance. Restored that message without weakening validation; **10 time/CLI tests passed in 0.462 seconds**. An earlier 19-test configuration pass was extended with unreadable-file coverage; the final focused **20 S06 tests passed in 11.253 seconds**. They verify exact round trips, null/zero semantics, complete schema validation, read/flush/replace failure preservation, first-run state, CLI precedence, restart persistence, root semantics, timezone/catalog/preference validation, legacy migration, headless imports and result/diagnostic identities.
- Full/build: `windows/build.ps1` passed all **207 tests in 29.298 seconds** and rebuilt `UsageTray.exe` successfully on project Python **3.14.5**, Windows 11 and PyInstaller **6.16.0**, using installed pinned dependencies, `PIP_NO_INDEX=1`, and workspace-local `windows/build/s06-temp` TEMP/TMP. The pre-existing optional pystray GTK SyntaxWarning remains nonblocking. The executable includes bundled tzdata; no generated binary/environment/history is a source deliverable.
- Packaged acceptance: **19 hidden offline executable scenarios passed** with synthetic fixtures and empty `PYTHONTZPATH` forcing bundled timezone fallback. Ten previous accounting scenarios retain **2,905,000 tokens / USD 18.8910**, provider values **18.4200 / 0.4710**, partial/all-unpriced/explicit-zero/missing-write behavior and labeled demo **108,000 / 0.2658**. Nine S06 scenarios verify explicit save, separate-process restart, persisted roots despite changed environment homes, exact saved Codex fee **30.000000000001** and Claude fee **0**, temporary text-to-HTML/fee override without rewriting settings, effective saved/override diagnostic states, executable SHA-256 identity matching the delivered binary, null-versus-zero fee behavior, version output with corrupt settings, rejected corrupt-file save, and recovery to a separate valid config. The expected corrupt-file save exited **2** and preserved its bytes; successful cases exited **0**. Fixture transcript sentinel absent from reports. No tray/provider process was launched by these offline checks.
- Independent probes: printed **200/200**, **200/200**, **250/250**, all `matches_expected: true`; inspected comparisons rather than relying on probe exit status.
- Verification/handoff: six changed/new Python modules parse, the complete settings example validates, changed Markdown links/fences/whitespace and `git diff --check` pass. CLI/documented persistence/version/report commands are exercised by source and packaged checks. Commit/push stays on the isolated branch and does not integrate the separate original/main checkout. S07 is ready; no later gate is claimed.
- Remaining limits / next dependency: no interactive tray restart/popup, real histories/accounts, live providers, macOS, Figma, remote CI, refreshed pricing, dependency/source reproducibility guarantee, concurrent settings writer serialization, directory-level power-loss durability, optional database/API or interface redesign verification. A hard interruption may leave an ignored sibling temporary file, never read as settings. Direct headless queries intentionally use explicit inputs and do not auto-load user settings. S07 next: separate polling from UI, runtime recovery and single-owner lifecycle. Shared-checkout integration still requires combined validation.

### Session S07 — Independent runtime, process ownership and recovery

- Status: **complete in isolated worktree**. Started from `6a29b00` on `codex/s01-observation-contracts`; read `AGENTS.md`, S07 dependencies and the requested `create-rule` skill. No subagents, optional hub infrastructure, Figma changes or interface redesign. Preserve separate original/main checkout work; this session does not integrate it.
- Decisions: [S07 runtime/recovery contract](s07-runtime-recovery.md) defines per-provider scheduling/wakes, freshness/categories, ownership, cancellation, process containment, report failures and bounded generated artifacts. Use a per-application-data OS byte lock instead of a server/IPC broker; one production polling owner covers all selected providers and alternate configs sharing that folder. Direct offline reports/config/diagnostics remain independent. Restart resets in-memory deadlines; explicit sequential real one-shot commands do not share cooldown history. Arbitrary Python/HTTP/filesystem work cannot be forcibly cancelled safely; bounded joins and stated limits are retained rather than claiming hard cancellation of all IO.
- Changed files: new `windows/usage_runtime.py`, `windows/usage_process.py`, `windows/usage_failures.py`, `windows/usage_artifacts.py`, `windows/tests/test_runtime.py` and `docs/s07-runtime-recovery.md`; updated `windows/usage_core.py`, `windows/usage_tray.py`, `windows/usage_reports.py`, `windows/usage_identity.py`, `windows/tests/fake_codex.py`, `windows/README.md`, `AGENTS.md` and this ledger. App version **0.7.0**. No dependency, bundled price, canonical counter, fee formula, credential-write or redirect-policy changes.
- Implemented: headless runtime with one independent worker/fetch lock/wake event per provider, idempotent start, 300-second minimum completion-to-next-success checks, exponential failure backoff and longer finite Retry-After. Refresh fans out and cannot bypass deadlines/locks. Monotonic deadlines stay in memory; UTC retry display derives from the current wall clock. Prior successful snapshots and checked times survive failure with stale labels; window collections are immutable in runtime views. Explicit blocked usage is separate from remaining percentages, and known adapter error branches carry safe categories. Generic RPC errors do not invent a specific remote cause. Tray redraws are notification-driven instead of once per second.
- Ownership/shutdown: real one-shot/tray entry points hold a stable app-owned lock file; duplicate owner exits **3**, with no competing workers. Acquisition has a bounded **250 ms** retry for Windows crash-release timing. Quit stops/wakes workers and renderer, joins with documented bounds, suppresses a pending report viewer when stop is observed, and cancels Codex RPC waits. Hidden Codex children start suspended, enter a kill-on-close Windows job before execution, and only then resume. Cleanup terminates/waits for the whole owned tree; abrupt parent death also kills those descendants. Job-assignment failure terminates before child code runs. User CLI processes and handed-off report viewers are not killed.
- Report recovery/retention: query/save/open failures use safe categories rather than a universal permission message. Viewer launch failure leaves the saved report intact. New automatic reports use reserved `Reports/Generated`, pruned after successful save to **100 files / 30 days**, protecting/counting the current file even after clock rollback. Cleanup is nonrecursive, restricted to matching regular generated files, excludes links/reparse files and refuses linked directories. Explicit exports use another folder; legacy Reports files, histories, credentials, builds and unknown filenames are untouched. Retention failure preserves the saved report and emits a static warning. All cleanup tests used synthetic temporary files; no real report/history pruning was run.
- Development evidence: the existing **22 adapter/protocol tests passed** before and after integration (final compatibility run **3.742 seconds**). A new fixture initially had a string syntax error, corrected before behavioral checks. The first owner-crash check exposed a release race; fixture process trees were contained, an isolated OS probe observed approximately **12 ms** before lock reacquisition, and production cleanup now waits for job process completion plus bounded ownership acquisition retry. Initial **16 runtime tests passed in 4.695 seconds**; added parent-crash, clock-rollback retention and linked-directory refusal cases. Final focused **19 S07 tests passed in 8.831 seconds**.
- Focused acceptance: one hung provider does not block the other; both wake when due; 30 cooldown wakes and 15 concurrent same-provider attempts do not multiply requests; idle wakes do not redraw; failure/retry/stale recovery and blocked usage stay distinct; wall-clock changes do not bypass monotonic eligibility; stopped runtimes reject late results; uncooperative threads return an explicit bounded-close failure. Real Windows tests verify cross-process contention/restart, cancellation and abrupt parent death killing both an owned protocol process and descendant while an unrelated fixture process remains alive, and pre-execution failure when job assignment fails. Report-open failure preserves the saved file. Retention fixtures verify count/age bounds, current-file protection, failure recovery and simulated linked-directory refusal. Tray Refresh/Quit/restart and idle redraw are **simulated callbacks using the real runtime**, not native tray-menu playback.
- Full/build: `windows/build.ps1` passed the complete **226-test suite** and rebuilt `UsageTray.exe` successfully using project Python **3.14.5**, Windows 11 and PyInstaller **6.16.0**, installed pinned dependencies, `PIP_NO_INDEX=1`, and workspace-local `windows/build/s07-temp` TEMP/TMP plus isolated test LOCALAPPDATA. Existing optional pystray GTK SyntaxWarning remains nonblocking. No generated environment/binary/test histories are source deliverables.
- Packaged acceptance: **23 hidden executable scenarios passed**, with empty PYTHONTZPATH exercising bundled timezone data and synthetic histories/protocol fixtures. Nineteen prior accounting/settings cases retain **2,905,000 tokens / USD 18.8910**, provider **18.4200 / 0.4710**, partial/all-unpriced/explicit-zero/missing-write distinctions, signed fee comparisons, exact persisted fees/roots/timezone/format, override non-persistence, version/settings identities and malformed-file recovery. Four S07 cases verify duplicate ownership rejection (**exit 3**), offline demo report while another owner holds the lock, normal packaged Codex protocol child/descendant cleanup (**exit 0**), and forced termination of the actual packaged runtime parent followed by descendant termination and lock reacquisition. A temporary fake npm Codex entry and installed Node supplied fixed local protocol responses; no real CLI authentication, account request or provider network call was made. Expected corrupt-settings save remains **exit 2**. No native tray icon/menu was exercised by these hidden checks.
- Verification/handoff: changed Python syntax, **226 discovered tests**, changed Markdown links/fences/whitespace, independent accounting probe comparisons and `git diff --check` pass. Commit/push remains on the isolated branch; no main merge or separate-checkout integration. S08 is ready; S09 release and later gates remain unclaimed.
- Remaining limits / next dependency: no native tray-menu/popup playback, live provider/account verification, real histories, clean-machine/other Python version testing, macOS, remote CI, refreshed pricing or HTTP total-response cancellation guarantee. Windows job restrictions fail closed. Lock files assume a local trusted application-data filesystem; no machine-wide ownership or concurrent settings serialization is added. Report retention bounds count/age rather than bytes and can fail under filesystem errors. S08 next: privacy/rendering/diagnostic verification, followed by S09 release/lifecycle checks including native interaction. Separate-checkout integration still requires combined validation.

### Session S08 - Privacy, safe display and explicit diagnostics

- Status: **complete in isolated worktree**. Started from `461c3a3` on `codex/s01-observation-contracts`; read `AGENTS.md`, S08 and dependencies, evaluation/integration privacy requirements and the requested `create-rule` skill. Preserve separate original/main checkout work. No subagents, optional hub infrastructure, Figma, broad interface redesign or live account requests.
- Decisions: [S08 privacy/diagnostic contract](s08-privacy-diagnostics.md) keeps canonical identities/source references in the internal service, applies reduced metadata only at display boundaries, and makes full paths/IDs an explicit report option. Diagnostics are user-selected operation exports rather than an automatic persistent event store. Future database/API DTOs are not implemented or claimed tested. These choices complete the scoped privacy boundary without introducing competing storage, changing accounting or redesigning the terminal.
- Changed files: new `windows/usage_privacy.py`, `windows/usage_diagnostics.py`, `windows/tests/test_privacy.py` and `docs/s08-privacy-diagnostics.md`; updated `windows/usage_core.py`, `windows/usage_reports.py`, `windows/usage_runtime.py`, `windows/usage_tray.py`, `windows/usage_identity.py`, `windows/tests/test_reports.py`, `windows/README.md`, `AGENTS.md` and this ledger. App version **0.8.0**; no new dependencies, parser/reconciliation version changes, bundled rate changes or token/money/fee formula changes.
- Verified boundaries: existing extractors retain allowlisted metadata only; sentinel fixtures follow both providers through reconciliation/query results and explicit/default saved text/HTML reports. Snapshot serialization now enumerates fields instead of dumping dataclasses; malformed Codex name objects cannot stringify nested payloads. HTML escapes text and sets a restrictive embedded-content policy. Common display projection makes terminal/Unicode control, bidi, format, line separator and surrogate characters inert, while preserving internal values. Default paths use basenames plus digest and IDs use abbreviated digests; full metadata requires explicit export and neither mode is anonymization.
- Diagnostics: schema-v1 random operation/build IDs, UTC timestamps, scopes, fixed status/phase/category, static recovery guidance and allowlisted counts/provider categories. Serialization rejects arbitrary/extra nested fields. Explicit atomic CLI report/one-shot exports cover query/save/viewer/settings/ownership/provider failures, partial coverage and export errors; no raw exception, path, source line, record ID or payload. Standalone diagnostics now return a redacted result for invalid settings without scanning/polling, preserving the bad file. No automatic diagnostic files/retention or telemetry; existing S07 generated-report retention is unchanged.
- Development evidence: initial report compatibility **35 tests passed in 11.184 seconds**. The new fixture run found an incorrect Window projection field plus future-dated CLI fixture timestamps; corrected the public field to `duration_minutes` and used past-time fixtures. **15 tests passed in 5.584 seconds**, expanded to 16/17 for import isolation and settings/ownership recovery. Final focused **17 S08 tests passed in 6.710 seconds**; **20 settings tests in 18.278 seconds** and **22 provider/protocol tests in 2.042 seconds** also pass. Redirect/auth/rate/network fixtures preserve credential bytes and exclude protected content. Native browser/terminal playback is not claimed from string/parser tests.
- Full/build: `windows/build.ps1` passed **243 tests in 47.319 seconds** and built `UsageTray.exe` successfully with project Python **3.14.5**, Windows 11, PyInstaller **6.16.0**, installed pinned dependencies, `PIP_NO_INDEX=1` and workspace-local `windows/build/s08-temp` TEMP/TMP plus isolated test application data. The pre-existing optional pystray GTK SyntaxWarning remains nonblocking. New modules are bundled automatically; generated binaries, virtual environments and synthetic build fixtures are ignored and not source deliverables.
- Packaged acceptance: **32 hidden executable cases passed**, comprising the prior 23 accounting/settings/runtime scenarios and nine S08 cases: default text/HTML metadata reduction and control/injection safety; explicit full metadata text/HTML; source-incomplete diagnostic status/counts; invalid-settings diagnostic **exit 2** with original bytes preserved; report-save failure **exit 1** with phase/category/counts; ownership rejection **exit 3** with safe recovery guidance; and clearly scoped demo one-shot diagnostics. Diagnostic build hashes match the actual executable. Prior scenarios retain **2,905,000 tokens / USD 18.8910**, partial/unpriced/zero distinctions, fee persistence/overrides, bundled timezone fallback, independent offline access and owned-child/crash recovery. Fixtures use synthetic files, empty PYTHONTZPATH, fake local Codex protocol/Node children and isolated application data; no real account/provider request or native tray/browser playback.
- Independent probes and handoff: inspected **200/200**, **200/200** and **250/250**, all `matches_expected: true`. **Nine** changed/new Python files parse; **four** changed/new Markdown files have valid fences and **38** local links; `git diff --check` passes. S08 acceptance is evidenced by end-to-end sentinels, inert display/HTML parsing, strict diagnostic serialization, actionable failure exports, preserved credential/redirect safeguards and packaged checks. Commit/push remains on the isolated branch with no main merge or original-checkout integration. S09 is ready; no later gate is claimed.
- Remaining limits: no full security certification, anonymization guarantee, database/API DTO verification, native tray/browser playback, real histories/live accounts, clean-machine/other-Python/macOS/remote-CI checks, refreshed prices, total HTTP cancellation, filesystem-race protection, concurrent export/settings serialization or crash-before-completion diagnostic guarantee. Explicit exports remain user-managed. Separate original/main checkout remains unintegrated. S09 is ready for the requested Windows release/native-interaction checks.

## 11. Completion and reassessment

- **Core complete:** S00–S09 gates pass; terminal functionality remains available; known accounting defects have regression coverage and correct outcomes.
- **Expression complete:** S10's usability and reconciliation checks pass after interface work is requested.
- **Hub complete:** the explicitly scoped S11–S14 gates pass; plans/Figma alone do not count as runtime integration.
- **Factor reassessment:** revisit F1–F10 using linked tests, runtime checks, and remaining limitations. Keep weights stable or explain a scope-driven change. Do not raise the score just to hit a target number.

Recommended next implementation unit in this worktree: **S09**. S00–S08 are complete here; validate the refined Windows release, native interaction and explicitly scoped read-only local-history evidence before claiming core completion or optional database expansion.
