# Usage Tray / Usage Hub: engineering refinement plan

Status: implementation backlog. This document does not implement its fixes or authorize executing every session automatically.

Baseline: local working tree based on Git `f93f87e`, with existing uncommitted Windows changes and documentation. Prepared from the October 23, 2026 review and subsequent refinement discussion. Windows is the primary runtime target; macOS observations are source review only.

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

Initial status: **all S00–S14 sessions are not started under this plan**. Earlier reviews, tests, pricing fixes, and documentation are baseline evidence; they do not automatically complete the broader session gates. Some tasks may already be satisfied when implementation begins; verify and record that evidence rather than repeating work unnecessarily.

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

## 11. Completion and reassessment

- **Core complete:** S00–S09 gates pass; terminal functionality remains available; known accounting defects have regression coverage and correct outcomes.
- **Expression complete:** S10's usability and reconciliation checks pass after interface work is requested.
- **Hub complete:** the explicitly scoped S11–S14 gates pass; plans/Figma alone do not count as runtime integration.
- **Factor reassessment:** revisit F1–F10 using linked tests, runtime checks, and remaining limitations. Keep weights stable or explain a scope-driven change. Do not raise the score just to hit a target number.

Recommended next implementation unit: **S00, followed by S01/S02**. Do not start by restyling the report or creating a database around the current reconciliation defects.
