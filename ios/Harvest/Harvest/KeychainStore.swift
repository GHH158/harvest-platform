import Foundation
import Security

enum KeychainStore {
    private static let service = "com.harvest.reader"
    private static let endpointAccount = "api-endpoint"

    static func endpoint() -> String? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: endpointAccount,
            kSecReturnData: true
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func save(endpoint: String) throws {
        let data = Data(endpoint.utf8)
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: endpointAccount
        ]
        let attributes = [kSecValueData: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecItemNotFound {
            var creation = query
            creation[kSecValueData] = data
            let creationStatus = SecItemAdd(creation as CFDictionary, nil)
            guard creationStatus == errSecSuccess else { throw KeychainError.unexpectedStatus(creationStatus) }
        } else if updateStatus != errSecSuccess {
            throw KeychainError.unexpectedStatus(updateStatus)
        }
    }
}

enum KeychainError: LocalizedError {
    case unexpectedStatus(OSStatus)

    var errorDescription: String? { "无法保存本机连接设置。" }
}
