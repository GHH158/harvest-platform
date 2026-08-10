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

    /// §5.15: an angle carries no draft text, so it only has to claim the in-flight
    /// slot. Whatever the learner had half-typed stays untouched in the field.
    mutating func beginSendingLens() -> Bool {
        guard !isSending else { return false }
        isSending = true
        return true
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
    /// GFM pipe table. Comparison tables (「たまに」vs「ときどき」, 语体对照) are a
    /// natural shape for language teaching, so the model reaches for them; without a
    /// case here they fell through to `.paragraph` and showed raw pipes.
    case table(header: [String], rows: [[String]])
    case divider
    case spacer
}

/// A row is `| a | b |`; outer pipes are optional in GFM. Returns nil for lines that
/// merely contain a pipe, so ordinary prose is never mistaken for a table.
func markdownTableCells(from line: String) -> [String]? {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    guard trimmed.contains("|") else { return nil }
    var body = trimmed
    if body.hasPrefix("|") { body.removeFirst() }
    if body.hasSuffix("|") { body.removeLast() }
    guard body.contains("|") || trimmed.hasPrefix("|") else { return nil }
    return body.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
}

/// The `|---|:--:|` line under the header is what makes a table a table.
func isMarkdownTableDivider(_ line: String) -> Bool {
    guard let cells = markdownTableCells(from: line), !cells.isEmpty else { return false }
    return cells.allSatisfy { cell in
        !cell.isEmpty && cell.allSatisfy { $0 == "-" || $0 == ":" || $0 == " " } && cell.contains("-")
    }
}

func markdownBlocks(from source: String) -> [MarkdownBlock] {
    let normalized = source.replacingOccurrences(of: "\r\n", with: "\n")
    let lines = normalized.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
    var blocks: [MarkdownBlock] = []
    var paragraphLines: [String] = []
    var codeLines: [String] = []
    var quoteLines: [String] = []
    var isInsideCodeFence = false
    var index = 0

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

    while index < lines.count {
        let line = lines[index]
        index += 1
        let trimmed = line.trimmingCharacters(in: .whitespaces)

        // A table is only a table when a divider row follows the header, so look one
        // line ahead before committing. Everything else stays line-at-a-time.
        if !isInsideCodeFence,
           index < lines.count,
           let header = markdownTableCells(from: line),
           header.count >= 2,
           isMarkdownTableDivider(lines[index]) {
            flushParagraph()
            flushQuote()
            index += 1  // consume the divider
            var rows: [[String]] = []
            while index < lines.count, let cells = markdownTableCells(from: lines[index]) {
                // Pad or trim so every row matches the header and the grid stays square.
                var row = cells
                if row.count < header.count { row += Array(repeating: "", count: header.count - row.count) }
                rows.append(Array(row.prefix(header.count)))
                index += 1
            }
            blocks.append(.table(header: header, rows: rows))
            continue
        }

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
    @State private var lenses: [QuestionLens] = []
    /// §5.17: false means the sheet shows only this sentence's history, which is the default.
    @State private var showsWholeMaterial = false

    init(materialID: Int, segment: Segment, focusText: String? = nil) {
        self.materialID = materialID
        self.segment = segment
        self.focusText = focusText
        // §11.9: never pre-fill the field. A ready-made sentence is cheaper to send
        // than to clear, so every question became the same word lookup and the
        // learner stopped asking anything else. Angles are offered instead (§5.15).
        _composer = State(initialValue: CompanionComposerState(draft: ""))
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
            if !lenses.isEmpty {
                lensBar
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
                    // The whole material's history is still there and still kept — the
                    // grammar skeleton's provenance hangs off these rows (§4.3). It is just
                    // not what you asked for when you tapped one sentence, so it waits here
                    // where you would scroll up looking for it.
                    if !showsWholeMaterial {
                        Button {
                            Task { await loadWholeMaterial() }
                        } label: {
                            Text("看这篇以前问过的")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                        }
                        .buttonStyle(.plain)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.bottom, 2)
                    }
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

    /// §5.15: one tap sends that angle. Shown whenever the learner can still ask —
    /// the point is that the options are visible before you have a question in mind,
    /// which an empty box does not achieve any better than a pre-filled one did.
    /// One row (2026-08-10). The first reworded set did not fit across 402pt and a
    /// horizontal scroll left 「跟中文差在哪」 clipped to 「跟中文差在」 — which reads like a
    /// typo and hides what tapping it gets you, exactly what §11.9 is about. Two rows fixed
    /// the legibility but ate height in a two-thirds sheet, so the labels were shortened
    /// instead: 15 characters across four capsules fits at the default text size.
    ///
    /// The ScrollView stays as a fallback rather than as the layout: at larger accessibility
    /// text sizes this degrades to scrolling instead of clipping, which is the failure mode
    /// that matters here.
    private var lensBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(lenses) { lens in
                    Button {
                        Task { await send(lens: lens.id) }
                    } label: {
                        Text(lens.labelZH)
                            .font(.subheadline)
                            .lineLimit(1)
                            .fixedSize()
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(DesignTokens.surface, in: Capsule())
                            .overlay { Capsule().stroke(DesignTokens.separator, lineWidth: 0.5) }
                    }
                    .buttonStyle(.plain)
                    .disabled(composer.isSending)
                    .opacity(composer.isSending ? 0.45 : 1)
                }
            }
            .padding(.horizontal, DesignTokens.pageInset)
        }
        .padding(.top, 10)
    }

    private var composerBar: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("或者，直接问你想问的", text: $composer.draft, axis: .vertical)
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
        let client = APIClient(baseURL: endpoint)
        do {
            // §5.17 (2026-08-10): this sheet is about one sentence, so it opens with only
            // that sentence's history. It used to load the whole material's — forty answers
            // about other sentences, on top of the one you just asked for. Same-sentence
            // history stays, because that IS context: asking 拆开看看 and then 这么说怪吗
            // about the same line is one conversation.
            messages = try await client.companion(materialID: materialID, segmentID: segment.id)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        // Angles are an addition, not a precondition: if this call fails the learner
        // can still type a question, so it must not surface as an error.
        lenses = (try? await client.companionLenses()) ?? []
    }

    /// Pulls in the rest of the material's history on request (§5.17). One way only: once
    /// you have asked to see it, going back to the narrow view would just hide something
    /// you are reading.
    @MainActor private func loadWholeMaterial() async {
        guard let client, !showsWholeMaterial else { return }
        do {
            let all = try await client.companion(materialID: materialID)
            withAnimation(.easeOut(duration: 0.22)) {
                messages = all
                showsWholeMaterial = true
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor private func send(lens: String? = nil) async {
        if lens == nil {
            guard composer.beginSending() != nil else { return }
        } else {
            guard composer.beginSendingLens() else { return }
        }
        let question = lens == nil ? composer.pendingQuestion : nil
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
                question: question,
                lens: lens,
                focusText: focusText
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
        // Only the newest replies. Each Japanese run costs one request and they are
        // awaited in sequence, so walking the whole history turned "open the sheet"
        // into dozens of serial round trips as a material accumulated questions.
        // Anything older still renders — just without ruby until it is asked about.
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
        case (.table, _), (_, .table):
            return 14
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
        case .table(let header, let rows):
            tableBlock(header: header, rows: rows)
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
        // CJK has no word spaces and a high ink density, so it needs more leading than
        // Latin at the same size before a wall of text becomes readable.
        return renderText(text, font: font, color: DesignTokens.ink)
            .lineSpacing(japanese ? 8 : 7)
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

    /// No decorative left rule: §13.10 records that as a UI debt to clear, and it also
    /// eats horizontal space on every heading. Weight and the space above already say
    /// "new section" — structure should be self-evident, not drawn on.
    private func headingRow(level: Int, text: String) -> some View {
        renderText(text, font: headingFont(level: level), color: DesignTokens.ink)
            .fixedSize(horizontal: false, vertical: true)
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
            // A bullet is already structure; boxing it puts a bordered card inside the
            // answer card and costs ~30pt of line width, which is what made long
            // explanations wrap every 13 characters. The serif face is enough to mark
            // Japanese apart from the Chinese around it.
            renderText(
                text,
                font: japanese ? .system(.body, design: .serif) : .body,
                color: DesignTokens.ink
            )
            .lineSpacing(japanese ? 7 : 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// Softer tone and an indent carry "aside" without a rule *and* a border *and* a
    /// fill all saying the same thing.
    private func quoteBlock(_ text: String) -> some View {
        renderText(text, font: .callout, color: DesignTokens.muted)
            .lineSpacing(6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.leading, 14)
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

    /// `isMostlyJapanese` cannot reliably separate a Japanese example from a Chinese
    /// explanation that quotes several Japanese phrases — its own comment says lines
    /// like that "stay ambiguous". A box and border on a false positive is the worst
    /// outcome: the paragraph loses ~28pt of width and wraps differently from every
    /// other paragraph in the same answer. Serif plus leading is enough of a signal,
    /// and it costs nothing when the guess is wrong.
    private func exampleBlock(_ text: String) -> some View {
        renderText(
            text,
            font: .system(.body, design: .serif),
            color: DesignTokens.ink
        )
        .lineSpacing(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
    }

    /// Up to three columns a phone can show as a real grid. Beyond that each column
    /// gets ~85pt and CJK wraps every three characters — measured on a real four-column
    /// answer, "ときどきジョギングをする" came out as four stacked fragments. Wide
    /// tables therefore transpose: one block per row, first cell as its title. Sideways
    /// scrolling is not the fix, because it hides the column you are comparing against.
    @ViewBuilder
    private func tableBlock(header: [String], rows: [[String]]) -> some View {
        if header.count > 3 {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    transposedRow(header: header, row: row)
                }
            }
        } else {
            VStack(spacing: 0) {
                tableRow(header, isHeader: true)
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    Divider().overlay(DesignTokens.separator)
                    tableRow(row, isHeader: false)
                        .background(index.isMultiple(of: 2) ? Color.clear : DesignTokens.canvas.opacity(0.5))
                }
            }
            .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay {
                RoundedRectangle(cornerRadius: 12).stroke(DesignTokens.separator, lineWidth: 0.5)
            }
        }
    }

    private func transposedRow(header: [String], row: [String]) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            if let title = row.first, !title.isEmpty {
                renderText(title, font: .subheadline.weight(.semibold), color: DesignTokens.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(Array(zip(header, row).dropFirst().enumerated()), id: \.offset) { _, pair in
                if !pair.1.isEmpty {
                    HStack(alignment: .top, spacing: 8) {
                        renderText(pair.0, font: .caption.weight(.semibold), color: DesignTokens.accent)
                            .frame(width: 62, alignment: .leading)
                            .fixedSize(horizontal: false, vertical: true)
                        renderText(pair.1, font: .footnote, color: DesignTokens.ink)
                            .lineSpacing(4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12).stroke(DesignTokens.separator, lineWidth: 0.5)
        }
    }

    private func tableRow(_ cells: [String], isHeader: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(cells.enumerated()), id: \.offset) { index, cell in
                if index > 0 {
                    Rectangle()
                        .fill(DesignTokens.separator)
                        .frame(width: 0.5)
                        .frame(maxHeight: .infinity)
                }
                renderText(
                    cell,
                    font: isHeader ? .footnote.weight(.semibold) : .footnote,
                    color: isHeader ? DesignTokens.accent : DesignTokens.ink
                )
                .lineSpacing(4)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 10)
                .padding(.vertical, 9)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
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
