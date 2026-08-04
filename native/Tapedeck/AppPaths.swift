import Foundation

/// Where the repo, its interpreter, and the server's logs live.
enum AppPaths {
    static let port = 7360

    static var appURL: URL { URL(string: "http://127.0.0.1:\(port)/")! }
    static var healthURL: URL { URL(string: "http://127.0.0.1:\(port)/api/health")! }

    /// Resolution order: env override → the path baked in by `make build` →
    /// a compile-time fallback.
    ///
    /// The baked Info.plist value is the normal source and cannot silently go
    /// stale, because building from a repo stamps that repo's path. The fallback
    /// is deliberately a single known location rather than a probe: if it is
    /// wrong, the preflight says so by name, which beats guessing.
    static let repoRoot: URL = {
        let env = ProcessInfo.processInfo.environment
        if let root = env["TAPEDECK_ROOT"], !root.isEmpty { return expand(root) }
        if let override = UserDefaults.standard.string(forKey: "RepoRoot"), !override.isEmpty {
            return expand(override)
        }
        if let baked = Bundle.main.object(forInfoDictionaryKey: "TDRepoRoot") as? String,
           !baked.isEmpty, !baked.hasPrefix("$(") {
            return expand(baked)
        }
        return expand("/Users/erik/Developer/trading/tapedeck")
    }()

    static var venvPython: URL { repoRoot.appendingPathComponent(".venv/bin/python3") }
    static var cli: URL { repoRoot.appendingPathComponent("tapedeck.py") }

    /// /tmp, matching the sibling apps: the repo stays clean, and a log that
    /// survives a reinstall is what the error view points at.
    static let logPath = "/tmp/tapedeck-server.log"
    static let errPath = "/tmp/tapedeck-server.err"

    static var isValidRepo: Bool { exists(cli) }

    static func exists(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.path)
    }

    private static func expand(_ path: String) -> URL {
        URL(fileURLWithPath: (path as NSString).expandingTildeInPath).standardizedFileURL
    }
}
