import SwiftUI

/// Holds the two things that settle out of real use: words you looked up, and grammar
/// points you ran into. They share a tab rather than adding a sixth one — §1.5 asks for
/// restraint in the navigation bar, and the two are the same idea at different grain.
struct AccumulationView: View {
    private enum Shelf: String, CaseIterable, Identifiable {
        case vocabulary = "生词"
        case grammar = "语法"
        var id: String { rawValue }
    }

    @State private var shelf: Shelf = .vocabulary
    var isActive: Bool = true

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $shelf) {
                ForEach(Shelf.allCases) { item in
                    Text(item.rawValue).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, DesignTokens.pageInset)
            .padding(.top, 8)
            .padding(.bottom, 10)

            switch shelf {
            case .vocabulary:
                VocabularyView(isActive: isActive && shelf == .vocabulary)
            case .grammar:
                GrammarView(isActive: isActive && shelf == .grammar)
            }
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("积累")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(for: GrammarPoint.self) { point in
            GrammarDetailView(point: point)
        }
    }
}
