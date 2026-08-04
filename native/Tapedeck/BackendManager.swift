import Darwin
import Foundation

/// Lock-guarded holder for the server process.
///
/// `shutdown()` runs from `AppDelegate.applicationWillTerminate`, which is not
/// actor-isolated, and the deployment target (macOS 13) predates
/// `MainActor.assumeIsolated`. Keeping the process reference outside the actor
/// avoids an actor hop at terminate time, when the app is already going away.
///
/// `owned` is the load-bearing bit: we only ever stop a server we started. A
/// server the user started with `tapedeck.py --serve` is adopted and left alone.
final class ServerProcessBox: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var owned = false

    func adopt() {
        lock.lock(); defer { lock.unlock() }
        process = nil
        owned = false
    }

    func own(_ process: Process) {
        lock.lock(); defer { lock.unlock() }
        self.process = process
        owned = true
    }

    func clear() {
        lock.lock(); defer { lock.unlock() }
        process = nil
        owned = false
    }

    /// The process to stop on quit — nil when there is nothing of ours to stop.
    func ownedProcess() -> Process? {
        lock.lock(); defer { lock.unlock() }
        return owned ? process : nil
    }
}

@MainActor
final class BackendManager: ObservableObject {
    static let shared = BackendManager()

    private init() {}

    enum Stage: Equatable {
        case starting
        case ready
        case failed(StartupFailure)
    }

    @Published var stage: Stage = .starting

    nonisolated static let processBox = ServerProcessBox()

    /// Preflight, adopt-or-spawn, then wait for the server to answer.
    func boot() async {
        stage = .starting

        if let failure = Diagnostics.preflight() {
            stage = .failed(failure)
            return
        }

        // Someone may already be serving this repo — `tapedeck.py --serve` in a
        // terminal, or a previous instance. Use it, and don't claim ownership:
        // quitting the app must not kill a server it didn't start.
        if await adoptExistingServer() {
            stage = .ready
            return
        }

        do {
            try spawn()
        } catch {
            stage = .failed(StartupFailure(
                title: "Could not start the server",
                detail: "\(AppPaths.venvPython.path)\n\(error.localizedDescription)",
                shellCommand: "cd \(AppPaths.repoRoot.path)/native && make venv"))
            return
        }

        for _ in 0..<30 {                       // 30 × 500ms = 15s
            do { try await Task.sleep(nanoseconds: 500_000_000) } catch { return }
            if await health() != nil {
                stage = .ready
                return
            }
            // A server that has already exited will never answer — say so now
            // rather than making the user wait out the full timeout.
            if let proc = Self.processBox.ownedProcess(), !proc.isRunning {
                stage = .failed(bootFailure(
                    detail: "The server exited immediately (status \(proc.terminationStatus))."))
                return
            }
        }
        stage = .failed(bootFailure(detail: "The server did not answer within 15 seconds."))
    }

    func restart() async {
        Self.shutdown()
        await boot()
    }

    private func bootFailure(detail: String) -> StartupFailure {
        var body = detail
        if let tail = Diagnostics.recentErrors() {
            body += "\n\n\(tail)"
        }
        return StartupFailure(title: "Server did not start", detail: body,
                              shellCommand: "tail -n 40 \(AppPaths.errPath)")
    }

    // MARK: - spawn / adopt

    private func spawn() throws {
        Self.rotateLogs()
        let proc = Process()
        proc.executableURL = AppPaths.venvPython
        proc.arguments = ["-m", "tapedeck.server",
                          "--host", "127.0.0.1",
                          "--port", String(AppPaths.port),
                          "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        proc.currentDirectoryURL = AppPaths.repoRoot

        var env = ProcessInfo.processInfo.environment
        // A GUI app inherits launchd's minimal PATH; the scan shells out to
        // tools that expect a login-shell PATH.
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:"
                    + (env["PATH"] ?? "")
        // Without this the run's progress lines only arrive when it finishes,
        // and the live status line in the page stays empty for the whole run.
        env["PYTHONUNBUFFERED"] = "1"
        proc.environment = env

        proc.standardOutput = Self.appendHandle(at: AppPaths.logPath)
        proc.standardError = Self.appendHandle(at: AppPaths.errPath)

        try proc.run()
        Self.processBox.own(proc)
    }

    /// True when a healthy server for *this* repo is already listening.
    private func adoptExistingServer() async -> Bool {
        guard let info = await health() else { return false }
        guard info.repoRoot == AppPaths.repoRoot.path else { return false }
        Self.processBox.adopt()
        return true
    }

    private struct Health {
        let repoRoot: String
        let ownerPID: Int?
    }

    private nonisolated func health() async -> Health? {
        var req = URLRequest(url: AppPaths.healthURL, timeoutInterval: 1.5)
        req.httpMethod = "GET"
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard (resp as? HTTPURLResponse)?.statusCode == 200,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  obj["ok"] as? Bool == true,
                  let root = obj["repo_root"] as? String
            else { return nil }
            return Health(repoRoot: root, ownerPID: obj["owner_pid"] as? Int)
        } catch {
            return nil
        }
    }

    // MARK: - shutdown

    /// SIGTERM, then SIGKILL if it hasn't gone in 4s. Synchronous on purpose:
    /// it must finish before this process image goes away, or the server
    /// outlives the app that owns it.
    ///
    /// The server also watches our pid and exits on its own, which is what
    /// covers force-quit and crashes — this is the clean path, not the only one.
    nonisolated static func shutdown() {
        guard let proc = processBox.ownedProcess(), proc.isRunning else {
            processBox.clear()
            return
        }
        proc.terminate()
        let deadline = Date().addingTimeInterval(4.0)
        while proc.isRunning && Date() < deadline {
            usleep(100_000)
        }
        if proc.isRunning {
            kill(proc.processIdentifier, SIGKILL)
            proc.waitUntilExit()
        }
        processBox.clear()
    }

    // MARK: - logs

    private nonisolated static func appendHandle(at path: String) -> FileHandle {
        let fm = FileManager.default
        if !fm.fileExists(atPath: path) {
            fm.createFile(atPath: path, contents: nil)
        }
        guard let handle = FileHandle(forWritingAtPath: path) else { return .nullDevice }
        handle.seekToEndOfFile()
        return handle
    }

    /// Nothing else bounds these files — only the app writes them, and it
    /// appends on every launch.
    private nonisolated static func rotateLogs(limit: Int = 5 * 1024 * 1024) {
        let fm = FileManager.default
        for path in [AppPaths.logPath, AppPaths.errPath] {
            guard let size = try? fm.attributesOfItem(atPath: path)[.size] as? Int,
                  size > limit else { continue }
            try? fm.removeItem(atPath: path + ".1")
            try? fm.moveItem(atPath: path, toPath: path + ".1")
        }
    }
}
