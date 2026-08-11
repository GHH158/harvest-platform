import Foundation

enum APIClientError: LocalizedError {
    case badResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .badResponse: "服务返回了无法读取的数据。"
        case .server(let message): message
        }
    }
}

struct APIClient {
    let baseURL: URL
    var session: URLSession = APIClient.sharedSession
    private let decoder = JSONDecoder()

    /// Shared session tuned for local Tailscale control-plane calls.
    /// Default `URLSession.shared` can hang for a minute+ when the Mac/Tailscale is cold,
    /// which freezes first launch behind "正在翻开素材库".
    private static let sharedSession: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 12
        configuration.timeoutIntervalForResource = 20
        configuration.httpMaximumConnectionsPerHost = 4
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: configuration)
    }()

    func materials() async throws -> [Material] {
        try await get("materials")
    }

    func material(id: Int) async throws -> MaterialDetail {
        try await get("materials/\(id)")
    }

    func createReading(title: String?, text: String? = nil, url: String? = nil) async throws -> MaterialSubmission {
        var body: [String: String] = [:]
        if let title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { body["title"] = title }
        if let text { body["text"] = text }
        if let url { body["url"] = url }
        return try await post("materials", body: body)
    }

    func createVideoLink(title: String?, url: String) async throws -> MaterialSubmission {
        var body = ["url": url]
        if let title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { body["title"] = title }
        return try await post("videos/link", body: body)
    }

    func retryMaterial(id: Int) async throws -> MaterialSubmission {
        try await postWithoutBody("materials/\(id)/retry")
    }

    func startTranscription(id: Int) async throws -> MaterialSubmission {
        try await postWithoutBody("materials/\(id)/start-transcription")
    }

    func playbackState(materialID: Int) async throws -> MaterialPlaybackState {
        try await get("materials/\(materialID)/playback")
    }

    func savePlaybackState(materialID: Int, positionMs: Int) async throws -> MaterialPlaybackState {
        var request = URLRequest(url: baseURL.appending(path: "materials/\(materialID)/playback"))
        request.httpMethod = "PUT"
        request.timeoutInterval = 12
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["position_ms": max(0, positionMs)])
        return try await send(request)
    }

    func chat(sessionID: String) async throws -> [ConversationMessage] {
        try await get("chat/\(sessionID)")
    }

    func sendChat(sessionID: String, message: String) async throws -> ChatReply {
        try await post("chat", body: ["session_id": sessionID, "message": message], timeout: 60)
    }

    func chatTopics() async throws -> [ChatTopic] {
        try await get("chat/topics")
    }

    func createChatSession(starterID: String? = nil, topic: String? = nil) async throws -> ChatSessionCreation {
        var body: [String: String] = [:]
        if let starterID { body["starter_id"] = starterID }
        if let topic { body["topic"] = topic }
        return try await post("chat/sessions", body: body, timeout: 45)
    }

    func chatSessions() async throws -> [ChatSession] {
        try await get("chat/sessions")
    }

    func chatSession(id: String) async throws -> ChatSessionDetail {
        try await get("chat/sessions/\(id)")
    }

    func deleteChatSession(id: String) async throws {
        try await delete("chat/sessions/\(id)")
    }

    func sendChatMessage(sessionID: String, message: String) async throws -> ChatTurnResponse {
        try await post("chat/sessions/\(sessionID)/messages", body: ["message": message], timeout: 60)
    }

    func chatCorrections(
        query: String = "",
        topic: String? = nil,
        category: ChatCorrectionCategory? = nil,
        cursor: Int? = nil
    ) async throws -> [ChatCorrection] {
        guard var components = URLComponents(
            url: baseURL.appending(path: "chat/corrections"),
            resolvingAgainstBaseURL: false
        ) else { throw APIClientError.badResponse }
        components.queryItems = [
            query.isEmpty ? nil : URLQueryItem(name: "query", value: query),
            topic.map { URLQueryItem(name: "topic", value: $0) },
            category.map { URLQueryItem(name: "category", value: $0.rawValue) },
            cursor.map { URLQueryItem(name: "cursor", value: String($0)) },
        ].compactMap { $0 }
        guard let url = components.url else { throw APIClientError.badResponse }
        return try await get(url: url)
    }

    func deleteChatCorrection(id: Int) async throws {
        try await delete("chat/corrections/\(id)")
    }

    func furigana(text: String) async throws -> [FuriganaSegment] {
        let response: FuriganaResponse = try await post("furigana", body: ["text": text])
        return response.segments
    }

    func dictionaryLookup(word: String, context: String? = nil) async throws -> DictionaryLookupResult {
        var body: [String: String] = ["word": word]
        if let context { body["context"] = context }
        // LLM lookup is slower than list APIs.
        return try await post("dictionary/lookup", body: body, timeout: 60)
    }

    func addVocabulary(
        word: String,
        reading: String?,
        meaning: String,
        partOfSpeech: String?,
        context: String?,
        exampleJA: String? = nil,
        exampleZH: String? = nil
    ) async throws -> VocabularyWord {
        var body: [String: String] = ["word": word, "meaning": meaning]
        if let reading { body["reading"] = reading }
        if let partOfSpeech { body["part_of_speech"] = partOfSpeech }
        if let context { body["context"] = context }
        if let exampleJA { body["example_ja"] = exampleJA }
        if let exampleZH { body["example_zh"] = exampleZH }
        return try await post("vocabulary", body: body)
    }

    func listVocabulary() async throws -> [VocabularyWord] {
        try await get("vocabulary")
    }

    func deleteVocabulary(id: Int) async throws {
        try await delete("vocabulary/\(id)")
    }

    func listGrammar() async throws -> [GrammarPoint] {
        try await get("grammar")
    }

    /// Explanations are generated on demand, so this call is slow the first time and
    /// instant afterwards — the server caches it.
    func grammarPoint(key: String) async throws -> GrammarPoint {
        try await get("grammar/\(key)")
    }

    @discardableResult
    func setGrammarStatus(key: String, status: String) async throws -> GrammarPoint {
        try await post("grammar/\(key)/status", body: ["status": status])
    }

    /// §5.11: the learner says one piece of evidence was mistagged. The row stays;
    /// only its `rejected_at` moves, so this is safe to retry.
    @discardableResult
    func rejectGrammarEvidence(eventID: Int) async throws -> GrammarPoint {
        try await postWithoutBody("grammar/evidence/\(eventID)/reject")
    }

    @discardableResult
    func unrejectGrammarEvidence(eventID: Int) async throws -> GrammarPoint {
        try await postWithoutBody("grammar/evidence/\(eventID)/unreject")
    }


    /// Words due for spaced-repetition review right now, oldest-due first.
    func reviewDueVocabulary(limit: Int = 20) async throws -> [VocabularyWord] {
        guard var components = URLComponents(
            url: baseURL.appending(path: "vocabulary/review"),
            resolvingAgainstBaseURL: false
        ) else { throw APIClientError.badResponse }
        components.queryItems = [URLQueryItem(name: "limit", value: String(limit))]
        guard let url = components.url else { throw APIClientError.badResponse }
        return try await get(url: url)
    }

    /// Records a review outcome; the server reschedules the word's next review time.
    func submitVocabularyReview(id: Int, correct: Bool) async throws -> VocabularyWord {
        var request = URLRequest(url: baseURL.appending(path: "vocabulary/\(id)/review"))
        request.httpMethod = "POST"
        request.timeoutInterval = 12
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["correct": correct])
        return try await send(request)
    }

    /// §5.17 (2026-08-10): pass `segmentID` to get just that sentence's history. The sheet
    /// opens on one sentence, so the whole material's history buried the answer you just
    /// asked for. Omit it for the "以前问过的" view, which deliberately wants everything.
    func companion(materialID: Int, segmentID: Int? = nil) async throws -> [ConversationMessage] {
        guard let segmentID else { return try await get("companion/\(materialID)") }
        var components = URLComponents(
            url: baseURL.appending(path: "companion/\(materialID)"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [URLQueryItem(name: "segment_id", value: String(segmentID))]
        guard let url = components?.url else { return try await get("companion/\(materialID)") }
        return try await get(url: url)
    }

    func companionLenses() async throws -> [QuestionLens] {
        try await get("companion/lenses")
    }

    func askMessages() async throws -> [ConversationMessage] {
        try await get("ask")
    }

    /// §5.18: at most one fact about where you left off, or nil.
    func resumeHint() async throws -> ResumeHint? {
        let envelope: ResumeHintEnvelope = try await get("home/resume")
        return envelope.hint
    }

    // MARK: Private journal (§14) — nothing here touches learning data.

    func journalEntries() async throws -> [JournalEntry] {
        try await get("journal")
    }

    /// Writing is enough to save it; the reply comes back in the same response (§14.2).
    /// A longer timeout than `ask` because there is no partial state to fall back on and
    /// the entry has already been stored server-side either way.
    func postJournalEntry(body: String) async throws -> JournalPostResult {
        var request = URLRequest(url: baseURL.appending(path: "journal"))
        request.httpMethod = "POST"
        request.timeoutInterval = 90
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["body": body])
        return try await send(request)
    }

    /// Appends another reply. Used after a failure, or when the first one did not land.
    func retryJournalReply(id: Int) async throws -> JournalReply {
        var request = URLRequest(url: baseURL.appending(path: "journal/\(id)/reply"))
        request.httpMethod = "POST"
        request.timeoutInterval = 90
        return try await send(request)
    }

    func updateJournalEntry(id: Int, body: String) async throws -> JournalEntry {
        var request = URLRequest(url: baseURL.appending(path: "journal/\(id)"))
        request.httpMethod = "PATCH"
        request.timeoutInterval = 12
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["body": body])
        return try await send(request)
    }

    /// Hard delete (§13.7 / §14.3): the replies cascade and nothing is merely hidden.
    func deleteJournalEntry(id: Int) async throws {
        try await delete("journal/\(id)")
    }

    /// §5.16: with a lens the text is what is being asked *about*; without one it is
    /// the question itself.
    func ask(text: String, lens: String? = nil) async throws -> ChatReply {
        var request = URLRequest(url: baseURL.appending(path: "ask"))
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: Any] = ["text": text]
        if let lens { body["lens"] = lens }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request)
    }

    /// §5.15: send a typed `question`, or a `lens` id for a one-tap angle. The server
    /// renders the angle's wording so it is defined in exactly one place.
    func sendCompanion(
        materialID: Int,
        segmentID: Int,
        question: String? = nil,
        lens: String? = nil,
        focusText: String? = nil
    ) async throws -> ChatReply {
        var request = URLRequest(url: baseURL.appending(path: "companion"))
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: Any] = ["material_id": materialID, "segment_id": segmentID]
        if let question, !question.isEmpty { body["question"] = question }
        if let lens { body["lens"] = lens }
        if let focusText, !focusText.isEmpty { body["focus_text"] = focusText }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request)
    }

    func uploadShadowing(segmentID: Int, audioURL: URL) async throws -> ShadowingSubmission {
        let boundary = "Harvest-\(UUID().uuidString)"
        var request = URLRequest(url: baseURL.appending(path: "shadowing"))
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"segment_id\"\r\n\r\n\(segmentID)\r\n".data(using: .utf8)!)
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"shadowing.m4a\"\r\nContent-Type: audio/m4a\r\n\r\n".data(using: .utf8)!)
        body.append(try Data(contentsOf: audioURL))
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body
        return try await send(request)
    }

    func shadowing(id: Int) async throws -> ShadowingAttempt {
        try await get("shadowing/\(id)")
    }

    func job(id: Int) async throws -> JobStatus { try await get("jobs/\(id)") }

    func uploadPhoto(_ photoURL: URL) async throws -> MaterialSubmission {
        try await uploadFile(
            path: "photos",
            field: "photo",
            fileURL: photoURL,
            filename: "photo.jpg",
            contentType: "image/jpeg"
        )
    }

    func uploadVideo(_ videoURL: URL, title: String?) async throws -> MaterialSubmission {
        let filename = videoURL.lastPathComponent.isEmpty ? "video.mp4" : videoURL.lastPathComponent
        return try await uploadFile(
            path: "videos",
            field: "video",
            fileURL: videoURL,
            filename: filename,
            contentType: "video/\(videoURL.pathExtension.lowercased() == "mov" ? "quicktime" : "mp4")",
            fields: title.map { ["title": $0] } ?? [:]
        )
    }

    func voiceTeacherStatus() async throws -> VoiceTeacherStatus { try await get("voice-teacher/status") }

    private func get<Response: Decodable>(_ path: String) async throws -> Response {
        try await get(url: baseURL.appending(path: path))
    }

    private func get<Response: Decodable>(url: URL) async throws -> Response {
        var request = URLRequest(url: url)
        request.timeoutInterval = 12
        return try await send(request)
    }

    private func post<Response: Decodable>(
        _ path: String,
        body: [String: String],
        timeout: TimeInterval = 12
    ) async throws -> Response {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return try await send(request)
    }

    private func postWithoutBody<Response: Decodable>(_ path: String) async throws -> Response {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.timeoutInterval = 12
        return try await send(request)
    }

    private func send<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw APIClientError.badResponse }
            guard (200..<300).contains(http.statusCode) else {
                let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
                throw APIClientError.server(detail ?? "服务暂时不可用（HTTP \(http.statusCode)）。")
            }
            do { return try decoder.decode(Response.self, from: data) } catch { throw APIClientError.badResponse }
        } catch let error as APIClientError {
            throw error
        } catch let error as URLError where error.code == .timedOut {
            throw APIClientError.server("连接超时。请确认 Mac 上的 Harvest 服务和 Tailscale 已就绪。")
        } catch {
            throw APIClientError.server(error.localizedDescription)
        }
    }

    private func delete(_ path: String) async throws {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "DELETE"
        request.timeoutInterval = 12
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw APIClientError.badResponse }
            guard (200..<300).contains(http.statusCode) else {
                let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
                throw APIClientError.server(detail ?? "服务暂时不可用（HTTP \(http.statusCode)）。")
            }
        } catch let error as APIClientError {
            throw error
        } catch let error as URLError where error.code == .timedOut {
            throw APIClientError.server("连接超时。请确认 Mac 上的 Harvest 服务和 Tailscale 已就绪。")
        } catch {
            throw APIClientError.server(error.localizedDescription)
        }
    }

    private func uploadFile<Response: Decodable>(
        path: String,
        field: String,
        fileURL: URL,
        filename: String,
        contentType: String,
        fields: [String: String] = [:]
    ) async throws -> Response {
        let boundary = "Harvest-\(UUID().uuidString)"
        let multipartURL = try await Task.detached {
            try makeMultipartFile(
                sourceURL: fileURL,
                boundary: boundary,
                field: field,
                filename: filename,
                contentType: contentType,
                fields: fields
            )
        }.value
        defer { try? FileManager.default.removeItem(at: multipartURL) }
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.upload(for: request, fromFile: multipartURL)
        guard let http = response as? HTTPURLResponse else { throw APIClientError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIClientError.server(detail ?? "服务暂时不可用（HTTP \(http.statusCode)）。")
        }
        do { return try decoder.decode(Response.self, from: data) } catch { throw APIClientError.badResponse }
    }
}

private func makeMultipartFile(
    sourceURL: URL,
    boundary: String,
    field: String,
    filename: String,
    contentType: String,
    fields: [String: String]
) throws -> URL {
    let destination = FileManager.default.temporaryDirectory.appending(path: "upload-\(UUID().uuidString).multipart")
    FileManager.default.createFile(atPath: destination.filePath, contents: nil)
    let output = try FileHandle(forWritingTo: destination)
    do {
        for (name, value) in fields {
            try output.write(contentsOf: Data(
                "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8
            ))
        }
        try output.write(contentsOf: Data(
            "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(field)\"; filename=\"\(filename)\"\r\nContent-Type: \(contentType)\r\n\r\n".utf8
        ))
        let input = try FileHandle(forReadingFrom: sourceURL)
        defer { try? input.close() }
        while let chunk = try input.read(upToCount: 1_048_576), !chunk.isEmpty {
            try output.write(contentsOf: chunk)
        }
        try output.write(contentsOf: Data("\r\n--\(boundary)--\r\n".utf8))
        try output.close()
        return destination
    } catch {
        try? output.close()
        try? FileManager.default.removeItem(at: destination)
        throw error
    }
}

// MARK: - §15 长视频拆分与合集

extension APIClient {
    /// Park the source on the Mac without creating anything yet (§15.2).
    ///
    /// `onProgress` exists because this runs while the learner is still cutting — a thin
    /// line at the top of the split screen, not a modal that blocks the work.
    func uploadVideoForSplit(
        _ sourceURL: URL,
        onProgress: @escaping @Sendable (Double) -> Void
    ) async throws -> VideoUploadHandle {
        let filename = sourceURL.lastPathComponent.isEmpty ? "video.mp4" : sourceURL.lastPathComponent
        return try await uploadFileReportingProgress(
            path: "videos/uploads",
            field: "video",
            fileURL: sourceURL,
            filename: filename,
            contentType: Self.uploadContentType(for: sourceURL),
            onProgress: onProgress
        )
    }

    func createCollection(
        uploadID: String,
        title: String?,
        cuts: [Int],
        sourceName: String? = nil
    ) async throws -> CollectionSubmission {
        var request = URLRequest(url: baseURL.appending(path: "collections"))
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: Any] = ["upload_id": uploadID, "cuts": cuts]
        if let title, !title.isEmpty { body["title"] = title }
        if let sourceName, !sourceName.isEmpty { body["source_name"] = sourceName }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request)
    }

    func collections() async throws -> [MaterialCollection] {
        try await get("collections")
    }

    func collectionDetail(id: Int) async throws -> CollectionDetail {
        try await get("collections/\(id)")
    }

    func deleteCollection(id: Int) async throws {
        try await delete("collections/\(id)")
    }

    /// §15.7: deleting one section deletes only that section.
    func deleteMaterial(id: Int) async throws {
        try await delete("materials/\(id)")
    }

    /// A zipped HLS bundle is still a video as far as this flow is concerned (§15.10).
    static func uploadContentType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "zip": "video/mp4"
        case "mov": "video/quicktime"
        default: "video/mp4"
        }
    }
}

// MARK: - §15.11 网络不够快时改走 OSS 直传

extension APIClient {
    /// A small, fast `PUT` timed against the Mac to decide whether the direct upload
    /// path is worth trying at all.
    ///
    /// §3.3 already found that HLS *playback* over Tailscale does not survive cellular;
    /// the same weak link cuts the other direction for a raw upload. Wi-Fi vs. cellular
    /// was considered and rejected as the signal — a phone can be on someone else's
    /// Wi-Fi, nowhere near the Mac, and still look "fast" by that test. Measuring the
    /// actual path is the only thing that is actually true of *this* attempt.
    ///
    /// Any failure (timeout, no route, Mac asleep) counts as "not adequate": OSS is the
    /// safer default when the direct path cannot even be measured.
    func probeUploadSpeedIsAdequate() async -> Bool {
        let payload = Data(count: 256 * 1_024)
        var request = URLRequest(url: baseURL.appending(path: "videos/uploads/probe"))
        request.httpMethod = "PUT"
        request.httpBody = payload
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 6
        configuration.timeoutIntervalForResource = 8
        configuration.waitsForConnectivity = false
        let probeSession = URLSession(configuration: configuration)
        defer { probeSession.finishTasksAndInvalidate() }
        let started = DispatchTime.now()
        do {
            let (_, response) = try await probeSession.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                return false
            }
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - started.uptimeNanoseconds) / 1_000_000_000
            guard elapsed > 0 else { return true }
            let bytesPerSecond = Double(payload.count) / elapsed
            // ~600 KB/s (≈4.8 Mbps): comfortably above what a healthy LAN or a good direct
            // Tailscale connection measures, comfortably below what a DERP-relayed or
            // congested-uplink path measures. Not a precise number — a fast/slow binary is
            // all this decision needs.
            return bytesPerSecond >= 600 * 1_024
        } catch {
            return false
        }
    }

    /// `POST /videos/oss-upload-url`: a presigned target for the raw upload itself.
    func requestOSSUploadURL(filename: String) async throws -> OSSUploadTicket {
        try await post("videos/oss-upload-url", body: ["filename": filename])
    }

    /// `PUT`s the file straight to OSS — no multipart envelope, no `Content-Type`, because
    /// the presigned URL was not signed for either (`ObjectStorage.presigned_put_url`).
    func putFileToOSS(
        _ fileURL: URL,
        to uploadURL: URL,
        onProgress: @escaping @Sendable (Double) -> Void
    ) async throws {
        var request = URLRequest(url: uploadURL)
        request.httpMethod = "PUT"
        request.timeoutInterval = 3_600
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 3_600
        configuration.timeoutIntervalForResource = 7_200
        let uploadSession = URLSession(configuration: configuration)
        defer { uploadSession.finishTasksAndInvalidate() }
        let (_, response) = try await uploadSession.upload(
            for: request,
            fromFile: fileURL,
            delegate: UploadProgressDelegate(onProgress: onProgress)
        )
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIClientError.server("传到云端失败（HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)）。")
        }
    }

    /// `POST /videos/uploads/from-oss`: hand the Mac the key it should pull down.
    func notifyOSSUpload(ossKey: String, filename: String) async throws -> Int {
        let job: OSSUploadFetchJob = try await post(
            "videos/uploads/from-oss",
            body: ["oss_key": ossKey, "filename": filename]
        )
        return job.jobID
    }

    /// Polls the `fetch_video_upload` job until the Mac has pulled the object down from
    /// OSS and unpacked it (§15.11) — the counterpart to the multipart upload's progress
    /// bar, except there is no byte count to show, only "the Mac is working on it".
    func fetchUploadJobStatus(id: Int) async throws -> VideoUploadFetchStatus {
        try await get("jobs/\(id)")
    }
}

private final class UploadProgressDelegate: NSObject, URLSessionTaskDelegate {
    private let onProgress: @Sendable (Double) -> Void

    init(onProgress: @escaping @Sendable (Double) -> Void) {
        self.onProgress = onProgress
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didSendBodyData bytesSent: Int64,
        totalBytesSent: Int64,
        totalBytesExpectedToSend totalBytesExpectedToSend: Int64
    ) {
        guard totalBytesExpectedToSend > 0 else { return }
        onProgress(min(1, Double(totalBytesSent) / Double(totalBytesExpectedToSend)))
    }
}

extension APIClient {
    /// Same multipart-on-disk approach as `uploadFile`, plus progress. A one-hour video is
    /// minutes of upload (§15.2), and a bar that never moves is indistinguishable from a
    /// hang.
    fileprivate func uploadFileReportingProgress<Response: Decodable>(
        path: String,
        field: String,
        fileURL: URL,
        filename: String,
        contentType: String,
        onProgress: @escaping @Sendable (Double) -> Void
    ) async throws -> Response {
        let boundary = "Harvest-\(UUID().uuidString)"
        let multipartURL = try await Task.detached {
            try makeMultipartFile(
                sourceURL: fileURL,
                boundary: boundary,
                field: field,
                filename: filename,
                contentType: contentType,
                fields: [:]
            )
        }.value
        defer { try? FileManager.default.removeItem(at: multipartURL) }
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        // A long upload must not be killed by the control-plane timeout.
        request.timeoutInterval = 3_600
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 3_600
        configuration.timeoutIntervalForResource = 7_200
        let uploadSession = URLSession(configuration: configuration)
        defer { uploadSession.finishTasksAndInvalidate() }
        let (data, response) = try await uploadSession.upload(
            for: request,
            fromFile: multipartURL,
            delegate: UploadProgressDelegate(onProgress: onProgress)
        )
        guard let http = response as? HTTPURLResponse else { throw APIClientError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIClientError.server(detail ?? "服务暂时不可用（HTTP \(http.statusCode)）。")
        }
        do { return try JSONDecoder().decode(Response.self, from: data) } catch { throw APIClientError.badResponse }
    }
}
