# S03 — Source quality, recovery, and captured time

Implementation starts from `82f2b5f` in the isolated refinement worktree. Windows Python is the target; this does not merge the original checkout or implement a database/dashboard. S02 accounting remains authoritative.

## Source result and issue contract

`windows/usage_ingestion.py` provides headless `scan_observations(provider, roots)`. Its immutable result contains metadata-only observations, structured `ScanIssue` entries, root/file counts, `issue_counts`, and a source state:

- `empty`: available roots were read successfully and contain no usage observations.
- `complete`: available roots/files were read without known ingestion gaps and contain observations. This describes the scan, never full account coverage or complete pricing.
- `partial`: a usable scan also has a known omission or malformed/unknown metadata.
- `failed`: no configured root was readable, or every discovered file failed verification/read. This is not a successful empty dataset.

Issue counts count affected lines/observations or directory enumeration errors; they do not estimate missing tokens. Repeated source metadata can affect several observations. Codes distinguish `missing_root`, `unavailable_root`, `no_roots`, `unreadable_directory`, `symlink_skipped`, `unreadable_file`, `unstable_file`, `source_changed_retried`, `append_deferred`, `malformed_record`, `incomplete_final_line`, `untrusted_suffix`, missing/invalid timestamps and IDs, and missing/invalid required token/cache counters. A successful retry is informational and does not itself make the result partial. Optional missing reasoning is not a missing billable category.

`Report.scans`, `source_states`, and `issue_counts` expose these results to callers. `Report.accounting_issues` separately preserves S02 reconciliation issues, including skipped reset/fork/gap intervals. Price coverage and tier assumptions remain separate valuation concerns for S04. The report command still exits zero when it successfully renders a report; that exit alone does not certify source completeness. Existing readers still return compatible Records and append readable messages; text/HTML reports also identify source states and issue counts. A complete scan can produce no accepted usage after reconciliation or range selection: these concepts are intentionally distinct.

Messages contain fixed explanations and issue codes, never exception bodies, raw lines or source contents. Issue source IDs are opaque normalized-path hashes. Observation SourceRefs retain internal source paths and physical line positions, as before; raw bytes and parsed payloads exist only during the scan. Reports never serialize the raw source payloads.

## Verified prefix and recovery policy

Each file is opened in binary, unbuffered mode. Capture its identity and initial size, read that prefix twice, and compare its bytes plus handle/current-path identity and size/mtime consistency before extracting observations. The bounded second read avoids silently trusting a buffered stale prefix. The generation fingerprint includes file identity, prefix length, and a digest of verified bytes; it is a snapshot evidence identifier, not global usage identity.

- Appending beyond an unchanged verified prefix accepts only that prefix and marks `append_deferred`/partial. A subsequent scan includes completed appended records exactly once through S02 reconciliation.
- Detected truncation, replacement or in-place mutation discards the attempted bytes and retries the entire file once. A successful retry reports `source_changed_retried`; repeated instability reports `unstable_file` and accepts no observations from that file.
- Read/access failure accepts no partial bytes from that file and reports `unreadable_file`. Other available files/providers remain usable with their own quality.
- Complete JSON objects at EOF are accepted even without a final LF. An unparsable final fragment without LF is `incomplete_final_line`; it is deferred, not reported as an observed zero. An invalid complete LF-terminated line is `malformed_record`. Strict UTF-8 decoding prevents corrupted metadata from becoming replacement-character identities.
- **Conservative corruption decision:** a malformed complete line may have contained identity, model or effort context. Accept the valid prefix before it and defer all subsequent records in that file with `untrusted_suffix` until repair/rescan. Do not silently carry context across unknown metadata. Independently valid copies can still supply supported observations through reconciliation. No missing token amount is fabricated. `source_lines` retains its older parsed-line compatibility interface; authoritative scans use this conservative suffix policy.

Discovery no longer filters by modification time. Read the available history before reconciliation and apply event-time ranges afterward, preserving out-of-range cumulative baselines. Duplicate/overlapping configured roots do not duplicate file observations. Symlink files/subfolders are excluded visibly; these scans do not establish coverage of excluded locations.

There is no committed usage database, automatic last-successful dataset cache, or retained-stale import service in this worktree. Fresh failed/partial scans are labeled honestly and never become demo data. An older caller-owned immutable result remains a separate historical snapshot; it is not silently substituted for a new scan. The transactional retained-stale publication requirement applies when persistence is introduced in S11. Provider last-successful live-limit state is separate and unchanged.

Limitations: verification is a bounded local-filesystem consistency check, not a global atomic snapshot or lock against writers. Files can change after verification. Generation fingerprints can change on append even when earlier canonical event IDs stay stable. Full histories are rescanned and one file's verified bytes are held transiently in memory; large-history performance and durable incremental recovery remain S11 work. Restored/deleted history cannot be reconstructed from a failed fresh scan without retained storage.

## Range and timezone migration

`windows/usage_time.py` defines immutable `RangeContext(start, end, timezone, label, boundary_policy="utc-half-open-v1")`. Start/end are UTC instants represented by the existing epoch-seconds type; containment is **`start <= event < end`**. This deliberately replaces the legacy inclusive end. An event exactly at the captured end belongs to a later query; starts remain inclusive.

`collect_report` captures the clock once, resolves provider ranges once, and uses them for filtering and both renderers. Compatibility `period_bounds` still returns the existing `(start, label)` pair. `Report.periods` and positional construction remain available; `Report.ranges` exposes complete contexts. Daily groups, history timestamps, displayed boundaries and offsets all use `Report.timezone`, not a later host-local clock setting.

The default is the integration contract's preferred named zone, **`America/Los_Angeles`**. This is an explicit migration from host-local day/month boundaries. `--timezone UTC` or another valid IANA name changes both boundaries and report dates, including reports opened from the tray. It is an invocation setting; persistence remains S06. Unknown/unavailable zones fail explicitly and never silently fall back to a fixed offset or host zone.

- Today and month-to-date begin at midnight/the first local calendar day in the selected zone, converted to UTC. Spring and fall DST days can be 23 or 25 hours; both repeated local-hour folds share their local day.
- Last 7 days is a trailing **168 hours**, not seven local calendar midnights.
- Session retains each provider's supplied current five-hour reset window when available. Offline queries use the existing trailing-five-hour fallback. Providers can have different starts but share the captured end/zone.

Pin the already-installed `tzdata==2026.2` runtime dependency and explicitly collect its data through PyInstaller. This supplies Windows IANA rules offline. It is not a fresh external release recommendation or pricing update.

## Verification and handoff

Use workspace-local `TEMP`/`TMP` (`windows/build/s03-temp`) and the project `.venv` interpreter.

Focused checks: **25 ingestion tests**, **10 range/CLI tests**, and the existing **35 report tests** passed. Controlled cases cover complete/empty/partial/failed sources; real temporary-file append/truncation/in-place mutation; simulated replacement-identity mismatch during a read; real replacement between scans; repeated instability; permissions/enumeration failures; malformed versus incomplete lines; EOF without LF; missing metadata; old-mtime baselines; duplicate roots; headless/privacy sentinels; midnight/month rollover; both DST transitions; exact end exclusion; provider sessions; and captured-clock/day reconciliation.

The independent accounting probes initially caught the overly strict no-LF policy: 100/100/200 instead of 200/200/250. After accepting complete JSON at EOF, all three printed comparisons returned **200/200**, **200/200**, **250/250**, `matches_expected=true`. Their exit code alone is not treated as evidence.

The initial full suite passed 134 tests in 10.104 seconds. After adding UTF-8 BOM/CRLF compatibility and a restored-mtime byte-mutation regression, the final full suite passed **136 tests in 7.692 seconds** through `windows/build.ps1` on project Python 3.14.5 with installed dependencies and `PIP_NO_INDEX=1`. Packaging succeeded. The fresh executable passed four controlled real-log text/HTML smoke checks: Los Angeles today totaled 200 and UTC today 100, with partial/corruption counts, excluded end labels, and no private sentinel. An empty `PYTHONTZPATH` forced bundled tzdata fallback. Month demo remained 108,000 / USD 0.2658. See the plan ledger for the final checks.

The physical-line provenance fixture now puts malformed data after its valid usage prefix. It still checks lines 2/4/5 and compatibility projection; the new corruption regression independently verifies suffix deferral and recovery after repair. Two legacy day/month expectations now explicitly use the named zone instead of the host zone, so they remain valid on UTC-hosted CI. No incorrect accounting expectation was adopted.

No real histories, provider credentials, live account queries, interactive tray lifecycle, macOS, Figma or remote CI checks were used. Named-zone migration can change historical calendar grouping relative to another host zone; this is intentional and visible. S04 is next: exact, versioned valuation and explicit coverage/tier policy, preserving these canonical facts, source issues and captured ranges.
