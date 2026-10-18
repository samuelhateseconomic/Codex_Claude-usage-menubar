import AppKit
import SwiftUI

// MARK: - Welcome / Manage Accounts window

/// What the window shows; the app delegate keeps it up to date after every refresh.
final class AccountsModel: ObservableObject {
    struct Row: Identifiable {
        let id: String          // service
        let email: String
        let label: String
        let ownLogin: Bool
        let summary: String     // "82% session · 88% week" or an error
        let hasError: Bool
    }
    @Published var rows: [Row] = []
    @Published var signingIn = false
    @Published var lastError: String?

    var signIn: () -> Void = {}
    var remove: (String) -> Void = { _ in }
    var rename: (String) -> Void = { _ in }
    var close: () -> Void = {}
}

struct AccountsView: View {
    @ObservedObject var model: AccountsModel

    var body: some View {
        VStack(spacing: 14) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable().frame(width: 76, height: 76)
            Text(model.rows.isEmpty ? "Welcome to Claude Usage Bar" : "Accounts")
                .font(.title2.weight(.semibold))
            Text("See how much of your Claude limits you have left, right in the menu bar. Sign in with every Claude account you want to keep an eye on.")
                .font(.callout).foregroundStyle(.secondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)

            if !model.rows.isEmpty {
                VStack(spacing: 0) {
                    ForEach(Array(model.rows.enumerated()), id: \.element.id) { i, row in
                        if i > 0 { Divider().padding(.leading, 46) }
                        AccountRow(row: row, model: model)
                    }
                }
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color(nsColor: .separatorColor)))
            }

            Button(action: model.signIn) {
                Label(model.rows.isEmpty ? "Sign in with Claude" : "Add Another Account", systemImage: "person.crop.circle.badge.plus")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent).controlSize(.large)
            .disabled(model.signingIn)

            if model.signingIn {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text("Finish signing in in your browser…").font(.caption).foregroundStyle(.secondary)
                }
            }
            if let e = model.lastError {
                Text(e).font(.caption).foregroundStyle(.red).multilineTextAlignment(.center)
            }

            Text("To add a different account, sign out of claude.ai in your browser first (or use a private window). Logins stay in this Mac's Keychain and are only sent to Anthropic.")
                .font(.caption2).foregroundStyle(.secondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)

            HStack {
                Spacer()
                Button("Done", action: model.close).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 440)
    }
}

struct AccountRow: View {
    let row: AccountsModel.Row
    @ObservedObject var model: AccountsModel

    var body: some View {
        HStack(spacing: 10) {
            Text(String(row.label.prefix(1)).uppercased())
                .font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                .frame(width: 26, height: 22)
                .background(RoundedRectangle(cornerRadius: 5).fill(Color.accentColor))
            VStack(alignment: .leading, spacing: 1) {
                Text(row.label).font(.body.weight(.medium))
                Text(row.email).font(.caption).foregroundStyle(.secondary)
                Text(row.summary).font(.caption).foregroundStyle(row.hasError ? Color.orange : Color.secondary)
            }
            Spacer()
            Menu {
                Button("Rename…") { model.rename(row.id) }
                if row.ownLogin {
                    Button("Remove Account", role: .destructive) { model.remove(row.id) }
                } else {
                    Button("Keep Signed In (sign in with Claude)…") { model.signIn() }
                }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton).fixedSize()
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
    }
}

final class AccountsWindowController {
    private var window: NSWindow?

    func show(model: AccountsModel) {
        if window == nil {
            let w = NSWindow(contentRect: .zero, styleMask: [.titled, .closable], backing: .buffered, defer: false)
            w.title = "Claude Usage Bar"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: AccountsView(model: model))
            w.setContentSize(w.contentView!.fittingSize)
            w.center()
            window = w
        }
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }

    func close() { window?.close() }
}
