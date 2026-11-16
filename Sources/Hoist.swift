import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct Receiver: Identifiable, Decodable {
    let id: String
    let name: String
    let model: String
}

final class CastBridge {
    let shared: Bool
    init(shared: Bool = false) { self.shared = shared }
    private let queue = DispatchQueue(label: "app.hoist.bridge")
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var buffer = Data()

    func request(_ payload: [String: Any], completion: @escaping (Result<[String: Any], Error>) -> Void) {
        queue.async { [self] in
            do {
                if self.process?.isRunning != true { try self.start() }
                var body = payload
                body["id"] = UUID().uuidString
                var data = try JSONSerialization.data(withJSONObject: body)
                data.append(10)
                try self.input?.write(contentsOf: data)
                let timeout = DispatchWorkItem { [task = self.process] in task?.terminate() }
                DispatchQueue.global().asyncAfter(deadline: .now() + 40, execute: timeout)
                defer { timeout.cancel() }
                while !self.buffer.contains(10) {
                    guard let chunk = self.output?.availableData, !chunk.isEmpty else {
                        throw NSError(domain: "Hoist", code: 1, userInfo: [NSLocalizedDescriptionKey: "The casting service stopped or timed out. Refresh devices to reconnect."])
                    }
                    self.buffer.append(chunk)
                }
                let end = self.buffer.firstIndex(of: 10)!
                let line = self.buffer.prefix(upTo: end)
                self.buffer.removeSubrange(...end)
                guard let reply = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
                    throw NSError(domain: "Hoist", code: 2, userInfo: [NSLocalizedDescriptionKey: "The casting service returned an invalid response."])
                }
                if reply["ok"] as? Bool != true {
                    throw NSError(domain: "Hoist", code: 3, userInfo: [NSLocalizedDescriptionKey: reply["error"] as? String ?? "Casting failed."])
                }
                let result = reply["result"] as? [String: Any] ?? [:]
                DispatchQueue.main.async { completion(.success(result)) }
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
            }
        }
    }

    private func start() throws {
        guard let resource = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
        let task = Process()
        task.executableURL = resource.appendingPathComponent("service/hoist-service")
        if shared { task.arguments = ["--app-service"] }
        let incoming = Pipe()
        let outgoing = Pipe()
        task.standardInput = incoming
        task.standardOutput = outgoing
        task.standardError = FileHandle.nullDevice
        try task.run()
        process = task
        input = incoming.fileHandleForWriting
        output = outgoing.fileHandleForReading
        buffer.removeAll()
    }

    func stop() {
        try? input?.close()
        process?.terminate()
    }
}

final class HoistModel: ObservableObject {
    @Published var devices: [Receiver] = []
    @Published var selected = UserDefaults.standard.string(forKey: "receiver") ?? ""
    @Published var link = ""
    @Published var file: URL?
    @Published var busy = false
    @Published var error: String?
    @Published var message = "Choose a screen. Make it a movie night."
    @Published var title = "Nothing playing yet"
    @Published var state = "IDLE"
    @Published var position = 0.0
    @Published var duration = 0.0
    @Published var volume = 0.5
    @Published var playbackDevice = ""
    @Published var hasSession = false
    @Published var seeking = false
    @Published var seekValue = 0.0
    @Published var changingVolume = false
    @Published var volumeValue = 0.5
    private var polling = false
    private var timer: Timer?
    let bridge = CastBridge(shared: true)

    init() {
        if CommandLine.arguments.contains("--preview") {
            devices = [Receiver(id: "preview", name: "Living room", model: "Google Cast")]
            selected = "preview"
            file = URL(fileURLWithPath: "/preview/Weekend film.mp4")
            title = "A bigger screen. A smaller app."
            message = "Interface preview · no device connected"
        } else {
            discover()
            timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.poll() }
        }
    }

    func discover() {
        perform(["action": "discover"]) { result in
            if let data = try? JSONSerialization.data(withJSONObject: result["devices"] ?? []),
               let devices = try? JSONDecoder().decode([Receiver].self, from: data) {
                self.devices = devices
                if !devices.contains(where: { $0.id == self.selected }) { self.selected = devices.first?.id ?? "" }
                self.message = devices.isEmpty ? "No screens found. Check Wi-Fi and Local Network access, then refresh." : "Ready when you are."
            }
        }
    }

    func chooseFile() {
        NSApp.activate(ignoringOtherApps: true)
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.movie, .audio]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.prompt = "Choose media"
        if panel.runModal() == .OK, let url = panel.url {
            file = url
            link = ""
            error = nil
        }
    }

    func cast() {
        guard !selected.isEmpty else { return }
        UserDefaults.standard.set(selected, forKey: "receiver")
        var request: [String: Any] = ["action": "play", "device": selected]
        if let file { request["path"] = file.path } else { request["url"] = link }
        message = "Connecting to your screen…"
        perform(request) { result in
            self.hasSession = true
            self.title = result["title"] as? String ?? "Your media"
            self.message = result["message"] as? String ?? "Sent to your screen."
            if let status = result["status"] as? [String: Any] { self.apply(status) }
        }
    }

    func control(_ action: String, value: Double? = nil) {
        var payload: [String: Any] = ["action": action]
        if let value { payload[action == "seek" ? "position" : "value"] = value }
        perform(payload) { result in
            self.apply(result)
            if action == "stop" {
                self.hasSession = false
                self.state = "IDLE"
                self.message = "Stopped. Your next watch is one click away."
            }
        }
    }

    func perform(_ payload: [String: Any], completion: @escaping ([String: Any]) -> Void) {
        guard !busy else { return }
        busy = true
        error = nil
        bridge.request(payload) { result in
            self.busy = false
            switch result {
            case .success(let value): completion(value)
            case .failure(let issue): self.error = issue.localizedDescription
            }
        }
    }

    private func poll() {
        guard !busy, !polling else { return }
        polling = true
        bridge.request(["action": "status"]) { result in
            self.polling = false
            if case .success(let status) = result { self.apply(status) }
            if case .failure(let issue) = result { self.error = issue.localizedDescription; self.hasSession = false }
        }
    }

    private func apply(_ status: [String: Any]) {
        state = status["state"] as? String ?? "IDLE"
        if status["device"] != nil { hasSession = state != "IDLE" && state != "UNKNOWN" }
        if let name = status["title"] as? String, !name.isEmpty { title = name }
        playbackDevice = status["deviceName"] as? String ?? ""
        position = status["position"] as? Double ?? 0
        duration = status["duration"] as? Double ?? 0
        volume = status["volume"] as? Double ?? 0.5
        if status["idleReason"] as? String == "ERROR" {
            error = "Your screen couldn’t play this media. Try an H.264/AAC MP4 or a supported direct stream."
        }
    }
}

struct HoistView: View {
    @ObservedObject var model: HoistModel
    private let mint = Color(red: 0.65, green: 0.95, blue: 0.72)

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 10) {
                Image(systemName: "tv")
                    .font(.system(size: 23, weight: .medium)).foregroundStyle(mint)
                    .frame(width: 44, height: 44).background(mint.opacity(0.1), in: RoundedRectangle(cornerRadius: 13))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Hoist").font(.system(size: 25, weight: .semibold, design: .rounded))
                    Text("SMALL APP. BIG SCREEN.").font(.system(size: 9, weight: .semibold)).tracking(1.5).foregroundStyle(.secondary)
                }
                Spacer()
                Text("PREVIEW").font(.system(size: 9, weight: .bold)).tracking(1)
                    .foregroundStyle(mint).padding(.horizontal, 8).padding(.vertical, 5)
                    .background(mint.opacity(0.1), in: Capsule())
            }

            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    label("YOUR SCREEN")
                    Spacer()
                    Button { model.discover() } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.plain).disabled(model.busy).help("Refresh devices")
                        .accessibilityLabel("Refresh devices")
                }
                if model.devices.isEmpty {
                    HStack(spacing: 10) {
                        Image(systemName: "tv").foregroundStyle(.secondary)
                        Text(model.busy ? "Looking for screens…" : "No screens found").font(.system(size: 13))
                        Spacer()
                        if model.busy { ProgressView().controlSize(.small) }
                    }.padding(14).background(.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
                } else {
                    Picker("Cast to", selection: $model.selected) {
                        ForEach(model.devices) { device in Text(device.name).tag(device.id) }
                    }.labelsHidden().pickerStyle(.menu).frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10).background(.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                label("SEND SOMETHING GOOD")
                Button { model.chooseFile() } label: {
                    HStack(spacing: 12) {
                        Image(systemName: model.file == nil ? "plus.rectangle.on.folder" : "film")
                            .font(.system(size: 22)).foregroundStyle(mint)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(model.file?.lastPathComponent ?? "Choose a video or audio file")
                                .font(.system(size: 13, weight: .medium)).lineLimit(1).truncationMode(.middle)
                            Text(model.file == nil ? "Or drop one here. It stays on your Mac." : "Click to choose a different file")
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                    }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                        .background(mint.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(mint.opacity(0.2), style: StrokeStyle(lineWidth: 1, dash: [4, 4])))
                }.buttonStyle(.plain).disabled(model.busy)
                    .onDrop(of: [.fileURL], isTargeted: nil) { providers in
                        guard !model.busy, let provider = providers.first else { return false }
                        _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
                            if let data, let url = URL(dataRepresentation: data, relativeTo: nil), url.isFileURL {
                                DispatchQueue.main.async { model.file = url; model.link = ""; model.error = nil }
                            }
                        }
                        return true
                    }
                HStack {
                    Image(systemName: "link").foregroundStyle(.secondary)
                    TextField("Or paste a YouTube / direct media link", text: $model.link)
                        .textFieldStyle(.plain).font(.system(size: 12))
                        .onChange(of: model.link) { value in if !value.isEmpty { model.file = nil } }
                        .onSubmit { if !model.busy { model.cast() } }
                    if model.file != nil {
                        Button { model.file = nil } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain).help("Clear file")
                    }
                }.padding(12).background(.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 10))
                Button { model.cast() } label: {
                    HStack {
                        if model.busy { ProgressView().controlSize(.small).tint(.black) }
                        Text(model.busy ? "Working…" : "Hoist to screen").font(.system(size: 14, weight: .semibold))
                        if !model.busy { Image(systemName: "arrow.up.right") }
                    }.frame(maxWidth: .infinity).padding(.vertical, 12)
                        .foregroundStyle(Color.black).background(mint, in: RoundedRectangle(cornerRadius: 11))
                }.buttonStyle(.plain)
                    .disabled(model.busy || model.selected.isEmpty || (model.file == nil && model.link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
                    .opacity(model.busy || model.selected.isEmpty || (model.file == nil && model.link.isEmpty) ? 0.45 : 1)
            }

            if model.hasSession {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        label(model.state == "PLAYING" ? "NOW PLAYING" : model.state)
                        Spacer()
                        Text(model.playbackDevice).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Text(model.title).font(.system(size: 13, weight: .medium)).lineLimit(2)
                    if model.duration > 0 {
                        Slider(value: Binding(get: { model.seeking ? model.seekValue : min(model.position, model.duration) }, set: { model.seekValue = $0 }), in: 0...max(1, model.duration), onEditingChanged: { editing in
                            model.seeking = editing
                            if !editing { model.control("seek", value: model.seekValue) }
                        }).tint(mint).accessibilityLabel("Playback position")
                        HStack {
                            Text(time(model.position)); Spacer(); Text(time(model.duration))
                        }.font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                    }
                    HStack(spacing: 15) {
                        Button { model.control(model.state == "PLAYING" ? "pause" : "resume") } label: {
                            Image(systemName: model.state == "PLAYING" ? "pause.fill" : "play.fill")
                        }.accessibilityLabel(model.state == "PLAYING" ? "Pause" : "Resume")
                        Button { model.control("stop") } label: { Image(systemName: "stop.fill") }.accessibilityLabel("Stop casting")
                        Image(systemName: "speaker.wave.2").font(.system(size: 11)).foregroundStyle(.secondary)
                        Slider(value: Binding(get: { model.changingVolume ? model.volumeValue : model.volume }, set: { model.volumeValue = $0 }), in: 0...1, onEditingChanged: { editing in
                            model.changingVolume = editing
                            if !editing { model.control("volume", value: model.volumeValue) }
                        }).tint(mint).accessibilityLabel("Volume")
                    }.buttonStyle(.plain).disabled(model.busy)
                }.padding(14).background(.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
            }

            Text(model.error ?? model.message).font(.system(size: 11)).foregroundStyle(model.error == nil ? Color.secondary : Color.orange)
                .fixedSize(horizontal: false, vertical: true)
            Divider().overlay(.white.opacity(0.05))
            HStack {
                Menu {
                    Button("Local Network settings…") { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_LocalNetwork")!) }
                    Button("Help & compatibility") { NSWorkspace.shared.open(URL(string: "https://github.com/TheOneWhoBurns/hoist#compatibility")!) }
                    Divider()
                    Button("Firefox companion…") { NSWorkspace.shared.open(URL(string: "https://github.com/TheOneWhoBurns/hoist/blob/main/extension/README.md")!) }
                    Text("Hoist 0.2.2 · Development preview")
                } label: { Image(systemName: "gearshape") }.menuStyle(.borderlessButton).frame(width: 24)
                Text("Keep Hoist open while streaming files.").font(.system(size: 10)).foregroundStyle(.secondary)
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }.padding(22).frame(width: 390).background(Color(red: 0.065, green: 0.08, blue: 0.075))
            .preferredColorScheme(.dark)
    }

    private func label(_ text: String) -> some View {
        Text(text).font(.system(size: 10, weight: .semibold)).tracking(1.3).foregroundStyle(.secondary)
    }

    private func time(_ seconds: Double) -> String {
        let value = max(0, Int(seconds))
        return String(format: "%d:%02d", value / 60, value % 60)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var item: NSStatusItem!
    let popover = NSPopover()
    var model: HoistModel!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureMenu()
        if CommandLine.arguments.contains("--diagnose") {
            let bridge = CastBridge()
            bridge.request(["action": "ping"]) { result in
                switch result {
                case .success(let reply):
                    print(String(data: try! JSONSerialization.data(withJSONObject: reply), encoding: .utf8)!)
                    bridge.stop()
                    exit(0)
                case .failure(let error):
                    fputs(error.localizedDescription + "\n", stderr)
                    bridge.stop()
                    exit(1)
                }
            }
            return
        }
        model = HoistModel()
        if let index = CommandLine.arguments.firstIndex(of: "--render-preview"), CommandLine.arguments.count > index + 1 {
            let view = NSHostingView(rootView: HoistView(model: model))
            let size = view.fittingSize
            view.frame = NSRect(origin: .zero, size: size)
            let window = NSWindow(contentRect: view.frame, styleMask: .borderless, backing: .buffered, defer: false)
            window.contentView = view
            view.layoutSubtreeIfNeeded()
            if let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
                view.cacheDisplay(in: view.bounds, to: bitmap)
                try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: CommandLine.arguments[index + 1]))
            }
            exit(0)
        }
        do {
            let directory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Mozilla/NativeMessagingHosts")
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let manifest: [String: Any] = ["name": "io.github.theonewhoburns.hoist", "description": "Hoist Firefox companion", "path": Bundle.main.resourceURL!.appendingPathComponent("hoist-native").path, "type": "stdio", "allowed_extensions": ["hoist@theonewhoburns.github.io"]]
            try JSONSerialization.data(withJSONObject: manifest, options: .prettyPrinted).write(to: directory.appendingPathComponent("io.github.theonewhoburns.hoist.json"), options: .atomic)
        } catch { model.error = "Firefox setup failed: \(error.localizedDescription)" }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "tv", accessibilityDescription: "Hoist")
        item.button?.target = self
        item.button?.action = #selector(toggle)
        item.button?.toolTip = "Hoist · Send something to the big screen"
        popover.behavior = CommandLine.arguments.contains("--check-layout") || CommandLine.arguments.contains("--ui-check") ? .applicationDefined : .transient
        let host = NSHostingController(rootView: HoistView(model: model))
        host.sizingOptions = [.preferredContentSize, .intrinsicContentSize]
        popover.contentViewController = host
        popover.contentSize = host.view.fittingSize
        if CommandLine.arguments.contains("--preview") || CommandLine.arguments.contains("--show") || CommandLine.arguments.contains("--ui-check") {
            DispatchQueue.main.async { self.toggle() }
        }
        if CommandLine.arguments.contains("--check-layout") {
            let delay = CommandLine.arguments.contains("--preview") ? 0.5 : 8.0
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                guard let view = self.popover.contentViewController?.view, let window = view.window, let screen = window.screen else {
                    print("Popover unavailable: shown=\(self.popover.isShown), size=\(self.popover.contentSize), anchor=\(String(describing: self.item.button?.window?.frame)), visible=\(String(describing: self.item.button?.window?.isVisible)), hidden=\(String(describing: self.item.button?.isHiddenOrHasHiddenAncestor)), bounds=\(String(describing: self.item.button?.bounds)), active=\(NSApp.isActive)")
                    exit(1)
                }
                let content = window.convertToScreen(view.convert(view.bounds, to: nil))
                let fits = screen.visibleFrame.insetBy(dx: -1, dy: -1).contains(content)
                let report: [String: Any] = ["fitsScreen": fits, "content": NSStringFromRect(content), "screen": NSStringFromRect(screen.visibleFrame), "devices": self.model.devices.map(\.name)]
                print(String(data: try! JSONSerialization.data(withJSONObject: report), encoding: .utf8)!)
                exit(fits ? 0 : 1)
            }
        }
    }

    private func configureMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu(title: "Hoist")
        appMenu.addItem(withTitle: "Quit Hoist", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        for (title, action, key) in [("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = editMenu
        main.addItem(editItem)
        NSApp.mainMenu = main
    }

    @objc func toggle() {
        guard let button = item.button else { return }
        if popover.isShown { popover.performClose(nil) } else {
            if model.devices.isEmpty && !model.busy { model.discover() }
            if let view = popover.contentViewController?.view {
                view.layoutSubtreeIfNeeded()
                popover.contentSize = view.fittingSize
            }
            NSApp.activate(ignoringOtherApps: true)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                self.popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) { model.bridge.stop() }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
