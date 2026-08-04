import Foundation

/// A startup failure the user can actually fix, with the command that fixes it.
struct StartupFailure: Equatable {
    let title: String
    let detail: String
    let shellCommand: String?
}

enum Diagnostics {
    /// Checked before spawning anything. Both cases are things the app cannot
    /// repair itself, so it names them precisely instead of failing at a health
    /// timeout 15 seconds later with nothing to go on.
    static func preflight() -> StartupFailure? {
        guard AppPaths.isValidRepo else {
            return StartupFailure(
                title: "Repo not found",
                detail: "No tapedeck.py in \(AppPaths.repoRoot.path). "
                      + "Rebuild from the right checkout, or point the app at it:",
                shellCommand: "defaults write com.erikbiebinger.tapedeck RepoRoot /path/to/tapedeck")
        }
        guard AppPaths.exists(AppPaths.venvPython) else {
            return StartupFailure(
                title: "Python environment missing",
                detail: "No .venv in \(AppPaths.repoRoot.path). Create it with:",
                shellCommand: "cd \(AppPaths.repoRoot.path)/native && make venv")
        }
        return nil
    }

    /// Reads back the tail of the server's stderr, so a boot traceback shows up
    /// in the window rather than only in a file the user has to know about.
    static func recentErrors(limit: Int = 12) -> String? {
        guard let text = try? String(contentsOfFile: AppPaths.errPath, encoding: .utf8) else {
            return nil
        }
        let lines = text.split(separator: "\n", omittingEmptySubsequences: true).suffix(limit)
        return lines.isEmpty ? nil : lines.joined(separator: "\n")
    }
}
