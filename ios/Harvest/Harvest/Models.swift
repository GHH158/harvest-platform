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
    let kind: String
    let title: String
    let status: String
    let errorMessage: String?
    let durationMs: Int?
    let audioURL: URL?
    let videoURL: URL?
    let segments: [Segment]
    let tokens: [Token]

    enum CodingKeys: String, CodingKey {
        case id, kind, title, status, segments, tokens
        case errorMessage = "error_message"
        case durationMs = "duration_ms"
        case audioURL = "audio_url"
        case videoURL = "video_url"
    }
}

struct Token: Codable, Identifiable, Hashable {
    let id: Int
    let segmentID: Int
    let index: Int
    let surface: String
    let startMs: Int
    let endMs: Int

    enum CodingKeys: String, CodingKey {
        case id, surface
        case segmentID = "segment_id"
        case index = "idx"
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

struct ConversationMessage: Codable, Identifiable, Hashable {
    let id: Int
    let role: String
    let content: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, role, content
        case createdAt = "created_at"
    }
}

struct ChatReply: Codable {
    let user: ConversationMessage
    let assistant: ConversationMessage
}

struct ShadowingUnit: Codable, Hashable {
    let surface: String
    let recognized: Bool
}

struct ShadowingAttempt: Codable {
    let id: Int
    let asrText: String?
    let diff: [ShadowingUnit]?
    let score: Double?

    enum CodingKeys: String, CodingKey {
        case id, score
        case asrText = "asr_text"
        case diff = "diff_json"
    }
}

struct ShadowingSubmission: Codable {
    let attemptID: Int
    let jobID: Int

    enum CodingKeys: String, CodingKey {
        case attemptID = "attempt_id"
        case jobID = "job_id"
    }
}

struct VoiceTeacherStatus: Codable { let configured: Bool; let model: String }

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
