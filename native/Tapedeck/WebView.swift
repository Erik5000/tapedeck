import SwiftUI
import WebKit

extension Notification.Name {
    static let reloadWebView = Notification.Name("Tapedeck.reloadWebView")
    static let hardReloadWebView = Notification.Name("Tapedeck.hardReloadWebView")
}

struct WebView: NSViewRepresentable {
    let url: URL

    final class Coordinator: NSObject {
        weak var webView: WKWebView?
        var observers: [NSObjectProtocol] = []

        deinit {
            observers.forEach(NotificationCenter.default.removeObserver)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.load(URLRequest(url: url))
        context.coordinator.webView = webView

        let center = NotificationCenter.default
        context.coordinator.observers = [
            center.addObserver(forName: .reloadWebView, object: nil, queue: .main) {
                [weak coordinator = context.coordinator] _ in
                coordinator?.webView?.reload()
            },
            // ⇧⌘R — the shell JS and the page CSS are both cached, so a plain
            // reload can keep serving an old app shell after an edit.
            center.addObserver(forName: .hardReloadWebView, object: nil, queue: .main) {
                [weak coordinator = context.coordinator] _ in
                coordinator?.webView?.reloadFromOrigin()
            },
        ]
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}
}
