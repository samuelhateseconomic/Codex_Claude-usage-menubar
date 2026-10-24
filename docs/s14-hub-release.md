# S14 packaged hub release record

Status: implementation and local automated acceptance complete on the refinement branch, starting at `7e3e832`; hosted verification pending. Native/distribution sign-off is unrun, so the full S14 release gate remains open. Application **0.13.0**. This document separates executable checks, browser interaction, simulated native menus and unrun distribution checks. The [refinement plan](project-refinement-plan.md), [integration contract](usage-hub-integration-plan.md) and [S13 runtime handoff](s13-runtime-integration.md) own the supporting contracts.

## Delivered changes

The actual 0.12.0 executable exposed slow queries on the established 40-file / 4,000-event fixture. Diagnostic authenticated HTTP samples were Overview **1.881183–3.500919 seconds**, conversation page **1.772706–2.472664**, and facets **7.249814–10.234307**. These samples overlapped investigation; they are evidence of a problem, not an isolated speed comparison. Profiling found repeated dataclass dictionary/deep-copy work in token addition and repeated full summaries for unfiltered facets.

Version 0.13.0 adds direct five-category integer addition, day conversion only for the day dimension, endpoint-specific grouping and reuse of the current authoritative facet result when self-omission changes no filter. It reuses immutable core query results within one owner, capped at **8 core queries and 20,000 matched detail references**. The owner also retains at most one decoded publication of up to 10,000 events within the existing 64 MiB event-metadata read limit. A serialized read connection checks SQLite `PRAGMA data_version` on every request, so any external commit invalidates that publication, including job/failure/coverage updates or manual SQL. File identity changes reset the reader. Each decoded generation also invalidates derived result reuse, so the two cache layers cannot disagree after a commit or reconnection. This follows the same-connection invalidation semantics in the [SQLite documentation](https://www.sqlite.org/pragma.html#pragma_data_version). The library path keeps fresh per-call reads; only the owner enables persistent reading and closes it after HTTP/jobs drain. The current publication and frozen context are validated before result reuse. Publication versions, source quality, freshness and the complete captured query context form the reuse boundary. A read failure still fails; changed facts, fees, rates, coverage or range cannot silently use an old result. API envelopes, pagination and mutable wire objects are rebuilt. There is no alternate arithmetic, browser valuation, on-disk cache or schema change. Failed reads close/reset the reader and propagate an error. No transaction is held between requests.

Explicit offline/API tray hosting also honors the saved report preference, matching the ordinary tray path. The existing settings JSON stays authoritative; default fees remain Codex USD20 and Claude USD20. Pricing/reconciliation/query semantics and released migrations 1–3 are unchanged.

## Repeatable executable acceptance

After `windows/build.ps1`, run from the repository root:

```powershell
.\windows\.venv\Scripts\python.exe windows/tests/packaged_dashboard_smoke.py --exe windows/dist/UsageTray.exe
.\windows\.venv\Scripts\python.exe windows/tests/packaged_local_hub_smoke.py --exe windows/dist/UsageTray.exe
.\windows\.venv\Scripts\python.exe windows/tests/packaged_hub_release.py --exe windows/dist/UsageTray.exe --measurements windows/build/hub-release-measurements.json
node --test windows/dashboard/tests/*.test.mjs
```

The new harness creates only owned synthetic files, contains every launched executable in a Windows Job Object, closes database handles and retries only bounded fixture cleanup. It performs these checks against the executable:

- First launch discovers per-user settings/database paths without `--config`, uses local frontend/icons/fonts and a bundled named timezone, and starts an offline real namespace without a development server.
- Anonymous reads, hostile Host/Origin, missing/wrong CSRF, wrong native control, absent-origin bootstrap, grant replay, expired grants, path traversal and preview access are denied. Shared-cookie tabs retain their CSRF value; independent cookie jars retain separate sessions. No authority is granted by fetching the public shell/assets.
- The second executable reuses the original owner, profile, publication and frozen query. Browser/HTTP connections are clients rather than the process owner.
- A populated schema-2 fixture upgrades through the bundled migration while preserving dataset identity and a verified old-schema backup/settings pair with all 4,000 facts. The fixture uses the authoritative writer, then removes only the two migration-3 tables/version entry inside its owned synthetic database; this reproduces the unchanged released schema-2 shape and is not a product downgrade feature. Restore uses new explicit paths and that copy upgrades/queries through the executable.
- A real import is observed running, then only the owned process tree is terminated before publication. Old facts/revision remain coherent. Relaunch replaces stale discovery/native/session capabilities, marks the old job interrupted, and publishes the entire new source generation.
- Fee settings survive compute/restart without changing canonical usage or API-equivalent value. Invalid requested settings preserve the accepted offline dataset, report an invalid configuration and return a safe settings failure. Explicit diagnostics omit transcript/credentials/capabilities/raw errors.
- Unsupported optional index versions are preserved and rejected, while the existing terminal report still works directly from approved synthetic roots. Application artifacts and reports exclude the transcript sentinel.

The retained smoke checks still reconcile the controlled **2,840,000 tokens / USD18.42** real fixture, the **8,920,000 / USD49.506** explicit demo and the **108,000 / USD0.2658** terminal demo. Synthetic accounting is not a current API price verification, real bill or account coverage claim.

## Timing method

The release harness imports **40 files / 4,000 accepted events / 4,000,000 tokens / USD8.000000000000**, spread over 40 conversations / 5 projects. It makes three captures. Overview timing includes authenticated HTTP Overview plus status. Explore timing follows existing browser navigation: frozen Overview, concurrent conversation page/facets, then status. Readiness/import time is excluded; provider calls are disabled. Exact full-result totals and facet record counts are asserted every time.

The JSON measurement artifact records machine/runtime/fixture size and all six durations. The initial target is under two seconds on this fixture; results are reported separately from correctness and are not a cross-machine SLA. HTTP bundles exclude browser JavaScript validation/layout/paint. The first result-reuse build passed functional executable acceptance, but its HTTP bundles still exceeded the target: Overview **2.889450 / 1.945617 / 1.196709 seconds**, Explore **3.521480 / 2.051891 / 2.146308**. This measured snapshot decoding cost motivated the owner-only reader; final measurements are recorded below.

## Local and hosted evidence

Final local source/build: **376 Python tests / 145.868 seconds**, PyInstaller **6.16.0**, executable **0.13.0**, **18/18** core executable checks. The final generation-binding API regression is included; focused API **45 / 41.296 seconds**, launch/clean-Quit **14 / 10.471 seconds**. Frontend **79 / 11,108.7254 ms** passed; no frontend source changed during S14. Independent probes print **200/200**, **200/200**, **250/250**, all `matches_expected: true`. Final packaged real/demo compatibility and hosted evidence are recorded at closing below.

The final executable passed the new release harness, including populated migration/backup/restore, actual interrupted job/restart, safe invalid-settings retention/diagnostics and exact audit terminal fallback. The first harness iteration incorrectly required a particular compact spelling of 4M; corrected it to assert the exact **4,001,000** audit counter rather than rounded shorthand. No accounting expectation was weakened.

Machine: Windows **11 10.0.26300-SP0**, AMD64, **22 logical CPUs**, project Python **3.14.5**. Synthetic fixture **851,070 source bytes**, 40 files / 4,000 events / 40 conversations / 5 projects. Final HTTP bundle samples:

- Overview: **2.926127 / 1.580168 / 0.956412 seconds**.
- Explore: **0.298711 / 0.279458 / 0.438928 seconds**.
- The first cold Overview exceeds the initial two-second target; later Overview and all Explore samples meet it. The JSON correctly records `all_http_bundles_under_target: false`. This remains an explicit startup-performance limitation. No timing threshold is forced on heterogeneous CI runners.

Actual browser acceptance used the **packaged executable and its real production listener/assets**, without a development static server. The native one-use handoff was removed from the URL, and another tab resumed the shared cookie session without obtaining a second runtime. Tabs kept independent selection; two loaded settings drafts produced a safe conflict when one changed the synthetic fee 20→21 and the other tried 22. The second draft remained typed; Reload showed the saved value, and 20/20 were restored. Pending computation was visibly labeled. Summary stayed **4,000,000 tokens / USD8**, conversation detail **100,000 / USD0.20**, first event **1,000 / USD0.002**, reasoning not recorded. Escape restored the second cursor page and opener focus; browser reload retained that page/provider/page size. Closing every test tab left the service running; a new tab resumed authentication and read the same full totals with default fees. DOM width **1265**, scroll width **1265**; no horizontal document overflow at that viewport. Narrow resizing is not supported by this browser surface and was not claimed. Temporary browser tabs/helper were closed after screenshot capture. No native taskbar action was simulated as a browser result.

Executable identity: `exe-sha256:c1801edd6fcfdea508caec146abd19de0e4745d83ec3d85ba43b0fc04960024c`. Hosted verification must identify the exact source commit; documentation-only follow-ups do not change this binary.

## Native and distribution limits

The installed Windows computer-use skill was read and the current native window inventory inspected. The taskbar/tray is not exposed as a targetable window; only Firefox and Codex were returned. No native tray-menu click or terminal-viewer playback is claimed. Existing actual menu code is exercised with a simulated icon, and real owner/job/provider/HTTP shutdown checks remain separately identified.

Before public distribution, manually verify the built executable's tray icon, explicit dashboard action, report viewer and Quit/relaunch on an accessible Windows desktop. Closing all browser tabs must leave the tray running; Quit must remove the owner and stop the local service. First owner settings/profile remain authoritative: quit/relaunch after updating the executable or changing offline/live mode. Existing sessions intentionally expire rather than persist across restarts.

No live provider/account login verification, new real-history scan, physically network-disconnected machine, installer/signing, native Figma playback, macOS, full accessibility/security certification or storage-device power-loss certification was performed. All browser assets are local and runtime checks use offline synthetic roots with no provider fetchers, but that is distinct from a physically disconnected clean machine. A narrow viewport interaction check is unrun unless later evidence below explicitly records one. The separate original/main checkout and Agent 2's uncommitted work remain untouched; integrating that checkout is a separate requested action.


## Hosted harness follow-up

[Initial S14 matrix 40141208923](https://github.com/samuelhateseconomic/Codex_Claude-usage-menubar/actions/runs/40141208923) at `a2e51b1f9d68ed2b0df4f2cbff3fd0687fcc226e` passed 376 Python / 79 frontend / 18 core executable checks, both retained launchers, populated migration, packaged authentication/expiry and actual job/restart checks in all four runtimes. Overall conclusion was **failure**: Python 3.13/3.14 raised SQLite `disk I/O error` in the new test harness when it tried to set an unsupported version on the just-terminated WAL fixture. Python 3.11/3.12 completed the whole release check. This is not accepted as a green matrix.

The unsupported-index case now restores the verified backup to separate **new** index/settings paths before setting version99 and exercising failure plus exact terminal fallback. It never edits the deliberately terminated owner's DB/WAL. No I/O error is ignored, no general retry is added, and the actual app/crash/restart assertions stay intact. Two regressions verify that original index, backup and settings remain byte-identical, and that existing destination files are refused. Focused fixture suite: **4 / 0.876 seconds**, including the two existing real Windows sharing tests. Application source and the tested `c1801edd...` binary are unchanged by this harness correction. Final hosted revalidation follows.

The new local fixture-isolation rerun measures Overview **1.324439 / 0.631449 / 0.629116 seconds**, Explore **0.153870 / 0.157759 / 0.148966**, all under target. Same executable/machine/fixture; retain the earlier cold **2.926127** observation as performance variability rather than discarding it. Initial hosted samples also all fell below two seconds on their four-CPU Windows runners; final CI artifact values are reported separately.
