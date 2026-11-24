import Cocoa

final class DragHandle: NSView {
    override func hitTest(_ point: NSPoint) -> NSView? { bounds.contains(convert(point, from: superview)) ? self : nil }
    override var mouseDownCanMoveWindow: Bool { true }
    override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
    override func resetCursorRects() { addCursorRect(bounds, cursor: .openHand) }
}

final class StudyLauncher: NSObject, NSApplicationDelegate {
    var panel: NSPanel!
    var status: NSStatusItem!
    var server: Process?
    var logHandle: FileHandle?
    var ready = false
    var attempts = 0
    let port = 52732
    var root: URL { Bundle.main.bundleURL.deletingLastPathComponent() }
    var address: URL { URL(string: "http://127.0.0.1:\(port)/login")! }

    func applicationDidFinishLaunching(_ notification: Notification) {
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status.button?.title = "词间"
        let menu = NSMenu()
        menu.addItem(withTitle: "打开学习平台", action: #selector(openStudy), keyEquivalent: "")
        menu.addItem(withTitle: "显示 / 隐藏悬浮入口", action: #selector(togglePanel), keyEquivalent: "")
        menu.addItem(NSMenuItem.separator())
        menu.addItem(withTitle: "退出词间（停止本启动器服务）", action: #selector(quit), keyEquivalent: "q")
        for item in menu.items { item.target = self }
        status.menu = menu
        panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 160, height: 48), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = true
        panel.backgroundColor = NSColor(calibratedRed: 0.08, green: 0.27, blue: 0.22, alpha: 0.95)
        panel.isOpaque = false
        panel.hasShadow = true
        panel.contentView?.wantsLayer = true
        panel.contentView?.layer?.cornerRadius = 14
        panel.contentView?.layer?.masksToBounds = true
        let button = NSButton(frame: NSRect(x: 28, y: 0, width: 132, height: 48))
        button.title = "词间 · 启动中"
        button.isBordered = false
        button.contentTintColor = .white
        button.font = NSFont.systemFont(ofSize: 14, weight: .medium)
        button.target = self
        button.action = #selector(openStudy)
        let handle = DragHandle(frame: NSRect(x: 0, y: 0, width: 28, height: 48))
        handle.toolTip = "按住这里拖动悬浮窗"
        let grip = NSTextField(labelWithString: "⠿")
        grip.frame = NSRect(x: 8, y: 13, width: 18, height: 24)
        grip.textColor = .white
        grip.font = NSFont.systemFont(ofSize: 19)
        grip.isEnabled = false
        handle.addSubview(grip)
        panel.contentView?.addSubview(handle)
        panel.contentView?.addSubview(button)
        if let screen = NSScreen.main {
            let frame = screen.visibleFrame
            panel.setFrameOrigin(NSPoint(x: frame.maxX - 180, y: frame.maxY - 72))
        }
        panel.orderFrontRegardless()
        startServer()
    }
    func startServer() {
        let python = ProcessInfo.processInfo.environment["IELTS_PYTHON"]
            ?? root.appendingPathComponent(".venv/bin/python").path
        guard FileManager.default.isExecutableFile(atPath: python), FileManager.default.fileExists(atPath: root.appendingPathComponent("app.py").path) else {
            showError("找不到 Python 环境或 app.py。请将启动器保留在项目文件夹内，并在项目目录创建 .venv 和安装 requirements.txt。")
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
        process.environment = environment
        let log = root.appendingPathComponent("instance/desktop-launcher.log")
        try? FileManager.default.createDirectory(at: log.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: log.path, contents: nil)
        logHandle = try? FileHandle(forWritingTo: log)
        process.standardOutput = logHandle
        process.standardError = logHandle
        do { try process.run(); server = process; poll() }
        catch { showError("启动失败：\(error.localizedDescription)") }
    }
    func poll() {
        guard server?.isRunning == true else { showError("平台未能启动。请查看 instance/desktop-launcher.log；可能是端口被占用。") ; return }
        attempts += 1
        URLSession.shared.dataTask(with: address) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200, self.server?.isRunning == true {
                    self.ready = true
                    (self.panel.contentView?.subviews.compactMap { $0 as? NSButton }.first)?.title = "词间 · 开始学习 ↗"
                } else if self.attempts < 40 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.poll() }
                } else { self.showError("启动超时，请查看 instance/desktop-launcher.log。") }
            }
        }.resume()
    }
    func showError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "词间启动提示"; alert.informativeText = message
        alert.runModal()
    }
    @objc func openStudy() { if ready { NSWorkspace.shared.open(address) } }
    @objc func togglePanel() { if panel.isVisible { panel.orderOut(nil) } else { panel.orderFrontRegardless() } }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) { if server?.isRunning == true { server?.terminate() }; try? logHandle?.close() }
}
let app = NSApplication.shared
let delegate = StudyLauncher()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
