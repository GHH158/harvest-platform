import Foundation

struct Material: Codable, Identifiable, Hashable {
    let id: Int
    let kind: String
    let title: String
    let sourceType: String
    let sourceRef: String?
    let status: String
    let errorMessage: String?
    let durationMs: Int?
    let audioURL: URL?

    enum CodingKeys: String, CodingKey {
        case id, kind, title, status
        case sourceType = "source_type"
        case sourceRef = "source_ref"
        case errorMessage = "error_message"
        case durationMs = "duration_ms"
        case audioURL = "audio_url"
    }
}

struct MaterialDetail: Codable {
    let id: Int
    let title: String
    let status: String
    let errorMessage: String?
    let durationMs: Int?
    let audioURL: URL?
    let segments: [Segment]

    enum CodingKeys: String, CodingKey {
        case id, title, status, segments
        case errorMessage = "error_message"
        case durationMs = "duration_ms"
        case audioURL = "audio_url"
    }
}

struct Segment: Codable, Identifiable, Hashable {
    let id: Int
    let materialID: Int
    let index: Int
    let textJA: String
    let textZH: String?
    let startMs: Int
    let endMs: Int

    enum CodingKeys: String, CodingKey {
        case id
        case materialID = "material_id"
        case index = "idx"
        case textJA = "text_ja"
        case textZH = "text_zh"
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}
