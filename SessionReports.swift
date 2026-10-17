import AppKit
import CryptoKit
import UserNotifications

// MARK: - Which config folder belongs to a login

/// "Claude Code-credentials" is ~/.claude; "Claude Code-credentials-<hash>" is the folder whose
/// path hashes (SHA-256, first 8 hex chars) to <hash> — that's how Claude Code names them.
func configDir(forService service: String) -> URL? {
    let fm = FileManager.default
    let home = fm.homeDirectoryForCurrentUser
    if service == "Claude Code-credentials" || service == "file" { return home.appendingPathComponent(".claude") }
    var candidates = ((try? fm.contentsOfDirectory(atPath: home.path)) ?? [])
        .filter { $0.hasPrefix(".claude") }
        .map { home.appendingPathComponent($0) }
        .filter { var isDir: ObjCBool = false; return fm.fileExists(atPath: $0.path, isDirectory: &isDir) && isDir.boolValue }
    if let env = ProcessInfo.processInfo.environment["CLAUDE_CONFIG_DIR"] { candidates.append(URL(fileURLWithPath: env)) }
    // The app's own logins are matched to whichever Claude Code folder is signed into the same email.
    if service.hasPrefix("app:") {
        let email = String(service.dropFirst(4))
        return candidates.first { savedAccount(configDir: $0)?["emailAddress"] as? String == email }
    }
    let suffix = service.replacingOccurrences(of: "Claude Code-credentials-", with: "")
    for c in candidates {
        let hash = SHA256.hash(data: Data(c.path.utf8)).map { String(format: "%02x", $0) }.joined()
        if hash.hasPrefix(suffix) { return c }
    }
    return nil
}

// MARK: - Local transcript analysis

/// API list prices per million tokens, used only for an "API-equivalent" estimate.
struct Price { let input, output, write5m, write1h, read: Double }

func price(for model: String) -> Price {
    if model.contains("fable") || model.contains("mythos") { return Price(input: 10, output: 50, write5m: 12.5, write1h: 20, read: 0.25) }
    if model.contains("opus-5-5") { return Price(input: 4, output: 20, write5m: 5, write1h: 8, read: 0.2) }
    if model.contains("opus") { return Price(input: 5, output: 25, write5m: 6.25, write1h: 10, read: 0.5) }
    if model.contains("sonnet-5") { return Price(input: 2, output: 10, write5m: 2.5, write1h: 4, read: 0.2) }
    if model.contains("sonnet") { return Price(input: 3, output: 15, write5m: 3.75, write1h: 6, read: 0.3) }
    if model.contains("haiku-5") { return Price(input: 0.1, output: 0.5, write5m: 0.125, write1h: 0.2, read: 0.01) }
    if model.contains("haiku") { return Price(input: 1, output: 5, write5m: 1.25, write1h: 2, read: 0.1) }
    return Price(input: 4, output: 20, write5m: 5, write1h: 8, read: 0.2)
}

struct Bucket {
    var responses = 0
    var input = 0, output = 0, write5m = 0, write1h = 0, read = 0
    var cost = 0.0
    var newTokens: Int { input + output + write5m + write1h }
    var total: Int { newTokens + read }
    mutating func add(_ o: Bucket) {
        responses += o.responses; input += o.input; output += o.output
        write5m += o.write5m; write1h += o.write1h; read += o.read; cost += o.cost
    }
}

struct LocalUsage {
    var total = Bucket()
    var byProject: [String: Bucket] = [:]
    var byModel: [String: Bucket] = [:]
    var byHour: [Date: Bucket] = [:]
    var bySession: [String: Bucket] = [:]
    var activeSlots = Set<Int>()          // 5-minute slots with at least one response
    var first: Date?, last: Date?
    var notices: [(Date, String)] = []    // limit / login messages Claude Code showed
    var costTimeline: [(Date, Double)] = []
    var activeMinutes: Int { activeSlots.count * 5 }
}

func analyzeTranscripts(configDir: URL, from start: Date, to end: Date) -> LocalUsage {
    var usage = LocalUsage()
    let fm = FileManager.default
    let projects = configDir.appendingPathComponent("projects")
    guard let walker = fm.enumerator(at: projects, includingPropertiesForKeys: [.contentModificationDateKey]) else { return usage }
    let iso = ISO8601DateFormatter()
    iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let home = fm.homeDirectoryForCurrentUser.path
    var seen = Set<String>()

    for case let url as URL in walker where url.pathExtension == "jsonl" {
        // Skip files untouched since the window started.
        if let m = try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate, m < start { continue }
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { continue }
        // Group by the folder the session was started in, not every folder it cd'd into.
        var sessionRoot: String?
        text.enumerateLines { line, _ in
            if sessionRoot == nil, let r = line.range(of: #""cwd":"([^"]+)""#, options: .regularExpression) {
                sessionRoot = String(line[r].dropFirst(7).dropLast())
            }
            guard line.contains("\"usage\"") || line.contains("<synthetic>"),
                  let data = line.data(using: .utf8),
                  let d = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let ts = (d["timestamp"] as? String).flatMap({ iso.date(from: $0) }),
                  ts >= start, ts <= end,
                  let msg = d["message"] as? [String: Any] else { return }
            let model = msg["model"] as? String ?? "unknown"

            if model == "<synthetic>" {
                let text = (msg["content"] as? [[String: Any]])?.compactMap { $0["text"] as? String }.joined(separator: " ") ?? ""
                if text.localizedCaseInsensitiveContains("limit") || text.localizedCaseInsensitiveContains("login") {
                    usage.notices.append((ts, text))
                }
                return
            }
            guard let u = msg["usage"] as? [String: Any] else { return }
            let key = "\(msg["id"] as? String ?? UUID().uuidString)|\(d["requestId"] as? String ?? "")"
            guard seen.insert(key).inserted else { return }

            func n(_ dict: [String: Any]?, _ k: String) -> Int { (dict?[k] as? NSNumber)?.intValue ?? 0 }
            var b = Bucket()
            b.responses = 1
            b.input = n(u, "input_tokens")
            b.output = n(u, "output_tokens")
            b.read = n(u, "cache_read_input_tokens")
            if let cc = u["cache_creation"] as? [String: Any] {
                b.write5m = n(cc, "ephemeral_5m_input_tokens")
                b.write1h = n(cc, "ephemeral_1h_input_tokens")
            } else {
                b.write5m = n(u, "cache_creation_input_tokens")
            }
            let p = price(for: model)
            b.cost = (Double(b.input) * p.input + Double(b.output) * p.output + Double(b.write5m) * p.write5m
                      + Double(b.write1h) * p.write1h + Double(b.read) * p.read) / 1_000_000

            var project = sessionRoot ?? d["cwd"] as? String ?? url.deletingLastPathComponent().lastPathComponent
            if project.hasPrefix(home) { project = "~" + project.dropFirst(home.count) }
            let hour = Calendar.current.dateInterval(of: .hour, for: ts)?.start ?? ts

            usage.total.add(b)
            usage.costTimeline.append((ts, b.cost))
            usage.byProject[project, default: Bucket()].add(b)
            usage.byModel[model, default: Bucket()].add(b)
            usage.byHour[hour, default: Bucket()].add(b)
            usage.bySession[d["sessionId"] as? String ?? url.lastPathComponent, default: Bucket()].add(b)
            usage.activeSlots.insert(Int(ts.timeIntervalSince1970 / 300))
            usage.first = min(usage.first ?? ts, ts)
            usage.last = max(usage.last ?? ts, ts)
        }
    }
    return usage
}

// MARK: - Usage outside Claude Code (chat + Cowork)

/// How much session limit one dollar of API-equivalent Claude Code work uses on this account.
struct Calibration {
    let pctPerDollar: Double
    let samples: Int
    var isDefault: Bool { samples == 0 }
}

struct OutsideEstimate {
    let claudeCodePct: Double
    let outsidePct: Double
    let outsideCost: Double
    let tokensLow: Int      // if it were all output tokens
    let tokensHigh: Int     // if it were all input tokens
    let calibration: Calibration
}

func estimateOutside(_ i: ReportInput, _ u: LocalUsage, _ cal: Calibration) -> OutsideEstimate {
    let cc = min(i.sessionUsed, u.total.cost * cal.pctPerDollar)
    let outside = max(0, i.sessionUsed - cc)
    let cost = outside / cal.pctPerDollar
    let p = price(for: "claude-opus-5-5")
    return OutsideEstimate(claudeCodePct: cc, outsidePct: outside, outsideCost: cost,
                           tokensLow: Int(cost / p.output * 1_000_000), tokensHigh: Int(cost / p.input * 1_000_000),
                           calibration: cal)
}

/// The account info Claude Code saved for a config folder (~/.claude uses ~/.claude.json).
func savedAccount(configDir: URL) -> [String: Any]? {
    let home = FileManager.default.homeDirectoryForCurrentUser
    let file = configDir.path == home.appendingPathComponent(".claude").path
        ? home.appendingPathComponent(".claude.json") : configDir.appendingPathComponent(".claude.json")
    guard let data = try? Data(contentsOf: file),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
    return json["oauthAccount"] as? [String: Any]
}

/// The organization a config folder is logged into (matches the desktop app's usage history).
func organizationId(configDir: URL) -> String? {
    savedAccount(configDir: configDir)?["organizationUuid"] as? String
}

/// The email Claude Code saved for a login, so naming accounts needs no network request.
func savedEmail(service: String) -> String? {
    if service.hasPrefix("app:") { return String(service.dropFirst(4)) }
    return configDir(forService: service).flatMap { savedAccount(configDir: $0)?["emailAddress"] as? String }
}

/// Past 5-hour windows (start, peak %) from the Claude desktop app's own usage history,
/// which samples the session limit every ~15 minutes.
func desktopHistoryWindows(org: String) -> [(Date, Double)] {
    let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    var samples: [(Double, Double)] = []
    for profile in ["Claude", "Claude-Work"] {
        let url = support.appendingPathComponent("\(profile)/plan-usage-history.json")
        guard let data = try? Data(contentsOf: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let list = json["samples"] as? [[String: Any]] else { continue }
        for x in list where x["org"] as? String == org {
            guard let t = (x["t"] as? NSNumber)?.doubleValue,
                  let fh = ((x["u"] as? [String: Any])?["fh"] as? NSNumber)?.doubleValue else { continue }
            samples.append((t / 1000, fh))
        }
    }
    samples.sort { $0.0 < $1.0 }
    var windows: [(Date, Double)] = []
    var start: Double?, peak = 0.0
    for (t, fh) in samples {
        // A drop in the percentage, or 5 hours passing, means a new window began.
        if let s = start, fh < peak - 0.5 || t > s + SessionReporter.sessionLength {
            windows.append((Date(timeIntervalSince1970: s), peak)); start = nil; peak = 0
        }
        if start == nil, fh > 0 { start = t - 15 * 60 }
        if start != nil { peak = max(peak, fh) }
    }
    if let s = start { windows.append((Date(timeIntervalSince1970: s), peak)) }
    return windows
}

/// Each past window gives "session % ÷ Claude Code dollars". Chat and Cowork only push that ratio up,
/// so a low percentile approximates what Claude Code alone costs.
func calibrate(service: String, configDir dir: URL?) -> Calibration {
    var ratios: [Double] = []
    if let dir, let org = organizationId(configDir: dir) {
        let windows = desktopHistoryWindows(org: org).filter { $0.0 > Date().addingTimeInterval(-35 * 86400) }
        if let first = windows.first?.0 {
            let timeline = analyzeTranscripts(configDir: dir, from: first, to: Date()).costTimeline
            for (start, peak) in windows {
                let end = start.addingTimeInterval(SessionReporter.sessionLength)
                let cost = timeline.filter { $0.0 >= start && $0.0 <= end }.reduce(0) { $0 + $1.1 }
                if cost >= 1, peak > 0 { ratios.append(peak / cost) }
            }
        }
    }
    // Windows this app reported on itself.
    for pair in (UserDefaults.standard.array(forKey: "calib:\(service)") as? [[Double]]) ?? [] where pair.count == 2 && pair[1] >= 1 {
        ratios.append(pair[0] / pair[1])
    }
    guard ratios.count >= 3 else { return Calibration(pctPerDollar: 1.0, samples: 0) }
    ratios.sort()
    return Calibration(pctPerDollar: ratios[ratios.count / 10], samples: ratios.count)
}

// MARK: - Tracking each 5-hour window

struct WindowTracker: Codable {
    var windowEnd: Date
    var trackedFrom: Date
    var peakSession: Double
    var weeklyStart: Double?
    var weeklyLatest: Double?
    var weeklyResetsAt: Date?
    var weeklyReset = false
}

struct ReportInput {
    let service: String
    let accountName: String
    let label: String
    let windowStart: Date
    let windowEnd: Date
    let trackedFrom: Date
    let sessionUsed: Double
    let weeklyStart: Double?
    let weeklyEnd: Double?
    let weeklyResetsAt: Date?
    let weeklyReset: Bool
    let isPreview: Bool

    var weeklyDelta: Double? {
        guard !weeklyReset, let s = weeklyStart, let e = weeklyEnd else { return nil }
        return max(0, e - s)
    }
    /// Weekly change only covers the whole window if we were watching from (near) its start.
    var weeklyCoversWholeWindow: Bool { trackedFrom.timeIntervalSince(windowStart) < 15 * 60 }
}

final class SessionReporter {
    static let sessionLength: TimeInterval = 5 * 3600
    static let reportsDir: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("ClaudeUsageBar/Reports")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    let defaults = UserDefaults.standard

    func tracker(_ service: String) -> WindowTracker? {
        defaults.data(forKey: "tracker:\(service)").flatMap { try? JSONDecoder().decode(WindowTracker.self, from: $0) }
    }

    func save(_ t: WindowTracker?, _ service: String) {
        if let t, let data = try? JSONEncoder().encode(t) { defaults.set(data, forKey: "tracker:\(service)") }
        else { defaults.removeObject(forKey: "tracker:\(service)") }
    }

    /// Earliest moment any tracked window ends, so the app can check right after a reset.
    func nextWindowEnd(services: [String]) -> Date? {
        (services.compactMap { tracker($0)?.windowEnd } + services.compactMap { weekTracker($0)?.weekEnd })
            .filter { $0 > Date() }.min()
    }

    func reportInput(_ old: WindowTracker, service: String, name: String, label: String) -> ReportInput {
        ReportInput(
            service: service, accountName: name, label: label,
            windowStart: old.windowEnd.addingTimeInterval(-Self.sessionLength), windowEnd: old.windowEnd,
            trackedFrom: old.trackedFrom, sessionUsed: old.peakSession,
            weeklyStart: old.weeklyStart, weeklyEnd: old.weeklyLatest, weeklyResetsAt: old.weeklyResetsAt,
            weeklyReset: old.weeklyReset, isPreview: false)
    }

    /// A window whose end time has passed can be reported without asking Anthropic for new numbers,
    /// so reports still arrive while usage checks are rate-limited.
    func endedWindow(service: String, name: String, label: String) -> ReportInput? {
        guard let old = tracker(service), Date() >= old.windowEnd else { return nil }
        save(nil, service)
        return old.peakSession >= 0.5 ? reportInput(old, service: service, name: name, label: label) : nil
    }

    /// Feed in the latest numbers; returns the window that just ended, if any.
    func observe(service: String, name: String, label: String, windows: [Window]) -> ReportInput? {
        let five = windows.first { $0.key == "five_hour" }
        let week = windows.first { $0.key == "seven_day" }
        let now = Date()
        var t = tracker(service)
        var ended: ReportInput?

        if let old = t {
            let rolledOver = five?.resetsAt.map { $0 > old.windowEnd.addingTimeInterval(600) } ?? false
            if now >= old.windowEnd || rolledOver {
                ended = reportInput(old, service: service, name: name, label: label)
                t = nil
            }
        }

        if let five, let end = five.resetsAt, end > now {
            if var cur = t {
                cur.peakSession = max(cur.peakSession, five.utilization)
                if let w = week {
                    if let r = cur.weeklyResetsAt, let nr = w.resetsAt, abs(nr.timeIntervalSince(r)) > 600 { cur.weeklyReset = true }
                    cur.weeklyLatest = w.utilization
                    cur.weeklyResetsAt = w.resetsAt
                }
                t = cur
            } else {
                t = WindowTracker(windowEnd: end, trackedFrom: now, peakSession: five.utilization,
                                  weeklyStart: week?.utilization, weeklyLatest: week?.utilization,
                                  weeklyResetsAt: week?.resetsAt)
            }
        }
        save(t, service)
        // Nothing happened in that window (e.g. it expired while the Mac slept unused): no report.
        if let e = ended, e.sessionUsed < 0.5 { return nil }
        return ended
    }

    /// Notes a finished session (limit used, Claude Code vs chat + Cowork) for the weekly report.
    /// Call off the main thread: it reads Claude Code's session files.
    func recordEnded(_ input: ReportInput) {
        let dir = configDir(forService: input.service)
        let usage = dir.map { analyzeTranscripts(configDir: $0, from: input.windowStart, to: input.windowEnd) } ?? LocalUsage()
        let estimate = estimateOutside(input, usage, calibrate(service: input.service, configDir: dir))
        if usage.total.cost >= 1 {
            let key = "calib:\(input.service)"
            var pairs = (defaults.array(forKey: key) as? [[Double]]) ?? []
            pairs.append([input.sessionUsed, usage.total.cost])
            defaults.set(Array(pairs.suffix(60)), forKey: key)
        }
        recordSession(SessionRecord(start: input.windowStart, used: input.sessionUsed, ccCost: usage.total.cost,
                                    ccPct: estimate.claudeCodePct, outsidePct: estimate.outsidePct), service: input.service)
    }

    static func recentReports(limit: Int = 10) -> [URL] {
        let fm = FileManager.default
        let files = (try? fm.contentsOfDirectory(at: reportsDir, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        return files.filter { $0.pathExtension == "html" && $0.lastPathComponent.contains("weekly") }
            .sorted {
                let a = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let b = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return a > b
            }
            .prefix(limit).map { $0 }
    }
}

// MARK: - HTML

let reportCSS = """
    :root{--bg:#f7f6f3;--card:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#e5e3de;--accent:#c96442;--track:#ece9e3}
    @media (prefers-color-scheme:dark){:root{--bg:#1c1b1a;--card:#262524;--fg:#f2f1ee;--muted:#a19f9a;--line:#3a3836;--accent:#e08a68;--track:#34322f}}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif}
    main{max-width:860px;margin:0 auto;padding:32px 16px 64px}
    h1{font-size:26px;margin:0}h2{font-size:16px;margin:32px 0 10px}h2 small{color:var(--muted);font-weight:400}
    .sub{color:var(--muted);margin:4px 0 24px}
    .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
    .tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
    .tl{color:var(--muted);font-size:13px}.tv{font-size:26px;font-weight:600;margin:2px 0}.ts{color:var(--muted);font-size:12px;min-height:16px}
    .insights{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 20px 6px 36px}
    .insights li{margin:10px 0}
    .chart{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
    .row{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13px}
    .rl{width:48px;color:var(--muted);text-align:right}.rv{width:56px;font-variant-numeric:tabular-nums}
    .track{flex:1;height:12px;background:var(--track);border-radius:6px;overflow:hidden}
    .bar{display:block;height:100%;background:var(--accent);border-radius:6px}
    table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:14px}
    th,td{padding:8px 12px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
    th{color:var(--muted);font-weight:500;font-size:12px}th:first-child,td.name{text-align:left;word-break:break-all}
    tr:last-child td{border-bottom:none}
    .stack{display:flex;height:16px;border-radius:8px;overflow:hidden;background:var(--track)}
    .s1{background:var(--accent)}.s2{background:#6b8fd6}
    .legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-top:10px}
    .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
    .k1{background:var(--accent)}.k2{background:#6b8fd6}
    .note{font-size:13px;color:var(--muted);margin:10px 2px 0}
    .notes{font-size:14px}.muted,.foot{color:var(--muted)}.foot{font-size:12px;margin-top:40px}
    @media (max-width:560px){th:nth-child(4),td:nth-child(4){display:none}}
"""


func fmtTokens(_ n: Int) -> String {
    switch n {
    case 1_000_000_000...: return String(format: "%.2fB", Double(n) / 1e9)
    case 1_000_000...: return String(format: "%.1fM", Double(n) / 1e6)
    case 1_000...: return String(format: "%.0fK", Double(n) / 1e3)
    default: return "\(n)"
    }
}

func esc(_ s: String) -> String {
    s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
        .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
}
