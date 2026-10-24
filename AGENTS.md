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
- Compact terminal views belong in `windows/usage_terminal.py` and consume immutable summaries. CLI/tray default to summary; retain `--audit` and legacy programmatic audit behavior. Detail paging is presentation-only and cannot narrow headline accounting. See [S10](docs/s10-terminal-views.md).
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
- Use `windows/usage_service.py` for selection, ordering, grouping and immutable `UsageResult` summaries; renderers only format that result. Preserve full canonical conversation identity for groups/drilldowns; display labels and legacy occurrence IDs are not global identities. See [the S05 contract](docs/s05-headless-query-service.md).
- Use `windows/usage_config.py` for validated settings and atomic writes. CLI overrides are temporary unless `--save-settings` is explicit; preserve malformed files and the documented legacy price migration. Direct headless queries use explicit inputs, without silently loading user settings. See [the S06 contract](docs/s06-persistent-configuration.md).
- Persist one fee configuration source, initially Codex USD 20/month and Claude USD 20/month. Compare full fees only for unfiltered calendar-month-to-date, optionally by provider; show signed differences and qualifications, not actual bills or realized savings.
- Capture one range/timezone context. The refined service uses UTC `[start, end)` with named local-day/month boundaries; migrate legacy inclusive-end behavior explicitly. Follow frozen revision/query-context rules on the hub track.

## Reliability, privacy, and integration

- Keep polling, per-provider wake/eligibility and ownership in `windows/usage_runtime.py`; preserve scoped child containment in `windows/usage_process.py`. Automatic report retention is restricted to the reserved Generated folder; never extend it to histories, legacy reports or explicit exports. See [the S07 contract](docs/s07-runtime-recovery.md).
- Keep provider refreshes independent, enforce cooldown/backoff, and preserve labeled last-successful state. Offline usage queries must not require provider polling or GUI imports.
- Handle append/truncation/replacement explicitly. Failed reads must not silently replace accepted history with empty data. Retain a coherent last committed dataset when persistence exists.
- One runtime owner schedules provider checks and database writes when clients/processes share a service. Do not persist monotonic deadlines as UTC timestamps.
- Extract allowlisted metadata only. Never persist/export/log prompts, responses, credentials, raw provider payloads, or raw source lines. Parsing source bytes does not imply permission to retain content.
- Use `windows/usage_privacy.py` for display-only projections and `windows/usage_diagnostics.py` for allowlisted explicit operation exports. Full report paths/IDs require `--include-metadata`; never serialize the internal query graph as redacted diagnostics. See [the S08 contract](docs/s08-privacy-diagnostics.md).
- Treat source metadata as untrusted text: escape HTML and neutralize terminal control sequences while preserving internal identities. Keep errors/diagnostics sanitized and actionable.
- Preserve credential redirect protections; do not write or refresh credentials as an incidental workaround.
- Use `windows/usage_index.py` for explicitly requested local persistence; its SQLite/codec modules own migrations, metadata projections and publication. Preserve retained-source states, exact stored valuations, JSON configuration authority and offline shared-service queries. Do not create a competing schema or make queries initiate imports/polling. See [S11](docs/s11-local-index.md).
- Use the S12 v1 query/HTTP/runtime/job modules and [contract](docs/s12-local-api.md) for production local API work. Keep exact numeric strings, frozen publication contexts/cursors, approved-root-only mutations, owner-controlled settings and authenticated reads/mutations. The production dashboard uses `windows/dashboard/local.html` and the `local-*` / `v1-*` frontend modules; keep the explicit `index.html` / `app.js` demo preview separate. Never route failed real queries to the preview.
- Use `windows/usage_hub_launch.py` for native dashboard/shared tray launches and [S13 runtime integration](docs/s13-runtime-integration.md) for lifetime/reuse boundaries. Keep browser launch explicit, persisted settings authoritative, and the runtime owner held until in-flight HTTP operations, provider workers and index jobs have stopped. The local index, v1 service and real-data dashboard are implemented; the full packaged release gate remains S14. Follow the integration contract for transactions, exact numeric contracts, frozen queries, job status, migrations, and loopback access controls.
- Do not silently substitute demo data for failed real connections. Keep real/demo scopes separate. Never infer missing quota history or running-conversation status.

## Verification and handoff

- Use `windows/.venv/Scripts/python.exe` when available; see the plan for workspace-local TEMP/TMP setup and focused/full-suite commands. Do not silently use an unrelated interpreter.
- Add meaningful regression fixtures for behavior changes. Accounting expectations must follow the invariant, not mirror a buggy legacy result. Run focused checks, then the relevant full suite; expand only for new evidence or release gates.
- Run `docs/review_accounting_probes.py` when relevant and inspect printed comparisons: its exit code currently does not assert correctness. Promote the cases into normal tests during S02.
- Run `git diff --check`; validate changed documentation links/examples. Do not add tests that merely duplicate implementation or claim proposed APIs were tested before they exist.
- Use `windows/tools/release_smoke.py` for bounded offline executable acceptance; `windows/build.ps1` runs it after packaging. Real-history release checks use the explicitly selected, read-only `windows/tools/local_history_audit.py`; never retain its internal query graph or source text. See [S09 release evidence](docs/s09-windows-release.md).
- Use `windows/build.ps1` when packaging is affected or at release gates; test relevant packaged behavior, not only build success. Generated `.venv`, build/dist artifacts, and real histories are not source deliverables.
- Validate absolute targets before recursive Windows cleanup/moves; operate only on intended workspace/application-owned paths. No source-history deletion as routine cleanup.
- Update the session ledger with changed files, decisions, exact checks/outcomes, acceptance evidence, remaining risks, and next dependency. Final responses state what changed, validation, and material limits without exposing private data.

## Figma workflow and core integration

- For Figma tasks, use the installed Figma plugin skills rather than duplicating their API instructions here. Load `figma-design-to-code` before design implementation or `get_design_context`; load `figma-use` before `use_figma`, together with `figma-generate-design` for composed screens or `figma-generate-library` for components/tokens.
- The reviewed design is [AI Usage Hub](https://www.figma.com/design/6Axot2OcYiKcSfGYcLh3Jh), with Overview at node `2:43`. Reinspect the requested nodes before work; saved IDs and screenshots are references, not current verification. Follow the plugin's session requirements.
- Use the [prototype test report](docs/usage-hub-figma-test-report.md) for known interaction limitations. For implementation, obtain current design context and its screenshot, inspect the existing stack/components, and adapt the design to project conventions. Preserve editable layers when delivering Figma changes.
- The refinement plan owns session dependencies; the integration contract owns data semantics; Figma owns the reviewed visual and interaction reference. Resolve conflicts explicitly in the ledger. Design exploration may proceed independently, while real-data dashboard integration follows the S11-S14 prerequisites. A Figma task does not complete a core gate.
- UI adapters consume the authoritative headless summary/query service. Keep parsing, reconciliation, pricing, fees, and aggregation in the core; never port Figma calculation-frame logic or sample totals into production calculations. Use integer-string token and decimal-string money contracts when implementing the API.
- Keep local unmatched-account usage separate from active-account live limits. Expose empty, partial, unpriced, stale, and failed states honestly; demo data must be explicitly selected and labeled. Preserve query context through filters, detail, Back, and refresh.
- Follow the [confirmed display rules](docs/usage-hub-integration-plan.md#15-confirmed-token-formatting-and-chart-axis-rules): thousands remain comma-separated integers; millions use M and billions B, with up to two decimal places. Formatting never changes exact counters. Both chart metrics need labeled Y axes/gridlines, a zero baseline, and a scale based on the largest matched daily column for the selected metric and filters.
- Keep the existing terminal/tray entry points and explicit dashboard launch. Reuse the existing database work once inspected; do not introduce a competing schema or require provider polling for offline usage views.
- Verify core behavior with relevant regression tests and UI behavior with rendered comparisons plus actual interaction checks where available: provider selection, chart metric/day filters, summary/detail reconciliation, Back, keyboard/focus, and narrow layouts. Report simulation, screenshot review, browser tests, and native Figma playback separately; never claim an unrun check passed. Record touched files, evidence, limitations, and the next dependency in the ledger.
