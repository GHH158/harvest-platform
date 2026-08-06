import SwiftUI

/// Cloze-style spaced-repetition review: blank the word out of its example sentence,
/// have the user type it back, then self-mark before the server reschedules the word.
struct VocabularyReviewView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @Environment(\.dismiss) private var dismiss
    @State private var queue: [VocabularyWord] = []
    @State private var index = 0
    @State private var answer = ""
    @State private var revealed = false
    @State private var isCorrect = false
    @State private var isLoading = true
    @State private var isSubmitting = false
    @State private var errorMessage: String?
    @State private var reviewedCount = 0
    @FocusState private var isAnswerFocused: Bool

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    private var current: VocabularyWord? {
        index < queue.count ? queue[index] : nil
    }

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView("正在加载复习内容")
                        .tint(DesignTokens.accent)
                        .foregroundStyle(DesignTokens.muted)
                } else if let current {
                    cardView(current)
                } else {
                    completionView
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(DesignTokens.canvas)
            .navigationTitle("复习")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("结束") { dismiss() }
                        .foregroundStyle(DesignTokens.accent)
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
        }
        .task { await load() }
    }

    @ViewBuilder
    private func cardView(_ word: VocabularyWord) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("第 \(index + 1) / \(queue.count) 个 · 已复习 \(reviewedCount)")
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)

                promptCard(word)

                if !revealed {
                    answerInput
                } else {
                    resultSection(word)
                }
            }
            .padding(DesignTokens.pageInset)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .scrollDismissesKeyboard(.interactively)
        .onAppear { isAnswerFocused = true }
    }

    private func promptCard(_ word: VocabularyWord) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let sentence = clozeSentence(word) {
                Text("补全句子里的空白")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(DesignTokens.muted)
                Text(sentence)
                    .font(.system(.title3, design: .serif))
                    .foregroundStyle(DesignTokens.ink)
                    .lineSpacing(6)
                if revealed, let zh = word.exampleZH {
                    Text(zh)
                        .font(.subheadline)
                        .foregroundStyle(DesignTokens.muted)
                }
            } else {
                Text("这个词是什么意思？")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(DesignTokens.muted)
                Text(word.word)
                    .font(.system(.largeTitle, design: .serif))
                    .foregroundStyle(DesignTokens.ink)
                if revealed {
                    Text(word.meaning)
                        .font(.subheadline)
                        .foregroundStyle(DesignTokens.muted)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 16))
        .overlay {
            RoundedRectangle(cornerRadius: 16)
                .stroke(DesignTokens.separator, lineWidth: 0.5)
        }
    }

    private var answerInput: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextField("输入这个词", text: $answer)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($isAnswerFocused)
                .padding(.horizontal, 12)
                .padding(.vertical, 11)
                .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                .overlay {
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(DesignTokens.separator, lineWidth: 0.5)
                }
                .submitLabel(.done)
                .onSubmit { reveal() }

            HStack(spacing: 10) {
                Button("不记得了") {
                    answer = ""
                    reveal(forceIncorrect: true)
                }
                .buttonStyle(.bordered)
                .tint(DesignTokens.muted)

                Button("提交", action: { reveal() })
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private func resultSection(_ word: VocabularyWord) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: isCorrect ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(isCorrect ? Color.green : DesignTokens.accent)
                Text(isCorrect ? "答对了" : "答案是")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(isCorrect ? Color.green : DesignTokens.accent)
            }
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(word.word)
                        .font(.system(.title2, design: .serif))
                        .foregroundStyle(DesignTokens.ink)
                    if let reading = word.reading, !reading.isEmpty {
                        Text(reading)
                            .font(.subheadline)
                            .foregroundStyle(DesignTokens.accent)
                    }
                }
                Text(word.meaning)
                    .font(.body)
                    .foregroundStyle(DesignTokens.ink)
            }
            Button(isSubmitting ? "正在提交…" : "下一个") {
                Task { await advance(word: word) }
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(isSubmitting)
        }
    }

    private var completionView: some View {
        VStack(spacing: 14) {
            Image(systemName: "checkmark.seal")
                .font(.system(size: 40))
                .foregroundStyle(DesignTokens.accent)
            Text(queue.isEmpty ? "暂时没有需要复习的词" : "今天的复习完成了")
                .font(.headline)
                .foregroundStyle(DesignTokens.ink)
            if reviewedCount > 0 {
                Text("复习了 \(reviewedCount) 个词")
                    .font(.subheadline)
                    .foregroundStyle(DesignTokens.muted)
            }
            Button("完成") { dismiss() }
                .buttonStyle(PrimaryButtonStyle())
                .padding(.top, 8)
        }
        .padding(DesignTokens.pageInset)
        .frame(maxWidth: .infinity)
    }

    /// Blanks the target word out of its example sentence. Falls back to a bare
    /// word/meaning card when no example was saved with this entry.
    private func clozeSentence(_ word: VocabularyWord) -> String? {
        guard let example = word.exampleJA, let range = example.range(of: word.word) else { return nil }
        return example.replacingCharacters(in: range, with: "＿＿＿＿")
    }

    private func matches(_ input: String, word: VocabularyWord) -> Bool {
        guard !input.isEmpty else { return false }
        if input == word.word { return true }
        if let reading = word.reading, !reading.isEmpty, input == reading { return true }
        return false
    }

    private func reveal(forceIncorrect: Bool = false) {
        guard let word = current else { return }
        let trimmed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        isCorrect = !forceIncorrect && matches(trimmed, word: word)
        revealed = true
        isAnswerFocused = false
    }

    @MainActor
    private func advance(word: VocabularyWord) async {
        guard let client else { return }
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            _ = try await client.submitVocabularyReview(id: word.id, correct: isCorrect)
            reviewedCount += 1
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        index += 1
        answer = ""
        revealed = false
    }

    @MainActor
    private func load() async {
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            isLoading = false
            return
        }
        do {
            queue = try await client.reviewDueVocabulary()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}

#Preview {
    VocabularyReviewView()
        .environmentObject(AppConfiguration())
}
