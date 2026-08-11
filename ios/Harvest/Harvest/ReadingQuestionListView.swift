import SwiftUI

/// §16: the flagged-questions list for one material — what you collected while reading
/// or watching, waiting to be worked through with the chat teacher in one batch.
struct ReadingQuestionListView: View {
    let materialID: Int
    let materialTitle: String
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var questions: [ReadingQuestion] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var editingQuestion: ReadingQuestion?
    @State private var noteDraft = ""

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    private var pending: [ReadingQuestion] {
        questions.filter { !$0.isArchived }
    }

    private var archived: [ReadingQuestion] {
        questions.filter { $0.isArchived }
    }

    var body: some View {
        Group {
            if isLoading && questions.isEmpty {
                WarmEmptyState(title: "正在打开", systemImage: "tray")
            } else if questions.isEmpty {
                WarmEmptyState(
                    title: "还没有收纳任何疑问",
                    systemImage: "tray",
                    message: "读的时候点一个词或一句话旁边的收纳图标，攒起来的疑问会出现在这里"
                )
            } else {
                list
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(materialTitle)
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom) {
            askTeacherButton
        }
        .task { await load() }
        .refreshable { await load() }
        .alert("改一下备注", isPresented: Binding(get: { editingQuestion != nil }, set: { if !$0 { editingQuestion = nil } })) {
            TextField("为什么不懂（可选）", text: $noteDraft)
            Button("取消", role: .cancel) { editingQuestion = nil }
            Button("保存") {
                if let editingQuestion { Task { await updateNote(editingQuestion) } }
            }
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

    private var list: some View {
        List {
            if !pending.isEmpty {
                Section("待处理 \(pending.count)") {
                    ForEach(pending) { question in row(question) }
                }
            }
            if !archived.isEmpty {
                Section("已归档") {
                    ForEach(archived) { question in row(question) }
                }
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
    }

    private func row(_ question: ReadingQuestion) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(question.excerpt)
                .font(.system(.body, design: .serif))
                .foregroundStyle(DesignTokens.ink)
                .strikethrough(question.isArchived, color: DesignTokens.muted)
            if let note = question.note, !note.isEmpty {
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
            }
        }
        .padding(.vertical, 4)
        .listRowBackground(DesignTokens.canvas)
        .contentShape(Rectangle())
        .onTapGesture {
            editingQuestion = question
            noteDraft = question.note ?? ""
        }
        .swipeActions(edge: .leading) {
            Button {
                Task { await toggleArchived(question) }
            } label: {
                Label(
                    question.isArchived ? "取消归档" : "归档",
                    systemImage: question.isArchived ? "arrow.uturn.backward" : "checkmark"
                )
            }
            .tint(question.isArchived ? DesignTokens.muted : .green)
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                Task { await delete(question) }
            } label: {
                Label("删除", systemImage: "trash")
            }
        }
    }

    /// Disabled on an empty queue — same rule the server enforces (§16), stated here too
    /// so the reason is visible instead of a request that predictably fails.
    private var askTeacherButton: some View {
        VStack(spacing: 6) {
            if pending.isEmpty, !questions.isEmpty {
                Text("待处理的疑问都归档了")
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
            }
            NavigationLink(value: HomeDestination.chatForMaterial(materialID)) {
                Text("去问老师 · \(pending.count) 条")
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(pending.isEmpty)
            .opacity(pending.isEmpty ? 0.45 : 1)
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.vertical, 12)
        .background(DesignTokens.canvas)
    }

    @MainActor
    private func load() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            questions = try await client.readingQuestions(materialID: materialID)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func toggleArchived(_ question: ReadingQuestion) async {
        guard let client else { return }
        do {
            let updated = try await client.setReadingQuestionArchived(id: question.id, archived: !question.isArchived)
            apply(updated)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func updateNote(_ question: ReadingQuestion) async {
        guard let client else { return }
        editingQuestion = nil
        do {
            let updated = try await client.updateReadingQuestionNote(
                id: question.id,
                note: noteDraft.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            apply(updated)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func delete(_ question: ReadingQuestion) async {
        guard let client else { return }
        do {
            try await client.deleteReadingQuestion(id: question.id)
            questions.removeAll { $0.id == question.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func apply(_ updated: ReadingQuestion) {
        guard let index = questions.firstIndex(where: { $0.id == updated.id }) else { return }
        questions[index] = updated
    }
}
