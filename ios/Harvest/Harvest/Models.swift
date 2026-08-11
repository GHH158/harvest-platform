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
    /// §15.5: present only for a section of a split collection.
    let collectionID: Int?
    let collectionIndex: Int?
    /// Where this section began in the source video, so a row can say 「从 10:21 开始」.
    let sourceOffsetMs: Int?

    /// §15.6: transcription is on demand, and `downloaded` is the state that says so.
    var awaitsTranscription: Bool { status == "downloaded" }

    enum CodingKeys: String, CodingKey {
        case id, kind, title, status
        case collectionID = "collection_id"
        case collectionIndex = "collection_index"
        case sourceOffsetMs = "source_offset_ms"
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

/// §5.15: a reading question angle. Only the id travels back to the server; the
/// wording of the question and its prompt focus stay server-side.
struct QuestionLens: Codable, Identifiable, Hashable {
    let id: String
    let labelZH: String

    enum CodingKeys: String, CodingKey {
        case id
        case labelZH = "label_zh"
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
    /// §16: set when this session was opened from "去问老师" on a specific lesson's
    /// flagged questions, instead of a topic. Nil for every ordinary topic session.
    let materialID: Int?

    enum CodingKeys: String, CodingKey {
        case id, topic
        case starterID = "starter_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case lastMessagePreview = "last_message_preview"
        case materialID = "material_id"
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
    /// §5.6: set only when the fix also moved the register, so the politeness choice can
    /// be told apart from the correction itself. Null in the normal case.
    let sameRegisterReplacement: String?
    let reasonZH: String
    let category: ChatCorrectionCategory

    enum CodingKeys: String, CodingKey {
        case id, original, replacement, category
        case correctionID = "correction_id"
        case index = "idx"
        case sameRegisterReplacement = "same_register_replacement"
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

// MARK: - §16 阅读疑问收纳

/// A word/phrase/sentence flagged while reading or watching, to be worked through with
/// the chat teacher after the lesson. Deliberately not typed (word vs. grammar vs.
/// sentence) — see docs/PROJECT.md §16.
struct ReadingQuestion: Codable, Identifiable, Hashable {
    let id: Int
    let materialID: Int
    let segmentID: Int?
    let excerpt: String
    let note: String?
    let status: String
    let createdAt: String
    let archivedAt: String?

    var isArchived: Bool { status == "archived" }

    enum CodingKeys: String, CodingKey {
        case id, excerpt, note, status
        case materialID = "material_id"
        case segmentID = "segment_id"
        case createdAt = "created_at"
        case archivedAt = "archived_at"
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
    let statusSource: String?
    let firstSource: String?
    let lastSource: String?
    let note: String?
    let hasMistake: Bool?
    let mistakeCount: Int?
    let latestMistake: String?
    let hasCompanionQuestion: Bool?
    let companionQuestionCount: Int?
    let latestQuestion: String?
    let needsAttention: Bool?
    let stateReason: String?
    let latestLearningEvidenceAt: String?
    let hasExplanation: Bool?
    let explanation: String?
    /// Individual证据 rows behind this point (§5.11), only present on `GET /grammar/{key}`
    /// and the reject/unreject responses — the list endpoint has no need for them.
    let evidence: [GrammarEvidenceItem]?

    enum CodingKeys: String, CodingKey {
        case id, key, level, category, status, note, explanation, evidence
        case titleJA = "title_ja"
        case titleZH = "title_zh"
        case statusSource = "status_source"
        case firstSource = "first_source"
        case lastSource = "last_source"
        case hasMistake = "has_mistake"
        case mistakeCount = "mistake_count"
        case latestMistake = "latest_mistake"
        case hasCompanionQuestion = "has_companion_question"
        case companionQuestionCount = "companion_question_count"
        case latestQuestion = "latest_question"
        case needsAttention = "needs_attention"
        case stateReason = "state_reason"
        case latestLearningEvidenceAt = "latest_learning_evidence_at"
        case hasExplanation = "has_explanation"
    }

    var isUnderstood: Bool { status == "understood" }
    var isEncountered: Bool { status == "encountered" }
    var requiresAttention: Bool { needsAttention ?? isEncountered }
    var isSettled: Bool { isUnderstood && !requiresAttention }
    /// A mistake may happen after the first encounter, so firstSource cannot answer this.
    var cameFromMistake: Bool { hasMistake ?? (firstSource == "correction") }
    var mistakeText: String? { latestMistake ?? note }
}

/// One registered piece of evidence behind a grammar point encounter (§5.11): a
/// mistake actually written, or a question actually asked in the companion. `id`
/// is the learning_event id — the target for the reject/unreject endpoints. A
/// rejected event simply stops appearing here; the server never sends it back.
struct GrammarEvidenceItem: Codable, Identifiable, Hashable {
    let id: Int
    let kind: String
    let originalFragment: String?
    let replacement: String?
    let reasonZH: String?
    let question: String?
    let contextJA: String?
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, kind, question, replacement
        case originalFragment = "original_fragment"
        case reasonZH = "reason_zh"
        case contextJA = "context_ja"
        case createdAt = "created_at"
    }

    var isMistake: Bool { kind == "correction" }
    var summaryText: String { isMistake ? (originalFragment ?? "") : (question ?? "") }
}

// MARK: - Private journal (§14)
//
// The one model here with nothing to do with Japanese. Deliberately unrelated to
// ConversationMessage: sharing a shape with the teaching entries would be the first
// step toward sharing a code path, and the isolation in §14.3 runs both ways.

struct JournalReply: Codable, Identifiable, Hashable {
    let id: Int
    let body: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, body
        case createdAt = "created_at"
    }
}

struct JournalEntry: Codable, Identifiable, Hashable {
    let id: Int
    let body: String
    let createdAt: String
    /// Absent from the PATCH response, which returns the bare row. Optional here so a
    /// missing key is "no replies loaded" rather than a decode failure.
    private let repliesRaw: [JournalReply]?

    var replies: [JournalReply] { repliesRaw ?? [] }

    enum CodingKeys: String, CodingKey {
        case id, body
        case createdAt = "created_at"
        case repliesRaw = "replies"
    }
}

/// `replyError` is non-nil when the entry was saved but the model call failed. The words
/// are kept either way (§14.2) — losing what you just wrote because a cloud API was down
/// would be the worst possible behaviour for this particular feature.
struct JournalPostResult: Codable {
    let entry: JournalEntry
    let replyError: String?

    enum CodingKeys: String, CodingKey {
        case entry
        case replyError = "reply_error"
    }
}

// MARK: - §5.18 首页的一句「上次到哪儿了」

/// Structured facts, not a rendered sentence: the server owns *which* single thing is
/// worth saying, the view owns how it reads (§1.5).
///
/// Note what is absent — there is no percentage and no completion field. §4.2 says a
/// saved playback position expresses media resumption, not learning progress, so the
/// ratio stays inside the repository as a filter and never reaches the client (§5.18).
struct ResumeHint: Codable, Hashable {
    /// "material" or "grammar".
    let kind: String
    let materialID: Int?
    let materialKind: String?
    let title: String?
    let positionMS: Int?
    /// Reading materials report a sentence number; video reports a timestamp instead.
    let sentenceNumber: Int?
    let grammarKey: String?
    let titleJA: String?
    let titleZH: String?

    enum CodingKeys: String, CodingKey {
        case kind, title
        case materialID = "material_id"
        case materialKind = "material_kind"
        case positionMS = "position_ms"
        case sentenceNumber = "sentence_number"
        case grammarKey = "grammar_key"
        case titleJA = "title_ja"
        case titleZH = "title_zh"
    }

    var isMaterial: Bool { kind == "material" }
}

/// An envelope only because a top-level JSON `null` does not decode into a Swift
/// Optional; `hint == nil` means there is nothing to show and the row disappears.
struct ResumeHintEnvelope: Codable {
    let hint: ResumeHint?
}

// MARK: - §15 长视频拆分与合集

/// A video parked on the Mac, not yet turned into anything (§15.2). The phone starts this
/// the moment a file is picked and keeps uploading while the learner marks cut points.
struct VideoUploadHandle: Codable {
    let uploadID: String
    let filename: String

    enum CodingKeys: String, CodingKey {
        case uploadID = "upload_id"
        case filename
    }
}

struct CollectionSubmission: Codable {
    let collectionID: Int
    let materialIDs: [Int]
    let jobID: Int

    enum CodingKeys: String, CodingKey {
        case collectionID = "collection_id"
        case materialIDs = "material_ids"
        case jobID = "job_id"
    }
}

// MARK: - §15.11 网络不够快时改走 OSS 直传

/// A presigned target for `PUT`-ing the raw upload straight to OSS, bypassing the Mac for
/// the one transfer that is actually big.
struct OSSUploadTicket: Codable {
    let ossKey: String
    let uploadURL: URL

    enum CodingKeys: String, CodingKey {
        case ossKey = "oss_key"
        case uploadURL = "upload_url"
    }
}

/// `POST /videos/uploads/from-oss` — the phone finished `PUT`-ing to OSS, and this is the
/// job that pulls it back onto the Mac.
struct OSSUploadFetchJob: Codable {
    let jobID: Int

    enum CodingKeys: String, CodingKey {
        case jobID = "job_id"
    }
}

/// What `GET /jobs/{id}` looks like for a `fetch_video_upload` job — the Mac pulling the
/// object back down from OSS and unpacking it. Richer than `JobStatus` because the result
/// this particular job produces (`upload_id`) lives in its `payload`, not in a dedicated
/// field.
struct VideoUploadFetchStatus: Codable {
    let status: String
    let errorMessage: String?
    let payload: Payload?

    struct Payload: Codable {
        let uploadID: String?
        let filename: String?

        enum CodingKeys: String, CodingKey {
            case uploadID = "upload_id"
            case filename
        }
    }

    enum CodingKeys: String, CodingKey {
        case status, payload
        case errorMessage = "error_message"
    }
}

/// §15.5: counts are derived on read, never stored, so they cannot disagree with the
/// sections they describe.
struct MaterialCollection: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let createdAt: String
    let sectionCount: Int
    let readyCount: Int
    let totalDurationMs: Int

    enum CodingKeys: String, CodingKey {
        case id, title
        case createdAt = "created_at"
        case sectionCount = "section_count"
        case readyCount = "ready_count"
        case totalDurationMs = "total_duration_ms"
    }
}

struct CollectionDetail: Codable {
    let collection: MaterialCollection
    let sections: [Material]
}
