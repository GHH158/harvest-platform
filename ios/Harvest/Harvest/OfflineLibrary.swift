import Foundation

struct OfflineEntry: Codable, Identifiable {
    let material: MaterialDetail
    let localAudioPath: String?
    let videoSegmentPaths: [String?]?
    let audioSegmentPaths: [String?]?
    let totalVideoSegments: Int?
    let totalAudioSegments: Int?
    let downloadedAt: Date

    init(
        material: MaterialDetail,
        localAudioPath: String? = nil,
        videoSegmentPaths: [String?]? = nil,
        audioSegmentPaths: [String?]? = nil,
        totalVideoSegments: Int? = nil,
        totalAudioSegments: Int? = nil,
        downloadedAt: Date = .now
    ) {
        self.material = material
        self.localAudioPath = localAudioPath
        self.videoSegmentPaths = videoSegmentPaths
        self.audioSegmentPaths = audioSegmentPaths
        self.totalVideoSegments = totalVideoSegments
        self.totalAudioSegments = totalAudioSegments
        self.downloadedAt = downloadedAt
    }

    var id: Int { material.id }
    var localAudioURL: URL? { localAudioPath.map(URL.init(fileURLWithPath:)) }
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
        return FileManager.default.fileExists(atPath: localAudioURL.path())
    }

    private func contiguousURLs(_ paths: [String?]) -> [URL] {
        var urls: [URL] = []
        for path in paths {
            guard let path, FileManager.default.fileExists(atPath: path) else { break }
            urls.append(URL(fileURLWithPath: path))
        }
        return urls
    }

    private func existingCount(_ paths: [String?]) -> Int {
        paths.compactMap(\.self).count { FileManager.default.fileExists(atPath: $0) }
    }
}

enum VideoOfflineMedia: Equatable {
    case watch
    case shadowing
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

@MainActor
final class OfflineLibrary: ObservableObject {
    @Published private(set) var entries: [OfflineEntry] = []
    @Published private(set) var activeDownloadIDs: Set<Int> = []
    private let fileManager = FileManager.default
    private let downloadSession: URLSession
    private let rootDirectoryOverride: URL?

    init(downloadSession: URLSession? = nil, rootDirectory: URL? = nil) {
        self.downloadSession = downloadSession ?? Self.makeDownloadSession()
        rootDirectoryOverride = rootDirectory
        load()
    }

    private static func makeDownloadSession() -> URLSession {
        let configuration = URLSessionConfiguration.default
        configuration.allowsCellularAccess = false
        configuration.waitsForConnectivity = true
        return URLSession(configuration: configuration)
    }

    func entry(for materialID: Int) -> OfflineEntry? { entries.first { $0.id == materialID } }

    func localAudioURL(for materialID: Int) -> URL? {
        guard let url = entry(for: materialID)?.localAudioURL, fileManager.fileExists(atPath: url.path()) else {
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
        for entry in entries where entry.hasIncompleteRequestedVideoMedia {
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

    private func downloadReading(_ material: MaterialDetail) async throws {
        guard let remoteURL = material.audioURL else { throw OfflineLibraryError.noAudio }
        let directory = try directory(for: material.id)
        let destination = directory.appending(path: "reading.mp3")
        try await download(remoteURL, to: destination)
        upsert(OfflineEntry(material: material, localAudioPath: destination.path()))
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
        try publishVideoEntry(material, media: media, paths: paths, total: mediaPlaylist.segments.count)

        for index in mediaPlaylist.segments.indices where paths[index] == nil {
            try Task.checkCancellation()
            let segment = mediaPlaylist.segments[index]
            let destination = segmentDestination(index: index, remoteURL: segment.url, directory: mediaDirectory)
            try await download(segment.url, to: destination)
            paths[index] = destination.path()
            try publishVideoEntry(material, media: media, paths: paths, total: mediaPlaylist.segments.count)
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
            return fileManager.fileExists(atPath: destination.path()) ? destination.path() : nil
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

    private func publishVideoEntry(
        _ material: MaterialDetail,
        media: VideoOfflineMedia,
        paths: [String?],
        total: Int
    ) throws {
        let previous = entry(for: material.id)
        upsert(
            OfflineEntry(
                material: material,
                videoSegmentPaths: media == .watch ? paths : previous?.videoSegmentPaths,
                audioSegmentPaths: media == .shadowing ? paths : previous?.audioSegmentPaths,
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

    private func load() {
        guard let url = try? manifestURL(), let data = try? Data(contentsOf: url),
              let restored = try? JSONDecoder().decode([OfflineEntry].self, from: data) else { return }
        entries = restored.filter(\.hasPlayableMedia)
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
