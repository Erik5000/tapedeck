import AppKit
import SwiftUI

struct ContentView: View {
    @ObservedObject private var backend = BackendManager.shared

    var body: some View {
        Group {
            switch backend.stage {
            case .starting:
                SplashView()
            case .ready:
                WebView(url: AppPaths.appURL)
            case .failed(let failure):
                FailureView(failure: failure) {
                    Task { await backend.boot() }
                }
            }
        }
        .frame(minWidth: 900, minHeight: 600)
        .task { await backend.boot() }
    }
}

struct SplashView: View {
    var body: some View {
        VStack(spacing: 14) {
            Text("TAPEDECK")
                .font(.system(size: 22, weight: .bold, design: .monospaced))
                .kerning(3)
            ProgressView()
            Text("starting the server…").foregroundStyle(.secondary).font(.callout)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct FailureView: View {
    let failure: StartupFailure
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle").font(.largeTitle)
            Text(failure.title).font(.headline)
            Text(failure.detail)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .textSelection(.enabled)
                .frame(maxWidth: 620)

            if let command = failure.shellCommand {
                Text(command)
                    .font(.system(.footnote, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(8)
                    .background(Color.secondary.opacity(0.12))
                    .cornerRadius(6)
            }

            HStack(spacing: 10) {
                Button("Retry", action: retry).keyboardShortcut(.defaultAction)
                if let command = failure.shellCommand {
                    Button("Copy command") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(command, forType: .string)
                    }
                }
                Button("Open log") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: AppPaths.errPath))
                }
                Button("Reveal repo") {
                    NSWorkspace.shared.activateFileViewerSelecting([AppPaths.repoRoot])
                }
            }
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
