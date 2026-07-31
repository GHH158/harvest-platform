import Foundation
import Testing
@testable import Harvest

final class StubURLProtocol: URLProtocol {
    nonisolated(unsafe) static var responses: [URL: Data] = [:]
    nonisolated(unsafe) static var requestedURLs: [URL] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url, let data = Self.responses[url] else {
            client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist))
            return
        }
        Self.requestedURLs.append(url)
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

struct HarvestTests {
    @Test func materialDecodesSentenceTimeline() throws {
        let data = """
        {"id":1,"kind":"reading","title":"雨の日","status":"ready","error_message":null,"duration_ms":1500,"audio_url":"https://example.com/a.mp3","video_url":null,"segments":[{"id":9,"material_id":1,"idx":0,"text_ja":"雨です。","text_zh":null,"start_ms":0,"end_ms":1500}],"tokens":[]}
        """.data(using: .utf8)!
        let material = try JSONDecoder().decode(MaterialDetail.self, from: data)
        #expect(material.segments[0].startMs == 0)
        #expect(material.segments[0].endMs == 1_500)
    }

    @Test func photoSubmissionDecodesMaterialContract() throws {
        let data = """
        {"material_id":41,"job_id":73,"status":"pending"}
        """.data(using: .utf8)!
        let submission = try JSONDecoder().decode(MaterialSubmission.self, from: data)
        #expect(submission.materialID == 41)
        #expect(submission.jobID == 73)
        #expect(submission.status == "pending")
    }

    @Test func shadowingAttemptDecodesAsyncStatus() throws {
        let data = """
        {"id":9,"asr_text":null,"diff_json":null,"score":null,"job_id":81,"status":"processing","error_message":null}
        """.data(using: .utf8)!
        let attempt = try JSONDecoder().decode(ShadowingAttempt.self, from: data)
        #expect(attempt.jobID == 81)
        #expect(attempt.status == "processing")
    }

    @Test func hlsPlaylistResolvesSegmentsAndDurations() throws {
        let playlist = try HLSPlaylist(
            text: """
            #EXTM3U
            #EXT-X-PLAYLIST-TYPE:VOD
            #EXTINF:6.0,
            segment-00000.ts
            #EXTINF:1.25,
            segment-00001.ts
            #EXT-X-ENDLIST
            """,
            baseURL: URL(string: "https://media.example/materials/7/hls/video/index.m3u8")!
        )

        #expect(playlist.segments.count == 2)
        #expect(playlist.segments[0].duration == 6)
        #expect(playlist.segments[1].url.absoluteString == "https://media.example/materials/7/hls/video/segment-00001.ts")
    }

    @MainActor @Test func segmentedPlayerAppendsNewlyDownloadedParts() {
        let player = SegmentQueuePlayer()
        let first = URL(fileURLWithPath: "/tmp/segment-00000.ts")
        let second = URL(fileURLWithPath: "/tmp/segment-00001.ts")

        player.update([first])
        #expect(player.player.items().count == 1)
        player.update([first, second])
        #expect(player.player.items().count == 2)
    }

    @Test func offlineEntryOnlyExposesContiguousDownloadedPrefix() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let first = root.appending(path: "segment-00000.ts")
        let third = root.appending(path: "segment-00002.ts")
        try Data("first".utf8).write(to: first)
        try Data("third".utf8).write(to: third)
        let materialData = """
        {"id":7,"kind":"video","title":"動画","status":"ready","error_message":null,"duration_ms":18000,"audio_url":"https://example.com/audio/index.m3u8","video_url":"https://example.com/video/index.m3u8","segments":[],"tokens":[]}
        """.data(using: .utf8)!
        let material = try JSONDecoder().decode(MaterialDetail.self, from: materialData)
        let entry = OfflineEntry(
            material: material,
            videoSegmentPaths: [first.path(), nil, third.path()],
            audioSegmentPaths: [],
            totalVideoSegments: 3,
            totalAudioSegments: nil
        )

        #expect(entry.downloadedVideoSegmentCount == 2)
        #expect(entry.localVideoSegmentURLs == [first])
        #expect(!entry.isWatchVideoComplete)
    }

    @MainActor @Test func segmentedDownloadResumesWithoutRefetchingStoredParts() async throws {
        let videoPlaylistURL = URL(string: "https://media.example/video/index.m3u8")!
        let audioPlaylistURL = URL(string: "https://media.example/audio/index.m3u8")!
        let videoSegmentURLs = (0...1).map { URL(string: "https://media.example/video/segment-0000\($0).ts")! }
        let audioSegmentURLs = (0...1).map { URL(string: "https://media.example/audio/segment-0000\($0).ts")! }
        let playlist = """
        #EXTM3U
        #EXTINF:6.0,
        segment-00000.ts
        #EXTINF:2.0,
        segment-00001.ts
        #EXT-X-ENDLIST
        """.data(using: .utf8)!
        StubURLProtocol.responses = [videoPlaylistURL: playlist, audioPlaylistURL: playlist]
        for url in videoSegmentURLs + audioSegmentURLs { StubURLProtocol.responses[url] = Data("segment".utf8) }
        StubURLProtocol.requestedURLs = []
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let library = OfflineLibrary(downloadSession: session, rootDirectory: root)
        let materialData = """
        {"id":7,"kind":"video","title":"動画","status":"ready","error_message":null,"duration_ms":8000,"audio_url":"https://media.example/audio/index.m3u8","video_url":"https://media.example/video/index.m3u8","segments":[],"tokens":[]}
        """.data(using: .utf8)!
        let material = try JSONDecoder().decode(MaterialDetail.self, from: materialData)

        try await library.download(material, videoMedia: .watch)
        #expect(library.entry(for: 7)?.isWatchVideoComplete == true)
        #expect(library.entry(for: 7)?.totalAudioSegments == nil)
        #expect(StubURLProtocol.requestedURLs.count == 3)
        #expect(!StubURLProtocol.requestedURLs.contains(audioPlaylistURL))

        StubURLProtocol.requestedURLs = []
        try await library.download(material, videoMedia: .watch)
        #expect(StubURLProtocol.requestedURLs == [videoPlaylistURL])

        StubURLProtocol.requestedURLs = []
        try await library.download(material, videoMedia: .shadowing)
        #expect(library.entry(for: 7)?.isShadowingAudioComplete == true)
        #expect(Set(StubURLProtocol.requestedURLs) == Set([audioPlaylistURL] + audioSegmentURLs))
    }
}
