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
    /// Locations of the `.movpkg` bundles produced by `AVAssetDownloadURLSession`.
    /// The older `*SegmentPaths` fields hold raw `.ts` files that AVFoundation cannot
    /// open at all; they are decoded only so existing manifests still parse.
    let videoAssetPath: String?
    let audioAssetPath: String?
    let videoProgress: Double?
    let audioProgress: Double?
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
        videoAssetPath: String? = nil,
        audioAssetPath: String? = nil,
        videoProgress: Double? = nil,
        audioProgress: Double? = nil,
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
        self.videoAssetPath = videoAssetPath
        self.audioAssetPath = audioAssetPath
        self.videoProgress = videoProgress
        self.audioProgress = audioProgress
        self.downloadedAt = downloadedAt
    }

    var id: Int { material.id }
    var localAudioURL: URL? {
        localAudioPath.map { URL(fileURLWithPath: normalizedStoredPath($0)) }
    }
    var localVideoAssetURL: URL? { existingAsset(videoAssetPath) }
    var localShadowingAssetURL: URL? { existingAsset(audioAssetPath) }
    var isWatchVideoComplete: Bool { localVideoAssetURL != nil }
    var isShadowingAudioComplete: Bool { localShadowingAssetURL != nil }
    var hasIncompleteRequestedVideoMedia: Bool {
        guard material.kind == "video" else { return false }
        return (videoProgress != nil && localVideoAssetURL == nil)
            || (audioProgress != nil && localShadowingAssetURL == nil)
    }
    var hasPlayableMedia: Bool {
        if material.kind == "video" {
            return localVideoAssetURL != nil || localShadowingAssetURL != nil
        }
        guard let localAudioURL else { return false }
        return FileManager.default.fileExists(atPath: localAudioURL.filePath)
    }

    private func existingAsset(_ path: String?) -> URL? {
        guard let path else { return nil }
        let resolved = normalizedStoredPath(path)
        guard FileManager.default.fileExists(atPath: resolved) else { return nil }
        return URL(fileURLWithPath: resolved)
    }

    /// Rewrites every stored file path, leaving the rest of the entry untouched.
    /// Used to switch between the in-memory absolute form and the persisted relative one.
    func mappingPaths(_ transform: (String) -> String) -> OfflineEntry {
        OfflineEntry(
            material: material,
            localAudioPath: localAudioPath.map(transform),
            videoSegmentPaths: videoSegmentPaths?.map { $0.map(transform) },
            audioSegmentPaths: audioSegmentPaths?.map { $0.map(transform) },
            videoSegmentDurations: videoSegmentDurations,
            audioSegmentDurations: audioSegmentDurations,
            totalVideoSegments: totalVideoSegments,
            totalAudioSegments: totalAudioSegments,
            videoAssetPath: videoAssetPath.map(transform),
            audioAssetPath: audioAssetPath.map(transform),
            videoProgress: videoProgress,
            audioProgress: audioProgress,
            downloadedAt: downloadedAt
        )
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
    private let assetDownloader = HLSAssetDownloader()

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
        switch media {
        case .watch:
            guard let videoURL = material.videoURL else { throw OfflineLibraryError.noVideo }
            remoteURL = videoURL
        case .shadowing:
            guard let audioURL = material.audioURL else { throw OfflineLibraryError.noAudio }
            remoteURL = audioURL
        }

        // Record that a download is under way, so the UI can show progress and the
        // player knows not to switch sources yet.
        publishAssetProgress(material, media: media, fraction: 0)
        let location = try await assetDownloader.download(
            remoteURL: remoteURL,
            title: material.title
        ) { [weak self] fraction in
            guard let self else { return }
            self.publishAssetProgress(material, media: media, fraction: fraction)
        }

        // AVFoundation writes the bundle into our container already; move it under the
        // material's own directory so the existing relative-path scheme still applies.
        let root = try directory(for: material.id)
        let destination = root.appending(path: media == .watch ? "watch.movpkg" : "shadowing.movpkg")
        if destination != location {
            try? fileManager.removeItem(at: destination)
            try fileManager.moveItem(at: location, to: destination)
        }
        publishAssetEntry(material, media: media, assetPath: destination.filePath)
    }

    private func publishAssetProgress(_ material: MaterialDetail, media: VideoOfflineMedia, fraction: Double) {
        let previous = entry(for: material.id)
        upsert(
            OfflineEntry(
                material: material,
                localAudioPath: previous?.localAudioPath,
                videoAssetPath: previous?.videoAssetPath,
                audioAssetPath: previous?.audioAssetPath,
                videoProgress: media == .watch ? fraction : previous?.videoProgress,
                audioProgress: media == .shadowing ? fraction : previous?.audioProgress
            )
        )
    }

    private func publishAssetEntry(_ material: MaterialDetail, media: VideoOfflineMedia, assetPath: String) {
        let previous = entry(for: material.id)
        upsert(
            OfflineEntry(
                material: material,
                localAudioPath: previous?.localAudioPath,
                videoAssetPath: media == .watch ? assetPath : previous?.videoAssetPath,
                audioAssetPath: media == .shadowing ? assetPath : previous?.audioAssetPath,
                videoProgress: media == .watch ? 1 : previous?.videoProgress,
                audioProgress: media == .shadowing ? 1 : previous?.audioProgress
            )
        )
        try? persist()
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
        let root = try? rootDirectory()
        func resolved(_ list: [OfflineEntry]) -> [OfflineEntry] {
            guard let root else { return list }
            return list.map { entry in entry.mappingPaths { absolutePath($0, root: root) } }
        }
        if let restored = try? JSONDecoder().decode([OfflineEntry].self, from: data) {
            entries = resolved(restored).filter(\.hasPlayableMedia)
            return
        }
        // Partially corrupted manifest: salvage every individually-valid entry instead
        // of silently wiping all downloads.
        let failable = try? JSONDecoder().decode([FailableCodable<OfflineEntry>].self, from: data)
        let salvaged = resolved(failable?.compactMap(\.wrapped) ?? []).filter(\.hasPlayableMedia)
        entries = salvaged
        loadWarning = salvaged.isEmpty
            ? "已下载清单损坏，原有文件已保留。可重新下载。"
            : "部分已下载记录损坏，已跳过。可重新下载。"
    }

    /// Paths live in memory as absolute (everything downstream expects that) but are
    /// persisted relative to the offline root: the app container's absolute path can
    /// change between installs, which would strand every previously downloaded file.
    private func relativePath(_ absolute: String, root: URL) -> String {
        let rootPath = root.filePath
        guard absolute.hasPrefix(rootPath) else { return absolute }
        return String(absolute.dropFirst(rootPath.count)).trimmingCharacters(
            in: CharacterSet(charactersIn: "/")
        )
    }

    private func absolutePath(_ stored: String, root: URL) -> String {
        guard stored.hasPrefix("/") else { return root.appending(path: stored).filePath }
        // Absolute path written by an older build: usable only if it still resolves,
        // otherwise re-anchor the layout suffix (material-<id>/…) onto the current root.
        let decoded = normalizedStoredPath(stored)
        if fileManager.fileExists(atPath: decoded) { return decoded }
        guard let marker = decoded.range(of: "/material-", options: .backwards) else { return decoded }
        let suffix = String(decoded[decoded.index(after: marker.lowerBound)...])
        return root.appending(path: suffix).filePath
    }

    private struct FailableCodable<T: Decodable>: Decodable {
        let wrapped: T?
        init(from decoder: Decoder) throws {
            wrapped = try? T(from: decoder)
        }
    }

    private func persist() throws {
        let root = try rootDirectory()
        let portable = entries.map { entry in entry.mappingPaths { relativePath($0, root: root) } }
        try JSONEncoder().encode(portable).write(to: manifestURL(), options: .atomic)
    }
}

enum OfflineLibraryError: LocalizedError {
    case noAudio
    case noVideo
    case videoMediaRequired
    case invalidPlaylist
    case masterPlaylistUnsupported
    case segmentDownloadFailed(Int?)
    case assetDownloadUnavailable

    var errorDescription: String? {
        switch self {
        case .noAudio: "朗读尚未准备好，暂时无法下载。"
        case .noVideo: "视频 HLS 尚未准备好，暂时无法下载。"
        case .videoMediaRequired: "请选择下载观看视频或跟读音频。"
        case .invalidPlaylist: "无法读取视频分片清单。"
        case .masterPlaylistUnsupported: "当前只接受材料自己的 HLS 媒体清单。"
        case .assetDownloadUnavailable:
            "这台设备无法离线下载视频（模拟器不支持，请在 iPhone 上试）。"
        case .segmentDownloadFailed(let status):
            if let status { "分片下载失败（HTTP \(status)），稍后可从缺失处继续。" }
            else { "分片下载失败，稍后可从缺失处继续。" }
        }
    }
}
