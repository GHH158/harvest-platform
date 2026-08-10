import SwiftUI

/// §5.17: the explanation comes up from the bottom over whatever you were reading or
/// watching, and closing it puts you back exactly where you were. Pushing a screen for
/// this used to tear down the player and lose the reading position, which is why the
/// reader carried extra state just to restore itself afterwards.
struct CompanionSheet: View {
    let request: CompanionRequest
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            CompanionView(
                materialID: request.materialID,
                segment: request.segment,
                focusText: request.focusText
            )
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                        .font(.subheadline.weight(.semibold))
                }
            }
        }
        // Opens at half height so the sentence behind it stays visible — the answer is
        // about that sentence, and hiding it forces you to remember what you asked.
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .presentationBackground(DesignTokens.canvas)
    }
}
