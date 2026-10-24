# S08: metadata privacy, safe display and explicit diagnostics

## Scope and boundaries

Windows Python 0.8.0 keeps the existing terminal/tray entry points. This session verifies extraction, reports, provider snapshots and local diagnostic exports. It does not implement database/API DTOs, telemetry, a dashboard or a complete security audit. Future persistence/API serializers must independently enforce explicit field allowlists under [the integration contract](usage-hub-integration-plan.md).

The existing extractors select conversation/project/model/effort/identity evidence, timestamps and numeric counters. They inspect Claude content block types only to recognize tool-result turns; they retain no content. Unknown nested payloads, transcript text, thinking text, request headers and credential objects are never copied into observations. Invalid counter/metadata values keep structured unknown/invalid states, rather than retaining the raw invalid value or fabricating zero. S08 sentinel tests follow both provider fixtures through extraction, reconciliation, immutable query results and saved text/HTML reports.

The internal service still needs complete project and conversation identities, and SourceRef can retain a local source path in memory. S08 deliberately leaves canonical identities, reconciliation ordering and token facts unchanged. A generic dataclass dump of that internal graph is not a supported redacted export. New diagnostics use an enumerated projection and revalidate its fields when writing; future storage must not serialize the entire graph.

Codex live-limit names must be nonempty strings of at most 200 characters; malformed objects fall back to a valid bucket ID or static label. Snapshot JSON explicitly enumerates supported snapshot/window fields, so subclass attributes or arbitrary response keys cannot become accidental exports. Valid provider names remain untrusted display text.

## Report metadata and safe rendering

Default reports show absolute project-path basenames with an eight-character path digest, plus twelve-character digests for conversation/turn labels. The suffix distinguishes equal basenames in different folders. These display digests never replace internal identities, group membership or exact counters. They are unsalted and abbreviated: they are not anonymization, cryptographic access control or guaranteed unique identifiers. Project names, model/effort labels and activity still need review before sharing.

Full project paths and conversation IDs require `--include-metadata` with `--report`, or the explicit Python renderer/save argument `include_metadata=True`. HTML history also includes full turn IDs in that mode; text reports retain their existing group-only layout. The tray uses reduced metadata. `--show-settings` remains an intentional settings export that includes configured root paths; it is not a redacted diagnostic command.

```powershell
# Run from windows/. Terminal output remains the default.
.\.venv\Scripts\python.exe .\usage_tray.py --report month
.\.venv\Scripts\python.exe .\usage_tray.py --report month --include-metadata --output .\private-report.txt
.\.venv\Scripts\python.exe .\usage_tray.py --report month --report-format html --include-metadata --output .\private-report.html
```

`usage_privacy.display_text` renders Unicode C-category characters (including C0/C1, ESC, bidi controls, zero-width format characters and lone surrogates), plus line/paragraph separators, as visible Unicode escapes. HTML then escapes text/attribute characters. Terminal reports sanitize every assembled line; provider menu lines, snapshot JSON labels/notes and printed report paths use the same projection. Embedded newlines cannot forge additional report rows. Internal values remain unchanged. Printable text that resembles an escape sequence remains inert text; display labels are not reversible encodings.

HTML reports also set a restrictive local content policy: no scripts, embedded resources, forms or base URL; inline report CSS is allowed. Static pricing links remain explicit navigation. Tests parse generated HTML for active injected elements/attributes; they are not a native browser policy-enforcement or visual-layout test. Terminal control fixtures likewise inspect output bytes/text without executing attack sequences in a terminal.

## Redacted diagnostic exports

`--diagnostics` performs configuration/version checks without scanning source logs, acquiring a polling owner, importing GUI modules or calling providers. Its existing version/settings identities, selected timezone/format and root modes/counts remain available, with a new structured operation result. Invalid settings produce build identities plus `settings_invalid`/`settings` recovery guidance and exit 2; the original settings bytes remain untouched. `--version` remains available independently.

`--diagnostic-output PATH` explicitly exports the outcome of `--report` or `--once`, including handled failures. It does not attach to an already-running tray and is not an automatic runtime event log. A report is an offline query; real `--once` deliberately polls the selected provider adapters and retains their existing ownership/cooldown scope. Use `--demo` for checks that must avoid credentials and provider requests.

```powershell
.\.venv\Scripts\python.exe .\usage_tray.py --diagnostics --output .\configuration-check.json
.\.venv\Scripts\python.exe .\usage_tray.py --report month --diagnostic-output .\report-operation.json
.\.venv\Scripts\python.exe .\usage_tray.py --once --demo --diagnostic-output .\demo-check.json
```

Schema 1 operation exports contain only a random operation ID, UTC start/end timestamps, application/build identity, fixed operation/scope/status/phase/category names, static recovery guidance, allowlisted nonnegative counts and selected provider names/categories. Counts cover matched records/conversations/projects, roots/files read/discovered, ingestion/accounting issues, unpriced records and tier-assumed records. A source-incomplete report can still be generated with exit 0; its operation status is `partial`. Counts absent before query completion remain absent, rather than invented zero values. Source issues, counter quality and price coverage remain separate report concepts.

Exports exclude prompts, responses, thinking text, raw lines/payloads, credentials, exception text/tracebacks, project/model/effort labels, root/source/output paths, conversation/turn/event IDs, live quota payloads, token amounts and money. Demo/local/configuration scopes are explicit. Operation IDs/timestamps/counts and build/settings fingerprints are still metadata; review a diagnostic before sharing it. Category guidance points to login, cooldown, local access/disk space, configuration, unsupported data/CLI response, ownership or viewer recovery without copying the original exception.

The operation-export writer rejects unexpected top-level/nested fields, invalid category/guidance values and malformed count structures before touching the destination. A sibling temporary file, flush/fsync and atomic replacement preserve a prior export on handled replacement failure. No directory-level power-loss durability or concurrent-writer serialization is claimed. CLI diagnostics reject collisions with the selected settings/price/report output and the reserved Generated folder. A failed diagnostic write returns a safe error (exit 1 after an otherwise successful operation), while preserving an already-saved report and the original operation failure code when present. Process crashes before the completion boundary cannot guarantee an export.

## Artifacts and retention

Settings remain at `%LOCALAPPDATA%\UsageTray\settings.json` unless `--config` selects another path; the legacy optional `prices.json` migration remains as in [S06](s06-persistent-configuration.md). Provider credentials remain in their existing CLI-owned locations and are read only by explicit real provider polling. The app does not refresh or write them as failure recovery.

Automatic reports use `%LOCALAPPDATA%\UsageTray\Reports\Generated` with S07's soft 100-file/30-day retention. Legacy reports under Reports and explicit report exports are untouched. Diagnostics have no automatic location, telemetry upload, rotation or cleanup: the user selects the destination and manages its retention. Handled temporary diagnostic files are removed; an interrupted writer can leave a sibling `.usage-diagnostic-*.tmp` file, which is never read automatically. No local history, credential, settings or user-export deletion is introduced. The stable `runtime.lock` file contains only its existing lock byte. Development build/test fixtures remain ignored under `windows/build` and are not product data.

Existing no-redirect behavior, sanitized adapter errors, short-lived scoped child processes, cancellation and last-successful provider state remain governed by [S07](s07-runtime-recovery.md). Synthetic HTTP fixtures verify rejected redirects, auth/rate/network errors and byte-for-byte credential preservation. No live account request, credential refresh, native tray interaction, browser playback or claim about malicious local filesystem races is implied. S09 owns the remaining Windows release/native interaction checks.
