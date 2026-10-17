import AppKit
import CryptoKit
import Network

// MARK: - The app's own login for each account

/// The app signs into each account itself, the same way Claude Code does, and keeps its own tokens.
/// That way it keeps working whatever Claude Code does with its login (logging out, moving where it
/// stores it, renewing at the same moment), and it can start with the Mac without Claude Code running.
struct AppLogin: Codable {
    var email: String
    var accessToken: String
    var refreshToken: String
    var expiresAt: Date
}

/// Claude Code's sign-in settings (from its source), so the app's login is the same kind it creates.
let tokenURL = URL(string: "https://platform.claude.com/v1/oauth/token")!
let authorizeURL = "https://claude.com/cai/oauth/authorize"
let claudeCodeClientID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
let appLoginScopes = "user:profile user:inference"
let appLoginService = "ClaudeUsageBar-login"

func quoted(_ s: String) -> String { "\"" + s.replacingOccurrences(of: "\"", with: "\\\"") + "\"" }

/// Stored in the login keychain through `/usr/bin/security`, like Claude Code's own entries,
/// so rebuilding the app never triggers keychain permission prompts.
enum LoginStore {
    static func emails() -> [String] {
        guard let dump = run(["dump-keychain"]) else { return [] }
        var out: [String] = []
        for item in dump.components(separatedBy: "keychain: ") where item.contains("\"svce\"<blob>=\"\(appLoginService)\"") {
            if let r = item.range(of: #""acct"<blob>="[^"]*""#, options: .regularExpression) {
                out.append(String(item[r].dropFirst(14).dropLast()))
            }
        }
        return out.sorted()
    }

    static func load(_ email: String) -> AppLogin? {
        guard let s = run(["find-generic-password", "-s", appLoginService, "-a", email, "-w"]),
              let data = s.trimmingCharacters(in: .whitespacesAndNewlines).data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(AppLogin.self, from: data)
    }

    static func save(_ l: AppLogin) {
        guard let data = try? JSONEncoder().encode(l) else { return }
        // `security -i` reads the command from stdin, so the secret never appears in the process list.
        let hex = data.map { String(format: "%02x", $0) }.joined()
        run(["-i"], input: "add-generic-password -U -a \(quoted(l.email)) -s \(quoted(appLoginService)) -l \(quoted("Claude Usage Bar login")) -X \(hex)\n")
    }

    static func remove(_ email: String) {
        run(["delete-generic-password", "-s", appLoginService, "-a", email])
    }
}

/// POSTs to the token endpoint; returns the JSON on success, or the error text.
func postToken(_ body: [String: Any]) async -> Result<[String: Any], Error> {
    var req = URLRequest(url: tokenURL)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = try? JSONSerialization.data(withJSONObject: body)
    req.timeoutInterval = 30
    do {
        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 200, let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            let text = String(data: data.prefix(300), encoding: .utf8) ?? ""
            return .failure(SignInError.server(code, text))
        }
        return .success(json)
    } catch {
        return .failure(error)
    }
}

enum SignInError: Error, CustomStringConvertible {
    case server(Int, String), denied(String), timedOut, listenerFailed, noEmail
    var description: String {
        switch self {
        case .server(let c, let t): return "Sign-in server error \(c): \(t)"
        case .denied(let why): return "Sign-in was cancelled or refused: \(why)"
        case .timedOut: return "Sign-in timed out"
        case .listenerFailed: return "Couldn't start the local sign-in listener"
        case .noEmail: return "Signed in, but couldn't tell which account it was"
        }
    }
}

/// Renews an expired token. Renewals for one account never overlap, since using the same refresh
/// token twice could get the login revoked.
actor RenewalGate {
    private var inFlight: [String: Task<AppLogin?, Never>] = [:]

    func login(_ email: String, force: Bool) async -> AppLogin? {
        if let t = inFlight[email] { return await t.value }
        let t = Task { await Self.renew(email, force: force) }
        inFlight[email] = t
        let v = await t.value
        inFlight[email] = nil
        return v
    }

    private static func renew(_ email: String, force: Bool) async -> AppLogin? {
        guard var l = LoginStore.load(email) else { return nil }
        if !force, l.expiresAt > Date().addingTimeInterval(120) { return l }
        guard case .success(let json) = await postToken([
            "grant_type": "refresh_token", "refresh_token": l.refreshToken, "client_id": claudeCodeClientID]),
              let access = json["access_token"] as? String,
              let expiresIn = (json["expires_in"] as? NSNumber)?.doubleValue else { return nil }
        l.accessToken = access
        l.refreshToken = json["refresh_token"] as? String ?? l.refreshToken
        l.expiresAt = Date().addingTimeInterval(expiresIn)
        LoginStore.save(l)
        return l
    }
}

let renewalGate = RenewalGate()

// MARK: - Which accounts to show

/// One account to show: the app's own login, or (until you sign in from the menu bar) Claude Code's.
struct UsageSource {
    let service: String
    let email: String?
    let ownLogin: Bool
    let token: (_ forceRenew: Bool) async -> String?
}

func usageSources() -> [UsageSource] {
    let own = LoginStore.emails()
    var out = own.map { email in
        UsageSource(service: "app:\(email)", email: email, ownLogin: true) { force in
            await renewalGate.login(email, force: force)?.accessToken
        }
    }
    // Claude Code's logins are read-only here: renewing them would race with Claude Code itself.
    for a in findAccounts() {
        let email = savedEmail(service: a.service)
        if let email, own.contains(email) { continue }
        let token = a.token
        out.append(UsageSource(service: a.service, email: email, ownLogin: false) { _ in token })
    }
    return out
}

// MARK: - Signing in through the browser

func randomURLSafe(_ bytes: Int) -> String {
    var b = [UInt8](repeating: 0, count: bytes)
    _ = SecRandomCopyBytes(kSecRandomDefault, bytes, &b)
    return base64URL(Data(b))
}

func base64URL(_ d: Data) -> String {
    d.base64EncodedString().replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
}

/// Opens claude.com's sign-in page in the browser and waits for it to redirect back to
/// http://localhost:<port>/callback, then trades the code for tokens (OAuth with PKCE).
final class SignInFlow {
    private var listener: NWListener?
    private var port: UInt16 = 0
    private let verifier = randomURLSafe(32)
    private let state = randomURLSafe(24)
    private var finished = false
    private let completion: (Result<AppLogin, Error>) -> Void

    init(completion: @escaping (Result<AppLogin, Error>) -> Void) { self.completion = completion }

    func start() {
        let params = NWParameters.tcp
        params.requiredInterfaceType = .loopback
        guard let l = try? NWListener(using: params, on: .any) else { return finish(.failure(SignInError.listenerFailed)) }
        listener = l
        l.stateUpdateHandler = { [weak self] st in
            switch st {
            case .ready: if let p = l.port?.rawValue { self?.openBrowser(port: p) }
            case .failed: self?.finish(.failure(SignInError.listenerFailed))
            default: break
            }
        }
        l.newConnectionHandler = { [weak self] c in self?.handle(c) }
        l.start(queue: .main)
        DispatchQueue.main.asyncAfter(deadline: .now() + 600) { [weak self] in self?.finish(.failure(SignInError.timedOut)) }
    }

    private func openBrowser(port: UInt16) {
        self.port = port
        var c = URLComponents(string: authorizeURL)!
        let challenge = base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))
        c.queryItems = [
            .init(name: "code", value: "true"),
            .init(name: "client_id", value: claudeCodeClientID),
            .init(name: "response_type", value: "code"),
            .init(name: "redirect_uri", value: "http://localhost:\(port)/callback"),
            .init(name: "scope", value: appLoginScopes),
            .init(name: "code_challenge", value: challenge),
            .init(name: "code_challenge_method", value: "S256"),
            .init(name: "state", value: state),
        ]
        NSWorkspace.shared.open(c.url!)
    }

    private func handle(_ conn: NWConnection) {
        conn.start(queue: .main)
        conn.receive(minimumIncompleteLength: 1, maximumLength: 16384) { [weak self] data, _, _, _ in
            guard let self, let data, let request = String(data: data, encoding: .utf8),
                  let line = request.components(separatedBy: "\r\n").first else { conn.cancel(); return }
            let parts = line.split(separator: " ")
            guard parts.count >= 2, let comps = URLComponents(string: "http://localhost" + parts[1]),
                  comps.path == "/callback" else {
                return respond(conn, 404, "Not found")
            }
            var q: [String: String] = [:]
            for item in comps.queryItems ?? [] { q[item.name] = item.value ?? "" }
            guard q["state"] == self.state, let code = q["code"], !code.isEmpty else {
                let why = q["error_description"] ?? q["error"] ?? "unexpected response"
                respond(conn, 400, page("Sign-in didn't finish", "\(why). You can try again from the menu bar."))
                return self.finish(.failure(SignInError.denied(why)))
            }
            Task { @MainActor in
                let result = await self.exchange(code)
                switch result {
                case .success(let l):
                    respond(conn, 200, page("Signed in as \(l.email)", "You can close this tab. Claude Usage Bar will keep this account signed in."))
                case .failure(let e):
                    respond(conn, 500, page("Sign-in failed", "\(e). You can try again from the menu bar."))
                }
                self.finish(result)
            }
        }
    }

    private func exchange(_ code: String) async -> Result<AppLogin, Error> {
        let result = await postToken([
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "http://localhost:\(port)/callback",
            "client_id": claudeCodeClientID, "code_verifier": verifier, "state": state])
        switch result {
        case .failure(let e): return .failure(e)
        case .success(let json):
            guard let access = json["access_token"] as? String, let refresh = json["refresh_token"] as? String,
                  let expiresIn = (json["expires_in"] as? NSNumber)?.doubleValue else {
                return .failure(SignInError.server(200, "token response was missing fields"))
            }
            var email = (json["account"] as? [String: Any])?["email_address"] as? String
            if email == nil { email = await fetchAccountName(token: access) }
            guard let email else { return .failure(SignInError.noEmail) }
            let l = AppLogin(email: email, accessToken: access, refreshToken: refresh, expiresAt: Date().addingTimeInterval(expiresIn))
            LoginStore.save(l)
            return .success(l)
        }
    }

    private func finish(_ r: Result<AppLogin, Error>) {
        guard !finished else { return }
        finished = true
        listener?.cancel()
        completion(r)
    }
}

private func respond(_ c: NWConnection, _ status: Int, _ html: String) {
    let body = Data(html.utf8)
    let head = "HTTP/1.1 \(status) \(status == 200 ? "OK" : "Error")\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n"
    c.send(content: Data(head.utf8) + body, completion: .contentProcessed { _ in c.cancel() })
}

private func page(_ title: String, _ text: String) -> String {
    """
    <!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
    <title>\(esc(title))</title>
    <style>:root{--bg:#f7f6f3;--fg:#1d1d1f;--muted:#6e6e73}@media (prefers-color-scheme:dark){:root{--bg:#1c1b1a;--fg:#f2f1ee;--muted:#a19f9a}}
    body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,sans-serif;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}
    main{max-width:440px;text-align:center}h1{font-size:22px}p{color:var(--muted)}</style>
    <main><h1>\(esc(title))</h1><p>\(esc(text))</p></main>
    """
}
