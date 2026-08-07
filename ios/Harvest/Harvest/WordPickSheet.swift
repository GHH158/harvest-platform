import SwiftUI

/// Fallback when clipboard is empty: type a word to look up.
struct WordPickSheet: View {
    var initialWord: String = ""
    let onPick: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var customWord = ""
    @FocusState private var isFocused: Bool

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                Text("在正文或消息里点一下日语词就能直接查。这里适合查点不中的词组，或者不在当前页面的词。")
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
                    .lineSpacing(4)

                HStack(spacing: 10) {
                    TextField("例如 美味しい", text: $customWord)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($isFocused)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 11)
                        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                        .overlay {
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(DesignTokens.separator, lineWidth: 0.5)
                        }
                        .submitLabel(.go)
                        .onSubmit { submit() }

                    Button("查询", action: submit)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 11)
                        .background(
                            DesignTokens.accent.opacity(canSubmit ? 1 : 0.45),
                            in: Capsule()
                        )
                        .disabled(!canSubmit)
                }

                Spacer()
            }
            .padding(DesignTokens.pageInset)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(DesignTokens.canvas)
            .navigationTitle("查词")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("取消") { dismiss() }
                        .foregroundStyle(DesignTokens.accent)
                }
            }
            .onAppear {
                if customWord.isEmpty { customWord = initialWord }
                isFocused = true
            }
        }
        .presentationDetents([.height(240), .medium])
        .presentationDragIndicator(.visible)
    }

    private var canSubmit: Bool {
        !customWord.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func submit() {
        let word = customWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !word.isEmpty else { return }
        onPick(word)
    }
}

#Preview {
    WordPickSheet { _ in }
}
