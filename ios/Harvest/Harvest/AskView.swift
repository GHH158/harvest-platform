import SwiftUI

/// §5.16: ask about anything without a material behind it — a textbook sentence, a
/// word, a doubt. Nothing is ever pre-filled here; the angles are what tell you what
/// kinds of answer are available (§11.9).
struct AskView: View {
    @EnvironmentObject private var configuration: AppConfiguration

    @State private var messages: [ConversationMessage] = []
    @State private var draft = ""
    @State private var lenses: [QuestionLens] = []
    @State private var isSending = false
    /// Shown the instant you send, before the round trip returns. Without it the text
    /// you just typed disappears into a bare spinner and the answer lands as a wall.
    @State private var pendingQuestion: String?
    @State private var errorMessage: String?
    @FocusState private var isInputFocused: Bool

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    private var trimmed: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        VStack(spacing: 0) {
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
        .navigationTitle("提问")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 26) {
                    if messages.isEmpty {
                        emptyState
                    }
                    ForEach(messages) { message in
                        AskBubble(message: message)
                            .id(message.id)
                    }
                    if let pendingQuestion {
                        AskQuestionBubble(text: pendingQuestion)
                            .id("pending-question")
                    }
                    if isSending {
                        HStack(spacing: 9) {
                            ProgressView()
                                .controlSize(.small)
                                .tint(DesignTokens.accent)
                            Text("老师正在整理…")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                        }
                        .id("pending-answer")
                    }
                }
                // Narrower than the standard page inset: with no card around the answer
                // this is the only thing setting line length, and long CJK explanations
                // want the width.
                .padding(.horizontal, 18)
                .padding(.vertical, 18)
            }
            .onChange(of: messages.count) {
                guard let last = messages.last else { return }
                withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
            }
            .onChange(of: pendingQuestion) {
                guard pendingQuestion != nil else { return }
                withAnimation { proxy.scrollTo("pending-answer", anchor: .bottom) }
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("把卡住的地方贴进来")
                .font(.title3.weight(.semibold))
                .foregroundStyle(DesignTokens.ink)
            Text("课本上的一句话、一个词都行。选一个角度直接问，或者自己写问题。")
                .font(.subheadline)
                .foregroundStyle(DesignTokens.muted)
        }
        .padding(.top, 24)
    }

    /// With text in the field an angle asks *about that text*; with the field empty
    /// there is nothing to aim at, so the angles wait rather than sending a bare
    /// question with no subject.
    private var lensBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(lenses) { lens in
                    Button {
                        Task { await send(lens: lens.id) }
                    } label: {
                        Text(lens.labelZH)
                            .font(.subheadline)
                            .padding(.horizontal, 13)
                            .padding(.vertical, 7)
                            .background(DesignTokens.surface, in: Capsule())
                            .overlay { Capsule().stroke(DesignTokens.separator, lineWidth: 0.5) }
                    }
                    .buttonStyle(.plain)
                    .disabled(isSending || trimmed.isEmpty)
                    .opacity(isSending || trimmed.isEmpty ? 0.4 : 1)
                }
            }
            .padding(.horizontal, DesignTokens.pageInset)
        }
        .padding(.top, 10)
    }

    private var composerBar: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("粘贴或输入…", text: $draft, axis: .vertical)
                .lineLimit(1...6)
                .focused($isInputFocused)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 15))
                .overlay {
                    RoundedRectangle(cornerRadius: 15).stroke(DesignTokens.separator, lineWidth: 0.5)
                }

            Button {
                Task { await send(lens: nil) }
            } label: {
                Image(systemName: "arrow.up")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(
                        DesignTokens.accent.opacity(!isSending && !trimmed.isEmpty ? 1 : 0.45),
                        in: Circle()
                    )
            }
            .disabled(isSending || trimmed.isEmpty)
            .accessibilityLabel("提问")
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
    }

    @MainActor private func load() async {
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            return
        }
        messages = (try? await client.askMessages()) ?? []
        lenses = (try? await client.companionLenses()) ?? []
    }

    @MainActor private func send(lens: String?) async {
        let value = trimmed
        guard !isSending, !value.isEmpty, let client else { return }
        isSending = true
        // Echo locally right away. With an angle the server decides the wording, so
        // show the text being asked about rather than guessing the final question.
        pendingQuestion = value
        draft = ""
        isInputFocused = false
        errorMessage = nil
        do {
            let reply = try await client.ask(text: value, lens: lens)
            pendingQuestion = nil
            messages += [reply.user]
            // Let the question settle before the answer arrives, so a long reply reads
            // as a response rather than appearing in the same frame as the question.
            try? await Task.sleep(for: .milliseconds(120))
            withAnimation(.easeOut(duration: 0.18)) {
                messages += [reply.assistant]
            }
        } catch {
            pendingQuestion = nil
            draft = value
            errorMessage = error.localizedDescription
        }
        isSending = false
    }
}

/// The question is short, so it reads as a card. The answer is long, so it does not:
/// a card around several hundred characters costs line width on both sides and adds a
/// second frame around content that is already structured. The answer is the page.
private struct AskBubble: View {
    let message: ConversationMessage

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        if isUser {
            AskQuestionBubble(text: message.content)
        } else {
            MarkdownMessageView(markdown: message.content)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct AskQuestionBubble: View {
    let text: String

    var body: some View {
        Text(text)
            .foregroundStyle(DesignTokens.ink)
            .lineSpacing(4)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 11)
            .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: 14))
    }
}
