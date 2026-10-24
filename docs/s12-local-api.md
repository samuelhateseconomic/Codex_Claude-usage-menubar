# S12: versioned local API and owner/job lifecycle

Status: implemented; local acceptance gates pass and hosted verification is recorded in the refinement ledger. S11 is the storage prerequisite; this session adds a production headless API. The existing reviewed dashboard still uses its explicit demo preview until S13. No real histories, provider credentials, authenticated accounts or external services are needed by the synthetic acceptance path.

## Start and ownership

From the repository root, use the project interpreter:

```powershell
.\windows\.venv\Scripts\python.exe windows\usage_api_main.py
# Explicitly open the local authenticated service status page:
.\windows\.venv\Scripts\python.exe windows\usage_api_main.py --open
# Explicitly enable existing CLI live-limit adapters and host the existing tray:
.\windows\.venv\Scripts\python.exe windows\usage_api_main.py --tray --live-limits
```

Default port is 8765; `--port 0` selects an available loopback port. `--config` and `--index` are explicit native configuration/recovery paths, never HTTP inputs. Default API launch is offline with respect to providers: it imports approved local logs, but does not read credentials or poll accounts. `--live-limits` explicitly opts into the existing adapters and independent five-minute/backoff scheduler. Automatic local imports run on owner startup and at a five-minute minimum while this process is alive. This is not a Codex scheduled automation or a persistent OS service.

One S07 `RuntimeOwner` owns the installation; one S12 worker runs SQLite import/reprice jobs. Repeated launches with the same index/settings paths reuse the existing process through a native capability exchange; they do not start a second writer/provider scheduler. Hosting/provider flags apply when creating the owner; reuse does not silently reconfigure a running host. Quit/relaunch that owner to change its hosting mode. An already-running legacy tray without this API is reported honestly; it is not killed or bypassed. The combined `--tray` mode injects the same `PollingRuntime` and a committed-index report callback into the existing tray. Legacy standalone terminal/report/tray modes remain; offline reports/diagnostics do not acquire the polling owner. Legacy CLI settings saves now acquire the owner and recheck their loaded version, refusing competing writes while an API/tray owner controls settings. Use the running settings API or quit that owner before a native CLI save.

The S12 checkpoint starts through `usage_api_main.py`. The [S13 runtime integration](s13-runtime-integration.md) adds the real dashboard/native launcher; S14 validates final packaged hub delivery. Existing packaged terminal/demo paths remain compatibility gates.

## Component ownership

- `usage_api_query.py`: headless v1 query normalization, frozen contexts, facets, stable exact-key paging and metadata DTO projection. It calls the S05 service over an immutable S11 `IndexSnapshot`; it does not implement token or valuation arithmetic.
- `usage_api_contract.py`: exact numeric/time projections, safe API errors, strict JSON input and the bounded schema vocabulary validator used by contract tests.
- `usage_api.py`: status/settings/jobs/limits/read/mutation routing. Production accepts only the explicit real index; the separate labeled demo preview cannot expose cached real limits.
- `usage_api_http.py`: session bootstrap/resume, authenticated reads, Host/Origin/CSRF protections and bounded HTTP transport. `usage_hub.create_server` remains the shared loopback server factory and selects preview versus v1 explicitly.
- `usage_jobs.py`: durable queued/coalesced import/reprice operations, configuration activation/recovery, work status and one worker. No raw errors/provider payloads are stored.
- `usage_api_limits.py`: latest safe active-account quota/check projection, independent provider eligibility, last-successful retention and persistence. Usage query routes never poll providers.
- `usage_api_runtime.py`: application owner, native reuse/discovery, optional shared tray and orderly shutdown. `usage_api_main.py` is the explicit native CLI.
- `usage_index.py`/`usage_service.py`: one committed snapshot, normalized project filtering/counting, shared aggregation/exact sorting and optional approved-root subset imports. No competing schema is introduced.

## Machine-readable contract and examples

Use [OpenAPI 3.1](api/usage-hub-v1.openapi.json), [response JSON Schema](api/usage-hub-v1.schema.json) and [20 actual synthetic response examples](api/usage-hub-v1.fixtures.json). `windows/tests/api_fixture_responses.py` constructs the examples through real extraction/reconciliation/index/query/job operations; they are synthetic ordinary local imports, not authenticated account readings or production demo seeding. The example collection intentionally includes different publications/filters/coverage states and is not one live reusable query session. IDs and request IDs are opaque examples, not secrets or persistent live capabilities.

Every successful response has contract version, dataset/mode, generated UTC instant, request ID, response kind and `data`. Usage responses add context ID, usage/pricing/configuration versions, frozen range and applied filters. `usage_revision` is an integer string; token categories/totals and nullable reasoning are integer strings. Money/rates are decimal strings, never JSON binary floats. Small bounded counts/page sizes are integers; quota percentages are finite numbers. Errors contain safe `error.code/message`, optional field/retry information and a request ID. A 429 limits response also retains its per-provider operation results.

The project validator implements exactly the JSON Schema vocabulary used by these files (`$ref`, `anyOf`, types, const/enum, required/extra fields, patterns and numeric/string/array bounds); it is not a general replacement for a complete JSON Schema engine. The checked-in schema is standard JSON Schema for other clients to consume. Semantic gates additionally assert signed-64-bit token bounds, category sums, reasoning subset, exact decimals and accounting outcomes.

## Read routes

All routes are below `/api/v1` and require the local session, except the one-use bootstrap exchange.

- `GET /session`: resume the current authenticated browser session and obtain its CSRF token in memory after reload. It does not grant a new session from an unauthenticated root-page visit.
- `GET /status`: active/requested versions, readiness/freshness, source scan counts, active/latest durable job state, last completed local import time and cached provider states. Invalid current settings are labeled `configuration_state=invalid`; committed usage remains readable.
- `GET /overview`: one matched summary, daily series, provider/model-effort breakdowns, top projects, recent conversations, comparison qualifications and separate ingestion/accounting issue counts.
- `GET /usage/conversations`, `/usage/projects`: full matched summary plus a bounded page. Conversation rows contain matched project/model/effort sets. Projects use dataset-scoped normalized identity across provider/event labels.
- `GET /usage/facets`: project/model/effort options under all other filters, omitting that facet's own selection; selected zero-match options stay visible.
- `GET /conversations/{id}`: matched summary and separately labeled lifetime first/last accepted usage, including multi-project/model sets. A known conversation with no matched events returns an empty matched summary and its lifetime metadata; an unknown ID is 404.
- `GET /conversations/{id}/events`: chronological accepted metadata/valuation evidence, no transcript. Reasoning stays within output; missing values remain null.
- `GET /limits`: latest cached active-CLI-account state, all validated quota windows, last attempt/success and next eligible UTC times. It does not accept report/date filters or imply account matching with local logs.
- `GET /settings`: validated editable fees/timezone/flat overrides/report preference, bounds and approved root IDs with safe basename/hash labels. No credential files, raw payloads or arbitrary root paths are returned.
- `GET /jobs/{id}`: durable queued/running/succeeded/failed/superseded status, safe phase/code, counts, times and resulting versions.

First-release query inputs are `dataset_id`, repeated lowercase `provider` (`codex`, `claude`), `period` (`today`, `week`, `month`), IANA `timezone`, repeated `project_id`, `model`, `effort`, literal metadata `q`, `selected_day`, sort/page size/cursor and context/base-context IDs. Missing provider means Both; an explicitly empty/unsupported selection is invalid. Selections combine OR within a category and AND across categories. Search covers project/conversation/model metadata, not prompts or regex; maximum 200 characters after trimming. Case-folded returned search can expand to 400 characters; keep the original user input for editing and use context IDs for unchanged follow-ups. Project IDs are validated within the dataset; unknown models remain unpriced rather than receiving fallback rates.

## Frozen queries and paging

A first usage request captures one clock, named zone, UTC `[start,end)` range, normalized filters and complete publication tuple. `query_context_id` requests that query unchanged; conflicting explicit fields are 422. `base_query_context_id` derives replacement filters while preserving range and versions; preset/timezone changes require a new initial query. The two context fields cannot be combined. Only an initial request/explicit coordinated refresh or preset/timezone change captures a new clock. Contexts expire after 30 minutes, with at most 1,024 in memory. Restart/expiry returns 409 `context_expired`; a changed committed tuple returns 409 `revision_changed`, requiring related widgets to refresh together. Old database snapshots are not promised.

Selected local days intersect the frozen preset and honor DST (including the 25-hour fall-back day); days outside it are rejected. Responses expose base and effective bounds. Provider-only calendar-month-to-date can compare full fees; day/project/model/effort/search filters disable comparison. Fees remain the one S06 source, initially USD 20/20; signed differences and partial-price qualifications are estimates, not bills or realized savings.

Default list ordering is exact priced subtotal descending, unpriced-only after priced zero, then stable opaque ID. Other list sorts are tokens descending and last matched activity descending; event pages use UTC occurrence/event ID ascending. Page size defaults to 50, allowed 1–100. HMAC-authenticated opaque cursors bind context, endpoint, sort, size and last exact key/ID; client offsets/SQL are never accepted. Malformed/tampered or conflicting cursors are rejected. Headlines/charts/facets always cover the full matched result, not the page. Frontend changes of filters/view/sort must clear the appropriate cursor and retain Back/list position in S13.

Inputs are bounded to a 16 KiB URL, 256 query fields, 64 values per metadata filter, 128 root IDs and a 1 MiB JSON body. Request duplicate keys/non-finite JSON/unknown fields/invalid UTF-8/URL escapes are rejected. Responses are capped at 8 MiB. Initial snapshot work is capped at 100,000 events and 64 MiB of event metadata; excessive work returns a safe 503, never silently truncated accounting. The adapter currently loads a whole committed snapshot before filtering, so these are supported-index bounds, not optimized arbitrary-large-history promises. S14 measures the agreed final API/UI fixture.

## Jobs, configuration and provider state

Migration 3 adds `jobs` and latest `provider_cache`; released migrations 1/2 are unchanged and older indexes receive S11 consistent backup/configuration protection before upgrade. Job uniqueness coalesces equivalent active requests. Queue capacity is 32; retain 1,000 latest completed states plus active jobs. A restarted owner marks abandoned running jobs interrupted; queued work survives. New configuration supersedes queued older configuration work. Successful job outcome/versions/counts commit in the same S11 transaction as the publication, through a trusted internal commit hook; a crash after commit cannot turn completed work into an interrupted job. Repricing never changes canonical tokens; failed work retains the previous publication and safe failure status. A failing job does not retry in a tight loop; normal owner cadence is at least five minutes.

`POST /index/refresh` accepts `{}` for enabled roots or `root_ids` already approved in local configuration. A subset rereads selected roots while preserving other accepted evidence/status and reconciles the entire retained conversation set. Root-configuration changes require a complete import before subset activation. Return 202 for new work or 200 with its coalesced current job. No arbitrary path/shell parameter exists.

`PATCH /settings` requires `expected_configuration_version` plus a changes object. Allowed changes are explicit decimal-string/null fees, decimal-string exact-model flat overrides, timezone, report preference and enabled approved root IDs. Disable/re-enable is distinct from deleting retained history. Validate the whole draft and acquire the writer before saving JSON; version conflict, busy writer or queue rejection does not silently replace settings. JSON is authority, with active database projection separate. An interrupted JSON-save/DB-queue boundary is recovered on restart; old complete results remain readable and pending is visible. Native configuration edits outside the owner are not a transactional cross-store system; S11 detects version drift and recovery requeues required work.

`POST /limits/refresh` accepts selected providers. Return per-provider accepted/in-progress/cooldown/unavailable outcomes independently; 202 for accepted work, 200 for coalesced/unavailable results, 429 only when all selected providers are cooling down. Reuse S07 locks/minimum cooldown/backoff and preserve the last successful snapshot on failure. Persist safe UTC check/eligibility projections, never monotonic deadlines; restart derives new in-process deadlines from the remaining UTC delay. No quota history, account activity import, credential modification or ordinary ChatGPT usage is introduced.

## Local authentication and lifecycle

Bind only `127.0.0.1`. Require the exact Host including port, reject foreign/multiple Origins and cross-/same-site foreign fetch metadata, and disable CORS. Protect metadata reads with an expiring process-local session, not merely loopback connectivity. A plain root GET serves a static status shell and never creates authentication.

An explicit native launch supplies a 30-second, one-use URL fragment handoff. The local bootstrap script removes it before exchanging it, receives an HttpOnly/SameSite=Strict cookie (API path, one-hour process-local session) and keeps CSRF only in memory. Authenticated `/session` resumes that session after reload. Further native handoffs reuse/renew a valid browser session instead of invalidating another tab's CSRF state. All mutations additionally require exact Origin and the per-session CSRF header. Expired/replayed grants and unauthenticated reads fail safely. No long-lived URL secret, localStorage/sessionStorage credential, external script/font or permissive CORS is used.

Native process reuse uses a process-lifetime capability in a sibling owner discovery file. It contains only loopback origin, capability and hashed index/configuration identity; it is never a browser bundle/settings/diagnostic/database field. POSIX mode is 0600; Windows relies on the private per-user application-data directory's inherited ACL. Keep custom application directories private. This boundary targets hostile browser origins and accidental concurrent launches; it does not certify protection from malicious software already running as the same OS user. On orderly Quit the owner removes discovery; a crash leaves an unusable old capability that the next owner replaces. Native/client output prints only the origin, not launch/session/control secrets.

One owner closes provider workers, rolls back interrupted jobs, closes HTTP and releases ownership only after its workers stop. Browser close does not stop the tray/service; app Quit does. Provider cancellation retains S07's known adapter limits; process-crash tests are not power-loss or arbitrary hostile-local-process certification.

## Accounting fix discovered by the API gates

A true multi-project conversation fixture exposed Claude extraction retaining the first `cwd` for every record in a file. Valid later explicit directories now update the project context; malformed explicit directories are flagged without becoming observed zeros. This changes project attribution/filter membership, not token categories or pricing. `PARSER_CACHE_VERSION=observations-v1:project-context-2` forces old file caches to reparse unchanged bytes. The observation representation/identity version stays `observations-v1`, preserving retained-source references; parser-cache policy is separate. Reconciled source facts/quality still drive the usage revision. Dedicated tests verify two projects/models in one conversation and reparse of a prior cache policy.

## Verification and S13 handoff

Focused gates include exact two-provider fixture totals, all numeric/coverage states, frozen clock/filter derivation, stale/restart contexts, exact cursor ties/tampering, self-omitting facets, normalized known/unknown projects, lifetime/detail/event reconciliation, DST, safe work limits, durable jobs/config recovery, root subsets, decimal-string-only drafts, cached provider failure/cooldown, actual second-process/CLI reuse and competing settings-write rejection. Simulated tray tests prove runtime/report injection; native tray playback is reported separately. Actual Windows in-app-browser launch/cookie/fragment/private-read evidence is recorded in the refinement ledger. HTTP security tests are not a comprehensive penetration test.

S13 should reuse these schemas/fixtures and existing frontend assets, replace `/api/preview` DTO assumptions, maintain context/cursor/list position, discard obsolete responses, refresh related widgets on 409, keep settings draft/Save/Cancel and last-complete-versus-pending states, and use cached active-account limits separately. Preserve terminal/tray access and explicit dashboard launch. No replacement dashboard, Figma edit, deployment or Agent 2 dispatch is included in S12. Full tests/build/probes/hosted matrix and unrun checks belong to the session ledger.
