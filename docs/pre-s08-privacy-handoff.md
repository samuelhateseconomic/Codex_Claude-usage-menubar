# Pre-S08 privacy regression handoff

Prepared October 24, 2026, America/Los_Angeles. Scope: independent regression preparation for [S08](project-refinement-plan.md#s08--verify-privacy-safe-rendering-and-diagnostics), while another agent owns S04. Preparation is complete; **S08 is not complete** and its S05-S07 dependencies remain unchanged.

Starting commit: `0f4ce44`. Existing uncommitted `usage_reports.py`, `usage_records.py`, `usage_observations.py`, and `test_observations.py` changes belong to the other core work and are excluded. No production parser, valuation, UI, credential handling, or scheduler was changed here.

## Delivered checks

[privacy_cases.py](../windows/tests/privacy_cases.py) supplies synthetic logs and exercises the actual legacy readers, report renderers, saved text/HTML files, and development-preview summary/detail DTOs. It never discovers real log roots or reads credentials. These are current `/api/preview` boundaries, not tests of the proposed database or `/api/v1` contract.

[test_privacy.py](../windows/tests/test_privacy.py) verifies:

- Both providers produce a nonempty usage record while transcript content, thinking text, nested credential/header fields, and arbitrary payload fields remain absent from records, text/HTML reports, saved exports, preview queries, and details for normally typed metadata.
- Hostile strings in project, conversation, model, effort, effort source, turn ID, and notices remain escaped HTML. Parsing that output produces no injected script/image elements or event-handler attributes. Rendering preserves the original record identity.
- Report labels and notices neutralize C0/C1 controls and a bidirectional override while preserving the original record. This test covers the report renderer, not every terminal/tray path.
- A failed preview scan returns a safe actionable diagnostic; generic query failures return fixed error codes rather than exception bodies. Synthetic query strings and session cookies do not appear in captured request logs or those error responses.

Existing provider credential/redirect and unexpected-exception tests remain in `test_usage.py`; they were run rather than duplicated.

## Confirmed gaps and repair handoff

### PRIV-01: legacy Codex malformed metadata can expose nested content

Synthetic nested objects placed separately in session ID, project path, model, and turn ID are coerced to strings by `read_codex()`. Their nested content reaches normalized records and public report/preview outputs. HTML escaping prevents markup execution but does not remove the exposed text.

Acceptance: reject non-string metadata before projection, retain a safe unknown/source-local identity where appropriate, and record structured invalid-field issues. Never stringify dictionaries/lists into metadata. Do not silently discard supported token facts or merge unrelated weak identities. Reuse the observation contracts once their acceptance path is ready rather than maintaining competing normalization policies.

Owner handoff: core reader/observation integration, followed by S08 verification. Fixture fields: `session`, `project`, `model`, `turn_id`.

### PRIV-02: legacy Claude malformed metadata can expose nested content

The same construction in session ID, model, and user-turn UUID reaches records or detailed reports through `read_claude()`. Normally located message/request/credential content stays excluded; this gap concerns invalid values inside metadata slots.

Acceptance: typed metadata projection and safe fallback/issue semantics, with no nested-content exposure in records, saved reports, summary/detail DTOs, or diagnostics. Preserve valid streamed-message identity and token accounting.

Owner handoff: core reader/observation integration, followed by S08 verification. Fixture fields: `session`, `model`, `turn_id`.

### PRIV-03: live Codex limit labels retain terminal controls

A synthetic `limitName` containing ESC and C1 OSC controls passes through `parse_codex()` into `Window.text()`. Report-specific cleaning does not protect this live-limit path. This is separate from the locally recorded token report and does not establish a browser code-execution issue.

Acceptance: validate provider label types at extraction and neutralize terminal controls at the display boundary. Preserve internal identities and normal Unicode labels; test active/stale tray lines and every terminal path that displays live snapshots.

Owner handoff: S07 provider/display boundary and S08 verification. Fixture field: `limit_label`.

## Explicit failure policy

The three strict regression assertions are marked `expectedFailure` while these repairs remain outside this preparation slice. They count as **open defects**, not passing privacy gates. A repair produces an unexpected success until its marker is removed and the test is reviewed.

[review_privacy_probes.py](review_privacy_probes.py) also checks all three cases independently. Unlike the older accounting probe, it **returns exit 1 when any gap remains** and prints only case identifiers and unsafe metadata-field names. It returns 0 only when every checked gap is resolved. Do not weaken assertions, change expectations to match leaking output, or add skips to make the S08 gate appear green.

Run from the repository root:

```powershell
$privacyTemp = Join-Path $PWD 'windows\build\privacy-temp'
New-Item -ItemType Directory -Path $privacyTemp -Force | Out-Null
$env:TEMP = $privacyTemp
$env:TMP = $privacyTemp
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -p test_privacy.py -v
.\windows\.venv\Scripts\python.exe docs/review_privacy_probes.py
```

Focused result: eight tests ran; **five passed and three were expected failures**. The first sandbox run could not connect to loopback (WinError 10013); the rerun with loopback access executed the diagnostic assertions successfully. Full working-tree result: **88 tests ran in 9.004 seconds, 85 passed and three expected failures**, including the other agent's observation tests. The strict probe exited **1**, listing all four Codex fields, all three Claude fields, and the live label. This is reproducible defect evidence, not a privacy release pass.

Commit isolation: the staged snapshot was exported into an ignored workspace directory with the committed core baseline, excluding the other agent's edits. It ran **74 Python tests in 8.446 seconds: 71 passes and three expected failures**. The same strict probe exited 1 for all three documented gaps, and both existing Node formatter/axis tests passed. Staged whitespace and changed-document link/fence checks passed. This confirms the new tests do not depend on the uncommitted observation modules.

## Artifact and release boundaries

- Generated saved reports default to `%LOCALAPPDATA%/UsageTray/Reports`, with `~/.local/share/UsageTray/Reports` as the fallback. Explicit output paths remain caller-selected. Current reports have no automatic retention bound; S07 owns that policy. Project names, full conversation IDs, and source notices can contain private local paths even when transcript content is absent. HTML exports already disclose that metadata scope.
- Test files live in workspace-local TEMP/TMP. Fixture `TemporaryDirectory` contexts remove only their owned synthetic files. No source history or user artifact was deleted.
- The development dashboard uses an in-memory snapshot, disabled HTTP request logging, and bundled static assets. There is no persistent database, diagnostic-export feature, or retention system to certify here. Normal preview query DTOs intentionally preserve metadata for safe UI rendering; HTML escaping belongs at rendering boundaries.
- The new HTML checks exercise the Python exporter. Browser DOM injection, complete JavaScript sink coverage, unsupported HTTP methods, all provider response variants, packaged lifecycle, crash dumps, database persistence, settings, and future redacted diagnostics remain unverified by this slice. No new Figma or browser action occurred.
- No production behavior or packaging dependency changed, so no rebuild was run. Existing packaged evidence is described in the [dashboard handoff](dashboard-implementation.md); it does not certify these privacy repairs.

Next: preserve this regression handoff while S04 finishes, then apply the core/shared-service/runtime changes through S05-S07. Full S08 must resolve these findings, remove the expected-failure markers, expand coverage to the final serializers/diagnostics, and obtain probe exit 0 before its gate can pass. The separate accounting defects remain governed by S02; no accounting gate is claimed here.
