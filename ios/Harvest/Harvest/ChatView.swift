import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var messages: [ConversationMessage] = []
    @State private var draft = ""
    @State private var errorMessage: String?
    @State private var isSending = false
    private let sessionID = "personal"

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    if messages.isEmpty {
                        Text("从一句简单的日语开始。")
                            .font(.system(.title2, design: .serif))
                            .foregroundStyle(DesignTokens.ink)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.top, 40)
                    }
                    ForEach(messages) { message in
                        Text(message.content)
                            .foregroundStyle(message.role == "user" ? Color.white : DesignTokens.ink)
                            .padding(12)
                            .background(message.role == "user" ? DesignTokens.accent : DesignTokens.surface, in: RoundedRectangle(cornerRadius: 14))
                            .frame(maxWidth: .infinity, alignment: message.role == "user" ? .trailing : .leading)
                    }
                }
                .padding(DesignTokens.pageInset)
            }
            if let errorMessage { Text(errorMessage).font(.footnote).foregroundStyle(DesignTokens.accent).padding(.horizontal, DesignTokens.pageInset) }
            HStack(spacing: 10) {
                TextField("用日语说点什么", text: $draft, axis: .vertical)
                    .padding(12).background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                Button("发送") { Task { await send() } }.disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSending).foregroundStyle(DesignTokens.accent)
            }
            .padding(DesignTokens.pageInset)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("聊天老师")
        .task { await load() }
    }

    @MainActor private func load() async {
        guard let endpoint = configuration.endpoint else { return }
        do { messages = try await APIClient(baseURL: endpoint).chat(sessionID: sessionID) } catch { errorMessage = error.localizedDescription }
    }

    @MainActor private func send() async {
        guard let endpoint = configuration.endpoint else { return }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        isSending = true; defer { isSending = false }
        do { let reply = try await APIClient(baseURL: endpoint).sendChat(sessionID: sessionID, message: text); messages += [reply.user, reply.assistant]; draft = ""; errorMessage = nil } catch { errorMessage = error.localizedDescription }
    }
}
