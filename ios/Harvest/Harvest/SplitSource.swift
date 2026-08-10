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
    private let needsScopedAccess: Bool

    /// What `AVPlayer` plays: the file itself, or the playlist inside the folder. Either way
    /// it is local, so scrubbing is instant and costs no traffic.
    var playbackURL: URL {
        switch kind {
        case .movie: rootURL
        case let .hlsBundle(playlist): playlist
        }
    }

    var suggestedTitle: String {
        rootURL.deletingPathExtension().lastPathComponent
    }

    enum Failure: LocalizedError {
        case noPlaylist
        case unreadable

        var errorDescription: String? {
            switch self {
            case .noPlaylist:
                "这个文件夹里没有找到播放列表。下载下来的视频通常有一个列表文件，里面第一行是 #EXTM3U。"
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
            return SplitSource(kind: .movie, rootURL: url, needsScopedAccess: scoped)
        }
        guard let playlist = findPlaylist(in: url) else {
            if scoped { url.stopAccessingSecurityScopedResource() }
            throw Failure.noPlaylist
        }
        return SplitSource(kind: .hlsBundle(playlist: playlist), rootURL: url, needsScopedAccess: scoped)
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
    }
}
