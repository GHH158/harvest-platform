import Foundation

struct OfflineEntry: Codable, Identifiable {
    let material: MaterialDetail
    let localAudioPath: String
    let downloadedAt: Date

    var id: Int { material.id }
    var localAudioURL: URL { URL(fileURLWithPath: localAudioPath) }
}

@MainActor
final class OfflineLibrary: ObservableObject {
    @Published private(set) var entries: [OfflineEntry] = []
    private let fileManager = FileManager.default

    init() { load() }

    func localAudioURL(for materialID: Int) -> URL? {
        entries.first(where: { $0.id == materialID && fileManager.fileExists(atPath: $0.localAudioPath) })?.localAudioURL
    }

    func download(_ material: MaterialDetail) async throws {
        guard let remoteURL = material.audioURL else { throw OfflineLibraryError.noAudio }
        let directory = try directory(for: material.id)
        let temporaryURL = try await URLSession.shared.download(from: remoteURL).0
        let destination = directory.appending(path: "reading.mp3")
        try? fileManager.removeItem(at: destination)
        try fileManager.moveItem(at: temporaryURL, to: destination)
        let entry = OfflineEntry(material: material, localAudioPath: destination.path(), downloadedAt: .now)
        entries.removeAll { $0.id == material.id }
        entries.append(entry)
        try persist()
    }

    func remove(_ entry: OfflineEntry) {
        try? fileManager.removeItem(at: entry.localAudioURL.deletingLastPathComponent())
        entries.removeAll { $0.id == entry.id }
        try? persist()
    }

    private func directory(for materialID: Int) throws -> URL {
        let directory = try rootDirectory().appending(path: "material-\(materialID)")
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func rootDirectory() throws -> URL {
        let applicationSupport = try fileManager.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let root = applicationSupport.appending(path: "HarvestOffline")
        try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func manifestURL() throws -> URL { try rootDirectory().appending(path: "manifest.json") }

    private func load() {
        guard let url = try? manifestURL(), let data = try? Data(contentsOf: url), let restored = try? JSONDecoder().decode([OfflineEntry].self, from: data) else { return }
        entries = restored.filter { fileManager.fileExists(atPath: $0.localAudioPath) }
    }

    private func persist() throws {
        try JSONEncoder().encode(entries).write(to: manifestURL(), options: .atomic)
    }
}

enum OfflineLibraryError: LocalizedError {
    case noAudio
    var errorDescription: String? { "朗读尚未准备好，暂时无法下载。" }
}
