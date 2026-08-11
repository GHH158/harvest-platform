import Foundation
import Network

/// Serves one directory over `http://127.0.0.1:<random>/` for the lifetime of a screen.
///
/// It exists for a single reason (§15.10): **`AVPlayer` cannot play an HLS playlist from a
/// `file://` URL.** The bundle is well-formed and ffmpeg reads it happily; AVFoundation
/// simply requires HTTP for HLS, which is also why this project's offline playback uses the
/// `.movpkg` bundles that `AVAssetDownloadURLSession` produces (see `HLSAssetDownloader`).
/// A downloaded folder is not in that format, so the only way to watch it while cutting is
/// to hand `AVPlayer` an HTTP URL.
///
/// Scope is deliberately narrow:
/// - bound to **loopback only**, so nothing else on the Wi-Fi can reach it;
/// - the port is assigned by the system, never hard-coded;
/// - it serves **one directory** and rejects anything that resolves outside it — this is not
///   "expose the app container over HTTP";
/// - it is a plain object, so it dies with the process. There is no daemon to leak.
final class LocalMediaServer: @unchecked Sendable {
    // @unchecked because every mutable field is only touched on `queue`; the compiler
    // cannot see that invariant, and the alternative is an actor whose `deinit` could not
    // synchronously close the socket — which is the guarantee this type exists to give.
    private let queue = DispatchQueue(label: "harvest.local-media-server")
    private var listener: NWListener?
    private var connections: [NWConnection] = []
    private var root: URL?

    var isRunning: Bool { listener != nil }

    deinit { stop() }

    /// Returns the base URL. Waits for the listener to be ready, because the assigned port
    /// is not known before that.
    func start(serving directory: URL) async throws -> URL {
        stop()
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: .ipv4(.loopback), port: .any)
        let created = try NWListener(using: parameters)
        root = directory.resolvingSymlinksInPath()
        listener = created
        created.newConnectionHandler = { [weak self] connection in
            self?.accept(connection)
        }
        // The listener reports readiness on its own queue, so the continuation is guarded by
        // a one-shot box: `stateUpdateHandler` can fire more than once.
        let once = ResumeOnce()
        return try await withCheckedThrowingContinuation { continuation in
            created.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    guard let port = created.port else {
                        once.finish { continuation.resume(throwing: Failure.noPort) }
                        return
                    }
                    once.finish {
                        continuation.resume(returning: URL(string: "http://127.0.0.1:\(port.rawValue)/")!)
                    }
                case let .failed(error):
                    once.finish { continuation.resume(throwing: error) }
                case .cancelled:
                    once.finish { continuation.resume(throwing: Failure.cancelled) }
                default:
                    break
                }
            }
            created.start(queue: queue)
        }
    }

    func stop() {
        listener?.cancel()
        listener = nil
        for connection in connections { connection.cancel() }
        connections = []
        root = nil
    }

    enum Failure: LocalizedError {
        case noPort
        case cancelled

        var errorDescription: String? {
            switch self {
            case .noPort: "本机播放服务没能拿到端口。"
            case .cancelled: "本机播放服务被取消了。"
            }
        }
    }

    // MARK: - Connections

    private func accept(_ connection: NWConnection) {
        connections.append(connection)
        connection.start(queue: queue)
        receiveHead(on: connection, accumulated: Data())
    }

    /// Reads until the blank line that ends the request head. A request can arrive split
    /// across packets, so this cannot assume one read is enough.
    private func receiveHead(on connection: NWConnection, accumulated: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 16 * 1024) { [weak self] chunk, _, isComplete, error in
            guard let self else { return }
            if error != nil || (isComplete && chunk == nil) {
                connection.cancel()
                return
            }
            var buffer = accumulated
            if let chunk { buffer.append(chunk) }
            guard let separator = buffer.range(of: Data("\r\n\r\n".utf8)) else {
                if buffer.count > 64 * 1024 {
                    self.respond(on: connection, status: "431 Request Header Fields Too Large")
                    return
                }
                self.receiveHead(on: connection, accumulated: buffer)
                return
            }
            let head = String(decoding: buffer[..<separator.lowerBound], as: UTF8.self)
            self.handle(head: head, on: connection)
        }
    }

    private func handle(head: String, on connection: NWConnection) {
        let lines = head.components(separatedBy: "\r\n")
        guard let requestLine = lines.first else {
            respond(on: connection, status: "400 Bad Request")
            return
        }
        let parts = requestLine.split(separator: " ")
        guard parts.count >= 2, parts[0] == "GET" || parts[0] == "HEAD" else {
            respond(on: connection, status: "405 Method Not Allowed")
            return
        }
        guard let file = resolve(String(parts[1])) else {
            respond(on: connection, status: "404 Not Found")
            return
        }
        guard let data = try? Data(contentsOf: file, options: .mappedIfSafe) else {
            respond(on: connection, status: "404 Not Found")
            return
        }
        let rangeHeader = lines.first { $0.lowercased().hasPrefix("range:") }
        let contentType = Self.contentType(for: file)
        guard let rangeHeader, let range = Self.byteRange(from: rangeHeader, count: data.count) else {
            respond(
                on: connection,
                status: "200 OK",
                headers: ["Content-Type": contentType, "Accept-Ranges": "bytes"],
                body: parts[0] == "HEAD" ? Data() : data,
                declaredLength: data.count
            )
            return
        }
        // AVPlayer asks for ranges as soon as you scrub, so this is not optional.
        let slice = data.subdata(in: range)
        respond(
            on: connection,
            status: "206 Partial Content",
            headers: [
                "Content-Type": contentType,
                "Accept-Ranges": "bytes",
                "Content-Range": "bytes \(range.lowerBound)-\(range.upperBound - 1)/\(data.count)",
            ],
            body: parts[0] == "HEAD" ? Data() : slice,
            declaredLength: slice.count
        )
    }

    /// Path resolution is the security boundary: the result must sit inside the one directory
    /// being served, so `..` and absolute paths cannot escape it.
    private func resolve(_ target: String) -> URL? {
        guard let root else { return nil }
        let path = target.components(separatedBy: "?").first ?? target
        let decoded = path.removingPercentEncoding ?? path
        let relative = decoded.hasPrefix("/") ? String(decoded.dropFirst()) : decoded
        guard !relative.isEmpty else { return nil }
        let candidate = root.appendingPathComponent(relative).resolvingSymlinksInPath()
        guard candidate.path == root.path || candidate.path.hasPrefix(root.path + "/") else { return nil }
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: candidate.path, isDirectory: &isDirectory),
              !isDirectory.boolValue
        else { return nil }
        return candidate
    }

    private func respond(
        on connection: NWConnection,
        status: String,
        headers: [String: String] = [:],
        body: Data = Data(),
        declaredLength: Int? = nil
    ) {
        var head = "HTTP/1.1 \(status)\r\n"
        for (name, value) in headers.sorted(by: { $0.key < $1.key }) {
            head += "\(name): \(value)\r\n"
        }
        head += "Content-Length: \(declaredLength ?? body.count)\r\n"
        head += "Connection: close\r\n\r\n"
        var payload = Data(head.utf8)
        payload.append(body)
        connection.send(
            content: payload,
            completion: .contentProcessed { _ in connection.cancel() }
        )
    }

    private static func contentType(for file: URL) -> String {
        switch file.pathExtension.lowercased() {
        case "m3u8", "m3u": "application/vnd.apple.mpegurl"
        case "ts": "video/mp2t"
        case "mp4", "m4v": "video/mp4"
        case "mov": "video/quicktime"
        case "aac": "audio/aac"
        case "m4s", "mp4a": "video/iso.segment"
        default: "application/octet-stream"
        }
    }

    /// Only the single-range form AVPlayer actually sends.
    private static func byteRange(from header: String, count: Int) -> Range<Int>? {
        guard count > 0 else { return nil }
        let value = header.drop(while: { $0 != ":" }).dropFirst().trimmingCharacters(in: .whitespaces)
        guard value.lowercased().hasPrefix("bytes=") else { return nil }
        let spec = value.dropFirst("bytes=".count)
        guard !spec.contains(",") else { return nil }
        let bounds = spec.components(separatedBy: "-")
        guard bounds.count == 2 else { return nil }
        let startText = bounds[0].trimmingCharacters(in: .whitespaces)
        let endText = bounds[1].trimmingCharacters(in: .whitespaces)
        if startText.isEmpty {
            // "bytes=-500" means the final 500 bytes.
            guard let suffix = Int(endText), suffix > 0 else { return nil }
            return max(0, count - suffix)..<count
        }
        guard let start = Int(startText), start < count else { return nil }
        let end = endText.isEmpty ? count - 1 : (Int(endText) ?? count - 1)
        guard end >= start else { return nil }
        return start..<min(count, end + 1)
    }
}


/// Makes a continuation resume exactly once, from whichever queue gets there first.
private final class ResumeOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var done = false

    func finish(_ body: () -> Void) {
        lock.lock()
        let alreadyDone = done
        done = true
        lock.unlock()
        guard !alreadyDone else { return }
        body()
    }
}
