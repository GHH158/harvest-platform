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
    private let decoder = JSONDecoder()

    func materials() async throws -> [Material] {
        try await get("materials")
    }

    func material(id: Int) async throws -> MaterialDetail {
        try await get("materials/\(id)")
    }

    func chat(sessionID: String) async throws -> [ConversationMessage] {
        try await get("chat/\(sessionID)")
    }

    func sendChat(sessionID: String, message: String) async throws -> ChatReply {
        try await post("chat", body: ["session_id": sessionID, "message": message])
    }

    func uploadShadowing(segmentID: Int, audioURL: URL) async throws -> ShadowingSubmission {
        let boundary = "Harvest-\(UUID().uuidString)"
        var request = URLRequest(url: baseURL.appending(path: "shadowing"))
        request.httpMethod = "POST"
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

    func uploadPhoto(_ photoURL: URL) async throws -> ShadowingSubmission {
        try await uploadFile(path: "photos", field: "photo", fileURL: photoURL)
    }

    func voiceTeacherStatus() async throws -> VoiceTeacherStatus { try await get("voice-teacher/status") }

    private func get<Response: Decodable>(_ path: String) async throws -> Response {
        let url = baseURL.appending(path: path)
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse else { throw APIClientError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIClientError.server(detail ?? "服务暂时不可用（HTTP \(http.statusCode)）。")
        }
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw APIClientError.badResponse
        }
    }

    private func post<Response: Decodable>(_ path: String, body: [String: String]) async throws -> Response {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return try await send(request)
    }

    private func send<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIClientError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIClientError.server(detail ?? "服务暂时不可用（HTTP \(http.statusCode)）。")
        }
        do { return try decoder.decode(Response.self, from: data) } catch { throw APIClientError.badResponse }
    }

    private func uploadFile<Response: Decodable>(path: String, field: String, fileURL: URL) async throws -> Response {
        let boundary = "Harvest-\(UUID().uuidString)"; var request = URLRequest(url: baseURL.appending(path: path)); request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data(); body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(field)\"; filename=\"photo.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(try Data(contentsOf: fileURL)); body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!); request.httpBody = body
        return try await send(request)
    }
}
