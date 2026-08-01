import SwiftUI

struct CompanionView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    let materialID: Int
    let segment: Segment
    let focusText: String?
    @State private var messages: [ConversationMessage] = []
    @State private var question = ""
    @State private var errorMessage: String?
    @State private var isSending = false

    init(materialID: Int, segment: Segment, focusText: String? = nil) {
        self.materialID = materialID
        self.segment = segment
        self.focusText = focusText
        if let focusText {
            _question = State(initialValue: "请解释「\(focusText)」在这句话里的意思和用法。")
        }
    }

    var body: some View {
        VStack(spacing: 14) {
            Text(segment.textJA)
                .font(.system(.title3, design: .serif))
                .foregroundStyle(DesignTokens.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let focusText {
                Text("正在问：\(focusText)")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DesignTokens.accent)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(messages) { message in
                        Text(message.content)
                            .padding(12)
                            .background(message.role == "user" ? DesignTokens.accentWash : DesignTokens.surface,
                                        in: RoundedRectangle(cornerRadius: 12))
                            .frame(maxWidth: .infinity, alignment: message.role == "user" ? .trailing : .leading)
                    }
                }
            }
            if let errorMessage { Text(errorMessage).font(.footnote).foregroundStyle(DesignTokens.accent) }
            HStack {
                TextField("这句哪里不明白？", text: $question, axis: .vertical)
                    .padding(12).background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                Button("提问") { Task { await send() } }
                    .disabled(question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSending)
                    .foregroundStyle(DesignTokens.accent)
            }
        }
        .padding(DesignTokens.pageInset)
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("陪读")
        .task { await load() }
    }

    @MainActor private func load() async {
        guard let endpoint = configuration.endpoint else { return }
        do { messages = try await APIClient(baseURL: endpoint).companion(materialID: materialID) }
        catch { errorMessage = error.localizedDescription }
    }

    @MainActor private func send() async {
        guard let endpoint = configuration.endpoint else { return }
        let value = question.trimmingCharacters(in: .whitespacesAndNewlines)
        isSending = true; defer { isSending = false }
        do {
            let reply = try await APIClient(baseURL: endpoint).sendCompanion(
                materialID: materialID, segmentID: segment.id, question: value
            )
            messages += [reply.user, reply.assistant]
            question = ""; errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }
}
