import Foundation
import Testing
@testable import Harvest

final class StubURLProtocol: URLProtocol {
    nonisolated(unsafe) static var responses: [URL: Data] = [:]
    nonisolated(unsafe) static var statusCodes: [URL: Int] = [:]
    nonisolated(unsafe) static var requestedURLs: [URL] = []
    nonisolated(unsafe) static var requestedRequests: [URLRequest] = []
    nonisolated(unsafe) static var requestedBodies: [Data?] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url, let data = Self.responses[url] else {
            client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist))
            return
        }
        Self.requestedURLs.append(url)
        Self.requestedRequests.append(request)
        Self.requestedBodies.append(Self.readBody(from: request))
        let response = HTTPURLResponse(
            url: url,
            statusCode: Self.statusCodes[url] ?? 200,
            httpVersion: "HTTP/1.1",
            headerFields: nil
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func readBody(from request: URLRequest) -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 1_024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            body.append(buffer, count: count)
        }
        return body
    }
}

@Suite(.serialized)
struct HarvestTests {
    private func stubSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return URLSession(configuration: configuration)
    }

    private func resetStub() {
        StubURLProtocol.responses = [:]
        StubURLProtocol.statusCodes = [:]
        StubURLProtocol.requestedURLs = []
        StubURLProtocol.requestedRequests = []
        StubURLProtocol.requestedBodies = []
    }

    @Test func voiceTeacherUsesWebSocketThroughTheMacEndpoint() throws {
        let secure = try #require(voiceTeacherWebSocketURL(baseURL: URL(string: "https://harvest.example.ts.net")!))
        let local = try #require(voiceTeacherWebSocketURL(baseURL: URL(string: "http://127.0.0.1:8000")!))
        #expect(secure.absoluteString == "wss://harvest.example.ts.net/voice-teacher/ws")
        #expect(local.absoluteString == "ws://127.0.0.1:8000/voice-teacher/ws")
    }

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

    @Test func chatModelsDecodeTopicsSessionsAndCorrectionTurns() throws {
        let topics = try JSONDecoder().decode([ChatTopic].self, from: """
        [{"id":"daily-weekend","category":"日常","title_ja":"今週末の予定","hint_zh":"这个周末的计划"}]
        """.data(using: .utf8)!)
        let detail = try JSONDecoder().decode(ChatSessionDetail.self, from: """
        {
          "session":{"id":"session-1","topic":"今週末の予定","starter_id":"daily-weekend","created_at":"2026-08-03T01:00:00Z","updated_at":"2026-08-03T01:01:00Z"},
          "messages":[{"id":1,"session_id":"session-1","role":"assistant","content":"週末は何をしますか？","created_at":"2026-08-03T01:00:00Z"}],
          "corrections":[]
        }
        """.data(using: .utf8)!)
        let corrected = try JSONDecoder().decode(ChatTurnResponse.self, from: correctedTurnData)
        let natural = try JSONDecoder().decode(ChatTurnResponse.self, from: naturalTurnData)

        #expect(topics[0].titleJA == "今週末の予定")
        #expect(detail.session.starterID == "daily-weekend")
        #expect(detail.messages[0].sessionID == "session-1")
        #expect(corrected.correction?.items[0].category == .grammar)
        #expect(natural.correction == nil)
    }

    @Test func topicDeckShowsEveryTopicBeforeRepeatingAndAvoidsImmediateRepeat() {
        let topics = (0..<16).map {
            ChatTopic(id: "topic-\($0)", category: "分类", titleJA: "テーマ\($0)", hintZH: "主题\($0)")
        }
        var deck = ChatTopicDeck()
        var firstRound = Set<String>()
        var lastBatch = Set<String>()

        for _ in 0..<4 {
            let batch = deck.nextBatch(from: topics)
            let ids = Set(batch.map(\.id))
            #expect(batch.count == 4)
            #expect(firstRound.isDisjoint(with: ids))
            firstRound.formUnion(ids)
            lastBatch = ids
        }
        let nextRoundFirstBatch = Set(deck.nextBatch(from: topics).map(\.id))

        #expect(firstRound.count == 16)
        #expect(lastBatch.isDisjoint(with: nextRoundFirstBatch))
    }

    @Test func customChineseAndJapaneseTopicsUseTheNewSessionAPI() async throws {
        resetStub()
        let baseURL = URL(string: "https://harvest.example")!
        let url = baseURL.appending(path: "chat/sessions")
        StubURLProtocol.responses[url] = sessionCreationData
        let client = APIClient(baseURL: baseURL, session: stubSession())

        _ = try await client.createChatSession(topic: "最近的工作")
        _ = try await client.createChatSession(topic: "最近読んだ本")

        #expect(StubURLProtocol.requestedRequests.count == 2)
        let bodies = try StubURLProtocol.requestedBodies.map { body -> [String: String] in
            let data = try #require(body)
            return try #require(JSONSerialization.jsonObject(with: data) as? [String: String])
        }
        #expect(bodies.map { $0["topic"]! } == ["最近的工作", "最近読んだ本"])
        #expect(StubURLProtocol.requestedRequests.allSatisfy { $0.httpMethod == "POST" })
    }

    @Test func transcriptRowsRenderCorrectionOnlyWhenPresent() throws {
        let corrected = try JSONDecoder().decode(ChatTurnResponse.self, from: correctedTurnData)
        let natural = try JSONDecoder().decode(ChatTurnResponse.self, from: naturalTurnData)

        let correctedRows = chatTranscriptRows(
            messages: [corrected.user, corrected.assistant],
            corrections: [try #require(corrected.correction)]
        )
        let naturalRows = chatTranscriptRows(
            messages: [natural.user, natural.assistant],
            corrections: []
        )

        #expect(correctedRows.map(\.id) == ["message-2", "correction-8", "message-3"])
        #expect(naturalRows.map(\.id) == ["message-4", "message-5"])
    }

    @MainActor @Test func failedSendKeepsDraftAndHistoryCanBeRestored() async throws {
        resetStub()
        let baseURL = URL(string: "https://harvest.example")!
        let detailURL = baseURL.appending(path: "chat/sessions/session-1")
        StubURLProtocol.responses[detailURL] = sessionDetailData
        let client = APIClient(baseURL: baseURL, session: stubSession())
        let store = ChatStore()

        await store.openSession(id: "session-1", using: client)
        store.draft = "昨日映画を見る"
        await store.send(using: client)

        #expect(store.activeSession?.id == "session-1")
        #expect(store.messages.count == 1)
        #expect(store.draft == "昨日映画を見る")
        #expect(store.errorMessage != nil)
    }

    @Test func correctionFiltersAndDeletesUseExpectedRequests() async throws {
        resetStub()
        let baseURL = URL(string: "https://harvest.example")!
        var components = URLComponents(
            url: baseURL.appending(path: "chat/corrections"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [
            URLQueryItem(name: "query", value: "过去时"),
            URLQueryItem(name: "topic", value: "週末"),
            URLQueryItem(name: "category", value: "grammar"),
            URLQueryItem(name: "cursor", value: "9"),
        ]
        let filteredURL = try #require(components.url)
        let deleteURL = baseURL.appending(path: "chat/corrections/8")
        StubURLProtocol.responses[filteredURL] = "[]".data(using: .utf8)!
        StubURLProtocol.responses[deleteURL] = Data()
        StubURLProtocol.statusCodes[deleteURL] = 204
        let client = APIClient(baseURL: baseURL, session: stubSession())

        let results = try await client.chatCorrections(
            query: "过去时",
            topic: "週末",
            category: .grammar,
            cursor: 9
        )
        try await client.deleteChatCorrection(id: 8)

        #expect(results.isEmpty)
        #expect(StubURLProtocol.requestedURLs == [filteredURL, deleteURL])
        #expect(StubURLProtocol.requestedRequests.last?.httpMethod == "DELETE")
    }

    private var sessionCreationData: Data {
        """
        {
          "session":{"id":"session-1","topic":"自定义主题","starter_id":null,"created_at":"2026-08-03T01:00:00Z","updated_at":"2026-08-03T01:00:00Z"},
          "assistant":{"id":1,"session_id":"session-1","role":"assistant","content":"話しましょう。何から始めますか？","created_at":"2026-08-03T01:00:00Z"}
        }
        """.data(using: .utf8)!
    }

    private var sessionDetailData: Data {
        """
        {
          "session":{"id":"session-1","topic":"週末","starter_id":null,"created_at":"2026-08-03T01:00:00Z","updated_at":"2026-08-03T01:00:00Z"},
          "messages":[{"id":1,"session_id":"session-1","role":"assistant","content":"週末は何をしますか？","created_at":"2026-08-03T01:00:00Z"}],
          "corrections":[]
        }
        """.data(using: .utf8)!
    }

    private var correctedTurnData: Data {
        """
        {
          "user":{"id":2,"session_id":"session-1","role":"user","content":"昨日映画を見る。","created_at":"2026-08-03T01:01:00Z"},
          "correction":{"id":8,"session_id":"session-1","user_message_id":2,"original_text":"昨日映画を見る。","corrected_text":"昨日、映画を見ました。","summary_zh":"过去的事情使用过去时。","created_at":"2026-08-03T01:01:00Z","items":[{"id":10,"correction_id":8,"idx":0,"original":"見る","replacement":"見ました","reason_zh":"使用过去时。","category":"grammar"}]},
          "assistant":{"id":3,"session_id":"session-1","role":"assistant","content":"面白そうですね。どんな映画でしたか？","created_at":"2026-08-03T01:01:01Z"}
        }
        """.data(using: .utf8)!
    }

    private var naturalTurnData: Data {
        """
        {
          "user":{"id":4,"session_id":"session-1","role":"user","content":"映画が好きです。","created_at":"2026-08-03T01:02:00Z"},
          "correction":null,
          "assistant":{"id":5,"session_id":"session-1","role":"assistant","content":"私も好きです。最近は何を見ましたか？","created_at":"2026-08-03T01:02:01Z"}
        }
        """.data(using: .utf8)!
    }
}
