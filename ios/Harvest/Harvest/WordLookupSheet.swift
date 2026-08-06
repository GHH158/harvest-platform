import SwiftUI
import UIKit

/// Normalize clipboard text into a short lookup query.
func clipboardLookupQuery() -> String? {
    let raw = UIPasteboard.general.string?
        .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard !raw.isEmpty else { return nil }
    let firstLine = raw.split(whereSeparator: \.isNewline).first.map(String.init) ?? raw
    let compressed = firstLine
        .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
        .trimmingCharacters(in: .whitespacesAndNewlines)
    guard !compressed.isEmpty else { return nil }
    // Dictionary is for short expressions, not whole paragraphs.
    if compressed.count > 40 {
        return String(compressed.prefix(40)).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return compressed
}

/// Lookup sheet for a copied (or manually entered) Japanese word.
struct WordLookupSheet: View {
    let word: String
    /// Surrounding sentence, when known, so the backend can disambiguate multi-sense words.
    var context: String? = nil
    @EnvironmentObject private var configuration: AppConfiguration
    @Environment(\.dismiss) private var dismiss
    @State private var result: DictionaryLookupResult?
    @State private var errorMessage: String?
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var savedToVocabulary = false
    @State private var wasAlreadySaved = false
    @State private var vocabularyError: String?
    @State private var exampleFurigana: [String: [FuriganaSegment]] = [:]

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    private var canSave: Bool {
        guard let result, !isSaving, !savedToVocabulary else { return false }
        return !(result.meaning ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                lookupContent
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(DesignTokens.canvas)
            .navigationTitle(word)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                        .foregroundStyle(DesignTokens.accent)
                }
            }
            .task { await lookup() }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    @ViewBuilder
    private var lookupContent: some View {
        if isLoading {
            VStack(spacing: 16) {
                ProgressView()
                    .controlSize(.regular)
                    .tint(DesignTokens.accent)
                    .padding(.top, 48)
                Text("正在查询…")
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
            }
            .frame(maxWidth: .infinity)
        } else if let errorMessage {
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 28))
                    .foregroundStyle(DesignTokens.accent)
                    .padding(.top, 48)
                Text(errorMessage)
                    .font(.callout)
                    .foregroundStyle(DesignTokens.muted)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, DesignTokens.pageInset)
                Button("重试") { Task { await lookup() } }
                    .foregroundStyle(DesignTokens.accent)
            }
            .frame(maxWidth: .infinity)
        } else if let result {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    wordHero(result)

                    Divider()
                        .overlay(DesignTokens.separator)
                        .padding(.vertical, 18)

                    detailRow(label: "读音", value: nonEmpty(result.reading), placeholder: "暂无")
                    detailRow(label: "词性", value: nonEmpty(result.partOfSpeech), placeholder: "暂无")
                    detailRow(label: "释义", value: nonEmpty(result.meaning), placeholder: "暂无")

                    if let hint = nonEmpty(result.memoryHint) {
                        memoryCard(hint)
                            .padding(.top, 20)
                    }

                    if !result.examples.isEmpty {
                        examplesSection(result.examples)
                            .padding(.top, 22)
                    }

                    saveSection(result)
                        .padding(.top, 28)
                }
                .padding(DesignTokens.pageInset)
            }
        }
    }

    private func wordHero(_ result: DictionaryLookupResult) -> some View {
        VStack(spacing: 8) {
            Text(word)
                .font(.system(.largeTitle, design: .serif))
                .foregroundStyle(DesignTokens.ink)
            if let reading = nonEmpty(result.reading) {
                Text(reading)
                    .font(.title3)
                    .foregroundStyle(DesignTokens.accent)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
    }

    private func memoryCard(_ hint: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("怎么记", systemImage: "lightbulb")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DesignTokens.accent)
            Text(hint)
                .font(.body)
                .foregroundStyle(DesignTokens.ink)
                .lineSpacing(5)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: 14))
        .overlay {
            RoundedRectangle(cornerRadius: 14)
                .stroke(DesignTokens.accent.opacity(0.18), lineWidth: 0.5)
        }
    }

    private func examplesSection(_ examples: [DictionaryExample]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("例句")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DesignTokens.muted)

            ForEach(Array(examples.enumerated()), id: \.offset) { _, example in
                VStack(alignment: .leading, spacing: 8) {
                    if let segments = exampleFurigana[example.ja], !segments.isEmpty {
                        FuriganaText(segments: segments, fontSize: 18)
                    } else {
                        Text(example.ja)
                            .font(.system(.body, design: .serif))
                            .foregroundStyle(DesignTokens.ink)
                            .lineSpacing(5)
                    }
                    Text(example.zh)
                        .font(.subheadline)
                        .foregroundStyle(DesignTokens.muted)
                        .lineSpacing(3)
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 14))
                .overlay {
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(DesignTokens.separator, lineWidth: 0.5)
                }
            }
        }
    }

    private func saveSection(_ result: DictionaryLookupResult) -> some View {
        VStack(spacing: 12) {
            if savedToVocabulary {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(Color.green)
                    Text(wasAlreadySaved ? "已在生词表中" : "已加入生词表")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(Color.green)
                }
            } else {
                Button {
                    Task { await save() }
                } label: {
                    HStack(spacing: 6) {
                        if isSaving {
                            ProgressView().controlSize(.small).tint(.white)
                        } else {
                            Image(systemName: "bookmark")
                        }
                        Text(isSaving ? "正在保存…" : "加入生词表")
                    }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(!canSave)
                .opacity(canSave ? 1 : 0.45)
            }

            if let vocabularyError {
                Text(vocabularyError)
                    .font(.caption)
                    .foregroundStyle(DesignTokens.accent)
                    .frame(maxWidth: .infinity, alignment: .center)
            } else if !canSave, !savedToVocabulary, nonEmpty(result.meaning) == nil {
                Text("暂无可用释义，无法加入生词表。")
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
        }
    }

    private func detailRow(label: String, value: String?, placeholder: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(DesignTokens.muted)
                .frame(width: 36, alignment: .leading)
            Text(value ?? placeholder)
                .font(.body)
                .foregroundStyle(value == nil ? DesignTokens.muted.opacity(0.6) : DesignTokens.ink)
                .lineSpacing(4)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 6)
    }

    private func nonEmpty(_ value: String?) -> String? {
        let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? nil : trimmed
    }

    @MainActor
    private func lookup() async {
        isLoading = true
        errorMessage = nil
        result = nil
        exampleFurigana = [:]
        savedToVocabulary = false
        wasAlreadySaved = false
        vocabularyError = nil
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            isLoading = false
            return
        }
        do {
            let lookup = try await client.dictionaryLookup(word: word, context: context)
            result = lookup
            isLoading = false
            await loadExampleFurigana(examples: lookup.examples, using: client)
        } catch {
            errorMessage = error.localizedDescription
            isLoading = false
        }
    }

    @MainActor
    private func loadExampleFurigana(examples: [DictionaryExample], using client: APIClient) async {
        var cache = exampleFurigana
        for example in examples {
            guard cache[example.ja] == nil else { continue }
            do {
                cache[example.ja] = try await client.furigana(text: example.ja)
            } catch {
                // Keep plain Japanese text if furigana fails.
            }
        }
        exampleFurigana = cache
    }

    @MainActor
    private func save() async {
        guard let result, let client, canSave else { return }
        let meaning = (result.meaning ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !meaning.isEmpty else {
            vocabularyError = "释义不能为空。"
            return
        }
        isSaving = true
        vocabularyError = nil
        defer { isSaving = false }
        do {
            // Persist the memory hook (not source sentence) as `context`, plus one
            // example sentence so the word can later be reviewed as a cloze blank.
            let example = result.examples.first
            let saved = try await client.addVocabulary(
                word: word,
                reading: result.reading,
                meaning: meaning,
                partOfSpeech: result.partOfSpeech,
                context: result.memoryHint,
                exampleJA: example?.ja,
                exampleZH: example?.zh
            )
            withAnimation(.easeOut(duration: 0.2)) {
                wasAlreadySaved = saved.alreadySaved
                savedToVocabulary = true
            }
        } catch {
            vocabularyError = error.localizedDescription
        }
    }
}

#Preview {
    WordLookupSheet(word: "食べる")
        .environmentObject(AppConfiguration())
}
