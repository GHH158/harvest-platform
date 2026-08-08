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
    let createdAt: String?
    let updatedAt: String?
    let thumbnailPath: String?
    let jobID: Int?
    let progressPercent: Int?
    let progressLabel: String?
    let etaMinutes: Int?
    let retryable: Bool?
    let failureTitle: String?
    let failureSummary: String?

    enum CodingKeys: String, CodingKey {
        case id, kind, title, status
        case sourceType = "source_type"
        case sourceRef = "source_ref"
        case errorMessage = "error_message"
        case durationMs = "duration_ms"
        case audioURL = "audio_url"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case thumbnailPath = "thumbnail_path"
        case jobID = "job_id"
        case progressPercent = "progress_percent"
        case progressLabel = "progress_label"
        case etaMinutes = "eta_minutes"
        case retryable
        case failureTitle = "failure_title"
        case failureSummary = "failure_summary"
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

struct MaterialPlaybackState: Codable, Equatable {
    let materialID: Int
    let positionMs: Int
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case materialID = "material_id"
        case positionMs = "position_ms"
        case updatedAt = "updated_at"
    }
}

struct Token: Codable, Identifiable, Hashable {
    let id: Int
    let segmentID: Int
    let index: Int
    let surface: String
    let reading: String?
    let startMs: Int
    let endMs: Int

    enum CodingKeys: String, CodingKey {
        case id, surface, reading
        case segmentID = "segment_id"
        case index = "idx"
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

struct ConversationMessage: Codable, Identifiable, Hashable {
    let id: Int
    let sessionID: String?
    let role: String
    let content: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, role, content
        case sessionID = "session_id"
        case createdAt = "created_at"
    }
}

struct ChatReply: Codable {
    let user: ConversationMessage
    let assistant: ConversationMessage
}

struct ChatTopic: Codable, Identifiable, Hashable {
    let id: String
    let category: String
    let titleJA: String
    let hintZH: String

    enum CodingKeys: String, CodingKey {
        case id, category
        case titleJA = "title_ja"
        case hintZH = "hint_zh"
    }
}

struct ChatSession: Codable, Identifiable, Hashable {
    let id: String
    let topic: String
    let starterID: String?
    let createdAt: String
    let updatedAt: String
    let lastMessagePreview: String?

    enum CodingKeys: String, CodingKey {
        case id, topic
        case starterID = "starter_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case lastMessagePreview = "last_message_preview"
    }
}

enum ChatCorrectionCategory: String, Codable, CaseIterable, Identifiable {
    case grammar
    case wordChoice = "word_choice"
    case naturalness
    case register
    case orthography

    var id: String { rawValue }

    var label: String {
        switch self {
        case .grammar: "语法"
        case .wordChoice: "词语选择"
        case .naturalness: "自然度"
        case .register: "语体与礼貌"
        case .orthography: "书写"
        }
    }
}

struct ChatCorrectionItem: Codable, Identifiable, Hashable {
    let id: Int
    let correctionID: Int
    let index: Int
    let original: String
    let replacement: String
    let reasonZH: String
    let category: ChatCorrectionCategory

    enum CodingKeys: String, CodingKey {
        case id, original, replacement, category
        case correctionID = "correction_id"
        case index = "idx"
        case reasonZH = "reason_zh"
    }
}

struct ChatCorrection: Codable, Identifiable, Hashable {
    let id: Int
    let sessionID: String
    let userMessageID: Int
    let originalText: String
    let correctedText: String
    let summaryZH: String
    let createdAt: String
    let topic: String?
    let items: [ChatCorrectionItem]

    enum CodingKeys: String, CodingKey {
        case id, topic, items
        case sessionID = "session_id"
        case userMessageID = "user_message_id"
        case originalText = "original_text"
        case correctedText = "corrected_text"
        case summaryZH = "summary_zh"
        case createdAt = "created_at"
    }
}

struct ChatSessionCreation: Codable {
    let session: ChatSession
    let assistant: ConversationMessage
}

struct ChatSessionDetail: Codable {
    let session: ChatSession
    let messages: [ConversationMessage]
    let corrections: [ChatCorrection]
}

struct ChatTurnResponse: Codable {
    let user: ConversationMessage
    let correction: ChatCorrection?
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
    let jobID: Int?
    let status: String
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case id, score, status
        case asrText = "asr_text"
        case diff = "diff_json"
        case jobID = "job_id"
        case errorMessage = "error_message"
    }
}

struct JobStatus: Codable {
    let id: Int
    let status: String
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case errorMessage = "error_message"
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

struct MaterialSubmission: Codable {
    let materialID: Int
    let jobID: Int
    let status: String

    enum CodingKeys: String, CodingKey {
        case materialID = "material_id"
        case jobID = "job_id"
        case status
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

struct FuriganaSegment: Codable, Hashable {
    let surface: String
    let reading: String?
}

struct FuriganaResponse: Codable {
    let segments: [FuriganaSegment]
}

// MARK: - Dictionary & Vocabulary

struct DictionaryExample: Codable, Hashable {
    let ja: String
    let zh: String
}

struct DictionaryLookupResult: Codable {
    let word: String
    let reading: String?
    let meaning: String?
    let partOfSpeech: String?
    let memoryHint: String?
    let examples: [DictionaryExample]

    enum CodingKeys: String, CodingKey {
        case word, reading, meaning, examples
        case partOfSpeech = "part_of_speech"
        case memoryHint = "memory_hint"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        word = try container.decode(String.self, forKey: .word)
        reading = try container.decodeIfPresent(String.self, forKey: .reading)
        meaning = try container.decodeIfPresent(String.self, forKey: .meaning)
        partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
        memoryHint = try container.decodeIfPresent(String.self, forKey: .memoryHint)
        examples = try container.decodeIfPresent([DictionaryExample].self, forKey: .examples) ?? []
    }
}

struct VocabularyWord: Codable, Identifiable {
    let id: Int
    let word: String
    let reading: String?
    let meaning: String
    let partOfSpeech: String?
    let context: String?
    let exampleJA: String?
    let exampleZH: String?
    let box: Int
    let reviewCount: Int
    let nextReviewAt: String
    let createdAt: String
    /// Only present on the save response: true when the word was already in the table.
    let alreadySaved: Bool

    /// A word only supports cloze review once it has a matched example pair.
    var hasExample: Bool { exampleJA != nil && exampleZH != nil }

    enum CodingKeys: String, CodingKey {
        case id, word, reading, meaning, context, box
        case partOfSpeech = "part_of_speech"
        case exampleJA = "example_ja"
        case exampleZH = "example_zh"
        case reviewCount = "review_count"
        case nextReviewAt = "next_review_at"
        case createdAt = "created_at"
        case alreadySaved = "already_saved"
    }

    // Custom decode so an older backend that hasn't rolled out the review-scheduling
    // columns yet (box/review_count/next_review_at/example_ja/example_zh) degrades
    // gracefully instead of failing the whole list with a decode error.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(Int.self, forKey: .id)
        word = try container.decode(String.self, forKey: .word)
        reading = try container.decodeIfPresent(String.self, forKey: .reading)
        meaning = try container.decode(String.self, forKey: .meaning)
        partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
        context = try container.decodeIfPresent(String.self, forKey: .context)
        exampleJA = try container.decodeIfPresent(String.self, forKey: .exampleJA)
        exampleZH = try container.decodeIfPresent(String.self, forKey: .exampleZH)
        box = try container.decodeIfPresent(Int.self, forKey: .box) ?? 1
        reviewCount = try container.decodeIfPresent(Int.self, forKey: .reviewCount) ?? 0
        nextReviewAt = try container.decodeIfPresent(String.self, forKey: .nextReviewAt) ?? ""
        createdAt = try container.decode(String.self, forKey: .createdAt)
        alreadySaved = try container.decodeIfPresent(Bool.self, forKey: .alreadySaved) ?? false
    }
}


/// One point in the grammar skeleton (§12). `status` is nil for 未接触 — absence is
/// the third state rather than a stored value, so a fresh catalogue needs no rows.
struct GrammarPoint: Codable, Identifiable, Hashable {
    let id: Int
    let key: String
    let titleJA: String
    let titleZH: String
    let level: String
    let category: String
    let status: String?
    let firstSource: String?
    let note: String?
    let hasExplanation: Bool?
    let explanation: String?

    enum CodingKeys: String, CodingKey {
        case id, key, level, category, status, note, explanation
        case titleJA = "title_ja"
        case titleZH = "title_zh"
        case firstSource = "first_source"
        case hasExplanation = "has_explanation"
    }

    var isUnderstood: Bool { status == "understood" }
    var isEncountered: Bool { status == "encountered" }
    /// Came from a real mistake rather than from browsing the catalogue.
    var cameFromMistake: Bool { firstSource == "correction" }
}

