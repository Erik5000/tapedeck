import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var sigtermSource: DispatchSourceSignal?

    func applicationDidFinishLaunching(_ notification: Notification) {
        installSignalHandlers()

        // SwiftUI creates the window asynchronously; defer to the next runloop
        // so NSApp.windows.first is populated.
        DispatchQueue.main.async {
            guard let window = NSApp.windows.first else { return }
            // First launch (no autosaved frame yet) → apply a size that suits a
            // wide table. Detect it by absence of the autosave key, since
            // SwiftUI's default is much smaller.
            if UserDefaults.standard.string(forKey: "NSWindow Frame TapedeckMain") == nil {
                window.setContentSize(NSSize(width: 1600, height: 1000))
                window.center()
            }
            // Register autosave AFTER applying defaults, so the first save
            // captures them rather than SwiftUI's default.
            window.setFrameAutosaveName("TapedeckMain")
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        // Window open = running, window closed = gone. The red button is a quit,
        // which is what stops the server (see applicationWillTerminate).
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Synchronous, and may block for up to 4s. That is the point: the
        // SIGTERM/SIGKILL has to land before this process image goes away,
        // otherwise the server outlives the app that owns it.
        BackendManager.shutdown()
    }

    /// Log out or shut down and launchd SIGTERMs us. Without this the default
    /// action kills the app outright, applicationWillTerminate never runs, and
    /// the server is left to the parent-pid watchdog to clean up.
    private func installSignalHandlers() {
        signal(SIGTERM, SIG_IGN)   // required, else the default action pre-empts us
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        source.setEventHandler { NSApp.terminate(nil) }
        source.resume()
        sigtermSource = source
    }
}
