import Foundation
import NaturalLanguage
import SwiftUI
import UIKit

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
    var quoteLines: [String] = []
    var isInsideCodeFence = false

    func flushParagraph() {
        guard !paragraphLines.isEmpty else { return }
        // Soft-wrap single newlines into one readable paragraph for Chinese prose.
        let text = paragraphLines
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        blocks.append(.paragraph(text))
        paragraphLines.removeAll(keepingCapacity: true)
    }

    func flushQuote() {
        guard !quoteLines.isEmpty else { return }
        blocks.append(.quote(quoteLines.joined(separator: "\n")))
        quoteLines.removeAll(keepingCapacity: true)
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
            flushQuote()
            isInsideCodeFence = true
            continue
        }

        if trimmed.isEmpty {
            flushParagraph()
            flushQuote()
            // Keep list groups tight: blank lines between list items should not
            // open a large section gap.
            if let last = blocks.last, !isListBlock(last), last != .spacer {
                blocks.append(.spacer)
            }
            continue
        }

        if ["---", "***", "___"].contains(trimmed) {
            flushParagraph()
            flushQuote()
            blocks.append(.divider)
            continue
        }

        let hashCount = trimmed.prefix { $0 == "#" }.count
        let headingRemainder = trimmed.dropFirst(hashCount)
        if (1...6).contains(hashCount), headingRemainder.first?.isWhitespace == true {
            flushParagraph()
            flushQuote()
            blocks.append(.heading(
                level: hashCount,
                text: String(headingRemainder.drop { $0.isWhitespace })
            ))
            continue
        }

        if let prefix = ["- ", "* ", "+ "].first(where: { trimmed.hasPrefix($0) }) {
            flushParagraph()
            flushQuote()
            blocks.append(.unorderedItem(String(trimmed.dropFirst(prefix.count))))
            continue
        }

        // Also accept fullwidth bullet "・" common in Chinese/Japanese teaching text.
        if trimmed.hasPrefix("・") {
            flushParagraph()
            flushQuote()
            let item = String(trimmed.dropFirst()).trimmingCharacters(in: .whitespaces)
            blocks.append(.unorderedItem(item))
            continue
        }

        if let item = orderedListItem(from: trimmed) {
            flushParagraph()
            flushQuote()
            blocks.append(.orderedItem(number: item.number, text: item.text))
            continue
        }

        if trimmed.hasPrefix(">") {
            flushParagraph()
            let quote = String(trimmed.dropFirst().drop { $0.isWhitespace })
            quoteLines.append(quote)
            continue
        }

        flushQuote()
        paragraphLines.append(line)
    }

    if isInsideCodeFence {
        blocks.append(.code(codeLines.joined(separator: "\n")))
    }
    flushQuote()
    flushParagraph()

    while blocks.first == .spacer { blocks.removeFirst() }
    while blocks.last == .spacer { blocks.removeLast() }
    return blocks
}

func isListBlock(_ block: MarkdownBlock) -> Bool {
    switch block {
    case .unorderedItem, .orderedItem: true
    default: false
    }
}

func inlineMarkdown(_ source: String) -> AttributedString {
    let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
    return (try? AttributedString(markdown: source, options: options)) ?? AttributedString(source)
}

/// Inline markdown with Harvest styling so bold/code/links are easy to scan.
func styledInlineMarkdown(
    _ source: String,
    baseFont: Font = .body,
    baseColor: Color = DesignTokens.ink
) -> AttributedString {
    var result = inlineMarkdown(source)
    result.font = baseFont
    result.foregroundColor = baseColor

    for run in result.runs {
        let range = run.range
        let intent = run.inlinePresentationIntent ?? []

        if intent.contains(.code) {
            result[range].font = .system(.callout, design: .monospaced)
            result[range].foregroundColor = DesignTokens.ink
            result[range].backgroundColor = DesignTokens.accentWash
        } else if intent.contains(.stronglyEmphasized) {
            result[range].font = baseFont.weight(.semibold)
            result[range].foregroundColor = DesignTokens.accent
        } else if intent.contains(.emphasized) {
            result[range].font = baseFont.italic()
            result[range].foregroundColor = DesignTokens.ink
        }

        if run.link != nil {
            result[range].foregroundColor = DesignTokens.accent
            result[range].underlineStyle = .single
        }
    }
    return result
}

/// UIKit counterpart of `styledInlineMarkdown`, for the UITextView-backed renderer.
/// SwiftUI's `AttributedString` font/color attributes do not survive a bridge to
/// `NSAttributedString`, so the inline intents have to be mapped to UIKit directly.
func inlineMarkdownAttributed(
    _ source: String,
    baseFont: UIFont,
    baseColor: UIColor,
    lineSpacing: CGFloat
) -> NSAttributedString {
    let parsed = inlineMarkdown(source)
    let result = NSMutableAttributedString()

    for run in parsed.runs {
        let piece = String(parsed[run.range].characters)
        guard !piece.isEmpty else { continue }
        let intent = run.inlinePresentationIntent ?? []
        var font = baseFont
        var color = baseColor
        var attributes: [NSAttributedString.Key: Any] = [:]

        if intent.contains(.code) {
            font = .monospacedSystemFont(ofSize: baseFont.pointSize * 0.95, weight: .regular)
            attributes[.backgroundColor] = UIColor(DesignTokens.accentWash)
        } else if intent.contains(.stronglyEmphasized) {
            font = baseFont.withSymbolicTraits(.traitBold)
            color = UIColor(DesignTokens.accent)
        } else if intent.contains(.emphasized) {
            font = baseFont.withSymbolicTraits(.traitItalic)
        }

        if run.link != nil {
            color = UIColor(DesignTokens.accent)
            attributes[.underlineStyle] = NSUnderlineStyle.single.rawValue
        }

        attributes[.font] = font
        attributes[.foregroundColor] = color
        result.append(NSAttributedString(string: piece, attributes: attributes))
    }

    let paragraph = NSMutableParagraphStyle()
    paragraph.lineSpacing = lineSpacing
    result.addAttribute(
        .paragraphStyle,
        value: paragraph,
        range: NSRange(location: 0, length: result.length)
    )
    return result
}

private extension UIFont {
    /// Adds traits while keeping the current size/design; falls back to self if unavailable.
    func withSymbolicTraits(_ traits: UIFontDescriptor.SymbolicTraits) -> UIFont {
        let combined = fontDescriptor.symbolicTraits.union(traits)
        guard let descriptor = fontDescriptor.withSymbolicTraits(combined) else { return self }
        return UIFont(descriptor: descriptor, size: pointSize)
    }
}

func containsInlineMarkdownSyntax(_ source: String) -> Bool {
    if ["**", "__", "`", "~~"].contains(where: source.contains) { return true }
    if source.range(of: #"\[[^\]]+\]\([^)]+\)"#, options: .regularExpression) != nil { return true }
    if source.range(of: #"(^|[^*])\*[^*\n]+\*"#, options: .regularExpression) != nil { return true }
    return source.range(of: #"(^|[^_])_[^_\n]+_"#, options: .regularExpression) != nil
}

/// True when a line is mostly Japanese script (example sentences, readings, etc.).
func isMostlyJapanese(_ text: String) -> Bool {
    let plain = text
        .replacingOccurrences(of: "**", with: "")
        .replacingOccurrences(of: "__", with: "")
        .replacingOccurrences(of: "`", with: "")
    var meaningful = 0
    var japanese = 0
    var kana = 0
    let skip = CharacterSet.whitespacesAndNewlines
        .union(.punctuationCharacters)
        .union(.symbols)
    for scalar in plain.unicodeScalars {
        if skip.contains(scalar) { continue }
        // Keep CJK punctuation out of the denominator so 「」doesn't dilute the ratio.
        if (0x3000...0x303F).contains(scalar.value) { continue }
        meaningful += 1
        let value = scalar.value
        let isKana = isKanaScalar(value) || (0xFF66...0xFF9D).contains(value)
        if isKana { kana += 1 }
        if isKana || (0x4E00...0x9FFF).contains(value) {
            japanese += 1
        }
    }
    guard meaningful >= 4 else { return false }
    // Kanji alone cannot tell Japanese from Chinese — a Chinese explanation scores
    // ~100% on the kanji ratio, which used to style every explanation as an example.
    // Kana is the unambiguous signal (same principle as `furiganaRuns`), but a Chinese
    // line quoting 「は」「が」 carries a trace of it, so require some real weight.
    // Measured on actual companion replies: pure Chinese prose sits at 0.00–0.15,
    // Japanese examples (usually trailed by a Chinese gloss) at 0.30–0.50. Lines that
    // quote a whole Japanese sentence inside Chinese prose overlap the bottom of that
    // range and stay ambiguous; 0.2 keeps real examples rather than chasing them.
    guard Double(kana) / Double(meaningful) >= 0.2 else { return false }
    return Double(japanese) / Double(meaningful) >= 0.42
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
func furiganaRuns(in text: String) -> [(text: String, annotate: Bool)] {
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

/// Tokenize text into words using Japanese word boundaries.
/// Includes non-token gaps (punctuation/spaces) so callers can rebuild layout if needed.
func japaneseWordTokens(in text: String) -> [(word: String, isJapanese: Bool)] {
    let tokenizer = NLTokenizer(unit: .word)
    tokenizer.setLanguage(.japanese)
    tokenizer.string = text
    var tokens: [(String, Bool)] = []
    var cursor = text.startIndex
    tokenizer.enumerateTokens(in: text.startIndex..<text.endIndex) { range, _ in
        if cursor < range.lowerBound {
            tokens.append((String(text[cursor..<range.lowerBound]), false))
        }
        let word = String(text[range])
        let hasKana = word.unicodeScalars.contains { isKanaScalar($0.value) }
        let hasKanji = word.unicodeScalars.contains { ($0.value >= 0x4E00 && $0.value <= 0x9FFF) }
        tokens.append((word, hasKana || hasKanji))
        cursor = range.upperBound
        return true
    }
    if cursor < text.endIndex {
        tokens.append((String(text[cursor...]), false))
    }
    return tokens
}

/// Locate the Japanese word token under a tapped UTF-16 offset, for tap-to-lookup.
/// Returns nil for punctuation/whitespace or non-Japanese text so taps there are ignored.
func japaneseWordRange(at utf16Offset: Int, in text: String) -> Range<String.Index>? {
    guard let point = Range(NSRange(location: utf16Offset, length: 1), in: text)?.lowerBound else {
        return nil
    }
    let tokenizer = NLTokenizer(unit: .word)
    tokenizer.setLanguage(.japanese)
    tokenizer.string = text
    let range = tokenizer.tokenRange(at: point)
    guard !range.isEmpty else { return nil }
    let word = text[range]
    guard word.unicodeScalars.contains(where: {
        isKanaScalar($0.value) || (0x4E00...0x9FFF).contains($0.value)
    }) else { return nil }
    return range
}

/// Unique Japanese surface forms suitable for dictionary lookup, in reading order.
func japaneseLookupCandidates(in text: String) -> [String] {
    var seen = Set<String>()
    var result: [String] = []
    for token in japaneseWordTokens(in: text) where token.isJapanese {
        let word = token.word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard word.count >= 1 else { continue }
        // Skip lone punctuation-like leftovers that slipped through.
        guard word.unicodeScalars.contains(where: {
            isKanaScalar($0.value) || (0x4E00...0x9FFF).contains($0.value)
        }) else { continue }
        if seen.insert(word).inserted {
            result.append(word)
        }
    }
    return result
}

/// Identifiable wrapper for dictionary result sheet.
struct LookupWord: Identifiable {
    let id = UUID()
    let word: String
    let context: String?
}

/// Identifiable wrapper for the intermediate "pick a word" sheet.
struct WordPickRequest: Identifiable {
    let id = UUID()
    let context: String
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
    @State private var showManualLookup = false
    @State private var lookupWord: LookupWord?

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
        VStack(spacing: 0) {
            contextHeader
            conversation
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, DesignTokens.pageInset)
                    .padding(.top, 8)
            }
            composerBar
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("陪读")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    lookupFromClipboard()
                } label: {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(DesignTokens.ink)
                }
                .accessibilityLabel("查词")
            }
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
    }

    private func lookupFromClipboard() {
        isInputFocused = false
        if let query = clipboardLookupQuery() {
            lookupWord = LookupWord(word: query, context: nil)
        } else {
            showManualLookup = true
        }
    }

    private var contextHeader: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("当前句子")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DesignTokens.muted)

            if showFurigana, let segments = furiganaCache[segment.textJA] {
                FuriganaText(segments: segments, fontSize: 20)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text(segment.textJA)
                    .font(.system(.title3, design: .serif))
                    .foregroundStyle(DesignTokens.ink)
                    .lineSpacing(6)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            if let focusText {
                Text("正在问「\(focusText)」")
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(DesignTokens.accent)
            }
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.top, 12)
        .padding(.bottom, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DesignTokens.surface)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(DesignTokens.separator)
                .frame(height: 0.5)
        }
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(messages) { message in
                        CompanionMessageBubble(
                            role: message.role,
                            content: message.content,
                            showFurigana: showFurigana,
                            furiganaCache: furiganaCache,
                            onWordTap: { word in
                                isInputFocused = false
                                lookupWord = LookupWord(word: word, context: message.content)
                            }
                        )
                        .id("message-\(message.id)")
                    }
                    if let pendingQuestion = composer.pendingQuestion {
                        CompanionMessageBubble(role: "user", content: pendingQuestion)
                            .id("pending-question")
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                                .tint(DesignTokens.accent)
                            Text("老师正在整理…")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 12)
                        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 16))
                        .id("pending-answer")
                        .accessibilityIdentifier("companion-pending-answer")
                    }
                }
                .padding(.horizontal, DesignTokens.pageInset)
                .padding(.vertical, 16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // Avoid full-area onTapGesture — it blocks long-press text selection/copy.
            .scrollDismissesKeyboard(.interactively)
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
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 15))
                .overlay {
                    RoundedRectangle(cornerRadius: 15)
                        .stroke(DesignTokens.separator, lineWidth: 0.5)
                }

            Button(action: submit) {
                Image(systemName: "arrow.up")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(
                        DesignTokens.accent.opacity(composer.canSend ? 1 : 0.45),
                        in: Circle()
                    )
            }
            .disabled(!composer.canSend)
            .accessibilityLabel("提问")
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
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
    var onWordTap: ((String) -> Void)?

    private var isUser: Bool { role == "user" }

    var body: some View {
        if isUser {
            SelectableText(
                text: content,
                font: .preferredFont(forTextStyle: .body),
                textColor: .white,
                lineSpacing: 4,
                onWordTap: onWordTap
            )
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(DesignTokens.accent, in: RoundedRectangle(cornerRadius: 16))
            .frame(
                maxWidth: UIScreen.main.bounds.width * 0.78,
                alignment: .trailing
            )
            .frame(maxWidth: .infinity, alignment: .trailing)
            .contextMenu {
                Button {
                    UIPasteboard.general.string = content
                } label: {
                    Label("复制全文", systemImage: "doc.on.doc")
                }
            }
        } else {
            // §5.4 requires Markdown semantics here — headings, bold, lists must never
            // reach the user as raw `#`/`**`. Prose renders through UITextView so a
            // single tap still looks a word up, and long-press still selects phrases.
            MarkdownMessageView(
                markdown: content,
                showFurigana: showFurigana,
                furiganaCache: furiganaCache,
                style: .teaching,
                onWordTap: onWordTap
            )
            .frame(maxWidth: .infinity, alignment: .leading)
            .contextMenu {
                Button {
                    UIPasteboard.general.string = content
                } label: {
                    Label("复制全文", systemImage: "doc.on.doc")
                }
            }
        }
    }
}

/// How richly Markdown is laid out.
/// - teaching: companion-style hierarchy (lead card, example panels)
/// - conversation: lighter chat replies — readable, not lecture-like
enum MarkdownRenderStyle {
    case teaching
    case conversation
}

struct MarkdownMessageView: View {
    let markdown: String
    var showFurigana = false
    var furiganaCache: [String: [FuriganaSegment]] = [:]
    var style: MarkdownRenderStyle = .teaching
    /// When set, prose renders through a UITextView so a single tap looks a word up.
    var onWordTap: ((String) -> Void)?

    private var blocks: [MarkdownBlock] {
        markdownBlocks(from: markdown)
    }

    /// First prose paragraph is the takeaway — give it visual weight in teaching mode.
    private var leadParagraphIndex: Int? {
        guard style == .teaching else { return nil }
        return blocks.firstIndex {
            if case .paragraph = $0 { return true }
            return false
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
                blockView(block, index: index)
                    .padding(.top, topPadding(for: block, at: index))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .foregroundStyle(DesignTokens.ink)
        .tint(DesignTokens.accent)
    }

    private func topPadding(for block: MarkdownBlock, at index: Int) -> CGFloat {
        guard index > 0 else { return 0 }
        let previous = blocks[index - 1]
        let section: CGFloat = style == .conversation ? 12 : 14
        switch (previous, block) {
        case (_, .spacer), (.spacer, _):
            return 0
        case (.unorderedItem, .unorderedItem), (.orderedItem, .orderedItem):
            return style == .conversation ? 6 : 8
        case (.unorderedItem, .orderedItem), (.orderedItem, .unorderedItem):
            return style == .conversation ? 6 : 8
        case (_, .heading):
            return style == .conversation ? 16 : 22
        case (.heading, _):
            return 10
        case (.paragraph, .unorderedItem), (.paragraph, .orderedItem):
            return 12
        case (.quote, _), (_, .quote):
            return section
        case (.code, _), (_, .code):
            return 12
        case (.divider, _), (_, .divider):
            return 16
        case (.paragraph, .paragraph):
            // Chat replies are often "answer\n\nfollow-up question" — open a clear beat.
            return style == .conversation ? 12 : section
        default:
            return section
        }
    }

    @ViewBuilder
    private func blockView(_ block: MarkdownBlock, index: Int) -> some View {
        switch block {
        case .paragraph(let text):
            if index == leadParagraphIndex {
                leadParagraph(text)
            } else if style == .teaching, isMostlyJapanese(text) {
                exampleBlock(text)
            } else {
                proseParagraph(text)
            }
        case .heading(let level, let text):
            headingRow(level: level, text: text)
        case .unorderedItem(let text):
            listRow(label: "•", text: text)
        case .orderedItem(let number, let text):
            listRow(label: "\(number).", text: text)
        case .quote(let text):
            quoteBlock(text)
        case .code(let text):
            codeBlock(text)
        case .divider:
            Rectangle()
                .fill(DesignTokens.separator)
                .frame(height: 0.5)
                .padding(.vertical, 4)
        case .spacer:
            Color.clear.frame(height: style == .conversation ? 6 : 10)
        }
    }

    private func proseParagraph(_ text: String) -> some View {
        let japanese = isMostlyJapanese(text)
        let font: Font = japanese ? .system(.body, design: .serif) : .body
        return renderText(text, font: font, color: DesignTokens.ink)
            .lineSpacing(japanese ? 6 : 5)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func leadParagraph(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("先看结论")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DesignTokens.accent)
            renderText(text, font: .body, color: DesignTokens.ink)
                .lineSpacing(6)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: 14))
        .overlay {
            RoundedRectangle(cornerRadius: 14)
                .stroke(DesignTokens.accent.opacity(0.18), lineWidth: 0.5)
        }
    }

    private func headingRow(level: Int, text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2)
                .fill(DesignTokens.accent.opacity(level <= 2 ? 0.85 : 0.45))
                .frame(width: 3, height: level <= 2 ? 18 : 14)
                .padding(.top, 3)
            renderText(text, font: headingFont(level: level), color: DesignTokens.ink)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func listRow(label: String, text: String) -> some View {
        let japanese = isMostlyJapanese(text)
        return HStack(alignment: .top, spacing: 10) {
            Text(label)
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .foregroundStyle(DesignTokens.accent)
                .frame(width: 20, alignment: .trailing)
                .padding(.top, 2)
            if japanese, style == .teaching {
                renderText(
                    text,
                    font: .system(.body, design: .serif),
                    color: DesignTokens.ink
                )
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                .overlay {
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(DesignTokens.separator, lineWidth: 0.5)
                }
            } else {
                renderText(
                    text,
                    font: japanese ? .system(.body, design: .serif) : .body,
                    color: DesignTokens.ink
                )
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func quoteBlock(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            RoundedRectangle(cornerRadius: 2)
                .fill(DesignTokens.accent.opacity(0.5))
                .frame(width: 3)
            renderText(text, font: .callout, color: DesignTokens.muted)
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .stroke(DesignTokens.separator, lineWidth: 0.5)
        }
    }

    private func codeBlock(_ text: String) -> some View {
        let japanese = isMostlyJapanese(text)
        return Text(text)
            .font(japanese ? .system(.body, design: .serif) : .system(.callout, design: .monospaced))
            .foregroundStyle(DesignTokens.ink)
            .textSelection(.enabled)
            .lineSpacing(japanese ? 6 : 3)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay {
                RoundedRectangle(cornerRadius: 12)
                    .stroke(DesignTokens.separator, lineWidth: 0.5)
            }
    }

    private func exampleBlock(_ text: String) -> some View {
        renderText(
            text,
            font: .system(.body, design: .serif),
            color: DesignTokens.ink
        )
        .lineSpacing(6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .stroke(DesignTokens.separator, lineWidth: 0.5)
        }
    }

    @ViewBuilder
    private func renderText(_ text: String, font: Font, color: Color) -> some View {
        // Ruby layout wins when furigana is on and there are no inline markers to lose
        // (§5.4: never show raw `**`/backticks just to render kana).
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
                styledProse(text, font: font, color: color)
            }
        } else {
            styledProse(text, font: font, color: color)
        }
    }

    /// Renders inline Markdown. With `onWordTap` it goes through UITextView so tapping
    /// a word opens the dictionary; otherwise plain SwiftUI `Text` keeps the view cheap.
    @ViewBuilder
    private func styledProse(_ text: String, font: Font, color: Color) -> some View {
        if let onWordTap {
            SelectableText(
                text: text,
                attributed: inlineMarkdownAttributed(
                    text,
                    baseFont: uiFont(for: font),
                    baseColor: UIColor(color),
                    lineSpacing: isMostlyJapanese(text) ? 6 : 5
                ),
                onWordTap: onWordTap
            )
        } else {
            Text(styledInlineMarkdown(text, baseFont: font, baseColor: color))
                .textSelection(.enabled)
        }
    }

    /// Maps the handful of `Font` values this renderer actually uses to UIKit.
    /// `Font` is Equatable but not pattern-matchable, hence the comparison chain.
    private func uiFont(for font: Font) -> UIFont {
        func serif(_ style: UIFont.TextStyle) -> UIFont {
            let base = UIFont.preferredFont(forTextStyle: style)
            guard let descriptor = base.fontDescriptor.withDesign(.serif) else { return base }
            return UIFont(descriptor: descriptor, size: 0)
        }
        if font == .system(.title3, design: .serif, weight: .semibold) {
            return serif(.title3).withSymbolicTraits(.traitBold)
        }
        if font == .system(.headline, design: .serif, weight: .semibold) {
            return serif(.headline).withSymbolicTraits(.traitBold)
        }
        if font == .system(.subheadline, design: .serif, weight: .semibold) {
            return serif(.subheadline).withSymbolicTraits(.traitBold)
        }
        if font == .system(.body, design: .serif) {
            return serif(.body)
        }
        if font == .callout {
            return .preferredFont(forTextStyle: .callout)
        }
        return .preferredFont(forTextStyle: .body)
    }

    private func headingFont(level: Int) -> Font {
        switch level {
        case 1: .system(.title3, design: .serif, weight: .semibold)
        case 2: .system(.headline, design: .serif, weight: .semibold)
        default: .system(.subheadline, design: .serif, weight: .semibold)
        }
    }
}
