import SwiftUI

@main
struct TapedeckApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // `Window`, not `WindowGroup`: one window, so ⌘W and ⌘Q mean the same
        // thing. That is what makes "closing the window stops the server"
        // unambiguous — with a WindowGroup the user can close the last window
        // and leave the app (and its server) running with no window to quit from.
        Window("TAPEDECK", id: "main") {
            ContentView()
        }
        .commands {
            CommandGroup(replacing: .newItem) { }
            CommandGroup(after: .toolbar) {
                Button("Reload") {
                    NotificationCenter.default.post(name: .reloadWebView, object: nil)
                }
                .keyboardShortcut("r", modifiers: .command)

                Button("Reload Ignoring Cache") {
                    NotificationCenter.default.post(name: .hardReloadWebView, object: nil)
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

                Divider()

                Button("Restart Server") {
                    Task { await BackendManager.shared.restart() }
                }
                .keyboardShortcut("r", modifiers: [.command, .option])

                Button("Open Server Log") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: AppPaths.logPath))
                }
                Button("Reveal Repo in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting([AppPaths.repoRoot])
                }
            }
        }
    }
}
