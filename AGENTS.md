# Agent instructions: Usage Tray / Usage Hub refinement

## Scope and references

- Applies repository-wide. Windows Python is the primary refinement target; Swift/macOS changes require separate justification and platform-appropriate verification.
- Read [the refinement plan](docs/project-refinement-plan.md) and the relevant session before implementation. It owns priorities, dependencies, gates, and handoffs.
- Use [the integration contract](docs/usage-hub-integration-plan.md) for optional hub DTO/database/API semantics and [the evaluation](docs/project-evaluation-2026-10-23.md) for defect evidence. The older hub plan is background.
- Current user instructions govern scope. A backlog is not authorization to execute every session, redesign the interface, modify Figma, deploy, push, or contact external services.

## Working method

- Inspect current Git status and applicable instructions first. Preserve existing edits; never reset, stash, overwrite, or clean them merely to simplify work.
- Work in a coherent requested session, respecting its dependencies. Verify already-completed tasks instead of repeating them. Record substantive design deviations and rationale in the plan ledger.
- Keep Python, current adapters, tray access, and compatible CLI/report behavior. Extract responsibilities incrementally; avoid a broad rewrite or adding infrastructure without a demonstrated need or scoped hub request.
- Fix accounting before presentation/storage expansion. Preserve the terminal; open a future dashboard explicitly unless the user changes that preference. Do not prioritize output styling during core refinement.
- Do not mark sessions complete from documentation, a successful build, or test count alone. Record actual gate evidence, unrun checks, limitations, and the next ready session.

## Accounting and value rules

- Local usage is all available unmatched local accounts; live limits are the active CLI account. Never imply account matching or full account coverage without evidence.
- Token total is uncached input + output + cache reads + 5-minute writes + 1-hour writes. Reasoning is a nullable subset of output, never an extra token or charge.
- Preserve explicit effort/source values; do not infer effort or a price multiplier from thinking budgets.
- Reconcile observations across copies before deriving deltas. File position and cumulative numeric tuples alone are not global event identity; reset epochs and fork baselines matter.
- Mandatory regressions: complete `100, 200` plus partial `200` totals **200** in every supported file order; reset `100, 200, 50, 100` retains **250** after excluding the ambiguous transition.
- Unknown/malformed metadata is not an observed zero. Keep ingestion issues, price coverage, counter quality, and tier assumptions distinct; never fabricate skipped token amounts.
- Unknown models stay unpriced. Empty, all-unpriced, partially priced, and legitimately zero-priced results are distinct.
- Estimate accepted events before aggregation. Preserve request-context evidence or label tier assumptions; aggregate counters do not prove one request's context.
- Use exact decimal money/rates in the refined shared service with documented bounds/rounding. Repricing cannot change canonical token facts. All renderers consume one authoritative summary.
- Persist one fee configuration source, initially Codex USD 20/month and Claude USD 20/month. Compare full fees only for unfiltered calendar-month-to-date, optionally by provider; show signed differences and qualifications, not actual bills or realized savings.
- Capture one range/timezone context. The refined service uses UTC `[start, end)` with named local-day/month boundaries; migrate legacy inclusive-end behavior explicitly. Follow frozen revision/query-context rules on the hub track.

## Reliability, privacy, and integration

- Keep provider refreshes independent, enforce cooldown/backoff, and preserve labeled last-successful state. Offline usage queries must not require provider polling or GUI imports.
- Handle append/truncation/replacement explicitly. Failed reads must not silently replace accepted history with empty data. Retain a coherent last committed dataset when persistence exists.
- One runtime owner schedules provider checks and database writes when clients/processes share a service. Do not persist monotonic deadlines as UTC timestamps.
- Extract allowlisted metadata only. Never persist/export/log prompts, responses, credentials, raw provider payloads, or raw source lines. Parsing source bytes does not imply permission to retain content.
- Treat source metadata as untrusted text: escape HTML and neutralize terminal control sequences while preserving internal identities. Keep errors/diagnostics sanitized and actionable.
- Preserve credential redirect protections; do not write or refresh credentials as an incidental workaround.
- Database/API/frontend are optional sessions, not existing features. Follow the integration contract for transactions, exact numeric contracts, frozen queries, job status, migrations, and loopback access controls.
- Do not silently substitute demo data for failed real connections. Keep real/demo scopes separate. Never infer missing quota history or running-conversation status.

## Verification and handoff

- Use `windows/.venv/Scripts/python.exe` when available; see the plan for workspace-local TEMP/TMP setup and focused/full-suite commands. Do not silently use an unrelated interpreter.
- Add meaningful regression fixtures for behavior changes. Accounting expectations must follow the invariant, not mirror a buggy legacy result. Run focused checks, then the relevant full suite; expand only for new evidence or release gates.
- Run `docs/review_accounting_probes.py` when relevant and inspect printed comparisons: its exit code currently does not assert correctness. Promote the cases into normal tests during S02.
- Run `git diff --check`; validate changed documentation links/examples. Do not add tests that merely duplicate implementation or claim proposed APIs were tested before they exist.
- Use `windows/build.ps1` when packaging is affected or at release gates; test relevant packaged behavior, not only build success. Generated `.venv`, build/dist artifacts, and real histories are not source deliverables.
- Validate absolute targets before recursive Windows cleanup/moves; operate only on intended workspace/application-owned paths. No source-history deletion as routine cleanup.
- Update the session ledger with changed files, decisions, exact checks/outcomes, acceptance evidence, remaining risks, and next dependency. Final responses state what changed, validation, and material limits without exposing private data.
