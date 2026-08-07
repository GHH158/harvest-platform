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

    @Test func appUsesCanonicalBundleAndModernLaunchScreen() {
        #expect(Bundle.main.bundleIdentifier == "com.gaohuanhuan.harvest.JapaneseLearning")
        #expect(Bundle.main.object(forInfoDictionaryKey: "UILaunchScreen") != nil)
    }

    @Test func readingTextUsesJapaneseWordsAndMergesLegacyCharacterTiming() throws {
        let legacyTokens = [
            Token(id: 1, segmentID: 9, index: 0, surface: "今", reading: nil, startMs: 0, endMs: 100),
            Token(id: 2, segmentID: 9, index: 1, surface: "日", reading: nil, startMs: 100, endMs: 200),
            Token(id: 3, segmentID: 9, index: 2, surface: "は", reading: nil, startMs: 200, endMs: 300),
        ]

        let words = japaneseReadingUnits(text: "今日は。", tokens: legacyTokens).filter(\.isWord)

        #expect(words.map(\.text) == ["今日", "は"])
        let today = try #require(words.first)
        #expect(today.startMs == 0)
        #expect(today.endMs == 200)
    }

    @Test func readingTextCarriesWordReadingIntoInlineQuestionTarget() throws {
        let wordToken = Token(
            id: 1,
            segmentID: 9,
            index: 0,
            surface: "今日",
            reading: "きょう",
            startMs: 0,
            endMs: 200
        )

        let maybeToday = japaneseReadingUnits(text: "今日。", tokens: [wordToken]).first { $0.isWord }
        let today = try #require(maybeToday)

        #expect(today.text == "今日")
        #expect(today.reading == "きょう")
    }

    @Test func readingTextPrefersServerInflectedWordBoundary() {
        let verb = Token(
            id: 1,
            segmentID: 9,
            index: 0,
            surface: "読みたい",
            reading: "よみたい",
            startMs: 0,
            endMs: 500
        )

        let words = japaneseReadingUnits(text: "読みたい。", tokens: [verb]).filter(\.isWord)

        #expect(words.map(\.text) == ["読みたい"])
        #expect(words.first?.reading == "よみたい")
    }

    @Test func readingHighlightPersistsAcrossASRGapsUntilNextWordStarts() {
        let units = [
            JapaneseReadingUnit(
                id: 0,
                text: "今日",
                reading: "きょう",
                isWord: true,
                startMs: 100,
                endMs: 220
            ),
            JapaneseReadingUnit(
                id: 1,
                text: "は",
                reading: nil,
                isWord: true,
                startMs: 500,
                endMs: 620
            ),
        ]

        #expect(activeReadingUnitID(in: units, at: 99) == nil)
        #expect(activeReadingUnitID(in: units, at: 350) == 0)
        #expect(activeReadingUnitID(in: units, at: 500) == 1)
        #expect(activeReadingUnitID(in: units, at: 900) == 1)
    }

    @Test func companionComposerImmediatelyShowsPendingAndRestoresFailedDraft() {
        var composer = CompanionComposerState(draft: "  「買って」の用法は？  ")

        let question = composer.beginSending()

        #expect(question == "「買って」の用法は？")
        #expect(composer.pendingQuestion == "「買って」の用法は？")
        #expect(composer.draft.isEmpty)
        #expect(composer.isSending)
        #expect(!composer.canSend)

        composer.failSending()

        #expect(composer.pendingQuestion == nil)
        #expect(composer.draft == "「買って」の用法は？")
        #expect(!composer.isSending)
        #expect(composer.canSend)
    }

    @Test func companionMarkdownParsesBlocksAndRemovesRawInlineMarkers() {
        let blocks = markdownBlocks(from: """
        # 语法说明

        **重点**：这里使用过去时。

           - 第一项
           2. 第二项
           > 请留意语气。
           > 第二行引用。
        ```ja
        昨日、映画を見ました。
        ```
        """).filter { $0 != .spacer }

        #expect(blocks == [
            .heading(level: 1, text: "语法说明"),
            .paragraph("**重点**：这里使用过去时。"),
            .unorderedItem("第一项"),
            .orderedItem(number: "2", text: "第二项"),
            .quote("请留意语气。\n第二行引用。"),
            .code("昨日、映画を見ました。"),
        ])
        #expect(String(inlineMarkdown("**重点**、`例句`与[说明](https://example.com)").characters) == "重点、例句与说明")
        #expect(String(styledInlineMarkdown("**重点** 和 `例句`").characters) == "重点 和 例句")
        #expect(containsInlineMarkdownSyntax("「皆さん」表示 **大家**"))
        #expect(!containsInlineMarkdownSyntax("「皆さん」表示大家"))
        #expect(isMostlyJapanese("参加者が集まらず、講演会が流会になった。"))
        #expect(!isMostlyJapanese("这里说明为什么使用「は」而不是「が」。"))
        // Kanji ratio alone cannot separate the two languages: a Chinese explanation is
        // ~100% kanji, so it used to be styled as a Japanese example. Kana is the real
        // signal. These are lines taken from actual companion replies.
        #expect(isMostlyJapanese("近所にコンビニがある。（附近有便利店。）"))
        #expect(isMostlyJapanese("参加者が集まらず、講演会が流会になった。（因参加者未凑齐，讲座取消了。）"))
        #expect(!isMostlyJapanese("「近所」侧重日常生活圈内的邻近感，带有自己熟悉、经常经过的语感。"))
        #expect(!isMostlyJapanese("词性与接续：名词，常以「近所に」「近所の＋名词」形式出现。"))
        // Known limit: a Chinese sentence that quotes a whole Japanese sentence lands in
        // the same kana range as a Japanese example followed by a Chinese translation
        // (measured on real replies: examples reach down to 0.30, explanations up to
        // 0.34). Those stay ambiguous on purpose rather than breaking real examples.
        #expect(isListBlock(.unorderedItem("x")))
        #expect(!isListBlock(.paragraph("x")))
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

    @Test func completedPlaybackOnlyRestartsWhenPlayIsPressedFromStoppedState() {
        #expect(shouldRestartCompletedPlayback(isPlaying: false, hasReachedEnd: true))
        #expect(!shouldRestartCompletedPlayback(isPlaying: true, hasReachedEnd: true))
        #expect(!shouldRestartCompletedPlayback(isPlaying: false, hasReachedEnd: false))
    }

    @Test func currentSentenceQuestionUsesPlaybackPositionAndDefaultsToFirstSentence() throws {
        let segments = [
            Segment(id: 1, materialID: 7, index: 0, textJA: "一文目", textZH: nil, startMs: 1_000, endMs: 3_000),
            Segment(id: 2, materialID: 7, index: 1, textJA: "二文目", textZH: nil, startMs: 3_200, endMs: 5_000),
        ]

        #expect(segmentForCurrentQuestion(segments: segments, positionMs: 0)?.id == 1)
        #expect(segmentForCurrentQuestion(segments: segments, positionMs: 2_500)?.id == 1)
        #expect(segmentForCurrentQuestion(segments: segments, positionMs: 3_200)?.id == 2)
        #expect(segmentForCurrentQuestion(segments: [], positionMs: 0) == nil)
    }

    @MainActor @Test func onlinePlayerReturnsToBeginningAfterNaturalCompletion() async throws {
        let player = OnlineMediaPlayer()
        player.prepare(url: URL(fileURLWithPath: "/tmp/finished-online-video.mp4"))
        let item = try #require(player.player.currentItem)

        NotificationCenter.default.post(name: .AVPlayerItemDidPlayToEndTime, object: item)
        await Task.yield()
        await Task.yield()
        #expect(player.hasReachedEnd)

        player.toggle()

        #expect(!player.hasReachedEnd)
        #expect(player.positionMs == 0)
        player.pause()
    }

    @MainActor @Test func segmentedPlayerRebuildsConsumedQueueBeforePlayingAgain() async throws {
        let player = SegmentQueuePlayer()
        player.update([URL(fileURLWithPath: "/tmp/finished-segment.ts")], durations: [6])
        let item = try #require(player.player.items().first)

        NotificationCenter.default.post(name: .AVPlayerItemDidPlayToEndTime, object: item)
        await Task.yield()
        await Task.yield()
        #expect(player.hasReachedEnd)

        player.toggle()

        #expect(!player.hasReachedEnd)
        #expect(player.player.items().count == 1)
        #expect(player.positionMs == 0)
        player.pause()
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

    @Test func materialListDecodesProgressFailureAndThumbnailProjection() throws {
        let materials = try JSONDecoder().decode([Material].self, from: """
        [{"id":7,"kind":"video","title":"長いタイトル","source_type":"url","source_ref":"https://example.com/video","status":"processing","error_message":null,"duration_ms":125000,"audio_url":null,"created_at":"2026-08-05T00:00:00+08:00","updated_at":"2026-08-05T00:01:00+08:00","thumbnail_path":"/materials/7/thumbnail","job_id":17,"progress_percent":82,"progress_label":"正在转录字幕","eta_minutes":5,"retryable":false,"failure_title":null,"failure_summary":null}]
        """.data(using: .utf8)!)

        #expect(materials[0].durationMs == 125_000)
        #expect(materials[0].thumbnailPath == "/materials/7/thumbnail")
        #expect(materials[0].progressPercent == 82)
        #expect(materials[0].etaMinutes == 5)
    }

    @Test func finishedVideoResumePositionRestartsButMiddlePositionIsPreserved() {
        #expect(normalizedResumePosition(900, durationMs: 100_000) == 0)
        #expect(normalizedResumePosition(42_000, durationMs: 100_000) == 42_000)
        #expect(normalizedResumePosition(96_000, durationMs: 100_000) == 0)
        #expect(normalizedResumePosition(42_000, durationMs: nil) == 42_000)
    }

    @Test func sentenceLoopRestartsAtTargetBoundaryOnlyWhilePlaying() {
        let segments = [
            Segment(id: 1, materialID: 7, index: 0, textJA: "一文目", textZH: nil, startMs: 1_000, endMs: 3_000),
            Segment(id: 2, materialID: 7, index: 1, textJA: "二文目", textZH: nil, startMs: 3_200, endMs: 5_000),
        ]

        #expect(sentenceLoopRestartPosition(
            segments: segments,
            targetSegmentID: 1,
            oldPositionMs: 2_950,
            newPositionMs: 3_010,
            isPlaying: true
        ) == 1_000)
        #expect(sentenceLoopRestartPosition(
            segments: segments,
            targetSegmentID: 1,
            oldPositionMs: 2_950,
            newPositionMs: 3_010,
            isPlaying: false
        ) == nil)
    }

    @Test func videoPlaybackStoreKeepsIndependentPositionsPerMaterial() throws {
        let suite = "HarvestTests.Playback.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = PlaybackProgressStore(defaults: defaults)
        let date = Date(timeIntervalSince1970: 1_800_000_000)

        store.save(materialID: 7, positionMs: 12_000, updatedAt: date)
        store.save(materialID: 8, positionMs: 34_000, updatedAt: date)

        #expect(store.load(materialID: 7) == StoredPlayback(positionMs: 12_000, updatedAt: date))
        #expect(store.load(materialID: 8)?.positionMs == 34_000)
    }

    @Test func playbackTimestampsParseAcrossPostgresPrecisions() throws {
        // PostgreSQL renders microseconds; ISO8601DateFormatter only takes milliseconds.
        // Failing to parse made the caller treat the server copy as "not newer", so a
        // resume point saved on another device was never picked up.
        let microseconds = try #require(parsePlaybackDate("2026-08-07T07:41:28.905934+08:00"))
        let milliseconds = try #require(parsePlaybackDate("2026-08-07T07:41:28.905+08:00"))
        #expect(abs(microseconds.timeIntervalSince(milliseconds)) < 0.01)

        #expect(parsePlaybackDate("2026-08-05T00:00:00Z") != nil)
        #expect(parsePlaybackDate("2026-08-07T07:41:28+08:00") != nil)
        #expect(parsePlaybackDate(nil) == nil)
        #expect(parsePlaybackDate("not a date") == nil)
    }

    @Test func resumePositionSurvivesAnItemThatIsNotReadyYet() {
        // The reader restores before the AVPlayerItem is ready; until the seek lands the
        // item reports 0, which used to be written back as real progress.
        #expect(normalizedResumePosition(19_000, durationMs: 54_000) == 19_000)
        #expect(normalizedResumePosition(0, durationMs: 54_000) == 0)
        // Near the end counts as finished, so the next open starts over.
        #expect(normalizedResumePosition(52_000, durationMs: 54_000) == 0)
    }

    @Test func videoPlaybackAPIReadsAndWritesIntegerMilliseconds() async throws {
        resetStub()
        let baseURL = URL(string: "https://harvest.example")!
        let url = baseURL.appending(path: "materials/7/playback")
        StubURLProtocol.responses[url] = """
        {"material_id":7,"position_ms":12000,"updated_at":"2026-08-05T00:00:00Z"}
        """.data(using: .utf8)!
        let client = APIClient(baseURL: baseURL, session: stubSession())

        let loaded = try await client.playbackState(materialID: 7)
        #expect(loaded.positionMs == 12_000)

        StubURLProtocol.responses[url] = """
        {"material_id":7,"position_ms":34500,"updated_at":"2026-08-05T00:01:00Z"}
        """.data(using: .utf8)!
        let saved = try await client.savePlaybackState(materialID: 7, positionMs: 34_500)
        let body = try #require(StubURLProtocol.requestedBodies.last.flatMap { $0 })
        let json = try #require(JSONSerialization.jsonObject(with: body) as? [String: Int])

        #expect(saved.positionMs == 34_500)
        #expect(StubURLProtocol.requestedRequests.last?.httpMethod == "PUT")
        #expect(json["position_ms"] == 34_500)
    }

    @MainActor @Test func cacheCleanupPreservesManifestReferencedFiles() async throws {
        let audioURL = URL(string: "https://media.example/reading.mp3")!
        StubURLProtocol.responses = [audioURL: Data("audio".utf8)]
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let library = OfflineLibrary(downloadSession: stubSession(), rootDirectory: root)
        let material = try JSONDecoder().decode(MaterialDetail.self, from: """
        {"id":9,"kind":"reading","title":"文章","status":"ready","error_message":null,"duration_ms":1000,"audio_url":"https://media.example/reading.mp3","video_url":null,"segments":[],"tokens":[]}
        """.data(using: .utf8)!)
        try await library.download(material)
        let referenced = try #require(library.localAudioURL(for: 9))
        let orphan = root.appending(path: "orphan.tmp")
        try Data("cache".utf8).write(to: orphan)

        let freed = library.clearCache()

        #expect(FileManager.default.fileExists(atPath: referenced.path()))
        #expect(!FileManager.default.fileExists(atPath: orphan.path()))
        #expect(freed > 0)
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
        #expect(store.pendingUserMessage == nil)
        #expect(store.errorMessage != nil)
    }

    @MainActor @Test func successfulSendReplacesPendingMessageWithoutDuplicates() async throws {
        resetStub()
        let baseURL = URL(string: "https://harvest.example")!
        let detailURL = baseURL.appending(path: "chat/sessions/session-1")
        let messageURL = baseURL.appending(path: "chat/sessions/session-1/messages")
        StubURLProtocol.responses[detailURL] = sessionDetailData
        StubURLProtocol.responses[messageURL] = naturalTurnData
        let client = APIClient(baseURL: baseURL, session: stubSession())
        let store = ChatStore()

        await store.openSession(id: "session-1", using: client)
        store.draft = "昨日、映画を見ました。"
        await store.send(using: client)

        #expect(store.pendingUserMessage == nil)
        #expect(store.messages.map(\.id) == [1, 4, 5])
        #expect(store.messages.filter { $0.role == "user" }.count == 1)
        #expect(store.draft.isEmpty)
        #expect(store.errorMessage == nil)
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

    @MainActor @Test func downloadedReadingIsRecognisedInsideAPathWithSpaces() async throws {
        // iOS stores this under "Library/Application Support", and `URL.path()`
        // percent-encodes by default: the file landed correctly but every
        // fileExists check on "Application%20Support" failed, so the download
        // button stayed on its initial icon and playback silently used the network.
        // Every existing offline test used a UUID directory with no space, which is
        // exactly why this survived.
        resetStub()
        let audioURL = URL(string: "https://media.example/reading.mp3")!
        StubURLProtocol.responses[audioURL] = Data("audio".utf8)
        let root = FileManager.default.temporaryDirectory
            .appending(path: "Application Support \(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let library = OfflineLibrary(downloadSession: stubSession(), rootDirectory: root)
        let materialData = """
        {"id":7,"kind":"reading","title":"読み物","status":"ready","error_message":null,"duration_ms":8000,"audio_url":"https://media.example/reading.mp3","video_url":null,"segments":[],"tokens":[]}
        """.data(using: .utf8)!
        let material = try JSONDecoder().decode(MaterialDetail.self, from: materialData)

        try await library.download(material)

        let stored = try #require(library.entry(for: 7)?.localAudioPath)
        #expect(!stored.contains("%20"))
        #expect(library.localAudioURL(for: 7) != nil)
        #expect(library.entry(for: 7)?.hasPlayableMedia == true)
    }

    @Test func legacyPercentEncodedPathsStillResolve() throws {
        // Manifests written before the fix carry the encoded form; they must keep
        // working rather than silently presenting as "not downloaded".
        let root = FileManager.default.temporaryDirectory
            .appending(path: "Application Support \(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let file = root.appending(path: "reading.mp3")
        try Data("audio".utf8).write(to: file)

        let encoded = file.path(percentEncoded: true)
        #expect(encoded.contains("%20"))
        #expect(!FileManager.default.fileExists(atPath: encoded))
        #expect(FileManager.default.fileExists(atPath: normalizedStoredPath(encoded)))
        #expect(normalizedStoredPath(file.filePath) == file.filePath)
    }
}
