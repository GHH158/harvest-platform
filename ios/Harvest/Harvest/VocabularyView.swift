import SwiftUI

struct VocabularyView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var words: [VocabularyWord] = []
    @State private var errorMessage: String?
    @State private var isLoading = false
    @State private var showingReview = false
    /// Avoid hitting /vocabulary until the user opens this tab.
    var isActive: Bool = true

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    var body: some View {
        Group {
            if isLoading && words.isEmpty {
                WarmEmptyState(
                    title: "加载中",
                    systemImage: "bookmark"
                )
            } else if words.isEmpty {
                WarmEmptyState(
                    title: "还没有生词",
                    systemImage: "bookmark",
                    message: "阅读、陪读或聊天时点一下不认识的日语词，在查词卡片里选「加入生词表」"
                )
            } else {
                VStack(spacing: 0) {
                    if !dueWords.isEmpty { dueBanner }
                    wordList
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("生词")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showingReview = true
                } label: {
                    Label("复习", systemImage: "rectangle.on.rectangle")
                }
                .disabled(words.isEmpty)
            }
        }
        .task(id: "\(configuration.endpoint?.absoluteString ?? "")-\(isActive)") {
            guard isActive else { return }
            await load()
        }
        .refreshable { await load() }
        .sheet(isPresented: $showingReview, onDismiss: { Task { await load() } }) {
            VocabularyReviewView()
                .environmentObject(configuration)
        }
        .overlay(alignment: .bottom) {
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .padding(.horizontal, DesignTokens.pageInset)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity)
                    .background(DesignTokens.surface.opacity(0.96))
            }
        }
    }

    /// Words the backend considers due. An unparseable timestamp counts as due, which
    /// matches the server storing `now()` for a freshly saved word.
    private var dueWords: [VocabularyWord] {
        let now = Date()
        return words.filter { word in
            guard let due = parseServerTimestamp(word.nextReviewAt) else { return true }
            return due <= now
        }
    }

    /// Spaced repetition only works if you can tell something is waiting. Plain state,
    /// no streak or score — §1.4 rules out gamification, not showing what is there.
    private var dueBanner: some View {
        Button {
            showingReview = true
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "rectangle.on.rectangle")
                    .foregroundStyle(DesignTokens.accent)
                Text("\(dueWords.count) 个词到期")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(DesignTokens.ink)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(DesignTokens.muted)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: 14))
            .overlay {
                RoundedRectangle(cornerRadius: 14)
                    .stroke(DesignTokens.accent.opacity(0.18), lineWidth: 0.5)
            }
        }
        .buttonStyle(.plain)
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.top, 12)
        .accessibilityLabel("\(dueWords.count) 个词到期，去复习")
    }

    private var wordList: some View {
        List {
            ForEach(words) { word in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(word.word)
                            .font(.system(.body, design: .serif))
                            .foregroundStyle(DesignTokens.ink)
                        if let reading = word.reading, !reading.isEmpty {
                            Text(reading)
                                .font(.subheadline)
                                .foregroundStyle(DesignTokens.accent)
                        }
                        Spacer()
                        if let pos = word.partOfSpeech, !pos.isEmpty {
                            Text(pos)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(DesignTokens.muted)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(DesignTokens.surface, in: Capsule())
                        }
                    }
                    Text(word.meaning)
                        .font(.subheadline)
                        .foregroundStyle(DesignTokens.ink)
                        .lineLimit(3)
                        .lineSpacing(2)
                    if let context = word.context, !context.isEmpty {
                        Text(context)
                            .font(.caption)
                            .foregroundStyle(DesignTokens.muted)
                            .lineLimit(2)
                    }
                }
                .padding(.vertical, 4)
                .listRowBackground(DesignTokens.canvas)
            }
            .onDelete { offsets in
                Task { await delete(at: offsets) }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }

    @MainActor
    private func load() async {
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            return
        }
        isLoading = true
        errorMessage = nil
        do {
            words = try await client.listVocabulary()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    @MainActor
    private func delete(at offsets: IndexSet) async {
        guard let client else { return }
        // Snapshot first — removing while iterating IndexSet shifts indices.
        let targets = offsets.sorted(by: >).map { words[$0] }
        for word in targets {
            do {
                try await client.deleteVocabulary(id: word.id)
                words.removeAll { $0.id == word.id }
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}

#Preview {
    NavigationStack {
        VocabularyView()
            .environmentObject(AppConfiguration())
    }
}
