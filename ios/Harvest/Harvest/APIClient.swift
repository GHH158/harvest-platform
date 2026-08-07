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

    func companion(materialID: Int) async throws -> [ConversationMessage] {
        try await get("companion/\(materialID)")
    }

    func sendCompanion(materialID: Int, segmentID: Int, question: String) async throws -> ChatReply {
        var request = URLRequest(url: baseURL.appending(path: "companion"))
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "material_id": materialID, "segment_id": segmentID, "question": question,
        ])
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
