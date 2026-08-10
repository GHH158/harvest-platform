import SwiftUI

/// The app opens here. No bottom tab bar: one clean surface you enter everything
/// from. Tapping is deliberately the primary way to move around — a natural-language
/// command box would cost a model call for things a single tap already does
/// reliably. The ask field is the one exception, because "why is this sentence like
/// this" is not something you can tap your way to (§5.16).
struct HomeView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var counts = HomeCounts()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                askCard
                destinations
                journalEntry
            }
            .padding(.horizontal, DesignTokens.pageInset)
            .padding(.top, 8)
            .padding(.bottom, 32)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("Harvest")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink(value: HomeDestination.settings) {
                    Image(systemName: "gearshape")
                }
                .accessibilityLabel("设置")
            }
        }
        .navigationDestination(for: HomeDestination.self) { destination in
            switch destination {
            case .ask: AskView()
            case .materials: MaterialListView()
            case .chat: ChatView()
            case .accumulation: AccumulationView()
            case .journal: JournalView()
            case .settings: SettingsView(isOnboarding: false)
            }
        }
        .task { await loadCounts() }
    }

    private var askCard: some View {
        NavigationLink(value: HomeDestination.ask) {
            VStack(alignment: .leading, spacing: 8) {
                Text("有哪里卡住了？")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(DesignTokens.ink)
                Text("课本上的一句话、一个词，或者任何想不通的地方")
                    .font(.subheadline)
                    .foregroundStyle(DesignTokens.muted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 16))
            .overlay {
                RoundedRectangle(cornerRadius: 16).stroke(DesignTokens.accent.opacity(0.35), lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
    }

    private var destinations: some View {
        VStack(spacing: 10) {
            row(.materials, icon: "text.book.closed", title: "素材",
                caption: "读过的文章与视频", detail: counts.materials.map { "\($0) 篇" })
            row(.chat, icon: "bubble.left.and.bubble.right", title: "聊天",
                caption: "用日语说，即时纠错", detail: counts.chatSessions.map { "\($0) 个话题" })
            row(.accumulation, icon: "square.stack.3d.up", title: "积累",
                caption: "生词与语法骨架", detail: counts.accumulationDetail)
        }
    }

    /// §14, placed as §5.16 requires: on the home screen but deliberately quiet. No card,
    /// no icon, no count, and set apart from the three learning rows above — you should
    /// not be reminded that you have something on your mind every time you open the app
    /// to study. A count here would not be information, it would be a nudge.
    private var journalEntry: some View {
        NavigationLink(value: HomeDestination.journal) {
            Text("说点别的")
                .font(.subheadline)
                .foregroundStyle(DesignTokens.muted)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
        }
        .buttonStyle(.plain)
        .padding(.top, 6)
    }

    private func row(
        _ destination: HomeDestination,
        icon: String,
        title: String,
        caption: String,
        detail: String?
    ) -> some View {
        NavigationLink(value: destination) {
            HStack(spacing: 14) {
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundStyle(DesignTokens.accent)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(DesignTokens.ink)
                    Text(caption)
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.muted)
                }
                Spacer(minLength: 8)
                if let detail {
                    // Plain counts only. §1.4 rules out progress bars, streaks and
                    // achievements; an empty shelf is allowed to just read as empty.
                    Text(detail)
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.muted)
                }
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DesignTokens.muted.opacity(0.6))
            }
            .padding(.vertical, 14)
            .padding(.horizontal, 16)
            .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
    }

    @MainActor private func loadCounts() async {
        guard let endpoint = configuration.endpoint else { return }
        // Counts are decoration on a working launcher: a failure here must leave the
        // rows tappable, so nothing is surfaced as an error.
        let client = APIClient(baseURL: endpoint)
        async let materials = try? client.materials()
        async let topics = try? client.chatSessions()
        async let vocabulary = try? client.listVocabulary()
        async let grammar = try? client.listGrammar()
        counts = HomeCounts(
            materials: await materials?.count,
            chatSessions: await topics?.count,
            vocabulary: await vocabulary?.count,
            grammarNeedsAttention: await grammar?.filter(\.requiresAttention).count
        )
    }
}

enum HomeDestination: Hashable {
    case ask
    case materials
    case chat
    case accumulation
    case journal
    case settings
}

struct HomeCounts {
    var materials: Int?
    var chatSessions: Int?
    var vocabulary: Int?
    var grammarNeedsAttention: Int?

    /// Two facts in one line, and each disappears when it has nothing to say.
    var accumulationDetail: String? {
        var parts: [String] = []
        if let vocabulary, vocabulary > 0 { parts.append("\(vocabulary) 个词") }
        if let grammarNeedsAttention, grammarNeedsAttention > 0 {
            parts.append("\(grammarNeedsAttention) 个点需要留意")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}
