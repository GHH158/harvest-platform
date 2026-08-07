import Foundation
import Network

extension URL {
    /// Real filesystem path for `FileManager` and for what we persist.
    ///
    /// `URL.path()` percent-encodes by default, so iOS's own "Application Support"
    /// became "Application%20Support". Downloads still landed correctly (they go
    /// through URL-based APIs), but every `fileExists`/`attributesOfItem` check on
    /// the encoded string failed — the download button never left its initial state,
    /// resumable downloads always restarted, and offline playback silently fell back
    /// to the network.
    var filePath: String { path(percentEncoded: false) }
}

/// Repairs paths persisted before `filePath` existed: they may still carry the
/// percent-encoded form, which no longer matches anything on disk.
func normalizedStoredPath(_ path: String) -> String {
    if FileManager.default.fileExists(atPath: path) { return path }
    guard let decoded = path.removingPercentEncoding, decoded != path else { return path }
    return decoded
}

struct OfflineEntry: Codable, Identifiable {
    let material: MaterialDetail
    let localAudioPath: String?
    let videoSegmentPaths: [String?]?
    let audioSegmentPaths: [String?]?
    let videoSegmentDurations: [Double]?
    let audioSegmentDurations: [Double]?
    let totalVideoSegments: Int?
    let totalAudioSegments: Int?
    let downloadedAt: Date

    init(
        material: MaterialDetail,
        localAudioPath: String? = nil,
        videoSegmentPaths: [String?]? = nil,
        audioSegmentPaths: [String?]? = nil,
        videoSegmentDurations: [Double]? = nil,
        audioSegmentDurations: [Double]? = nil,
        totalVideoSegments: Int? = nil,
        totalAudioSegments: Int? = nil,
        downloadedAt: Date = .now
    ) {
        self.material = material
        self.localAudioPath = localAudioPath
        self.videoSegmentPaths = videoSegmentPaths
        self.audioSegmentPaths = audioSegmentPaths
        self.videoSegmentDurations = videoSegmentDurations
        self.audioSegmentDurations = audioSegmentDurations
        self.totalVideoSegments = totalVideoSegments
        self.totalAudioSegments = totalAudioSegments
        self.downloadedAt = downloadedAt
    }

    var id: Int { material.id }
    var localAudioURL: URL? {
        localAudioPath.map { URL(fileURLWithPath: normalizedStoredPath($0)) }
    }
    var localVideoSegmentURLs: [URL] { contiguousURLs(videoSegmentPaths ?? []) }
    var localHLSAudioSegmentURLs: [URL] { contiguousURLs(audioSegmentPaths ?? []) }
    var downloadedVideoSegmentCount: Int { existingCount(videoSegmentPaths ?? []) }
    var downloadedAudioSegmentCount: Int { existingCount(audioSegmentPaths ?? []) }
    var isWatchVideoComplete: Bool {
        guard material.kind == "video", let totalVideoSegments else { return false }
        return downloadedVideoSegmentCount == totalVideoSegments
    }
    var isShadowingAudioComplete: Bool {
        guard material.kind == "video", let totalAudioSegments else { return false }
        return downloadedAudioSegmentCount == totalAudioSegments
    }
    var hasIncompleteRequestedVideoMedia: Bool {
        guard material.kind == "video" else { return false }
        return (totalVideoSegments != nil && !isWatchVideoComplete)
            || (totalAudioSegments != nil && !isShadowingAudioComplete)
    }
    var hasPlayableMedia: Bool {
        if material.kind == "video" {
            return !localVideoSegmentURLs.isEmpty || !localHLSAudioSegmentURLs.isEmpty
        }
        guard let localAudioURL else { return false }
        return FileManager.default.fileExists(atPath: localAudioURL.filePath)
    }

    private func contiguousURLs(_ paths: [String?]) -> [URL] {
        var urls: [URL] = []
        for path in paths {
            guard let path else { break }
            let resolved = normalizedStoredPath(path)
            guard FileManager.default.fileExists(atPath: resolved) else { break }
            urls.append(URL(fileURLWithPath: resolved))
        }
        return urls
    }

    private func existingCount(_ paths: [String?]) -> Int {
        paths.compactMap(\.self).count { FileManager.default.fileExists(atPath: normalizedStoredPath($0)) }
    }
}

enum VideoOfflineMedia: Equatable {
    case watch
    case shadowing
}

enum ConnectivityStatus: Equatable {
    case unknown
    case wifi
    case cellular
    case unavailable
}

struct HLSSegment: Hashable {
    let url: URL
    let duration: Double
}

struct HLSPlaylist {
    let segments: [HLSSegment]

    init(text: String, baseURL: URL) throws {
        var parsed: [HLSSegment] = []
        var pendingDuration: Double?
        for rawLine in text.components(separatedBy: .newlines) {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            if line.hasPrefix("#EXTINF:") {
                let value = line.dropFirst("#EXTINF:".count).split(separator: ",", maxSplits: 1)[0]
                pendingDuration = Double(value)
            } else if !line.isEmpty && !line.hasPrefix("#") {
                guard !line.lowercased().hasSuffix(".m3u8") else { throw OfflineLibraryError.masterPlaylistUnsupported }
                guard let url = URL(string: line, relativeTo: baseURL)?.absoluteURL else {
                    throw OfflineLibraryError.invalidPlaylist
                }
                parsed.append(HLSSegment(url: url, duration: pendingDuration ?? 0))
                pendingDuration = nil
            }
        }
        guard !parsed.isEmpty else { throw OfflineLibraryError.invalidPlaylist }
        segments = parsed
    }
}

struct OfflineStorageInfo: Equatable {
    let usedBytes: Int64
    let availableBytes: Int64
}

@MainActor
final class OfflineLibrary: ObservableObject {
    @Published private(set) var entries: [OfflineEntry] = []
    @Published private(set) var activeDownloadIDs: Set<Int> = []
    @Published private(set) var connectivity: ConnectivityStatus = .unknown
    @Published private(set) var loadWarning: String?
    private let fileManager = FileManager.default
    private let downloadSession: URLSession
    private let rootDirectoryOverride: URL?
    private let monitor = NWPathMonitor()

    init(downloadSession: URLSession? = nil, rootDirectory: URL? = nil) {
        self.downloadSession = downloadSession ?? Self.makeDownloadSession()
        rootDirectoryOverride = rootDirectory
        load()
        // Real usage only (tests inject a session and should not start a path monitor).
        if downloadSession == nil {
            monitor.pathUpdateHandler = { [weak self] path in
                let status: ConnectivityStatus
                if path.status == .satisfied {
                    status = path.isExpensive ? .cellular : .wifi
                } else {
                    status = .unavailable
                }
                Task { @MainActor in self?.connectivity = status }
            }
            monitor.start(queue: .global(qos: .utility))
        }
    }

    private static func makeDownloadSession() -> URLSession {
        let configuration = URLSessionConfiguration.default
        configuration.allowsCellularAccess = false
        // Never block app startup waiting for Wi-Fi/Tailscale to appear.
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 300
        return URLSession(configuration: configuration)
    }

    func entry(for materialID: Int) -> OfflineEntry? { entries.first { $0.id == materialID } }

    func localAudioURL(for materialID: Int) -> URL? {
        guard let url = entry(for: materialID)?.localAudioURL, fileManager.fileExists(atPath: url.filePath) else {
            return nil
        }
        return url
    }

    func isDownloading(_ materialID: Int) -> Bool { activeDownloadIDs.contains(materialID) }

    func download(_ material: MaterialDetail, videoMedia: VideoOfflineMedia? = nil) async throws {
        guard !activeDownloadIDs.contains(material.id) else { return }
        activeDownloadIDs.insert(material.id)
        defer { activeDownloadIDs.remove(material.id) }
        if material.kind == "video" {
            guard let videoMedia else { throw OfflineLibraryError.videoMediaRequired }
            try await downloadVideo(material, media: videoMedia)
        } else {
            try await downloadReading(material)
        }
    }

    func resumeIncompleteDownloads() {
        // Cap concurrent resume work so a reinstall/cold start does not stampede the network.
        let pending = entries.filter(\.hasIncompleteRequestedVideoMedia).prefix(2)
        for entry in pending {
            Task { try? await self.resume(entry) }
        }
    }

    func resume(_ entry: OfflineEntry) async throws {
        guard entry.material.kind == "video" else { return }
        if entry.totalVideoSegments != nil && !entry.isWatchVideoComplete {
            try await download(entry.material, videoMedia: .watch)
        }
        if let refreshed = self.entry(for: entry.id),
           refreshed.totalAudioSegments != nil, !refreshed.isShadowingAudioComplete {
            try await download(refreshed.material, videoMedia: .shadowing)
        }
    }

    func remove(_ entry: OfflineEntry) {
        guard !isDownloading(entry.id) else { return }
        if let directory = try? directory(for: entry.id) { try? fileManager.removeItem(at: directory) }
        entries.removeAll { $0.id == entry.id }
        try? persist()
    }

    func remove(ids: Set<Int>) {
        for entry in entries where ids.contains(entry.id) && !isDownloading(entry.id) {
            if let directory = try? directory(for: entry.id) { try? fileManager.removeItem(at: directory) }
        }
        entries.removeAll { ids.contains($0.id) && !isDownloading($0.id) }
        try? persist()
    }

    func storageInfo() -> OfflineStorageInfo {
        guard let root = try? rootDirectory() else { return OfflineStorageInfo(usedBytes: 0, availableBytes: 0) }
        let available = (try? root.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?
            .volumeAvailableCapacityForImportantUsage ?? 0
        return OfflineStorageInfo(usedBytes: directoryBytes(root), availableBytes: available)
    }

    /// Removes URL cache and files not referenced by the persisted offline
    /// manifest. Registered complete and partial HLS segments remain resumable.
    @discardableResult
    func clearCache() -> Int64 {
        URLCache.shared.removeAllCachedResponses()
        guard let root = try? rootDirectory() else { return 0 }
        let before = directoryBytes(root)
        var referenced = Set<String>()
        if let manifest = try? manifestURL() { referenced.insert(manifest.standardizedFileURL.filePath) }
        for entry in entries {
            if let path = entry.localAudioPath { referenced.insert(URL(fileURLWithPath: path).standardizedFileURL.filePath) }
            for path in (entry.videoSegmentPaths ?? []).compactMap(\.self) {
                referenced.insert(URL(fileURLWithPath: path).standardizedFileURL.filePath)
            }
            for path in (entry.audioSegmentPaths ?? []).compactMap(\.self) {
                referenced.insert(URL(fileURLWithPath: path).standardizedFileURL.filePath)
            }
        }
        if let enumerator = fileManager.enumerator(
            at: root,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) {
            for case let url as URL in enumerator {
                let isFile = (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
                if isFile, !referenced.contains(url.standardizedFileURL.filePath) {
                    try? fileManager.removeItem(at: url)
                }
            }
        }
        return max(0, before - directoryBytes(root))
    }

    private func downloadReading(_ material: MaterialDetail) async throws {
        guard let remoteURL = material.audioURL else { throw OfflineLibraryError.noAudio }
        let directory = try directory(for: material.id)
        let destination = directory.appending(path: "reading.mp3")
        let attributes = try? fileManager.attributesOfItem(atPath: destination.filePath)
        let existingSize = (attributes?[.size] as? NSNumber)?.intValue ?? 0
        try await downloadResumable(remoteURL, to: destination, resumeOffset: existingSize)
        upsert(OfflineEntry(material: material, localAudioPath: destination.filePath))
        try persist()
    }

    private func downloadVideo(_ material: MaterialDetail, media: VideoOfflineMedia) async throws {
        let remoteURL: URL
        let directoryName: String
        switch media {
        case .watch:
            guard let videoURL = material.videoURL else { throw OfflineLibraryError.noVideo }
            remoteURL = videoURL
            directoryName = "hls-video"
        case .shadowing:
            guard let audioURL = material.audioURL else { throw OfflineLibraryError.noAudio }
            remoteURL = audioURL
            directoryName = "hls-audio"
        }

        let mediaPlaylist = try await playlist(from: remoteURL)
        let root = try directory(for: material.id)
        let mediaDirectory = root.appending(path: directoryName)
        try fileManager.createDirectory(at: mediaDirectory, withIntermediateDirectories: true)
        var paths = existingPaths(for: mediaPlaylist.segments, in: mediaDirectory)
        let durations = mediaPlaylist.segments.map(\.duration)
        try publishVideoEntry(
            material, media: media, paths: paths, durations: durations, total: mediaPlaylist.segments.count
        )

        for index in mediaPlaylist.segments.indices where paths[index] == nil {
            try Task.checkCancellation()
            let segment = mediaPlaylist.segments[index]
            let destination = segmentDestination(index: index, remoteURL: segment.url, directory: mediaDirectory)
            try await download(segment.url, to: destination)
            paths[index] = destination.filePath
            try publishVideoEntry(material, media: media, paths: paths, durations: durations, total: mediaPlaylist.segments.count)
        }
    }

    private func playlist(from url: URL) async throws -> HLSPlaylist {
        let (data, response) = try await downloadSession.data(from: url)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
              let text = String(data: data, encoding: .utf8) else {
            throw OfflineLibraryError.invalidPlaylist
        }
        return try HLSPlaylist(text: text, baseURL: url)
    }

    private func existingPaths(for segments: [HLSSegment], in directory: URL) -> [String?] {
        segments.indices.map { index in
            let destination = segmentDestination(index: index, remoteURL: segments[index].url, directory: directory)
            return fileManager.fileExists(atPath: destination.filePath) ? destination.filePath : nil
        }
    }

    private func segmentDestination(index: Int, remoteURL: URL, directory: URL) -> URL {
        let suffix = remoteURL.pathExtension.isEmpty ? "ts" : remoteURL.pathExtension
        return directory.appending(path: String(format: "segment-%05d.%@", index, suffix))
    }

    private func download(_ remoteURL: URL, to destination: URL) async throws {
        let (temporaryURL, response) = try await downloadSession.download(from: remoteURL)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            try? fileManager.removeItem(at: temporaryURL)
            throw OfflineLibraryError.segmentDownloadFailed((response as? HTTPURLResponse)?.statusCode)
        }
        try? fileManager.removeItem(at: destination)
        try fileManager.moveItem(at: temporaryURL, to: destination)
    }

    /// Byte-range resumable download for single-file media (reading audio).
    /// `200` → write whole body (server ignored Range); `206` → append to the
    /// existing partial file; `416` → already complete.
    private func downloadResumable(_ remoteURL: URL, to destination: URL, resumeOffset: Int) async throws {
        var request = URLRequest(url: remoteURL)
        if resumeOffset > 0 {
            request.setValue("bytes=\(resumeOffset)-", forHTTPHeaderField: "Range")
        }
        let (data, response) = try await downloadSession.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw OfflineLibraryError.segmentDownloadFailed(nil) }
        switch http.statusCode {
        case 200:
            try data.write(to: destination, options: .atomic)
        case 206:
            if !fileManager.fileExists(atPath: destination.filePath) {
                fileManager.createFile(atPath: destination.filePath, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: destination)
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
            try handle.close()
        case 416:
            break
        default:
            throw OfflineLibraryError.segmentDownloadFailed(http.statusCode)
        }
    }

    private func publishVideoEntry(
        _ material: MaterialDetail,
        media: VideoOfflineMedia,
        paths: [String?],
        durations: [Double],
        total: Int
    ) throws {
        let previous = entry(for: material.id)
        upsert(
            OfflineEntry(
                material: material,
                videoSegmentPaths: media == .watch ? paths : previous?.videoSegmentPaths,
                audioSegmentPaths: media == .shadowing ? paths : previous?.audioSegmentPaths,
                videoSegmentDurations: media == .watch ? durations : previous?.videoSegmentDurations,
                audioSegmentDurations: media == .shadowing ? durations : previous?.audioSegmentDurations,
                totalVideoSegments: media == .watch ? total : previous?.totalVideoSegments,
                totalAudioSegments: media == .shadowing ? total : previous?.totalAudioSegments
            )
        )
        try persist()
    }

    private func upsert(_ entry: OfflineEntry) {
        entries.removeAll { $0.id == entry.id }
        entries.append(entry)
    }

    private func directory(for materialID: Int) throws -> URL {
        let directory = try rootDirectory().appending(path: "material-\(materialID)")
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func rootDirectory() throws -> URL {
        if let rootDirectoryOverride {
            try fileManager.createDirectory(at: rootDirectoryOverride, withIntermediateDirectories: true)
            return rootDirectoryOverride
        }
        let applicationSupport = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let root = applicationSupport.appending(path: "HarvestOffline")
        try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func manifestURL() throws -> URL { try rootDirectory().appending(path: "manifest.json") }

    private func directoryBytes(_ root: URL) -> Int64 {
        guard let enumerator = fileManager.enumerator(
            at: root,
            includingPropertiesForKeys: [.isRegularFileKey, .fileAllocatedSizeKey, .fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else { return 0 }
        var total: Int64 = 0
        for case let url as URL in enumerator {
            guard let values = try? url.resourceValues(
                forKeys: [.isRegularFileKey, .fileAllocatedSizeKey, .fileSizeKey]
            ), values.isRegularFile == true else { continue }
            total += Int64(values.fileAllocatedSize ?? values.fileSize ?? 0)
        }
        return total
    }

    private func load() {
        guard let url = try? manifestURL(), let data = try? Data(contentsOf: url) else { return }
        if let restored = try? JSONDecoder().decode([OfflineEntry].self, from: data) {
            entries = restored.filter(\.hasPlayableMedia)
            return
        }
        // Partially corrupted manifest: salvage every individually-valid entry instead
        // of silently wiping all downloads.
        let failable = try? JSONDecoder().decode([FailableCodable<OfflineEntry>].self, from: data)
        let salvaged = failable?.compactMap(\.wrapped).filter(\.hasPlayableMedia) ?? []
        entries = salvaged
        loadWarning = salvaged.isEmpty
            ? "已下载清单损坏，原有文件已保留。可重新下载。"
            : "部分已下载记录损坏，已跳过。可重新下载。"
    }

    private struct FailableCodable<T: Decodable>: Decodable {
        let wrapped: T?
        init(from decoder: Decoder) throws {
            wrapped = try? T(from: decoder)
        }
    }

    private func persist() throws {
        try JSONEncoder().encode(entries).write(to: manifestURL(), options: .atomic)
    }
}

enum OfflineLibraryError: LocalizedError {
    case noAudio
    case noVideo
    case videoMediaRequired
    case invalidPlaylist
    case masterPlaylistUnsupported
    case segmentDownloadFailed(Int?)

    var errorDescription: String? {
        switch self {
        case .noAudio: "朗读尚未准备好，暂时无法下载。"
        case .noVideo: "视频 HLS 尚未准备好，暂时无法下载。"
        case .videoMediaRequired: "请选择下载观看视频或跟读音频。"
        case .invalidPlaylist: "无法读取视频分片清单。"
        case .masterPlaylistUnsupported: "当前只接受材料自己的 HLS 媒体清单。"
        case .segmentDownloadFailed(let status):
            if let status { "分片下载失败（HTTP \(status)），稍后可从缺失处继续。" }
            else { "分片下载失败，稍后可从缺失处继续。" }
        }
    }
}
