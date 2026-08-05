import Combine
import Foundation

@MainActor
final class AppConfiguration: ObservableObject {
    @Published private(set) var endpoint: URL?

    init() {
        endpoint = KeychainStore.endpoint().flatMap(URL.init(string:))
    }

    func saveEndpoint(_ value: String) throws {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), let scheme = url.scheme, ["http", "https"].contains(scheme), url.host != nil else {
            throw ConfigurationError.invalidURL
        }
        try KeychainStore.save(endpoint: trimmed)
        endpoint = url
    }

    func clearEndpoint() {
        KeychainStore.deleteEndpoint()
        endpoint = nil
    }
}

enum ConfigurationError: LocalizedError {
    case invalidURL

    var errorDescription: String? { "请输入完整地址，例如 https://harvest.example.ts.net。" }
}
