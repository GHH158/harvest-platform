import Foundation
import SwiftUI

struct CompanionComposerState: Equatable {
    var draft: String
    private(set) var pendingQuestion: String?
    private(set) var isSending = false

    init(draft: String = "") {
        self.draft = draft
    }

    var canSend: Bool {
        !isSending && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    mutating func beginSending() -> String? {
        guard canSend else { return nil }
        let value = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        pendingQuestion = value
        draft = ""
        isSending = true
        return value
    }

    mutating func completeSending() {
        pendingQuestion = nil
        isSending = false
    }

    mutating func failSending() {
        if let pendingQuestion {
            draft = pendingQuestion
        }
        pendingQuestion = nil
        isSending = false
    }
}

enum MarkdownBlock: Equatable {
    case paragraph(String)
    case heading(level: Int, text: String)
    case unorderedItem(String)
    case orderedItem(number: String, text: String)
    case quote(String)
    case code(String)
    case divider
    case spacer
}

func markdownBlocks(from source: String) -> [MarkdownBlock] {
    let normalized = source.replacingOccurrences(of: "\r\n", with: "\n")
    let lines = normalized.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
    var blocks: [MarkdownBlock] = []
    var paragraphLines: [String] = []
    var codeLines: [String] = []
    var isInsideCodeFence = false

    func flushParagraph() {
        guard !paragraphLines.isEmpty else { return }
        blocks.append(.paragraph(paragraphLines.joined(separator: "\n")))
        paragraphLines.removeAll(keepingCapacity: true)
    }

    for line in lines {
        let trimmed = line.trimmingCharacters(in: .whitespaces)

        if isInsideCodeFence {
            if trimmed.hasPrefix("```") {
                blocks.append(.code(codeLines.joined(separator: "\n")))
                codeLines.removeAll(keepingCapacity: true)
                isInsideCodeFence = false
            } else {
                codeLines.append(line)
            }
            continue
        }

        if trimmed.hasPrefix("```") {
            flushParagraph()
            isInsideCodeFence = true
            continue
        }

        if trimmed.isEmpty {
            flushParagraph()
            if !blocks.isEmpty, blocks.last != .spacer {
                blocks.append(.spacer)
            }
            continue
        }

        if ["---", "***", "___"].contains(trimmed) {
            flushParagraph()
            blocks.append(.divider)
            continue
        }

        let hashCount = trimmed.prefix { $0 == "#" }.count
        let headingRemainder = trimmed.dropFirst(hashCount)
        if (1...6).contains(hashCount), headingRemainder.first?.isWhitespace == true {
            flushParagraph()
            blocks.append(.heading(
                level: hashCount,
                text: String(headingRemainder.drop { $0.isWhitespace })
            ))
            continue
        }

        if let prefix = ["- ", "* ", "+ "].first(where: { trimmed.hasPrefix($0) }) {
            flushParagraph()
            blocks.append(.unorderedItem(String(trimmed.dropFirst(prefix.count))))
            continue
        }

        if let item = orderedListItem(from: trimmed) {
            flushParagraph()
            blocks.append(.orderedItem(number: item.number, text: item.text))
            continue
        }

        if trimmed.hasPrefix(">") {
            flushParagraph()
            let quote = trimmed.dropFirst().drop { $0.isWhitespace }
            blocks.append(.quote(String(quote)))
            continue
        }

        paragraphLines.append(line)
    }

    if isInsideCodeFence {
        blocks.append(.code(codeLines.joined(separator: "\n")))
    }
    flushParagraph()

    while blocks.first == .spacer { blocks.removeFirst() }
    while blocks.last == .spacer { blocks.removeLast() }
    return blocks
}

func inlineMarkdown(_ source: String) -> AttributedString {
    let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
    return (try? AttributedString(markdown: source, options: options)) ?? AttributedString(source)
}

func containsInlineMarkdownSyntax(_ source: String) -> Bool {
    if ["**", "__", "`", "~~"].contains(where: source.contains) { return true }
    if source.range(of: #"\[[^\]]+\]\([^)]+\)"#, options: .regularExpression) != nil { return true }
    if source.range(of: #"(^|[^*])\*[^*\n]+\*"#, options: .regularExpression) != nil { return true }
    return source.range(of: #"(^|[^_])_[^_\n]+_"#, options: .regularExpression) != nil
}

private func orderedListItem(from line: String) -> (number: String, text: String)? {
    let number = line.prefix { $0.isNumber }
    guard !number.isEmpty else { return nil }
    let remainder = line.dropFirst(number.count)
    guard let marker = remainder.first, marker == "." || marker == ")" else { return nil }
    let itemText = remainder.dropFirst()
    guard itemText.first?.isWhitespace == true else { return nil }
    return (String(number), String(itemText.drop { $0.isWhitespace }))
}

private func isKanaScalar(_ value: UInt32) -> Bool {
    (value >= 0x3040 && value <= 0x309F) || (value >= 0x30A0 && value <= 0x30FF)
}

/// Split text into runs of CJK/kana vs everything else. A run is annotatable only
/// when it contains kana (unambiguously Japanese); pure-kanji runs are left alone
/// so Chinese text is never mis-annotated with Japanese readings.
private func furiganaRuns(in text: String) -> [(text: String, annotate: Bool)] {
    var runs: [(String, Bool)] = []
    var current = ""
    var currentIsCJK = false
    var currentHasKana = false
    func flush() {
        if !current.isEmpty {
            runs.append((current, currentIsCJK && currentHasKana))
            current = ""
            currentIsCJK = false
            currentHasKana = false
        }
    }
    for scalar in text.unicodeScalars {
        let isCJK = (scalar.value >= 0x3040 && scalar.value <= 0x30FF)
            || (scalar.value >= 0x4E00 && scalar.value <= 0x9FFF)
        if !current.isEmpty && isCJK != currentIsCJK { flush() }
        current.unicodeScalars.append(scalar)
        currentIsCJK = isCJK
        if isKanaScalar(scalar.value) { currentHasKana = true }
    }
    flush()
    return runs
}

struct CompanionView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    let materialID: Int
    let segment: Segment
    let focusText: String?
    @State private var messages: [ConversationMessage] = []
    @State private var composer: CompanionComposerState
    @State private var errorMessage: String?
    @State private var furiganaCache: [String: [FuriganaSegment]] = [:]
    @FocusState private var isInputFocused: Bool
    @AppStorage("showFurigana") private var showFurigana = false

    init(materialID: Int, segment: Segment, focusText: String? = nil) {
        self.materialID = materialID
        self.segment = segment
        self.focusText = focusText
        let initialDraft = focusText.map { "请解释「\($0)」在这句话里的意思和用法。" } ?? ""
        _composer = State(initialValue: CompanionComposerState(draft: initialDraft))
    }

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    var body: some View {
        VStack(spacing: 14) {
            contextHeader
            conversation
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            composerBar
        }
        .padding(DesignTokens.pageInset)
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("陪读")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showFurigana.toggle()
                    if showFurigana, let client {
                        Task { await prefetchFurigana(using: client) }
                    }
                } label: {
                    Image(systemName: showFurigana ? "character.book.closed.fill" : "character.book.closed")
                        .foregroundStyle(DesignTokens.ink)
                }
                .accessibilityLabel(showFurigana ? "隐藏假名" : "显示假名")
            }
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("完成") { isInputFocused = false }
            }
        }
        .task { await load() }
        .onChange(of: showFurigana) { _, enabled in
            if enabled, let client { Task { await prefetchFurigana(using: client) } }
        }
        .onChange(of: messages.count) {
            if showFurigana, let client { Task { await prefetchFurigana(using: client) } }
        }
    }

    private var contextHeader: some View {
        VStack(alignment: .leading, spacing: 8) {
            if showFurigana, let segments = furiganaCache[segment.textJA] {
                FuriganaText(segments: segments, fontSize: 19)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text(segment.textJA)
                    .font(.system(.title3, design: .serif))
                    .foregroundStyle(DesignTokens.ink)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let focusText {
                Text("正在问：\(focusText)")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DesignTokens.accent)
            }
        }
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(messages) { message in
                        CompanionMessageBubble(
                            role: message.role,
                            content: message.content,
                            showFurigana: showFurigana,
                            furiganaCache: furiganaCache
                        )
                        .id("message-\(message.id)")
                    }
                    if let pendingQuestion = composer.pendingQuestion {
                        CompanionMessageBubble(role: "user", content: pendingQuestion)
                            .id("pending-question")
                        HStack(spacing: 9) {
                            ProgressView()
                                .controlSize(.small)
                                .tint(DesignTokens.accent)
                            Text("老师正在整理…")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                        .id("pending-answer")
                        .accessibilityIdentifier("companion-pending-answer")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollDismissesKeyboard(.interactively)
            .contentShape(Rectangle())
            .onTapGesture { isInputFocused = false }
            .onChange(of: composer.pendingQuestion) { _, pendingQuestion in
                guard pendingQuestion != nil else { return }
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo("pending-answer", anchor: .bottom)
                }
            }
            .onChange(of: messages.last?.id) { _, messageID in
                guard let messageID else { return }
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo("message-\(messageID)", anchor: .bottom)
                }
            }
        }
    }

    private var composerBar: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("这句哪里不明白？", text: $composer.draft, axis: .vertical)
                .lineLimit(1...5)
                .focused($isInputFocused)
                .submitLabel(.send)
                .onSubmit { submit() }
                .padding(12)
                .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
            Button("提问") { submit() }
                .disabled(!composer.canSend)
                .foregroundStyle(DesignTokens.accent)
                .padding(.vertical, 12)
        }
    }

    private func submit() {
        guard composer.canSend else { return }
        Task { await send() }
    }

    @MainActor private func load() async {
        guard let endpoint = configuration.endpoint else {
            errorMessage = "请先在设置中填写服务地址。"
            return
        }
        do {
            messages = try await APIClient(baseURL: endpoint).companion(materialID: materialID)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor private func send() async {
        guard let value = composer.beginSending() else { return }
        isInputFocused = false
        errorMessage = nil
        guard let endpoint = configuration.endpoint else {
            composer.failSending()
            errorMessage = "请先在设置中填写服务地址。"
            return
        }

        do {
            let reply = try await APIClient(baseURL: endpoint).sendCompanion(
                materialID: materialID,
                segmentID: segment.id,
                question: value
            )
            messages += [reply.user, reply.assistant]
            composer.completeSending()
        } catch {
            composer.failSending()
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func prefetchFurigana(using client: APIClient) async {
        await ensureFurigana(for: segment.textJA, using: client)
        for message in messages where message.role == "assistant" {
            for block in markdownBlocks(from: message.content) {
                switch block {
                case .paragraph(let text), .heading(_, let text), .unorderedItem(let text),
                     .orderedItem(_, let text), .quote(let text):
                    for run in furiganaRuns(in: text) where run.annotate {
                        await ensureFurigana(for: run.text, using: client)
                    }
                case .code, .divider, .spacer:
                    break
                }
            }
        }
    }

    @MainActor
    private func ensureFurigana(for text: String, using client: APIClient) async {
        guard !text.isEmpty, furiganaCache[text] == nil else { return }
        do {
            let segments = try await client.furigana(text: text)
            // @State does not invalidate on in-place subscript mutation.
            var updated = furiganaCache
            updated[text] = segments
            furiganaCache = updated
        } catch {
            // Keep the message readable without ruby if the fetch fails.
        }
    }
}

private struct CompanionMessageBubble: View {
    let role: String
    let content: String
    var showFurigana = false
    var furiganaCache: [String: [FuriganaSegment]] = [:]

    private var isUser: Bool { role == "user" }

    var body: some View {
        Group {
            if isUser {
                Text(content)
                    .foregroundStyle(DesignTokens.ink)
            } else {
                MarkdownMessageView(
                    markdown: content,
                    showFurigana: showFurigana,
                    furiganaCache: furiganaCache
                )
            }
        }
        .padding(12)
        .background(isUser ? DesignTokens.accentWash : DesignTokens.surface,
                    in: RoundedRectangle(cornerRadius: 12))
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}

private struct MarkdownMessageView: View {
    let markdown: String
    var showFurigana = false
    var furiganaCache: [String: [FuriganaSegment]] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(markdownBlocks(from: markdown).enumerated()), id: \.offset) { _, block in
                blockView(block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .foregroundStyle(DesignTokens.ink)
        .tint(DesignTokens.accent)
    }

    @ViewBuilder
    private func blockView(_ block: MarkdownBlock) -> some View {
        switch block {
        case .paragraph(let text):
            renderText(text)
        case .heading(let level, let text):
            renderText(text)
                .font(headingFont(level: level))
                .padding(.top, level == 1 ? 3 : 0)
        case .unorderedItem(let text):
            listRow(label: "•", text: text)
        case .orderedItem(let number, let text):
            listRow(label: "\(number).", text: text)
        case .quote(let text):
            HStack(alignment: .top, spacing: 9) {
                RoundedRectangle(cornerRadius: 2)
                    .fill(DesignTokens.accent.opacity(0.55))
                    .frame(width: 3)
                renderText(text)
            }
            .fixedSize(horizontal: false, vertical: true)
        case .code(let text):
            ScrollView(.horizontal, showsIndicators: false) {
                Text(text)
                    .font(.system(.footnote, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(10)
            }
            .background(DesignTokens.canvas, in: RoundedRectangle(cornerRadius: 8))
        case .divider:
            Divider().overlay(DesignTokens.separator)
        case .spacer:
            Color.clear.frame(height: 2)
        }
    }

    @ViewBuilder
    private func renderText(_ text: String) -> some View {
        if showFurigana && !containsInlineMarkdownSyntax(text) {
            let runs = furiganaRuns(in: text)
            if runs.contains(where: { $0.annotate }) {
                FlowLayout(spacing: 2) {
                    ForEach(Array(runs.enumerated()), id: \.offset) { _, run in
                        if run.annotate, let segments = furiganaCache[run.text] {
                            ForEach(segments, id: \.self) { segment in
                                RubyUnit(text: segment.surface, reading: segment.reading)
                            }
                        } else {
                            RubyUnit(text: run.text, reading: nil)
                        }
                    }
                }
            } else {
                Text(inlineMarkdown(text))
            }
        } else {
            Text(inlineMarkdown(text))
        }
    }

    private func listRow(label: String, text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .foregroundStyle(DesignTokens.accent)
                .frame(minWidth: 14, alignment: .trailing)
            renderText(text)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func headingFont(level: Int) -> Font {
        switch level {
        case 1: .system(.title3, design: .serif, weight: .semibold)
        case 2: .system(.headline, design: .serif, weight: .semibold)
        default: .system(.subheadline, design: .serif, weight: .semibold)
        }
    }
}
