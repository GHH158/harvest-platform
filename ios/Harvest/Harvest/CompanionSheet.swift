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
        // Two thirds, not half: the sheet prints the sentence at its own top, so the
        // page's copy behind it does not need to stay visible and the extra third goes
        // to the answer. Drag up for full height when a reply is long.
        .presentationDetents([.fraction(0.66), .large])
        .presentationDragIndicator(.visible)
        .presentationBackground(DesignTokens.canvas)
    }
}
