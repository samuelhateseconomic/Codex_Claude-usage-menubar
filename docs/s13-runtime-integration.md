# S13 runtime integration checkpoint

Status: runtime implementation in progress, dashboard adaptation is being implemented separately by Agent 2. This document does not claim the combined S13 gate is complete.

## Frontend connection seam

The production integration target serves Agent 2's `windows/dashboard/local.html` at `/`, plus local JavaScript modules, the existing shared style, SVG icons and fonts. The explicit preview retains `index.html`; it is not a production fallback. It injects `data-api-mode="v1"` on the HTML root. The explicit isolated preview injects `data-api-mode="preview"`. Frontend code should select the transport from this native server marker, never from a failed real query. Both servers allow only packaged application asset names; arbitrary filesystem paths are not mapped.

Production uses the S12 session protocol: consume/remove the fragment `launch` token, exchange it at `/api/v1/session/bootstrap`, or resume an existing cookie at `GET /api/v1/session`. Keep the CSRF token in memory. A plain page/asset GET grants no session. Native handoffs can include an initial `provider=codex` or `provider=claude` fragment selection; Both is the default. The existing authenticated developer status page remains at `/service`, with `/api-bootstrap.js`.

Production CSP permits local scripts, styles, images, fonts and API connections, without inline scripts/styles, remote resources or framing. Frontend modules must remain local. Exact counters/money and query/context/job semantics remain the S12 contract; no calculations move into this bridge.

## Native launch and lifetime

`usage_hub_launch.py` owns the native launch bridge. Real `usage_tray.py --dashboard` starts the API and automatically imports only approved local roots; provider polling remains disabled on this explicit dashboard-only launch. The source CLI stays alive until Ctrl+C. A windowed executable hosts an offline tray so Quit remains available. `--no-browser` creates no tab; repeated launches reuse the existing owner without changing its hosting/provider profile.

The ordinary real tray with effective settings equal to the loaded configuration now uses the same owner, index, jobs, provider runtime and committed report callback. It preserves existing automatic live-limit checks and never opens a browser on startup. Its explicit **Open usage dashboard...** menu action creates a new short-lived handoff. Browser close is not app Quit. The native Quit stops admission, drains in-flight HTTP operations, and waits for provider cancellation and index rollback/publication shutdown before releasing ownership. A settings mutation that already holds the writer transaction must finish before another owner can start.

Temporary legacy CLI settings overrides keep their former terminal/tray behavior. They are not injected into a dashboard backed by different saved settings; its menu states that the dashboard is unavailable. Save settings separately and relaunch to use them in the shared hub. Explicit real dashboard launch rejects temporary fee/price/timezone overrides and report/export/root commands, preserving the single configuration authority. If optional hub startup fails, the ordinary tray can continue on the existing core with an unavailable dashboard label. Explicit dashboard failure remains an error, with no demo substitution.

The normal shared tray uses an available loopback port; explicit dashboard source launch defaults to 8765 or `--dashboard-port 0`. Reused owners retain their existing port. `usage_api_main.py --open` keeps the developer status-page launch, while `--tray` can now host offline cached/local usage without requiring live checks. `--live-limits` remains explicit for that headless entry point.

## Verification and remaining work

The focused launcher/static/lifecycle module adds 12 tests; API authentication/query/job/ownership checks (42), existing preview checks (10), settings checks (20), and provider/runtime checks (19) have passed locally. The full source suite passed: **369 tests / 119.717 seconds**. These checks use synthetic roots, real SQLite/HTTP/process launches, and a simulated pystray menu. Native taskbar playback, the combined frontend interaction gate, final packaging and hosted matrix results will be recorded after integration. No real histories/provider credentials, native Figma edits or deployment are used in these checks.
