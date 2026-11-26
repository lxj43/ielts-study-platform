import Cocoa
import WebKit

@MainActor
final class StudyLauncher: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private let port: Int = {
        let selected = Int(ProcessInfo.processInfo.environment["IELTS_DESKTOP_PORT"] ?? "") ?? 52732
        return (1...65535).contains(selected) ? selected : 52732
    }()
    private let healthToken = UUID().uuidString
    private var server: Process?
    private var logHandle: FileHandle?
    private var status: NSStatusItem?
    private var activeWindow: NSWindow?
    private var ready = false
    private var startupFailed = false
    private var quitting = false
    private var pendingPage: String?

    private var root: URL { Bundle.main.bundleURL.deletingLastPathComponent() }
    private var logFile: URL { root.appendingPathComponent("instance/desktop-launcher.log") }
    private var address: URL { URL(string: "http://127.0.0.1:\(port)")! }

    private lazy var webView: WKWebView = {
        let view = WKWebView(frame: .zero)
        view.navigationDelegate = self
        view.autoresizingMask = [.width, .height]
        view.allowsBackForwardNavigationGestures = true
        return view
    }()

    private lazy var mainWindow: NSWindow = {
        let screen = NSScreen.main?.visibleFrame
        let size = NSSize(width: min(1100, (screen?.width ?? 1180) - 80),
                          height: min(780, (screen?.height ?? 840) - 60))
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "词间 · IELTS"
        window.contentMinSize = NSSize(width: 380, height: 430)
        window.isReleasedWhenClosed = false
        window.center()
        return window
    }()

    private lazy var floatingWindow: NSPanel = {
        let screen = NSScreen.main?.visibleFrame
        let size = NSSize(width: 430, height: min(630, (screen?.height ?? 700) - 70))
        let panel = NSPanel(contentRect: NSRect(origin: .zero, size: size),
                            styleMask: [.titled, .closable, .resizable],
                            backing: .buffered, defer: false)
        panel.title = "词间 · 置顶浮窗"
        panel.contentMinSize = NSSize(width: 350, height: 390)
        panel.isReleasedWhenClosed = false
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isExcludedFromWindowsMenu = true
        if let screen {
            panel.setFrameTopLeftPoint(NSPoint(x: screen.maxX - size.width - 20, y: screen.maxY - 20))
        }
        return panel
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        configureMenus()
        webView.loadHTMLString("""
            <!doctype html><meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <body style="margin:0;background:#f5f3ec;color:#17362d;font:16px system-ui;
                min-height:100vh;display:grid;place-items:center">正在启动词间…</body>
            """, baseURL: nil)
        if ProcessInfo.processInfo.arguments.contains("--floating") {
            openFloatingReview()
        } else {
            showMainWindow()
        }
        startServer()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return false
    }

    private func command(_ title: String, _ action: Selector, _ key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    private func configureMenus() {
        let menuBar = NSMenu()
        let appItem = NSMenuItem()
        appItem.submenu = NSMenu(title: "词间")
        appItem.submenu?.addItem(command("退出词间", #selector(quit), "q"))
        menuBar.addItem(appItem)

        let editItem = NSMenuItem()
        editItem.submenu = NSMenu(title: "编辑")
        let editActions: [(String, Selector, String)] = [
            ("撤销", Selector(("undo:")), "z"),
            ("剪切", #selector(NSText.cut(_:)), "x"),
            ("拷贝", #selector(NSText.copy(_:)), "c"),
            ("粘贴", #selector(NSText.paste(_:)), "v"),
            ("全选", #selector(NSText.selectAll(_:)), "a")
        ]
        for (title, action, key) in editActions {
            editItem.submenu?.addItem(withTitle: title, action: action, keyEquivalent: key)
        }
        menuBar.addItem(editItem)

        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(command("主窗口", #selector(showMainWindow), "1"))
        windowMenu.addItem(command("切换主窗口 / 置顶浮窗", #selector(toggleFloatingWindow), "2"))
        windowMenu.addItem(command("在浮窗打开每日复习", #selector(openFloatingReview)))
        windowMenu.addItem(.separator())
        windowMenu.addItem(command("重新载入页面", #selector(reloadPage), "r"))
        windowMenu.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = windowMenu
        menuBar.addItem(windowItem)
        NSApp.mainMenu = menuBar

        let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status.button?.title = "词间"
        let statusMenu = NSMenu()
        statusMenu.addItem(command("打开主窗口", #selector(showMainWindow)))
        statusMenu.addItem(command("切换主窗口 / 置顶浮窗", #selector(toggleFloatingWindow)))
        statusMenu.addItem(command("在浮窗打开每日复习", #selector(openFloatingReview)))
        statusMenu.addItem(.separator())
        statusMenu.addItem(command("退出词间", #selector(quit)))
        status.menu = statusMenu
        self.status = status
    }

    private func show(_ window: NSWindow) {
        if let host = window.contentView, webView.superview !== host {
            webView.removeFromSuperview()
            webView.frame = host.bounds
            host.addSubview(webView)
        }
        if activeWindow !== window {
            activeWindow?.orderOut(nil)
            activeWindow = window
        }
        window.makeKeyAndOrderFront(nil)
        if #available(macOS 14.0, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    @objc private func showMainWindow() { show(mainWindow) }

    @objc private func toggleFloatingWindow() {
        if let panel = activeWindow as? NSPanel, panel.isVisible {
            showMainWindow()
        } else {
            show(floatingWindow)
        }
    }

    @objc private func openFloatingReview() {
        show(floatingWindow)
        if ready {
            load("/review")
        } else {
            pendingPage = "/review"
        }
    }

    @objc private func reloadPage() {
        if ready { webView.reload() }
    }

    @objc private func quit() { NSApp.terminate(nil) }

    private func load(_ path: String) {
        webView.load(URLRequest(url: URL(string: path, relativeTo: address)!.absoluteURL))
    }

    private func startServer() {
        let fileManager = FileManager.default
        let pythonCandidates = [
            ProcessInfo.processInfo.environment["IELTS_PYTHON"],
            root.appendingPathComponent(".venv/bin/python").path,
            "/opt/miniconda3/envs/ielts-study/bin/python",
            fileManager.homeDirectoryForCurrentUser.appendingPathComponent("miniconda3/envs/ielts-study/bin/python").path
        ].compactMap { $0 }
        guard let python = pythonCandidates.first(where: fileManager.isExecutableFile(atPath:)),
              fileManager.fileExists(atPath: root.appendingPathComponent("app.py").path) else {
            showStartupError("请把应用保留在项目文件夹中，并安装该项目的 Python 依赖。")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["app.py"]
        process.currentDirectoryURL = root
        var environment = ProcessInfo.processInfo.environment
        environment["PORT"] = String(port)
        environment["HOST"] = "127.0.0.1"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["IELTS_DESKTOP_SESSION"] = healthToken
        process.environment = environment
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                self?.showStartupError("学习服务已退出，请查看启动日志。")
            }
        }
        do {
            try fileManager.createDirectory(at: logFile.deletingLastPathComponent(), withIntermediateDirectories: true)
            if !fileManager.fileExists(atPath: logFile.path) {
                fileManager.createFile(atPath: logFile.path, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: logFile)
            try handle.seekToEnd()
            logHandle = handle
            process.standardOutput = handle
            process.standardError = handle
            try process.run()
            server = process
            checkServer(remaining: 30)
        } catch {
            showStartupError("无法启动学习服务：\(error.localizedDescription)")
        }
    }

    private func checkServer(remaining: Int) {
        guard !quitting, !startupFailed, server?.isRunning == true else { return }
        var request = URLRequest(url: address.appendingPathComponent("_desktop/health"),
                                 cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 1)
        request.setValue(healthToken, forHTTPHeaderField: "X-IELTS-Desktop")
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            let healthy = (response as? HTTPURLResponse)?.statusCode == 204
            DispatchQueue.main.async {
                guard let self, !self.quitting, !self.startupFailed, self.server?.isRunning == true else { return }
                if healthy {
                    self.ready = true
                    self.load(self.pendingPage ?? "/")
                    self.pendingPage = nil
                } else if remaining > 0 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                        self.checkServer(remaining: remaining - 1)
                    }
                } else {
                    self.showStartupError("学习服务启动超时，请查看启动日志。")
                }
            }
        }.resume()
    }

    private func showStartupError(_ message: String) {
        guard !startupFailed, !quitting else { return }
        startupFailed = true
        ready = false
        if server?.isRunning == true { server?.terminate() }
        let alert = NSAlert()
        alert.messageText = "词间运行提示"
        alert.informativeText = message
        alert.addButton(withTitle: "知道了")
        if FileManager.default.fileExists(atPath: logFile.path) {
            alert.addButton(withTitle: "查看日志")
        }
        if let activeWindow, activeWindow.isVisible {
            alert.beginSheetModal(for: activeWindow) { [logFile] response in
                if response == .alertSecondButtonReturn { NSWorkspace.shared.open(logFile) }
            }
        }
    }

    func webView(_ view: WKWebView, decidePolicyFor navigation: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigation.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" {
            decisionHandler(.allow)
        } else if url.scheme == "http", url.host == "127.0.0.1", url.port == port {
            if navigation.targetFrame == nil {
                view.load(navigation.request)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
        } else {
            if navigation.navigationType == .linkActivated, ["https", "http"].contains(url.scheme ?? "") {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        if server?.isRunning == true { server?.terminate() }
        try? logHandle?.close()
    }
}

@main
struct StudyApplication {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = StudyLauncher()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
    }
}
