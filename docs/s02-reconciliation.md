# S02 observation-first reconciliation

Status: **complete in the isolated refinement worktree**. Started from `e23f62f` on `codex/s01-observation-contracts`. The original shared checkout and remote were not updated.

This implements the accounting gate in the [refinement plan](project-refinement-plan.md), using the [S01 contracts](s01-observation-contracts.md). The [historical evaluation](project-evaluation-2026-10-23.md) remains the evidence for the original defects.

## Result and integration

Both public readers now extract observations across their eligible files before invoking the pure [reconciler](../windows/usage_reconciliation.py). They project accepted canonical events back to the existing `Record` interface and append safe issue messages to existing report notices. Terminal and HTML consumers use these corrected records; no GUI, pricing, or provider imports are required by reconciliation.

- Complete `100,200` plus partial `200` retains **200** with either file order, reversed roots, or repeated imports.
- `100,200,50,100` retains **250**: initial 100 + next 100 + final 50. The unknown reset transition remains excluded and visible.
- Copied suffixes spanning multiple resets preserve totals, epoch identity, and supported source mappings.

Canonical events use reconciliation version `reconciliation-v2`. Accepted event provenance includes the contributing observation references and, for a cumulative delta, its supporting baseline references. Repricing is not part of identity. Extraction now explicitly records whether Claude effort came from message/request metadata, so a missing later stream field does not erase an earlier explicit value or get confused with inherited user-turn effort.

## Ordering, duplicate evidence, and epochs

Provider conversation identity establishes the conversation namespace. Missing identity remains source-local with a warning; unrelated same-basename files cannot merge. Repeated identical source references are idempotent. Contradictory observations at one source reference exclude the affected conversation rather than overwrite evidence.

For Codex cumulative histories:

1. Group matching observations by timestamp and the three native cumulative categories. Reasoning and model/effort context are additional evidence, not extra token categories or standalone identity.
2. Between timestamps, use chronological order. If a source's physical sequence contradicts its timestamps, exclude that conversation visibly.
3. Within one timestamp, derive directed ordering edges from each source's physical sequence. Accept only a unique complete ordering. Missing ordering evidence or a cycle excludes that clock interval; numeric magnitude and filenames do not resolve ambiguity.
4. Merge compatible missing copy context. Conflicting model labels become `unknown` and remain unpriced; conflicting effort or turn attribution becomes unknown with a metadata issue. Same-clock repeated counters with conflicting contexts keep their quantity while qualifying attribution.
5. Derive category deltas once from the reconciled sequence. A decrease creates a new epoch anchored in the prior epoch and transition evidence. Exclude the transition but retain subsequent valid increments, even when a numeric total recurs.
6. Zero-delta notifications never create another charge. They do not change the anchor used for a later reset epoch, and later notifications do not relabel an already accepted earlier event.

Event IDs combine the provider/conversation, reconciliation version, epoch, point evidence, and source kind. A timestamp/counter fingerprint is only a reconciled point within this process: it is not sufficient to establish global identity by itself. Multiple occurrences of an indistinguishable point within the same clock bucket can create an ordering cycle; that unsupported ambiguity is excluded instead of aligned by occurrence number.

A non-fork initial cumulative point retains the compatibility zero-origin assumption, now recorded as quality and a notice. Missing earlier reset history cannot be reconstructed. Fork history before the recorded creation boundary seeds counters without becoming child usage. A fork with only post-creation counters seeds from its first available point, excluding that uncertain interval; counting resumes on later supported increments. Conflicting or unavailable fork boundaries exclude the conversation.

Missing/invalid core counters and unordered intervals break the usable baseline. The next complete point re-establishes it without a charge; later supported deltas resume. A cache-read increment exceeding inclusive input is excluded, while its complete cumulative point can still support subsequent valid deltas. Unknown excluded token amounts remain null in accounting issues.

## Last-usage fallback and Claude streams

Codex histories with no cumulative evidence use available message/request identity for updates, otherwise labeled timestamp-and-counter deduplication. Different unidentified last-usage values at one timestamp are ambiguous and excluded. When a conversation also has cumulative history, last-only observations are excluded to avoid double charging overlapping work; this may omit an unsupported tail and is explicitly reported. The reconciler does not guess how to combine those two measurement modes.

Claude preserves message/request identity and category maxima across streamed updates and copies, attributing the result to the latest supported timestamp. A missing request ID may join a message only when its available request identity is unambiguous; otherwise that weaker observation is excluded. Explicit effort takes precedence over inherited turn metadata; contradictory explicit values produce unknown effort with a visible qualification.

Detailed cache-write TTL counters take precedence over legacy aggregate writes for the same message. The aggregate must fit the retained detailed category maxima; contradictory representations exclude the message. This prevents assigning an earlier legacy total to five-minute writes and then also adding the final one-hour category. Without details, a valid legacy aggregate uses the existing labeled five-minute price assumption. Unknown required categories are excluded rather than invented as zero.

## Verification evidence

The first two normal regression tests were run before the fix. Truncated-first/repeated-import/root-order cases failed at **300 vs 200**, and the reset test failed by omitting the final 50-token increment. They then passed under the reconciler.

Focused final results:

- **28 reconciliation tests passed**, covering file/root order, repeated imports, reset suffixes and permutations, tied timestamps, cycles, zero notifications, fork baselines, counter gaps, cache invariants, metadata conflicts, last-only/mixed modes, Claude stream/cache transitions, shared renderers, and a headless import subprocess.
- **16 observation tests passed**. One provenance-only fixture accidentally declared a fork at the same instant as its sole usage point; that declaration was removed so it tests ordinary projection. Separate S02 tests now assert the conservative missing-fork-baseline behavior. No buggy accounting expectation was retained.
- Independent probes printed **200/200**, **200/200**, and **250/250** (observed/expected); all three `matches_expected` values were true. The script's exit code alone remains insufficient evidence.
- Full project suite through `windows/build.ps1`: **101 tests passed in 6.445 seconds**, no skips reported.
- Windows build succeeded with the project Python **3.14.5**, pinned installed dependencies and `PIP_NO_INDEX=1`; no dependency changes. Worktree-local TEMP/TMP was `windows/build/s02-temp`.
- The freshly built executable processed controlled synthetic reset/overlap log files, with isolated source/config roots, in both text and HTML modes: **250** tokens, **USD 0.000625** underlying fixture expectation rounded to **0.0006** in each report, and a reset notice. Both exited zero; no demo substitution occurred.
- Packaged offline demo still showed DEMO, **108,000** tokens, and **USD 0.2658**. Saved-output checks used hidden processes; no live tray or provider request was launched.
- Documentation links, fences, whitespace, and `git diff --check` passed.

Commands ran from this worktree using its existing project virtual environment:

```powershell
$env:TEMP = Join-Path $PWD 'windows\build\s02-temp'
$env:TMP = $env:TEMP
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -p test_reconciliation.py -v
.\windows\.venv\Scripts\python.exe -m unittest discover -s windows/tests -p test_observations.py -v
.\windows\.venv\Scripts\python.exe docs/review_accounting_probes.py
$env:PIP_NO_INDEX = '1'
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build.ps1
```

## Limits and next handoff

These fixtures establish supported reconciliation behavior, not complete-account accuracy or certification of every provider log shape. Conservative exclusions can reduce reported usage; their unknown amounts must not be treated as observed zero. Canonical accounting issues are structured, while current compatibility reports expose readable notices. General ingestion completeness, source generations, append/truncation/replacement recovery, old-mtime discovery, and timezone/range migration remain **S03** work.

Valuation still uses the existing float path and request-tier assumptions until S04. A new shared query/summary result remains S05. No database/API/UI redesign, live-history scan, account comparison, macOS run, external Figma action, CI execution, merge, or push occurred in S02. The separate shared checkout's competing implementation remains outside this validation.

Next ready session: **S03 — explicit source quality, recovery, and time**. Preserve these canonical regression expectations while improving the scanner; do not reintroduce per-file delta derivation or suppress exclusion notices to make totals look complete.
