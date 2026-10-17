import AppKit
import ServiceManagement
import UserNotifications

// MARK: - Usage model

struct Window {
    let key: String       // five_hour, seven_day, ...
    let label: String
    let utilization: Double   // percent used, 0...100
    let resetsAt: Date?
    var remaining: Double { max(0, 100 - utilization) }
}

enum FetchError: Error, CustomStringConvertible {
    case noCredentials, unauthorized, signedOut, rateLimited(Date?), http(Int), badResponse(String)
    var description: String {
        switch self {
        case .noCredentials: return "No accounts yet — choose Sign In to an Account…"
        case .unauthorized: return "Claude Code's login has expired — sign in from this menu to keep it live"
        case .signedOut: return "Signed out — choose Sign In Again below"
        case .rateLimited: return "Anthropic asked the app to check less often"
        case .http(let c): return "HTTP error \(c)"
        case .badResponse(let s): return "Unexpected response: \(s)"
        }
    }
}

// MARK: - Claude Code's logins (read-only)

/// One Claude Code login. Each CLAUDE_CONFIG_DIR gets its own keychain entry:
/// "Claude Code-credentials" for ~/.claude, "Claude Code-credentials-<hash>" for others.
struct Account {
    let service: String
    let keychainAccount: String?     // the entry's "account" attribute, needed to update it
    var stored: [String: Any]        // the whole saved JSON, so we can write it back unchanged
    var oauth: [String: Any] { stored["claudeAiOauth"] as? [String: Any] ?? [:] }
    var token: String { oauth["accessToken"] as? String ?? "" }
    var expiresAt: Date? { (oauth["expiresAt"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue / 1000) } }
}

@discardableResult
func run(_ args: [String], input: String? = nil) -> String? {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/security")
    p.arguments = args
    let out = Pipe(), inp = Pipe()
    p.standardOutput = out
    p.standardError = Pipe()
    if input != nil { p.standardInput = inp }
    guard (try? p.run()) != nil else { return nil }
    if let input {
        inp.fileHandleForWriting.write(Data(input.utf8))
        try? inp.fileHandleForWriting.close()
    }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return p.terminationStatus == 0 ? String(data: data, encoding: .utf8) : nil
}

func parseStored(_ blob: String) -> [String: Any]? {
    guard let data = blob.trimmingCharacters(in: .whitespacesAndNewlines).data(using: .utf8),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let oauth = json["claudeAiOauth"] as? [String: Any],
          let token = oauth["accessToken"] as? String, !token.isEmpty else { return nil }
    return json
}

let credentialsFile = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".claude/.credentials.json")

func readAccount(service: String) -> Account? {
    if service == "file" {
        return (try? String(contentsOf: credentialsFile, encoding: .utf8)).flatMap(parseStored)
            .map { Account(service: "file", keychainAccount: nil, stored: $0) }
    }
    guard let blob = run(["find-generic-password", "-s", service, "-w"]), let stored = parseStored(blob) else { return nil }
    let attrs = run(["find-generic-password", "-s", service]) ?? ""
    let acct = attrs.range(of: #""acct"<blob>="[^"]*""#, options: .regularExpression)
        .map { String(attrs[$0].dropFirst(14).dropLast()) }
    return Account(service: service, keychainAccount: acct, stored: stored)
}

func findAccounts() -> [Account] {
    // List keychain item names only (no secrets), then read each Claude Code entry.
    var services = ["Claude Code-credentials"]
    if let dump = run(["dump-keychain"]) {
        let re = try! NSRegularExpression(pattern: #""svce"<blob>="(Claude Code-credentials[^"]*)""#)
        for m in re.matches(in: dump, range: NSRange(dump.startIndex..., in: dump)) {
            if let r = Range(m.range(at: 1), in: dump) { services.append(String(dump[r])) }
        }
    }
    var seen = Set<String>()
    let accounts = services.filter { seen.insert($0).inserted }.compactMap(readAccount)
    if accounts.isEmpty, let a = readAccount(service: "file") { return [a] }
    return accounts
}

// MARK: - API

func apiRequest(_ path: String, token: String) -> URLRequest {
    var req = URLRequest(url: URL(string: "https://api.anthropic.com\(path)")!)
    req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    req.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")
    req.setValue("application/json", forHTTPHeaderField: "Accept")
    req.timeoutInterval = 20
    return req
}

/// Returns the account's email (or name) for labeling.
func fetchAccountName(token: String) async -> String? {
    guard let (data, resp) = try? await URLSession.shared.data(for: apiRequest("/api/oauth/profile", token: token)),
          (resp as? HTTPURLResponse)?.statusCode == 200,
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let acct = json["account"] as? [String: Any] else { return nil }
    return (acct["email_address"] as? String) ?? (acct["email"] as? String)
        ?? (acct["display_name"] as? String) ?? (acct["full_name"] as? String)
}

func fetchUsage(token: String) async throws -> [Window] {
    let req = apiRequest("/api/oauth/usage", token: token)

    let (data, resp) = try await URLSession.shared.data(for: req)
    let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
    if code == 401 || code == 403 { throw FetchError.unauthorized }
    if code == 429 {
        let wait = ((resp as? HTTPURLResponse)?.value(forHTTPHeaderField: "Retry-After")).flatMap(Double.init)
        throw FetchError.rateLimited(wait.map { Date().addingTimeInterval($0) })
    }
    guard code == 200 else { throw FetchError.http(code) }
    guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw FetchError.badResponse(String(data: data.prefix(200), encoding: .utf8) ?? "")
    }

    let iso = ISO8601DateFormatter()
    iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let isoPlain = ISO8601DateFormatter()
    func parse(_ key: String, _ label: String) -> Window? {
        guard let w = json[key] as? [String: Any],
              let u = (w["utilization"] as? NSNumber)?.doubleValue else { return nil }
        let r = (w["resets_at"] as? String).flatMap { iso.date(from: $0) ?? isoPlain.date(from: $0) }
        return Window(key: key, label: label, utilization: u, resetsAt: r)
    }
    let windows = [
        parse("five_hour", "Session (5h)"),
        parse("seven_day", "Weekly — all models"),
        parse("seven_day_opus", "Weekly — Opus"),
        parse("seven_day_sonnet", "Weekly — Sonnet"),
    ].compactMap { $0 }
    if windows.isEmpty { throw FetchError.badResponse("no usage windows") }
    return windows
}

// MARK: - Drawing

func color(forRemaining r: Double) -> NSColor {
    r > 50 ? .systemGreen : (r > 20 ? .systemOrange : .systemRed)
}

/// Small horizontal bar showing remaining capacity.
func barImage(remaining: Double, width: CGFloat = 34, height: CGFloat = 8) -> NSImage {
    let img = NSImage(size: NSSize(width: width, height: height), flipped: false) { rect in
        let track = NSBezierPath(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), xRadius: height / 2, yRadius: height / 2)
        NSColor.labelColor.withAlphaComponent(0.25).setFill()
        track.fill()
        let frac = CGFloat(max(0, min(100, remaining)) / 100)
        if frac > 0 {
            var fill = rect.insetBy(dx: 0.5, dy: 0.5)
            fill.size.width = max(height - 1, fill.width * frac)
            color(forRemaining: remaining).setFill()
            NSBezierPath(roundedRect: fill, xRadius: height / 2, yRadius: height / 2).fill()
        }
        return true
    }
    img.isTemplate = false
    return img
}

/// Two thin stacked bars: session on top, week below.
func doubleBarImage(session: Double, week: Double, width: CGFloat = 30) -> NSImage {
    let h: CGFloat = 14, bar: CGFloat = 5
    let img = NSImage(size: NSSize(width: width, height: h), flipped: false) { _ in
        for (i, remaining) in [session, week].enumerated() {
            let y = i == 0 ? h - bar - 1.5 : 1.5
            let rect = NSRect(x: 0.5, y: y, width: width - 1, height: bar)
            NSColor.labelColor.withAlphaComponent(0.25).setFill()
            NSBezierPath(roundedRect: rect, xRadius: bar / 2, yRadius: bar / 2).fill()
            let frac = CGFloat(max(0, min(100, remaining)) / 100)
            if frac > 0 {
                var fill = rect
                fill.size.width = max(bar, rect.width * frac)
                color(forRemaining: remaining).setFill()
                NSBezierPath(roundedRect: fill, xRadius: bar / 2, yRadius: bar / 2).fill()
            }
        }
        return true
    }
    img.isTemplate = false
    return img
}

func formatReset(_ d: Date?) -> String {
    guard let d else { return "" }
    let s = Int(d.timeIntervalSinceNow)
    if s <= 0 { return "resetting now" }
    let days = s / 86400, h = (s % 86400) / 3600, m = (s % 3600) / 60
    if days > 0 {
        let f = DateFormatter()
        f.dateFormat = "EEE h:mm a"
        return "resets \(f.string(from: d)) (in \(days)d \(h)h)"
    }
    return h > 0 ? "resets in \(h)h \(m)m" : "resets in \(m)m"
}

// MARK: - App

struct AccountState {
    let service: String
    var name: String
    var windows: [Window] = []
    var error: String?
    var updated: Date?
    var ownLogin = false
    var retryAt: Date?               // don't ask Anthropic again before this (after a 429)
    var backoff: TimeInterval = 0
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, UNUserNotificationCenterDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    var accounts: [AccountState] = []
    var globalError: String?
    var timer: Timer?
    var resetTimer: Timer?
    var prunedThisLaunch = false
    let reporter = SessionReporter()
    let defaults = UserDefaults.standard

    /// Opening the app again (Finder, Spotlight, `open`) brings the icon back and shows its menu,
    /// in case it got hidden behind the notch or by too many menu bar items.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        item.isVisible = true
        DispatchQueue.main.async { self.item.button?.performClick(nil) }
        return false
    }

    /// Menu bar style: 0 = names and percentages, 1 = initials ("P 69% B 54%"), 2 = one icon (lowest account),
    /// 3 = one chosen account with both its session and weekly numbers.
    var barStyle: Int {
        if let v = defaults.object(forKey: "barStyle") as? Int { return v }
        return defaults.bool(forKey: "compact") ? 1 : 0
    }
    var compact: Bool { barStyle == 1 }

    /// The account shown by style 3; defaults to the first one.
    var focusAccount: AccountState? {
        let chosen = defaults.string(forKey: "focusAccount")
        return accounts.first { $0.service == chosen } ?? accounts.first
    }

    @objc func setFocusAccount(_ sender: NSMenuItem) {
        defaults.set(sender.representedObject as? String, forKey: "focusAccount")
        defaults.set(3, forKey: "barStyle")
        updateButton(); rebuildMenu()
    }

    @objc func setBarStyle(_ sender: NSMenuItem) {
        defaults.set(sender.tag, forKey: "barStyle")
        updateButton(); rebuildMenu()
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        item.button?.imagePosition = .imageLeft
        item.button?.title = "Claude …"
        menu.delegate = self
        item.menu = menu
        rebuildMenu()
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
        // Start with the Mac by default (once; turning it off in the menu sticks).
        if !defaults.bool(forKey: "loginItemSetUp") {
            try? SMAppService.mainApp.register()
            defaults.set(true, forKey: "loginItemSetUp")
        }
        refresh()
        // Waking from sleep: refresh right away instead of showing hours-old numbers.
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 10) { self?.refresh() }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in self?.refresh() }
    }

    // Recompute "resets in" text each time the menu opens.
    func menuWillOpen(_ menu: NSMenu) { rebuildMenu() }

    func nickname(_ service: String) -> String? { defaults.string(forKey: "nick:\(service)") }

    /// Short label for the menu bar: nickname, else the email's local part.
    func shortLabel(_ a: AccountState) -> String {
        if let n = nickname(a.service), !n.isEmpty { return n }
        let base = a.name.split(separator: "@").first.map(String.init) ?? a.name
        return base.count > 10 ? String(base.prefix(10)) : base
    }

    @objc func refresh() {
        Task { @MainActor in
            let found = await Task.detached { usageSources() }.value
            if found.isEmpty {
                accounts = []
                globalError = FetchError.noCredentials.description
                updateButton(); rebuildMenu()
                return
            }
            globalError = nil
            let results = await withTaskGroup(of: (Int, AccountState).self) { group in
                for (i, acct) in found.enumerated() {
                    let previous = accounts.first { $0.service == acct.service }
                    group.addTask {
                        // Still backing off after a 429: keep showing the last numbers.
                        if let p = previous, let r = p.retryAt, r > Date() { return (i, p) }
                        let nameKey = "name:\(acct.service)"
                        var st = AccountState(service: acct.service,
                                              name: acct.email ?? UserDefaults.standard.string(forKey: nameKey)
                                                  ?? previous?.name ?? acct.service)
                        st.ownLogin = acct.ownLogin
                        do {
                            guard var token = await acct.token(false) else {
                                throw FetchError.signedOut
                            }
                            if !st.name.contains("@"), let n = await fetchAccountName(token: token) {
                                st.name = n
                                UserDefaults.standard.set(n, forKey: nameKey)
                            }
                            do {
                                st.windows = try await fetchUsage(token: token)
                            } catch FetchError.unauthorized where acct.ownLogin {
                                // Expired early: renew once and try again.
                                guard let t = await acct.token(true) else { throw FetchError.signedOut }
                                token = t
                                st.windows = try await fetchUsage(token: token)
                            }
                            st.updated = Date()
                        } catch FetchError.rateLimited(let serverRetry) {
                            // Back off 5 → 10 → 20 → 30 min, or longer if Anthropic says so.
                            st.backoff = min(1800, max(300, (previous?.backoff ?? 0) * 2))
                            st.retryAt = max(serverRetry ?? .distantPast, Date().addingTimeInterval(st.backoff))
                            let f = DateFormatter(); f.timeStyle = .short
                            st.error = "Usage checks paused (too many requests) — retrying at \(f.string(from: st.retryAt!))"
                            st.windows = previous?.windows ?? []
                            st.updated = previous?.updated
                        } catch {
                            st.error = (error as? FetchError)?.description ?? error.localizedDescription
                            st.windows = previous?.windows ?? []
                            st.updated = previous?.updated
                        }
                        return (i, st)
                    }
                }
                var out: [(Int, AccountState)] = []
                for await r in group { out.append(r) }
                return out.sorted { $0.0 < $1.0 }.map { $0.1 }
            }
            // The same account logged into two config dirs would show twice; keep one.
            var seen = Set<String>()
            accounts = results.filter { seen.insert($0.name).inserted }
            writeStatusLog()
            if !prunedThisLaunch {
                prunedThisLaunch = true
                let services = accounts.map(\.service)
                Task.detached { pruneOldData(services: services) }
            }
            checkForEndedSessions()
            updateButton()
            rebuildMenu()
        }
    }

    /// Last refresh result, for troubleshooting: ~/Library/Logs/ClaudeUsageBar.log
    func writeStatusLog() {
        var lines = ["refreshed \(Date())"]
        for a in accounts {
            lines.append("[\(a.name)] (\(a.service))")
            for w in a.windows { lines.append("  \(w.label): \(Int(w.remaining.rounded()))% left, \(formatReset(w.resetsAt))") }
            if let e = a.error { lines.append("  error: \(e)") }
        }
        let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/ClaudeUsageBar.log")
        try? lines.joined(separator: "\n").appending("\n").write(to: url, atomically: true, encoding: .utf8)
    }

    // MARK: Reports

    /// Generates a report for every 5-hour window that ended since the last refresh.
    func checkForEndedSessions() {
        for a in accounts {
            // Weekly reset: report on the week that just ended.
            let endedWeek = a.error == nil
                ? reporter.observeWeek(service: a.service, name: a.name, label: shortLabel(a), windows: a.windows)
                : reporter.endedWeek(service: a.service, name: a.name, label: shortLabel(a))
            if let endedWeek {
                Task.detached { [reporter] in
                    // Give the last session's report a minute to finish so the week includes it.
                    try? await Task.sleep(nanoseconds: 60_000_000_000)
                    let (url, summary) = reporter.generateWeekly(endedWeek)
                    pruneOldData(services: [endedWeek.service])
                    await MainActor.run { self.notify(title: "Claude week reset — \(endedWeek.label)", body: summary, url: url) }
                }
            }
            let ended = a.error == nil
                ? reporter.observe(service: a.service, name: a.name, label: shortLabel(a), windows: a.windows)
                : reporter.endedWindow(service: a.service, name: a.name, label: shortLabel(a))
            guard let ended else { continue }
            // No report for single sessions; just remember it for the weekly report.
            Task.detached { [reporter] in reporter.recordEnded(ended) }
        }
        // Check again shortly after the next window ends, instead of waiting for the 5-minute timer.
        resetTimer?.invalidate()
        if let next = reporter.nextWindowEnd(services: accounts.map(\.service)) {
            resetTimer = Timer(fire: next.addingTimeInterval(30), interval: 0, repeats: false) { [weak self] _ in self?.refresh() }
            RunLoop.main.add(resetTimer!, forMode: .common)
        }
    }

    func notify(title: String, body: String, url: URL) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        c.sound = .default
        c.userInfo = ["url": url.path]
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: url.lastPathComponent, content: c, trigger: nil))
        rebuildMenu()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        if let path = response.notification.request.content.userInfo["url"] as? String {
            NSWorkspace.shared.open(URL(fileURLWithPath: path))
        }
        done()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }

    @objc func previewWeek(_ sender: NSMenuItem) {
        guard let service = sender.representedObject as? String,
              let a = accounts.first(where: { $0.service == service }),
              let input = reporter.weekPreviewInput(service: a.service, name: a.name, label: shortLabel(a), windows: a.windows)
        else { return }
        Task.detached { [reporter] in
            let (url, _) = reporter.generateWeekly(input)
            await MainActor.run { NSWorkspace.shared.open(url); self.rebuildMenu() }
        }
    }

    @objc func openReport(_ sender: NSMenuItem) {
        if let url = sender.representedObject as? URL { NSWorkspace.shared.open(url) }
    }

    @objc func openReportsFolder() { NSWorkspace.shared.open(SessionReporter.reportsDir) }

    func reportsMenu() -> NSMenuItem {
        let sub = NSMenu()
        for a in accounts where a.windows.contains(where: { $0.key == "seven_day" && $0.resetsAt != nil }) {
            let mi = withTarget(NSMenuItem(title: "This Week So Far — \(shortLabel(a))", action: #selector(previewWeek(_:)), keyEquivalent: ""))
            mi.representedObject = a.service
            sub.addItem(mi)
        }
        let recent = SessionReporter.recentReports()
        if !recent.isEmpty {
            if sub.numberOfItems > 0 { sub.addItem(.separator()) }
            for url in recent {
                let mi = withTarget(NSMenuItem(title: url.deletingPathExtension().lastPathComponent, action: #selector(openReport(_:)), keyEquivalent: ""))
                mi.representedObject = url
                sub.addItem(mi)
            }
        }
        sub.addItem(.separator())
        sub.addItem(withTarget(NSMenuItem(title: "Open Reports Folder", action: #selector(openReportsFolder), keyEquivalent: "")))
        let item = NSMenuItem(title: "Weekly Reports", action: nil, keyEquivalent: "")
        item.submenu = sub
        return item
    }

    func tightest(_ a: AccountState) -> Window? {
        a.windows.prefix(2).min { $0.remaining < $1.remaining }
    }

    func updateButton() {
        guard let b = item.button else { return }
        let withData = accounts.filter { tightest($0) != nil }
        if withData.isEmpty {
            b.image = nil
            b.attributedTitle = NSAttributedString(string: globalError != nil || !accounts.isEmpty ? "Claude ⚠︎" : "Claude …")
            return
        }
        // One account, both limits: "P ▬ 80% · 33%" (session · week).
        if barStyle == 3, let a = focusAccount {
            let session = a.windows.first { $0.key == "five_hour" }
            let week = a.windows.first { $0.key == "seven_day" }
            if session != nil || week != nil {
                let font = NSFont.menuBarFont(ofSize: 0)
                let t = NSMutableAttributedString()
                if accounts.count > 1 {
                    t.append(NSAttributedString(string: " \(String(shortLabel(a).prefix(1)).uppercased())", attributes: [.font: font]))
                }
                func pct(_ w: Window?) {
                    guard let w else { t.append(NSAttributedString(string: "–", attributes: [.font: font])); return }
                    t.append(NSAttributedString(string: "\(Int(w.remaining.rounded()))%",
                                                attributes: [.font: font, .foregroundColor: color(forRemaining: w.remaining)]))
                }
                t.append(NSAttributedString(string: " ", attributes: [.font: font]))
                pct(session)
                t.append(NSAttributedString(string: " · ", attributes: [.font: font, .foregroundColor: NSColor.secondaryLabelColor]))
                pct(week)
                if a.error != nil { t.append(NSAttributedString(string: "⚠︎", attributes: [.font: font])) }
                b.image = doubleBarImage(session: session?.remaining ?? 0, week: week?.remaining ?? 0)
                b.attributedTitle = t
                b.toolTip = "\(a.name)\nSession (5h): \(session.map { "\(Int($0.remaining.rounded()))% left" } ?? "–")\nWeek: \(week.map { "\(Int($0.remaining.rounded()))% left" } ?? "–")"
                return
            }
        }
        // Minimal: one bar + the lowest percentage of any account; details stay in the menu.
        if barStyle == 2, accounts.count > 1,
           let low = withData.min(by: { tightest($0)!.remaining < tightest($1)!.remaining }), let w = tightest(low) {
            b.image = barImage(remaining: w.remaining, width: 22)
            b.attributedTitle = NSAttributedString(string: " \(Int(w.remaining.rounded()))%" + (accounts.contains { $0.error != nil } ? "⚠︎" : ""))
            b.toolTip = withData.map { "\($0.name): \(Int(tightest($0)!.remaining.rounded()))% left" }.joined(separator: "\n")
            return
        }
        if accounts.count == 1, let w = tightest(accounts[0]) {
            b.image = barImage(remaining: w.remaining)
            b.attributedTitle = NSAttributedString(string: " \(Int(w.remaining.rounded()))%" + (accounts[0].error != nil ? " ⚠︎" : ""))
            b.toolTip = "\(accounts[0].name): \(Int(w.remaining.rounded()))% left (\(w.label))"
            return
        }
        // Several accounts: "name 88%  other 40%" with colored percentages.
        b.image = nil
        let font = NSFont.menuBarFont(ofSize: 0)
        let t = NSMutableAttributedString()
        var tips: [String] = []
        for (i, a) in accounts.enumerated() {
            if i > 0 { t.append(NSAttributedString(string: compact ? " " : "  ", attributes: [.font: font])) }
            // Compact mode: first letter of the name only ("P 69% B 54%").
            let label = compact ? String(shortLabel(a).prefix(1)).uppercased() : shortLabel(a)
            t.append(NSAttributedString(string: "\(label) ", attributes: [.font: font]))
            if let w = tightest(a) {
                t.append(NSAttributedString(string: "\(Int(w.remaining.rounded()))%",
                    attributes: [.font: font, .foregroundColor: color(forRemaining: w.remaining)]))
                tips.append("\(a.name): \(Int(w.remaining.rounded()))% left")
            } else {
                t.append(NSAttributedString(string: "—", attributes: [.font: font]))
            }
            if a.error != nil { t.append(NSAttributedString(string: "⚠︎", attributes: [.font: font])) }
        }
        b.attributedTitle = t
        b.toolTip = tips.joined(separator: "\n")
    }

    func header(_ text: String) -> NSMenuItem {
        let mi = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        mi.attributedTitle = NSAttributedString(string: text, attributes: [
            .font: NSFont.systemFont(ofSize: 12, weight: .semibold),
            .foregroundColor: NSColor.secondaryLabelColor])
        return mi
    }

    func rebuildMenu() {
        // Laid out like macOS's own menus (e.g. the input-source menu): icon, one line per item,
        // a checkmark on the account shown in the menu bar, and separators between groups.
        menu.removeAllItems()
        let f = DateFormatter(); f.timeStyle = .short

        if let e = globalError {
            menu.addItem(infoItem(e, symbol: "exclamationmark.triangle"))
            menu.addItem(.separator())
        }

        for a in accounts {
            let row = withTarget(NSMenuItem(title: shortLabel(a), action: #selector(setFocusAccount(_:)), keyEquivalent: ""))
            row.image = badgeImage(String(shortLabel(a).prefix(1)).uppercased())
            row.representedObject = a.service
            row.state = barStyle == 3 && focusAccount?.service == a.service ? .on : .off
            row.toolTip = "\(a.name)\nClick to show this account in the menu bar"
            menu.addItem(row)
            for w in a.windows {
                let mi = withTarget(NSMenuItem(title: "", action: #selector(noop), keyEquivalent: ""))
                mi.indentationLevel = 1
                mi.image = barImage(remaining: w.remaining, width: 36, height: 8)
                let t = NSMutableAttributedString(string: "\(shortWindowName(w))  ",
                                                  attributes: [.font: NSFont.menuFont(ofSize: 0)])
                t.append(NSAttributedString(string: "\(Int(w.remaining.rounded()))% left",
                                            attributes: [.font: NSFont.menuFont(ofSize: 0), .foregroundColor: color(forRemaining: w.remaining)]))
                let reset = formatReset(w.resetsAt)
                if !reset.isEmpty {
                    t.append(NSAttributedString(string: "  ·  \(reset)",
                                                attributes: [.font: NSFont.menuFont(ofSize: 0), .foregroundColor: NSColor.secondaryLabelColor]))
                }
                mi.attributedTitle = t
                menu.addItem(mi)
            }
            if let e = a.error {
                let mi = infoItem(e, symbol: "exclamationmark.triangle")
                mi.indentationLevel = 1
                menu.addItem(mi)
            }
        }
        if !accounts.isEmpty { menu.addItem(.separator()) }

        // Stands in for the Claude app's own menu bar icon, so that one can be hidden.
        if let claudeApp = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.anthropic.claudefordesktop") {
            let open = withTarget(NSMenuItem(title: "Open Claude", action: #selector(openClaudeApp), keyEquivalent: "o"))
            let icon = NSWorkspace.shared.icon(forFile: claudeApp.path)
            icon.size = NSSize(width: 16, height: 16)
            open.image = icon
            menu.addItem(open)
        }
        menu.addItem(symbolItem(reportsMenu(), "chart.bar.doc.horizontal"))
        menu.addItem(symbolItem(withTarget(NSMenuItem(title: "Open Usage Page…", action: #selector(openUsagePage), keyEquivalent: "")), "safari"))
        menu.addItem(symbolItem(withTarget(NSMenuItem(title: "Refresh Now", action: #selector(refresh), keyEquivalent: "r")), "arrow.clockwise"))
        menu.addItem(.separator())

        // Menu bar style.
        let styles = NSMenu()
        for (tag, title) in [(0, "Names and Percentages"), (1, "Initials Only"), (2, "Single Icon (lowest account)"),
                             (3, "One Account: Session + Week")] {
            let mi = withTarget(NSMenuItem(title: title, action: #selector(setBarStyle(_:)), keyEquivalent: ""))
            mi.tag = tag
            mi.state = barStyle == tag ? .on : .off
            styles.addItem(mi)
        }
        let styleItem = NSMenuItem(title: "Menu Bar Style", action: nil, keyEquivalent: "")
        styleItem.submenu = styles
        menu.addItem(styleItem)

        // Accounts: rename, sign in/out.
        let acctMenu = NSMenu()
        for a in accounts {
            let sub = NSMenu()
            let rename = withTarget(NSMenuItem(title: "Rename…", action: #selector(rename(_:)), keyEquivalent: ""))
            rename.representedObject = a.service
            sub.addItem(rename)
            if a.ownLogin {
                let signedOut = a.error == FetchError.signedOut.description
                let out = withTarget(NSMenuItem(title: signedOut ? "Sign In Again…" : "Sign Out",
                                                action: signedOut ? #selector(signIn) : #selector(signOut(_:)), keyEquivalent: ""))
                out.representedObject = a.service
                sub.addItem(out)
            } else {
                sub.addItem(withTarget(NSMenuItem(title: "Keep Signed In Without Claude Code…", action: #selector(signIn), keyEquivalent: "")))
            }
            let mi = NSMenuItem(title: "\(shortLabel(a))  —  \(a.name)", action: nil, keyEquivalent: "")
            mi.image = badgeImage(String(shortLabel(a).prefix(1)).uppercased())
            mi.submenu = sub
            acctMenu.addItem(mi)
        }
        if !accounts.isEmpty { acctMenu.addItem(.separator()) }
        acctMenu.addItem(withTarget(NSMenuItem(title: signInFlow == nil ? "Sign In to an Account…" : "Waiting for browser sign-in…",
                                               action: signInFlow == nil ? #selector(signIn) : nil, keyEquivalent: "")))
        let acctItem = NSMenuItem(title: "Accounts", action: nil, keyEquivalent: "")
        acctItem.submenu = acctMenu
        menu.addItem(acctItem)

        let login = withTarget(NSMenuItem(title: "Launch at Login", action: #selector(toggleLogin), keyEquivalent: ""))
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(login)
        menu.addItem(.separator())

        if let t = accounts.compactMap(\.updated).max() {
            menu.addItem(infoItem("Updated \(f.string(from: t))", symbol: nil))
        }
        menu.addItem(withTarget(NSMenuItem(title: "Quit Claude Usage Bar", action: #selector(quit), keyEquivalent: "q")))
    }

    @objc func noop() {}

    /// A short name for a limit window, e.g. "Session", "Week".
    func shortWindowName(_ w: Window) -> String {
        switch w.key {
        case "five_hour": return "Session"
        case "seven_day": return "Week"
        case "seven_day_opus": return "Opus week"
        case "seven_day_sonnet": return "Sonnet week"
        default: return w.label
        }
    }

    /// Grey, non-clickable line (status or warning).
    func infoItem(_ text: String, symbol: String?) -> NSMenuItem {
        let mi = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        mi.attributedTitle = NSAttributedString(string: text, attributes: [
            .font: NSFont.menuFont(ofSize: 12), .foregroundColor: NSColor.secondaryLabelColor])
        if let symbol { mi.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil) }
        return mi
    }

    func symbolItem(_ mi: NSMenuItem, _ symbol: String) -> NSMenuItem {
        mi.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
        return mi
    }

    /// A rounded badge with a letter cut out, like the input-source badges ("A", "拼").
    func badgeImage(_ letter: String) -> NSImage {
        let size = NSSize(width: 20, height: 16)
        let img = NSImage(size: size, flipped: false) { rect in
            NSColor.black.setFill()
            NSBezierPath(roundedRect: rect, xRadius: 4, yRadius: 4).fill()
            let font = NSFont.systemFont(ofSize: 11, weight: .bold)
            let str = NSAttributedString(string: letter, attributes: [.font: font, .foregroundColor: NSColor.black])
            let s = str.size()
            NSGraphicsContext.current?.compositingOperation = .destinationOut
            str.draw(at: NSPoint(x: (rect.width - s.width) / 2, y: (rect.height - s.height) / 2))
            return true
        }
        img.isTemplate = true
        return img
    }

    func withTarget(_ mi: NSMenuItem) -> NSMenuItem { mi.target = self; return mi }

    @objc func rename(_ sender: NSMenuItem) {
        guard let service = sender.representedObject as? String else { return }
        let alert = NSAlert()
        alert.messageText = "Short name for this account"
        alert.informativeText = accounts.first { $0.service == service }?.name ?? ""
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 200, height: 24))
        field.stringValue = nickname(service) ?? ""
        field.placeholderString = "e.g. Personal, Work"
        alert.accessoryView = field
        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let v = field.stringValue.trimmingCharacters(in: .whitespaces)
        if v.isEmpty { defaults.removeObject(forKey: "nick:\(service)") }
        else { defaults.set(v, forKey: "nick:\(service)") }
        updateButton(); rebuildMenu()
    }

    @objc func openClaudeApp() {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.anthropic.claudefordesktop") else { return }
        NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
    }

    @objc func openUsagePage() { NSWorkspace.shared.open(URL(string: "https://claude.ai/settings/usage")!) }

    // MARK: Signing in

    var signInFlow: SignInFlow?

    @objc func signIn() {
        guard signInFlow == nil else { return }
        let flow = SignInFlow { [weak self] result in
            guard let self else { return }
            self.signInFlow = nil
            switch result {
            case .success(let login):
                self.adoptSettings(fromClaudeCodeLoginOf: login.email)
                self.notifyPlain("Signed in", "\(login.email) will stay signed in and show live usage.")
            case .failure(let e):
                self.globalError = "Sign-in failed: \(e)"
            }
            self.refresh()
        }
        signInFlow = flow
        flow.start()
        rebuildMenu()
    }

    /// Carry over the nickname and report history from the Claude Code login for the same account.
    func adoptSettings(fromClaudeCodeLoginOf email: String) {
        guard let old = accounts.first(where: { !$0.ownLogin && $0.name == email })?.service
                ?? ["Claude Code-credentials"].first(where: { savedEmail(service: $0) == email }) else { return }
        let new = "app:\(email)"
        for prefix in ["nick:", "tracker:", "calib:"] {
            if defaults.object(forKey: prefix + new) == nil, let v = defaults.object(forKey: prefix + old) {
                defaults.set(v, forKey: prefix + new)
            }
        }
    }

    @objc func signOut(_ sender: NSMenuItem) {
        guard let service = sender.representedObject as? String, service.hasPrefix("app:") else { return }
        LoginStore.remove(String(service.dropFirst(4)))
        refresh()
    }

    func notifyPlain(_ title: String, _ body: String) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }

    @objc func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            else { try SMAppService.mainApp.register() }
        } catch {
            globalError = "Launch at login: \(error.localizedDescription)"
        }
        rebuildMenu()
    }

    @objc func quit() { NSApp.terminate(nil) }
}

@main
enum Main {
    static let delegate = AppDelegate()
    static func main() {
        let app = NSApplication.shared
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }
}
