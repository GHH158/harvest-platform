import SwiftUI

struct ChatTopicDeck {
    private var remaining: [ChatTopic] = []
    private var previousBatchIDs: Set<String> = []
    private var universeIDs: Set<String> = []

    mutating func nextBatch(from topics: [ChatTopic]) -> [ChatTopic] {
        let currentIDs = Set(topics.map(\.id))
        if currentIDs != universeIDs {
            remaining = []
            previousBatchIDs = []
            universeIDs = currentIDs
        }
        if remaining.isEmpty {
            let shuffled = topics.shuffled()
            let notRecentlyShown = shuffled.filter { !previousBatchIDs.contains($0.id) }
            let recentlyShown = shuffled.filter { previousBatchIDs.contains($0.id) }
            remaining = notRecentlyShown + recentlyShown
        }
        let count = min(4, remaining.count)
        let batch = Array(remaining.prefix(count))
        remaining.removeFirst(count)
        previousBatchIDs = Set(batch.map(\.id))
        return batch
    }
}

enum ChatTranscriptRow: Identifiable, Hashable {
    case message(ConversationMessage)
    case correction(ChatCorrection)

    var id: String {
        switch self {
        case .message(let message): "message-\(message.id)"
        case .correction(let correction): "correction-\(correction.id)"
        }
    }
}

func chatTranscriptRows(
    messages: [ConversationMessage],
    corrections: [ChatCorrection]
) -> [ChatTranscriptRow] {
    let byMessageID = Dictionary(uniqueKeysWithValues: corrections.map { ($0.userMessageID, $0) })
    return messages.flatMap { message in
        var rows: [ChatTranscriptRow] = [.message(message)]
        if message.role == "user", let correction = byMessageID[message.id] {
            rows.append(.correction(correction))
        }
        return rows
    }
}

@MainActor
final class ChatStore: ObservableObject {
    @Published private(set) var topics: [ChatTopic] = []
    @Published private(set) var displayedTopics: [ChatTopic] = []
    @Published private(set) var activeSession: ChatSession?
    @Published private(set) var messages: [ConversationMessage] = []
    @Published private(set) var corrections: [ChatCorrection] = []
    @Published private(set) var pendingUserMessage: ConversationMessage?
    @Published var draft = ""
    @Published var errorMessage: String?
    @Published private(set) var isLoading = false
    @Published private(set) var isSending = false
    /// Text-keyed ruby cache shared with Markdown rendering (same as companion).
    @Published private(set) var furiganaCache: [String: [FuriganaSegment]] = [:]
    private var topicDeck = ChatTopicDeck()

    var transcriptRows: [ChatTranscriptRow] {
        let visibleMessages = pendingUserMessage.map { messages + [$0] } ?? messages
        return chatTranscriptRows(messages: visibleMessages, corrections: corrections)
    }

    func loadTopics(using client: APIClient) async {
        guard topics.isEmpty else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            topics = try await client.chatTopics()
            displayedTopics = topicDeck.nextBatch(from: topics)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func showNextTopics() {
        displayedTopics = topicDeck.nextBatch(from: topics)
    }

    func start(topic: ChatTopic, using client: APIClient) async {
        await createSession(starterID: topic.id, customTopic: nil, using: client)
    }

    func startCustomTopic(using client: APIClient) async {
        let topic = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !topic.isEmpty else { return }
        await createSession(starterID: nil, customTopic: topic, using: client)
    }

    func openSession(id: String, using client: APIClient) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let detail = try await client.chatSession(id: id)
            activeSession = detail.session
            messages = detail.messages
            corrections = detail.corrections
            pendingUserMessage = nil
            draft = ""
            errorMessage = nil
            await loadMaterialQuestions(using: client)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// §16: the checklist shown alongside a material-linked session, so archiving can
    /// happen right where the discussion is — not as a separate trip back to the list.
    @Published private(set) var materialQuestions: [ReadingQuestion] = []

    private func loadMaterialQuestions(using client: APIClient) async {
        guard let materialID = activeSession?.materialID else {
            materialQuestions = []
            return
        }
        materialQuestions = (try? await client.readingQuestions(materialID: materialID, status: "pending")) ?? []
    }

    /// The archive decision is the learner's, made explicitly here — never inferred from
    /// what the model said (§16).
    func archiveMaterialQuestion(_ question: ReadingQuestion, using client: APIClient) async {
        do {
            _ = try await client.setReadingQuestionArchived(id: question.id, archived: true)
            materialQuestions.removeAll { $0.id == question.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func send(using client: APIClient) async {
        guard let activeSession, !isSending else { return }
        let message = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else { return }
        pendingUserMessage = ConversationMessage(
            id: Int.min,
            sessionID: activeSession.id,
            role: "user",
            content: message,
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        draft = ""
        isSending = true
        defer { isSending = false }
        do {
            let turn = try await client.sendChatMessage(sessionID: activeSession.id, message: message)
            pendingUserMessage = nil
            messages.append(turn.user)
            if let correction = turn.correction { corrections.append(correction) }
            messages.append(turn.assistant)
            errorMessage = nil
        } catch {
            pendingUserMessage = nil
            // Restore the failed text without erasing anything typed while waiting.
            draft = draft.isEmpty ? message : "\(message)\n\(draft)"
            errorMessage = error.localizedDescription
        }
    }

    func beginNewTopic() {
        activeSession = nil
        messages = []
        corrections = []
        pendingUserMessage = nil
        draft = ""
        errorMessage = nil
        materialQuestions = []
        if displayedTopics.isEmpty { showNextTopics() }
    }

    func removeCorrection(id: Int) {
        corrections.removeAll { $0.id == id }
    }

    func ensureFurigana(for text: String, using client: APIClient) async {
        guard !text.isEmpty, furiganaCache[text] == nil else { return }
        do {
            let segments = try await client.furigana(text: text)
            // @Published does not fire on in-place subscript mutation; reassign the
            // whole dictionary so the transcript re-renders with ruby.
            var updated = furiganaCache
            updated[text] = segments
            furiganaCache = updated
        } catch {
            // Keep the message readable without ruby if the fetch fails.
        }
    }

    func prefetchFurigana(using client: APIClient) async {
        // Bounded for the same reason as the companion sheet: one sequential request
        // per Japanese run, so a long session made turning ruby on feel like a hang.
        for message in messages.suffix(6) where message.role == "assistant" {
            for block in markdownBlocks(from: message.content) {
                switch block {
                case .paragraph(let text), .heading(_, let text), .unorderedItem(let text),
                     .orderedItem(_, let text), .quote(let text):
                    for run in furiganaRuns(in: text) where run.annotate {
                        await ensureFurigana(for: run.text, using: client)
                    }
                case .code, .table, .divider, .spacer:
                    break
                }
            }
        }
    }

    private func createSession(
        starterID: String?,
        customTopic: String?,
        using client: APIClient
    ) async {
        isSending = true
        defer { isSending = false }
        do {
            let creation = try await client.createChatSession(starterID: starterID, topic: customTopic)
            activeSession = creation.session
            messages = [creation.assistant]
            corrections = []
            pendingUserMessage = nil
            draft = ""
            errorMessage = nil
            materialQuestions = []
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// §16: "去问老师" — a session pre-loaded with this lesson's flagged questions,
    /// same shape as `createSession` above but there is no topic to pick.
    func startFromMaterial(materialID: Int, using client: APIClient) async {
        isSending = true
        defer { isSending = false }
        do {
            let creation = try await client.createChatSession(materialID: materialID)
            activeSession = creation.session
            messages = [creation.assistant]
            corrections = []
            pendingUserMessage = nil
            draft = ""
            errorMessage = nil
            await loadMaterialQuestions(using: client)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct ChatView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @StateObject private var store = ChatStore()
    @State private var showingHistory = false
    @State private var showingCorrections = false
    @State private var showManualLookup = false
    @State private var lookupWord: LookupWord?
    @FocusState private var isInputFocused: Bool
    @AppStorage("showFurigana") private var showFurigana = false
    /// Avoid loading chat topics until the user opens this tab (TabView would otherwise fire on cold start).
    var isActive: Bool = true
    /// §16: "去问老师" arrives here wanting a session pre-loaded with one lesson's
    /// flagged questions, not the topic picker. Consumed once, in `.task` below —
    /// re-entering this same `ChatView` instance later (e.g. after `beginNewTopic()`)
    /// must not keep recreating it.
    var initialMaterialID: Int? = nil
    @State private var hasStartedFromMaterial = false

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    var body: some View {
        VStack(spacing: 0) {
            if store.activeSession == nil {
                topicHome
            } else {
                if !store.materialQuestions.isEmpty {
                    materialQuestionsPanel
                }
                conversation
            }
            if let errorMessage = store.errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, DesignTokens.pageInset)
                    .padding(.top, 8)
            }
            composer
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(store.activeSession?.topic ?? "聊天老师")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            secondaryActions
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("完成") { isInputFocused = false }
            }
        }
        .task(id: "\(configuration.endpoint?.absoluteString ?? "")-\(isActive)") {
            guard isActive, let client else { return }
            if let initialMaterialID, !hasStartedFromMaterial {
                hasStartedFromMaterial = true
                await store.startFromMaterial(materialID: initialMaterialID, using: client)
                return
            }
            await store.loadTopics(using: client)
        }
        .sheet(isPresented: $showingHistory) {
            NavigationStack {
                if let client {
                    ChatHistoryView(
                        client: client,
                        onSelect: { sessionID in
                            isInputFocused = false
                            Task { await store.openSession(id: sessionID, using: client) }
                        },
                        onDelete: { sessionID in
                            if store.activeSession?.id == sessionID { store.beginNewTopic() }
                        }
                    )
                }
            }
        }
        .sheet(isPresented: $showingCorrections) {
            NavigationStack {
                if let client {
                    CorrectionLibraryView(client: client) { correctionID in
                        store.removeCorrection(id: correctionID)
                    }
                }
            }
        }
        .sheet(isPresented: $showManualLookup) {
            WordPickSheet { word in
                showManualLookup = false
                DispatchQueue.main.async {
                    lookupWord = LookupWord(word: word, context: nil)
                }
            }
        }
        .sheet(item: $lookupWord) { item in
            WordLookupSheet(word: item.word, context: item.context)
                .environmentObject(configuration)
        }
        .onChange(of: lookupWord?.id) { _, _ in
            if lookupWord != nil { isInputFocused = false }
        }
    }

    /// Copy a word from the message, then tap 查词. Uses clipboard first.
    private func lookupFromClipboard() {
        isInputFocused = false
        // Prefer the current selection range if the system put it on the pasteboard.
        if let query = clipboardLookupQuery() {
            lookupWord = LookupWord(word: query, context: nil)
            return
        }
        showManualLookup = true
    }

    private var topicHome: some View {
        ScrollView {
            VStack(spacing: 26) {
                VStack(spacing: 8) {
                    Text("今日は何を話しましょう？")
                        .font(.system(.title2, design: .serif, weight: .semibold))
                        .foregroundStyle(DesignTokens.ink)
                    Text("选一个主题，或者直接写下任何想聊的事")
                        .font(.subheadline)
                        .foregroundStyle(DesignTokens.muted)
                }
                .padding(.top, 54)

                if store.isLoading && store.displayedTopics.isEmpty {
                    ProgressView("正在准备主题")
                        .tint(DesignTokens.accent)
                        .foregroundStyle(DesignTokens.muted)
                        .frame(maxWidth: .infinity, minHeight: 240)
                } else {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                        ForEach(store.displayedTopics) { topic in
                            Button {
                                guard let client else { return }
                                isInputFocused = false
                                Task { await store.start(topic: topic, using: client) }
                            } label: {
                                TopicCard(topic: topic)
                            }
                            .buttonStyle(.plain)
                            .disabled(store.isSending)
                        }
                    }
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) { store.showNextTopics() }
                    } label: {
                        Label("换一批", systemImage: "arrow.triangle.2.circlepath")
                            .font(.subheadline.weight(.medium))
                    }
                    .foregroundStyle(DesignTokens.accent)
                    .disabled(store.isSending || store.topics.isEmpty)
                }
            }
            .padding(.horizontal, DesignTokens.pageInset)
            .padding(.bottom, 30)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
    }

    /// §16: checked off right where the discussion happens, not as a separate trip back
    /// to the material's question list. Checking a box is the learner's own judgement
    /// call, made explicitly — never inferred from what the model just said.
    private var materialQuestionsPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(store.materialQuestions) { question in
                HStack(alignment: .top, spacing: 8) {
                    Button {
                        guard let client else { return }
                        Task { await store.archiveMaterialQuestion(question, using: client) }
                    } label: {
                        Image(systemName: "circle")
                            .foregroundStyle(DesignTokens.muted)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("标记「\(question.excerpt)」已经懂了")

                    VStack(alignment: .leading, spacing: 2) {
                        Text(question.excerpt)
                            .font(.subheadline)
                            .foregroundStyle(DesignTokens.ink)
                        if let note = question.note, !note.isEmpty {
                            Text(note)
                                .font(.caption)
                                .foregroundStyle(DesignTokens.muted)
                        }
                    }
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.vertical, 10)
        .background(DesignTokens.surface)
        .overlay(alignment: .bottom) {
            Divider().overlay(DesignTokens.separator)
        }
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(store.transcriptRows) { row in
                        transcriptRow(row)
                    }
                    if store.isSending {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small).tint(DesignTokens.accent)
                            Text("老师正在想…")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                        }
                        .id("thinking")
                    }
                }
                .padding(DesignTokens.pageInset)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // Do not add a full-area onTapGesture here — it blocks text selection/copy.
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: store.messages.count) {
                guard let last = store.transcriptRows.last else { return }
                withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                if showFurigana, let client {
                    Task { await store.prefetchFurigana(using: client) }
                }
            }
            .onChange(of: store.isSending) {
                if store.isSending { withAnimation { proxy.scrollTo("thinking", anchor: .bottom) } }
            }
        }
    }

    @ViewBuilder
    private func transcriptRow(_ row: ChatTranscriptRow) -> some View {
        switch row {
        case .message(let message):
            MessageBubble(
                message: message,
                showFurigana: showFurigana,
                furiganaCache: store.furiganaCache,
                onWordTap: { word in
                    isInputFocused = false
                    lookupWord = LookupWord(word: word, context: message.content)
                }
            )
        case .correction(let correction):
            CorrectionCard(correction: correction, showsTopic: false)
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(
                store.activeSession == nil ? "输入任意中文或日语主题" : "用日语聊下去",
                text: $store.draft,
                axis: .vertical
            )
            .lineLimit(1...5)
            .focused($isInputFocused)
            .padding(.horizontal, 14)
            .padding(.vertical, 11)
            .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 15))
            .overlay {
                RoundedRectangle(cornerRadius: 15)
                    .stroke(DesignTokens.separator, lineWidth: 0.5)
            }
            .submitLabel(.send)
            .onSubmit { submit() }

            Button(action: submit) {
                Image(systemName: "arrow.up")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(DesignTokens.accent, in: Circle())
            }
            .disabled(
                store.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    || store.isSending
            )
            .opacity(store.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.45 : 1)
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
    }

    @ToolbarContentBuilder
    private var secondaryActions: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                lookupFromClipboard()
            } label: {
                Image(systemName: "character.book.closed")
                    .foregroundStyle(DesignTokens.ink)
            }
            .accessibilityLabel("查词")
        }
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Button {
                    showFurigana.toggle()
                    if showFurigana, let client {
                        Task { await store.prefetchFurigana(using: client) }
                    }
                } label: {
                    Label("显示假名", systemImage: showFurigana ? "checkmark.circle.fill" : "circle")
                }
                Button {
                    lookupFromClipboard()
                } label: {
                    Label("查词组或剪贴板", systemImage: "doc.on.clipboard")
                }
                if store.activeSession != nil {
                    Button {
                        store.beginNewTopic()
                    } label: {
                        Label("新主题", systemImage: "plus.bubble")
                    }
                }
                Button { showingHistory = true } label: {
                    Label("历史", systemImage: "clock")
                }
                Button { showingCorrections = true } label: {
                    Label("纠错库", systemImage: "text.badge.checkmark")
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .foregroundStyle(DesignTokens.ink)
            }
        }
    }

    private func submit() {
        guard let client else { return }
        isInputFocused = false
        Task {
            if store.activeSession == nil {
                await store.startCustomTopic(using: client)
            } else {
                await store.send(using: client)
            }
        }
    }
}

private struct TopicCard: View {
    let topic: ChatTopic

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(topic.category)
                .font(.caption.weight(.semibold))
                .foregroundStyle(DesignTokens.accent)
            Text(topic.titleJA)
                .font(.system(.headline, design: .serif))
                .foregroundStyle(DesignTokens.ink)
                .lineLimit(3)
            Spacer(minLength: 0)
            Text(topic.hintZH)
                .font(.caption)
                .foregroundStyle(DesignTokens.muted)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, minHeight: 126, alignment: .topLeading)
        .padding(16)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: DesignTokens.cardRadius))
        .overlay {
            RoundedRectangle(cornerRadius: DesignTokens.cardRadius)
                .stroke(DesignTokens.separator, lineWidth: 0.5)
        }
    }
}

private struct MessageBubble: View {
    let message: ConversationMessage
    var showFurigana = false
    var furiganaCache: [String: [FuriganaSegment]] = [:]
    var onWordTap: ((String) -> Void)?

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        // Tap a word to look it up directly; long-press still selects/copies for phrases.
        SelectableText(
            text: message.content,
            font: .preferredFont(forTextStyle: .body),
            // Japanese has no word spaces, so lines need more air than Latin before a
            // reply reads as separate sentences rather than one block.
            textColor: isUser ? .white : UIColor(DesignTokens.ink),
            lineSpacing: 8,
            onWordTap: onWordTap
        )
        .padding(.horizontal, 15)
        .padding(.vertical, 13)
        .background(
            isUser ? DesignTokens.accent : DesignTokens.surface,
            in: RoundedRectangle(cornerRadius: 16)
        )
        .overlay {
            if !isUser {
                RoundedRectangle(cornerRadius: 16)
                    .stroke(DesignTokens.separator, lineWidth: 0.5)
            }
        }
        .frame(
            maxWidth: UIScreen.main.bounds.width * (isUser ? 0.78 : 0.88),
            alignment: isUser ? .trailing : .leading
        )
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
        .contextMenu {
            Button {
                UIPasteboard.general.string = message.content
            } label: {
                Label("复制全文", systemImage: "doc.on.doc")
            }
        }
    }
}

private struct CorrectionCard: View {
    let correction: ChatCorrection
    let showsTopic: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                Label("表达调整", systemImage: "pencil.and.outline")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(DesignTokens.accent)
                Spacer()
                if showsTopic, let topic = correction.topic {
                    Text(topic)
                        .font(.caption)
                        .foregroundStyle(DesignTokens.muted)
                        .lineLimit(1)
                }
            }
            correctionText(label: "原句", text: correction.originalText, muted: true)
            correctionText(label: "更自然", text: correction.correctedText, muted: false)
            Text(correction.summaryZH)
                .font(.subheadline)
                .foregroundStyle(DesignTokens.ink)
            ForEach(correction.items.prefix(3)) { item in
                VStack(alignment: .leading, spacing: 5) {
                    Text("\(item.original) → \(item.replacement)")
                        .font(.system(.subheadline, design: .serif).weight(.medium))
                        .foregroundStyle(DesignTokens.ink)
                    // §5.6: only present when the fix also moved the register. Body-sized
                    // like the reason, because it is the same kind of thing — something you
                    // actually need to read — not metadata.
                    if let alternative = item.sameRegisterReplacement, !alternative.isEmpty {
                        Text("保持你原来的语体：\(alternative)")
                            .font(.system(.subheadline, design: .serif))
                            .foregroundStyle(DesignTokens.ink.opacity(0.85))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    // The reason is the part actually worth reading, so it was the
                    // wrong thing to set in the smallest, lightest type on the screen.
                    // The category stays small; the explanation reads as body text.
                    Text(item.category.label)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(DesignTokens.accent.opacity(0.85))
                    Text(item.reasonZH)
                        .font(.subheadline)
                        .foregroundStyle(DesignTokens.ink.opacity(0.85))
                        .lineSpacing(5)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(16)
        .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: DesignTokens.cardRadius))
        .overlay {
            RoundedRectangle(cornerRadius: DesignTokens.cardRadius)
                .stroke(DesignTokens.accent.opacity(0.22), lineWidth: 0.5)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func correctionText(label: String, text: String, muted: Bool) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(DesignTokens.muted)
            Text(text)
                .font(.system(.body, design: .serif))
                .foregroundStyle(muted ? DesignTokens.muted : DesignTokens.ink)
        }
    }
}

private struct ChatHistoryView: View {
    @Environment(\.dismiss) private var dismiss
    let client: APIClient
    let onSelect: (String) -> Void
    let onDelete: (String) -> Void
    @State private var sessions: [ChatSession] = []
    @State private var errorMessage: String?
    @State private var isLoading = true

    var body: some View {
        Group {
            if isLoading && sessions.isEmpty {
                ProgressView("读取会话历史")
            } else if sessions.isEmpty {
                ContentUnavailableView("还没有聊天历史", systemImage: "bubble.left")
            } else {
                List {
                    ForEach(sessions) { session in
                        Button {
                            onSelect(session.id)
                            dismiss()
                        } label: {
                            VStack(alignment: .leading, spacing: 7) {
                                Text(session.topic)
                                    .font(.system(.headline, design: .serif))
                                    .foregroundStyle(DesignTokens.ink)
                                if let preview = session.lastMessagePreview {
                                    Text(preview)
                                        .font(.subheadline)
                                        .foregroundStyle(DesignTokens.muted)
                                        .lineLimit(2)
                                }
                            }
                            .padding(.vertical, 8)
                        }
                        .listRowBackground(DesignTokens.surface)
                        .swipeActions {
                            Button(role: .destructive) {
                                Task { await delete(session) }
                            } label: {
                                Label("删除", systemImage: "trash")
                            }
                        }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .background(DesignTokens.canvas)
        .navigationTitle("聊天历史")
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("完成") { dismiss() }
            }
        }
        .safeAreaInset(edge: .bottom) {
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .padding()
            }
        }
        .task { await load() }
    }

    @MainActor
    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            sessions = try await client.chatSessions()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func delete(_ session: ChatSession) async {
        do {
            try await client.deleteChatSession(id: session.id)
            sessions.removeAll { $0.id == session.id }
            onDelete(session.id)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct CorrectionLibraryView: View {
    @Environment(\.dismiss) private var dismiss
    let client: APIClient
    let onDelete: (Int) -> Void
    @State private var corrections: [ChatCorrection] = []
    @State private var sessions: [ChatSession] = []
    @State private var query = ""
    @State private var selectedTopic = ""
    @State private var selectedCategory: ChatCorrectionCategory?
    @State private var errorMessage: String?
    @State private var isLoading = true

    private var topics: [String] {
        Array(Set(sessions.map(\.topic))).sorted()
    }

    var body: some View {
        Group {
            if isLoading && corrections.isEmpty {
                ProgressView("读取纠错库")
            } else if corrections.isEmpty {
                ContentUnavailableView(
                    query.isEmpty && selectedTopic.isEmpty && selectedCategory == nil ? "还没有纠错记录" : "没有符合筛选的记录",
                    systemImage: "text.badge.checkmark"
                )
            } else {
                List {
                    ForEach(corrections) { correction in
                        CorrectionCard(correction: correction, showsTopic: true)
                            .listRowInsets(EdgeInsets(top: 7, leading: 18, bottom: 7, trailing: 18))
                            .listRowBackground(DesignTokens.canvas)
                            .listRowSeparator(.hidden)
                            .swipeActions {
                                Button(role: .destructive) {
                                    Task { await delete(correction) }
                                } label: {
                                    Label("删除纠错", systemImage: "trash")
                                }
                            }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .background(DesignTokens.canvas)
        .navigationTitle("纠错库")
        .searchable(text: $query, prompt: "搜索原句、修正版或说明")
        .onSubmit(of: .search) { Task { await loadCorrections() } }
        .onChange(of: selectedTopic) { Task { await loadCorrections() } }
        .onChange(of: selectedCategory) { Task { await loadCorrections() } }
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("完成") { dismiss() }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Section("主题") {
                        Button("全部主题") { selectedTopic = "" }
                        ForEach(topics, id: \.self) { topic in
                            Button(topic) { selectedTopic = topic }
                        }
                    }
                    Section("类别") {
                        Button("全部类别") { selectedCategory = nil }
                        ForEach(ChatCorrectionCategory.allCases) { category in
                            Button(category.label) { selectedCategory = category }
                        }
                    }
                } label: {
                    Label("筛选", systemImage: "line.3.horizontal.decrease.circle")
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .padding()
            }
        }
        .task {
            async let loadedSessions = client.chatSessions()
            async let loadedCorrections = client.chatCorrections()
            do {
                sessions = try await loadedSessions
                corrections = try await loadedCorrections
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
            isLoading = false
        }
    }

    @MainActor
    private func loadCorrections() async {
        isLoading = true
        defer { isLoading = false }
        do {
            corrections = try await client.chatCorrections(
                query: query.trimmingCharacters(in: .whitespacesAndNewlines),
                topic: selectedTopic.isEmpty ? nil : selectedTopic,
                category: selectedCategory
            )
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func delete(_ correction: ChatCorrection) async {
        do {
            try await client.deleteChatCorrection(id: correction.id)
            corrections.removeAll { $0.id == correction.id }
            onDelete(correction.id)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
