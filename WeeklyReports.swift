import Foundation

// MARK: - What the weekly report remembers

/// A finished 5-hour session, saved when its report is made, so the weekly report can list it.
struct SessionRecord: Codable {
    var start: Date
    var used: Double        // % of the session limit
    var ccCost: Double      // API-equivalent cost of Claude Code work
    var ccPct: Double       // share of the session limit from Claude Code (estimated)
    var outsidePct: Double  // share from chat + Cowork (estimated)
    var estimated: Bool?    // limit wasn't observed; inferred from Claude Code activity alone
}

struct WeekRecord: Codable {
    var end: Date
    var used: Double
}

struct WeekTracker: Codable {
    var weekEnd: Date
    var trackedFrom: Date
    var peak: Double
}

struct WeekReportInput {
    let service: String
    let accountName: String
    let label: String
    let weekStart: Date
    let weekEnd: Date
    let trackedFrom: Date
    let weeklyUsed: Double
    let isPreview: Bool
}

func loadCodable<T: Decodable>(_ key: String) -> T? {
    UserDefaults.standard.data(forKey: key).flatMap { try? JSONDecoder().decode(T.self, from: $0) }
}

func storeCodable<T: Encodable>(_ value: T?, _ key: String) {
    if let value, let data = try? JSONEncoder().encode(value) { UserDefaults.standard.set(data, forKey: key) }
    else { UserDefaults.standard.removeObject(forKey: key) }
}

func recordSession(_ r: SessionRecord, service: String) {
    var list: [SessionRecord] = loadCodable("sessions:\(service)") ?? []
    list.removeAll { abs($0.start.timeIntervalSince(r.start)) < 30 * 60 }
    list.append(r)
    storeCodable(Array(list.sorted { $0.start < $1.start }.suffix(300)), "sessions:\(service)")
}

// MARK: - Tracking each week

extension SessionReporter {
    static let weekLength: TimeInterval = 7 * 86400

    func weekTracker(_ service: String) -> WeekTracker? { loadCodable("week:\(service)") }

    func weekInput(_ t: WeekTracker, service: String, name: String, label: String) -> WeekReportInput {
        WeekReportInput(service: service, accountName: name, label: label,
                        weekStart: t.weekEnd.addingTimeInterval(-Self.weekLength), weekEnd: t.weekEnd,
                        trackedFrom: t.trackedFrom, weeklyUsed: t.peak, isPreview: false)
    }

    /// Feed in the latest numbers; returns the week that just ended, if any.
    func observeWeek(service: String, name: String, label: String, windows: [Window]) -> WeekReportInput? {
        let week = windows.first { $0.key == "seven_day" }
        let now = Date()
        var t = weekTracker(service)
        var ended: WeekReportInput?
        if let old = t {
            let rolledOver = week?.resetsAt.map { $0 > old.weekEnd.addingTimeInterval(86400) } ?? false
            if now >= old.weekEnd || rolledOver {
                ended = weekInput(old, service: service, name: name, label: label)
                t = nil
            }
        }
        if let week, let end = week.resetsAt, end > now {
            if var cur = t {
                cur.peak = max(cur.peak, week.utilization)
                cur.weekEnd = end    // the reset time wobbles by a minute or so; keep the latest
                t = cur
            } else {
                t = WeekTracker(weekEnd: end, trackedFrom: now, peak: week.utilization)
            }
        }
        storeCodable(t, "week:\(service)")
        if let e = ended, e.weeklyUsed < 0.5 { return nil }
        return ended
    }

    /// A week whose end has passed can be reported without new numbers (e.g. while rate-limited).
    func endedWeek(service: String, name: String, label: String) -> WeekReportInput? {
        guard let old = weekTracker(service), Date() >= old.weekEnd else { return nil }
        storeCodable(nil as WeekTracker?, "week:\(service)")
        return old.peak >= 0.5 ? weekInput(old, service: service, name: name, label: label) : nil
    }

    func weekPreviewInput(service: String, name: String, label: String, windows: [Window]) -> WeekReportInput? {
        guard let week = windows.first(where: { $0.key == "seven_day" }), let end = week.resetsAt else { return nil }
        return WeekReportInput(service: service, accountName: name, label: label,
                               weekStart: end.addingTimeInterval(-Self.weekLength), weekEnd: Date(),
                               trackedFrom: weekTracker(service)?.trackedFrom ?? Date(),
                               weeklyUsed: week.utilization, isPreview: true)
    }

    /// Builds the weekly HTML report and writes it to disk. Call off the main thread.
    func generateWeekly(_ input: WeekReportInput) -> (URL, String) {
        let dir = configDir(forService: input.service)
        let usage = dir.map { analyzeTranscripts(configDir: $0, from: input.weekStart, to: input.weekEnd) } ?? LocalUsage()
        let cal = calibrate(service: input.service, configDir: dir)
        let sessions = weekSessions(input, usage: usage, cal: cal, dir: dir)

        var history: [WeekRecord] = loadCodable("weeks:\(input.service)") ?? []
        let lastWeek = history.last { $0.end < input.weekStart.addingTimeInterval(3600) }
        if !input.isPreview {
            history.removeAll { abs($0.end.timeIntervalSince(input.weekEnd)) < 86400 }
            history.append(WeekRecord(end: input.weekEnd, used: input.weeklyUsed))
            storeCodable(Array(history.sorted { $0.end < $1.end }.suffix(52)), "weeks:\(input.service)")
        }

        let html = renderWeeklyReport(input, usage, sessions, cal, lastWeek)
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HHmm"
        let safeLabel = input.label.replacingOccurrences(of: "/", with: "-")
        let name = "\(f.string(from: input.weekEnd)) \(safeLabel) weekly\(input.isPreview ? " (in progress)" : "").html"
        let url = Self.reportsDir.appendingPathComponent(name)
        try? html.write(to: url, atomically: true, encoding: .utf8)

        let hit = sessions.filter { $0.used >= 95 && $0.estimated != true }.count
        var summary = "Used \(Int(input.weeklyUsed.rounded()))% of the weekly limit"
        if !sessions.isEmpty { summary += " · \(sessions.count) session\(sessions.count == 1 ? "" : "s")\(hit > 0 ? " (\(hit) hit the limit)" : "")" }
        return (url, summary + ". Click to see the report.")
    }

    /// The week's 5-hour sessions: the ones this app reported on, plus any the Claude desktop app's
    /// usage history saw (from before the app was tracking), each split into Claude Code vs chat + Cowork.
    func weekSessions(_ i: WeekReportInput, usage: LocalUsage, cal: Calibration, dir: URL?) -> [SessionRecord] {
        var list = ((loadCodable("sessions:\(i.service)") as [SessionRecord]?) ?? [])
            .filter { $0.start >= i.weekStart.addingTimeInterval(-3600) && $0.start < i.weekEnd }
        if let dir, let org = organizationId(configDir: dir) {
            for (start, peak) in desktopHistoryWindows(org: org) where start >= i.weekStart && start < i.weekEnd {
                if list.contains(where: { abs($0.start.timeIntervalSince(start)) < 45 * 60 }) { continue }
                let end = start.addingTimeInterval(Self.sessionLength)
                let cost = usage.costTimeline.filter { $0.0 >= start && $0.0 <= end }.reduce(0) { $0 + $1.1 }
                let cc = min(peak, cost * cal.pctPerDollar)
                list.append(SessionRecord(start: start, used: peak, ccCost: cost, ccPct: cc, outsidePct: max(0, peak - cc)))
            }
        }
        // Claude Code work outside every known session happened while nothing was recording the limit.
        // Group it into 5-hour windows and estimate the limit it used from the calibration.
        var clusterStart: Date?, clusterCost = 0.0
        func closeCluster() {
            if let s = clusterStart, clusterCost >= 0.05 {
                let used = min(100, clusterCost * cal.pctPerDollar)
                list.append(SessionRecord(start: s, used: used, ccCost: clusterCost, ccPct: used, outsidePct: 0, estimated: true))
            }
            clusterStart = nil; clusterCost = 0
        }
        let known = list
        for (t, cost) in usage.costTimeline.sorted(by: { $0.0 < $1.0 })
        where !known.contains(where: { t >= $0.start && t <= $0.start.addingTimeInterval(Self.sessionLength) }) {
            if let s = clusterStart, t > s.addingTimeInterval(Self.sessionLength) { closeCluster() }
            if clusterStart == nil { clusterStart = t }
            clusterCost += cost
        }
        closeCluster()
        return list.sorted { $0.start < $1.start }
    }
}

// MARK: - Weekly HTML

func weeklyInsights(_ i: WeekReportInput, _ u: LocalUsage, _ sessions: [SessionRecord],
                    _ ccShare: Double?, _ lastWeek: WeekRecord?) -> [String] {
    var out: [String] = []
    let pct = { (x: Double) in "\(Int(x.rounded()))%" }
    let day = DateFormatter(); day.dateFormat = "EEE"

    if i.weeklyUsed >= 95 {
        out.append("You ran out (or nearly ran out) of your weekly limit. Moving routine work to Sonnet and starting fresh sessions more often would stretch it.")
    } else if i.weeklyUsed >= 75 {
        out.append("Heavy week: \(pct(i.weeklyUsed)) of the weekly limit used.")
    } else if i.weeklyUsed < 30 {
        out.append("Light week: only \(pct(i.weeklyUsed)) of the weekly limit used, so there was plenty of room to spare.")
    }

    if let lastWeek {
        let d = i.weeklyUsed - lastWeek.used
        if abs(d) >= 3 { out.append("That's \(d > 0 ? "up" : "down") \(Int(abs(d).rounded())) points from last week (\(pct(lastWeek.used))).") }
        else { out.append("About the same as last week (\(pct(lastWeek.used))).") }
    }

    let hit = sessions.filter { $0.used >= 95 && $0.estimated != true }
    if !hit.isEmpty {
        let f = DateFormatter(); f.dateFormat = "EEE h a"
        out.append("\(hit.count) session\(hit.count == 1 ? "" : "s") hit the 5-hour limit: \(hit.map { f.string(from: $0.start) }.joined(separator: ", ")).")
    }

    if let ccShare, i.weeklyUsed >= 5 {
        let outside = (1 - ccShare) * 100
        if outside >= 60 { out.append("Most of this week's usage (about \(pct(outside)), estimated) went to chat or Cowork rather than Claude Code.") }
        else if outside >= 20 { out.append("About \(pct(outside)) of this week's usage (estimated) went to chat or Cowork; the rest was Claude Code.") }
        else { out.append("Almost all of this week's usage was Claude Code.") }
    }

    // Busiest day by Claude Code work.
    var byDay: [Date: Int] = [:]
    for (h, b) in u.byHour { byDay[Calendar.current.startOfDay(for: h), default: 0] += b.newTokens }
    if let top = byDay.max(by: { $0.value < $1.value }), byDay.count > 1 {
        out.append("Busiest Claude Code day: \(day.string(from: top.key)) (\(fmtTokens(top.value)) new tokens).")
    }

    if let top = u.byProject.max(by: { $0.value.total < $1.value.total }), u.byProject.count > 1 {
        let share = Double(top.value.total) / Double(max(1, u.total.total))
        if share > 0.5 { out.append("Top project: \(top.key) (\(pct(share * 100)) of Claude Code tokens).") }
    }

    let opus = u.byModel.filter { $0.key.contains("opus") || $0.key.contains("fable") }.values.reduce(0) { $0 + $1.newTokens }
    if u.total.newTokens > 0, Double(opus) / Double(u.total.newTokens) > 0.8, i.weeklyUsed >= 50 {
        out.append("Nearly all Claude Code work ran on Opus. Using Sonnet for routine steps uses much less of the weekly limit.")
    }
    return out
}

func renderWeeklyReport(_ i: WeekReportInput, _ u: LocalUsage, _ sessions: [SessionRecord],
                        _ cal: Calibration, _ lastWeek: WeekRecord?) -> String {
    let dayF = DateFormatter(); dayF.dateFormat = "EEE MMM d"
    let shortDay = DateFormatter(); shortDay.dateFormat = "EEE"
    let startF = DateFormatter(); startF.dateFormat = "EEE h:mm a"
    let money = { (x: Double) in String(format: "$%.2f", x) }
    let pct = { (x: Double) in "\(Int(x.rounded()))%" }

    // Split the week the same way each session was split, weighted by how much of the limit each used.
    let totalSessionPct = sessions.reduce(0) { $0 + $1.used }
    let ccShare: Double? = totalSessionPct > 0 ? sessions.reduce(0) { $0 + $1.ccPct } / totalSessionPct : nil
    let outsideCost = sessions.reduce(0) { $0 + $1.outsidePct } / cal.pctPerDollar
    let p = price(for: "claude-opus-5-5")

    func tile(_ label: String, _ value: String, _ sub: String = "") -> String {
        "<div class=tile><div class=tl>\(esc(label))</div><div class=tv>\(esc(value))</div><div class=ts>\(esc(sub))</div></div>"
    }
    var tiles = tile("Weekly limit used", pct(i.weeklyUsed),
                     lastWeek.map { "last week: \(pct($0.used))" } ?? (i.isPreview ? "so far" : ""))
    let hit = sessions.filter { $0.used >= 95 && $0.estimated != true }.count
    tiles += tile("5-hour sessions", "\(sessions.count)", hit > 0 ? "\(hit) hit the limit" : "none hit the limit")
    tiles += tile("Claude Code", money(u.total.cost), "\(u.total.responses) replies · API-equivalent")
    if let ccShare {
        tiles += tile("Chat + Cowork", "≈ \(pct(i.weeklyUsed * (1 - ccShare)))", "of the weekly limit · \(pct((1 - ccShare) * 100)) of your usage")
    }

    let insightHTML = weeklyInsights(i, u, sessions, ccShare, lastWeek).map { "<li>\(esc($0))</li>" }.joined()

    // Where the week went.
    var split = ""
    if let ccShare, i.weeklyUsed >= 0.5 {
        let cc = ccShare * 100
        split = """
          <h2>Where the weekly limit went</h2>
          <div class=chart>
            <div class=stack><span class=s1 style="width:\(String(format: "%.1f", cc))%"></span><span class=s2 style="width:\(String(format: "%.1f", 100 - cc))%"></span></div>
            <div class=legend><span><i class=k1></i>Claude Code (measured)</span><span><i class=k2></i>Chat + Cowork (estimated)</span></div>
          </div>
          <table><thead><tr><th>Source</th><th>Weekly limit</th><th>Tokens</th><th>API-equiv.</th></tr></thead><tbody>
            <tr><td class=name>Claude Code <small class=muted>measured</small></td><td>\(pct(i.weeklyUsed * ccShare))</td><td>\(fmtTokens(u.total.newTokens)) new + \(fmtTokens(u.total.read)) cache reads</td><td>\(money(u.total.cost))</td></tr>
            <tr><td class=name>Chat + Cowork <small class=muted>estimated</small></td><td>≈ \(pct(i.weeklyUsed * (1 - ccShare)))</td><td>\(outsideCost < 0.01 ? "–" : "≈ \(fmtTokens(Int(outsideCost / p.output * 1e6)))–\(fmtTokens(Int(outsideCost / p.input * 1e6)))")</td><td>\(outsideCost < 0.01 ? "–" : "≈ \(money(outsideCost))")</td></tr>
          </tbody></table>
          <p class=note>Each session is split into Claude Code vs chat + Cowork (see the session reports), and the week is split in the same proportion. Chat and Cowork can't be told apart because neither saves usage on this Mac.</p>
        """
    }

    // Sessions this week.
    var sessionRows = sessions.map { r in
        "<tr><td class=name>\(startF.string(from: r.start))</td><td>\(r.estimated == true ? "≈ " : "")\(pct(r.used))\(r.estimated == true ? "*" : "")\(r.used >= 95 ? " ⚠︎" : "")</td><td>\(pct(r.ccPct))</td><td>\(pct(r.outsidePct))</td><td>\(money(r.ccCost))</td></tr>"
    }.joined()
    if sessionRows.isEmpty { sessionRows = "<tr><td class=name colspan=5>No sessions recorded yet. They're listed once the app has watched them.</td></tr>" }
    let sessionTable = """
      <h2>Sessions <small>5-hour windows</small></h2>
      <table><thead><tr><th>Started</th><th>Limit used</th><th>Claude Code</th><th>Chat + Cowork</th><th>CC API-equiv.</th></tr></thead><tbody>\(sessionRows)</tbody></table>
      \(sessions.contains { $0.estimated == true } ? "<p class=note>* Nothing was recording the limit during these sessions (neither this app nor the Claude desktop app was open), so the limit used is estimated from Claude Code activity, and any chat or Cowork use in them isn't counted.</p>" : "")
    """

    // Claude Code activity by day.
    var days: [Date] = []
    var d = Calendar.current.startOfDay(for: i.weekStart)
    while d <= i.weekEnd { days.append(d); d = Calendar.current.date(byAdding: .day, value: 1, to: d)! }
    var byDay: [Date: Bucket] = [:]
    for (h, b) in u.byHour { byDay[Calendar.current.startOfDay(for: h), default: Bucket()].add(b) }
    let sessionsByDay = Dictionary(grouping: sessions) { Calendar.current.startOfDay(for: $0.start) }
    let maxDay = max(1, days.map { byDay[$0]?.newTokens ?? 0 }.max() ?? 1)
    let dayBars = days.map { day -> String in
        let v = byDay[day]?.newTokens ?? 0
        let n = sessionsByDay[day]?.count ?? 0
        return "<div class=row><span class=rl>\(shortDay.string(from: day))</span><span class=track><span class=bar style=\"width:\(String(format: "%.1f", Double(v) / Double(maxDay) * 100))%\"></span></span><span class=rv>\(v > 0 ? fmtTokens(v) : "–")</span><span class=rn>\(n > 0 ? "\(n) session\(n == 1 ? "" : "s")" : "")</span></div>"
    }.joined()

    func table(_ head: String, _ rows: [(String, Bucket)]) -> String {
        guard !rows.isEmpty else { return "" }
        let body = rows.prefix(10).map { name, b in
            "<tr><td class=name>\(esc(name))</td><td>\(b.responses)</td><td>\(fmtTokens(b.newTokens))</td><td>\(fmtTokens(b.read))</td><td>\(money(b.cost))</td></tr>"
        }.joined()
        return "<table><thead><tr><th>\(head)</th><th>Replies</th><th>New tokens</th><th>Cache reads</th><th>API-equiv.</th></tr></thead><tbody>\(body)</tbody></table>"
    }
    let projects = u.byProject.sorted { $0.value.total > $1.value.total }.map { ($0.key, $0.value) }
    let models = u.byModel.sorted { $0.value.total > $1.value.total }.map { ($0.key, $0.value) }

    let local = u.total.responses > 0 ? """
      <h2>Claude Code by day <small>new tokens</small></h2><div class=chart>\(dayBars)</div>
      <h2>By project</h2>\(table("Project", projects))
      <h2>By model</h2>\(table("Model", models))
    """ : "<p class=muted>No Claude Code activity was saved on this Mac for this account this week.</p>"

    let title = i.isPreview ? "This week so far" : "Weekly report"
    let range = "\(dayF.string(from: i.weekStart)) – \(dayF.string(from: i.weekEnd))"
    let partial = i.trackedFrom.timeIntervalSince(i.weekStart) > 6 * 3600 && sessions.isEmpty
        ? "<p class=note>The app started watching this account partway through the week, so earlier sessions may be missing.</p>" : ""

    return """
    <!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
    <title>\(esc(title)) · \(esc(i.label))</title>
    <style>
    \(reportCSS)    .rn{width:76px;color:var(--muted);font-size:12px}
    @media (max-width:560px){.rn{display:none}}
    </style></head><body><main>
    <h1>\(esc(title)) — \(esc(i.label))</h1>
    <p class=sub>\(esc(i.accountName)) · \(esc(range))</p>
    <div class=tiles>\(tiles)</div>
    \(insightHTML.isEmpty ? "" : "<h2>Takeaways</h2><ul class=insights>\(insightHTML)</ul>")
    \(split)
    \(sessionTable)
    \(partial)
    \(local)
    <p class=foot>Limit percentages come from Anthropic. Claude Code tokens come from its session files on this Mac; chat and Cowork are estimated from the limit they used beyond that. The API-equivalent cost uses list prices and is only a comparison: on a subscription you aren't charged per token.</p>
    </main></body></html>
    """
}

// MARK: - Keeping only the last 4 weeks

/// Deletes report files and saved session/week records older than 4 weeks, and
/// "This Week So Far" previews older than a day. Runs at launch and after each weekly report.
func pruneOldData(services: [String]) {
    let keep: TimeInterval = 28 * 86400
    let cutoff = Date().addingTimeInterval(-keep)
    let fm = FileManager.default
    let files = (try? fm.contentsOfDirectory(at: SessionReporter.reportsDir,
                                             includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
    for url in files where url.pathExtension == "html" {
        let modified = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
        let isPreview = url.lastPathComponent.contains("(in progress)")
        if modified < cutoff || (isPreview && modified < Date().addingTimeInterval(-86400)) {
            try? fm.removeItem(at: url)
        }
    }
    for service in services {
        if let list: [SessionRecord] = loadCodable("sessions:\(service)") {
            storeCodable(list.filter { $0.start >= cutoff }, "sessions:\(service)")
        }
        if let weeks: [WeekRecord] = loadCodable("weeks:\(service)") {
            storeCodable(Array(weeks.filter { $0.end >= cutoff.addingTimeInterval(-7 * 86400) }.suffix(4)), "weeks:\(service)")
        }
    }
}
