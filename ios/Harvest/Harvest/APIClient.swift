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
}
