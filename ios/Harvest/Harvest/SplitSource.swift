import Foundation

/// What the learner picked in the file browser: either a single video, or a downloaded HLS
/// bundle — a playlist plus hundreds of segments (§15.10).
///
/// The bundle case is the reason the picker accepts folders at all. A downloaded video from
/// a web page is usually not one file, and restricting the importer to `.movie` hid the
/// playlist entirely, which is a large part of why importing felt impossible.
struct SplitSource {
    enum Kind {
        case movie
        case hlsBundle(playlist: URL)
    }

    let kind: Kind
    let rootURL: URL
    /// What the learner picked, kept separately: for a bundle `rootURL` points at our own
    /// copy, whose directory name is a UUID and makes a terrible title.
    let displayName: String
    private let needsScopedAccess: Bool

    /// What `AVPlayer` plays: the file itself, or the playlist inside the folder. Either way
    /// it is local, so scrubbing is instant and costs no traffic.
    var playbackURL: URL {
        switch kind {
        case .movie: rootURL
        case let .hlsBundle(playlist): playlist
        }
    }

    var suggestedTitle: String { displayName }

    enum Failure: LocalizedError {
        case noPlaylist
        case playlistAlone
        case unreadable

        var errorDescription: String? {
            switch self {
            case .noPlaylist:
                "这个文件夹里没有找到播放列表。下载下来的视频通常有一个列表文件，里面第一行是 #EXTM3U。"
            case .playlistAlone:
                "你选的是播放列表本身，分片没跟着来。请退回上一层，选它所在的整个文件夹。"
            case .unreadable:
                "读不到这个文件，换一个位置再试。"
            }
        }
    }

    static func resolve(_ url: URL) throws -> SplitSource {
        let scoped = url.startAccessingSecurityScopedResource()
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) else {
            if scoped { url.stopAccessingSecurityScopedResource() }
            throw Failure.unreadable
        }
        if !isDirectory.boolValue {
            // A picked file whose bytes say `#EXTM3U` is a playlist without its segments.
            // Uploading it alone is useless, so say what to do instead of failing later.
            if looksLikePlaylist(url) {
                if scoped { url.stopAccessingSecurityScopedResource() }
                throw Failure.playlistAlone
            }
            return SplitSource(
                kind: .movie,
                rootURL: url,
                displayName: url.deletingPathExtension().lastPathComponent,
                needsScopedAccess: scoped
            )
        }
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard findPlaylist(in: url) != nil else { throw Failure.noPlaylist }
        // §15.10: copied into our own container before anything plays it. A security-scoped
        // URL is granted to *this* process, but HLS segments are fetched by the system's
        // media daemon, which has no such grant — so playing a picked folder in place fails
        // with nothing but a black frame. The copy also removes any question of the scope
        // outliving playback.
        let copied = try copyBundleIntoContainer(from: url)
        return SplitSource(
            kind: .hlsBundle(playlist: copied.playlist),
            rootURL: copied.root,
            displayName: url.lastPathComponent,
            needsScopedAccess: false
        )
    }

    private static func looksLikePlaylist(_ url: URL) -> Bool {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return false }
        defer { try? handle.close() }
        return (try? handle.read(upToCount: 7)) == Data("#EXTM3U".utf8)
    }

    /// Copies the bundle somewhere this app owns, and makes sure the playlist ends in
    /// `.m3u8`. AVFoundation decides what a local file is from its extension, so the
    /// extensionless `play` that downloaders produce is not recognised as HLS at all.
    private static func copyBundleIntoContainer(from directory: URL) throws -> (root: URL, playlist: URL) {
        let container = URL.cachesDirectory.appendingPathComponent("harvest-split", isDirectory: true)
        let destination = container.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
        let names = try FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )
        for name in names where !name.hasDirectoryPath {
            try FileManager.default.copyItem(at: name, to: destination.appendingPathComponent(name.lastPathComponent))
        }
        guard var playlist = findPlaylist(in: destination) else { throw Failure.noPlaylist }
        if playlist.pathExtension.lowercased() != "m3u8" {
            let renamed = playlist.deletingLastPathComponent().appendingPathComponent("index.m3u8")
            try FileManager.default.moveItem(at: playlist, to: renamed)
            playlist = renamed
        }
        try normaliseSegmentExtensions(playlist: playlist)
        return (destination, playlist)
    }

    /// Give every segment a `.ts` name and rewrite the playlist to match.
    ///
    /// AVFoundation, like ffmpeg, decides what a local file is from its extension, and some
    /// downloaders strip them from the segments as well as from the playlist. Since the
    /// bundle is already being copied, renaming here is free and makes playback work for
    /// both shapes. Only extensionless entries are touched — a bundle that already says
    /// `.ts` is left exactly as it is.
    private static func normaliseSegmentExtensions(playlist: URL) throws {
        let directory = playlist.deletingLastPathComponent()
        let text = try String(contentsOf: playlist, encoding: .utf8)
        var rewritten: [String] = []
        var changed = false
        for line in text.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#"), !trimmed.contains("://") else {
                rewritten.append(line)
                continue
            }
            let candidate = directory.appendingPathComponent(trimmed)
            guard candidate.pathExtension.isEmpty,
                  FileManager.default.fileExists(atPath: candidate.path)
            else {
                rewritten.append(line)
                continue
            }
            let renamed = candidate.appendingPathExtension("ts")
            if !FileManager.default.fileExists(atPath: renamed.path) {
                try FileManager.default.moveItem(at: candidate, to: renamed)
            }
            rewritten.append("\(trimmed).ts")
            changed = true
        }
        guard changed else { return }
        try rewritten.joined(separator: "\n").write(to: playlist, atomically: true, encoding: .utf8)
    }

    /// Found by content, not by extension (§15.10). A downloader may keep `.m3u8`, may strip
    /// every extension, and iOS hides known ones — the first seven bytes are the only
    /// reliable signal.
    private static func findPlaylist(in directory: URL) -> URL? {
        let names = (try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )) ?? []
        // Prefer a real `.m3u8` when there is one; a bundle can contain more than one
        // playlist (variant streams) and the named one is the one the downloader wrote.
        let sorted = names.sorted { lhs, rhs in
            (lhs.pathExtension.lowercased() == "m3u8" ? 0 : 1) < (rhs.pathExtension.lowercased() == "m3u8" ? 0 : 1)
        }
        return sorted.first { url in
            guard let handle = try? FileHandle(forReadingFrom: url) else { return false }
            defer { try? handle.close() }
            return (try? handle.read(upToCount: 7)) == Data("#EXTM3U".utf8)
        }
    }

    /// One file to upload, whatever was picked.
    ///
    /// A bundle is zipped with `NSFileCoordinator`'s `.forUploading`, which is built into the
    /// system: no third-party archiver, and no need to fire hundreds of requests. Zipping
    /// barely shrinks already-compressed video, so the transfer is about the size of the
    /// original — no extra cost, but a long video still takes minutes, and those are the
    /// minutes spent cutting (§15.10).
    func uploadableCopy() async throws -> URL {
        switch kind {
        case .movie:
            return rootURL
        case .hlsBundle:
            return try await withCheckedThrowingContinuation { continuation in
                var coordinatorError: NSError?
                var result: Result<URL, Error> = .failure(Failure.unreadable)
                NSFileCoordinator().coordinate(
                    readingItemAt: rootURL,
                    options: [.forUploading],
                    error: &coordinatorError
                ) { zipURL in
                    // The coordinator's copy only lives for the duration of this block.
                    let destination = FileManager.default.temporaryDirectory
                        .appendingPathComponent("harvest-\(UUID().uuidString).zip")
                    do {
                        try FileManager.default.copyItem(at: zipURL, to: destination)
                        result = .success(destination)
                    } catch {
                        result = .failure(error)
                    }
                }
                if let coordinatorError {
                    continuation.resume(throwing: coordinatorError)
                    return
                }
                continuation.resume(with: result)
            }
        }
    }

    func releaseAccess() {
        if needsScopedAccess {
            rootURL.stopAccessingSecurityScopedResource()
        }
        // The copy exists only for this screen.
        if case .hlsBundle = kind, rootURL.path.contains("harvest-split") {
            try? FileManager.default.removeItem(at: rootURL)
        }
    }
}
