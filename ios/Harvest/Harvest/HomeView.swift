import SwiftUI

/// The app opens here. No bottom tab bar: one clean surface you enter everything
/// from. Tapping is deliberately the primary way to move around — a natural-language
/// command box would cost a model call for things a single tap already does
/// reliably. §17 retired the standalone ask field that used to be the exception here;
/// anything you cannot tap your way to now goes to the chat teacher, which is the
/// headline entry below.
///
/// Rebuilt 2026-08-10 after real use. It had grown four different visual treatments in
/// one screen — a bordered card, tinted rows with accent icons, and two bare text lines —
/// and the two bare lines looked identical while meaning completely different things
/// (resume your learning vs. a private entry with nothing to do with Japanese). Now
/// everything is one form: text, separated by whitespace and grouping rather than by
/// boxes, which is what §1.5 asks for.
///
/// The animation is not decoration either. §1.5 requires state changes to keep time
/// continuity, and this screen had none: counts arrived asynchronously and popped in.
struct HomeView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var counts = HomeCounts()
    /// §5.18. Nil means there is nothing worth saying, and then nothing is shown.
    @State private var resume: ResumeHint?
    /// Already fetched for the grammar count; kept so the resume line can open the
    /// actual point instead of dropping you on the list to find it again.
    @State private var grammarPoints: [GrammarPoint] = []
    /// Drives the staggered entrance. Set once, after the first frame.
    @State private var hasAppeared = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                resumeLine
                chatCard
                destinations
                journalEntry
            }
            .padding(.horizontal, DesignTokens.pageInset)
            .padding(.top, 10)
            .padding(.bottom, 40)
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
            case .materials: MaterialListView()
            case .chat: ChatView()
            case .accumulation: AccumulationView()
            case .journal: JournalView()
            case let .material(materialID): ReaderView(materialID: materialID)
            case let .grammar(point): GrammarDetailView(point: point)
            case .settings: SettingsView(isOnboarding: false)
            case let .questions(materialID, materialTitle):
                ReadingQuestionListView(materialID: materialID, materialTitle: materialTitle)
            case let .chatForMaterial(materialID): ChatView(initialMaterialID: materialID)
            }
        }
        .task {
            await loadCounts()
            withAnimation(.easeOut(duration: 0.34)) { hasAppeared = true }
        }
    }

    // MARK: - Rows

    /// §5.18, and now the first thing on the screen: opening the app, "where was I" comes
    /// before "what could I do". Set in body text with the material name after a middot —
    /// it is a statement about where you stopped, never a verdict about how long ago.
    @ViewBuilder private var resumeLine: some View {
        if let resume, let destination = resumeDestination(resume) {
            NavigationLink(value: destination) {
                HStack(spacing: 6) {
                    Text(resumeText(resume))
                        .font(.system(size: 17, design: .serif))
                        .foregroundStyle(DesignTokens.ink)
                        .lineLimit(1)
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(DesignTokens.accent.opacity(0.7))
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(SoftPressStyle())
            .padding(.bottom, 26)
            .entrance(hasAppeared, order: 0)
        }
    }

    /// §17: 聊天是唯一的问答入口了(独立提问退场),所以它占这个位置——正门仍然是一句
    /// 招呼,而不是一列目录(§1.5)。版式沿用原来的 `askCard`:标题大一号、不加卡片框。
    /// 故意不显示话题计数——头条是邀请,不是仪表盘(§1.4);计数留在下面那两行里。
    private var chatCard: some View {
        NavigationLink(value: HomeDestination.chat) {
            VStack(alignment: .leading, spacing: 6) {
                Text("今天想聊点什么？")
                    .font(.system(size: 27, design: .serif))
                    .foregroundStyle(DesignTokens.ink)
                Text("用日语说说话，随手纠错")
                    .font(.subheadline)
                    .foregroundStyle(DesignTokens.muted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(SoftPressStyle())
        .padding(.bottom, 30)
        .entrance(hasAppeared, order: 1)
    }

    private var destinations: some View {
        VStack(alignment: .leading, spacing: 20) {
            row(.materials, title: "素材", caption: "读过的文章和视频",
                detail: counts.materials.map { "\($0) 篇" }, order: 2)
            row(.accumulation, title: "积累", caption: "撞见过的词和语法",
                detail: counts.accumulationDetail, order: 3)
        }
    }

    private func row(
        _ destination: HomeDestination,
        title: String,
        caption: String,
        detail: String?,
        order: Int
    ) -> some View {
        NavigationLink(value: destination) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 19, design: .serif))
                        .foregroundStyle(DesignTokens.ink)
                    Text(caption)
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.muted)
                }
                Spacer(minLength: 8)
                if let detail {
                    // Plain counts only. §1.4 rules out progress bars, streaks and
                    // achievements; an empty shelf is allowed to just read as empty.
                    // Fades in when it arrives instead of popping (§1.5).
                    Text(detail)
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.muted)
                        .transition(.opacity)
                        .id(detail)
                }
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(DesignTokens.muted.opacity(0.5))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(SoftPressStyle())
        .entrance(hasAppeared, order: order)
    }

    /// §14, placed as §5.16 requires: on the home screen but deliberately quiet — no card,
    /// no icon, no count, and set well apart from the three learning rows.
    ///
    /// It used to look exactly like the resume line above, which was the worst of the old
    /// screen's problems: the same shape for "carry on studying" and for "somewhere with
    /// nothing to do with Japanese". Now it sits alone under a hairline, right-aligned,
    /// with no chevron — a different gesture entirely.
    private var journalEntry: some View {
        VStack(spacing: 0) {
            Rectangle()
                .fill(DesignTokens.separator)
                .frame(height: 0.5)
                .padding(.top, 34)
            NavigationLink(value: HomeDestination.journal) {
                Text("说点别的")
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .padding(.top, 14)
                    .contentShape(Rectangle())
            }
            .buttonStyle(SoftPressStyle())
        }
        .entrance(hasAppeared, order: 5)
    }

    // MARK: - Copy

    private func resumeText(_ hint: ResumeHint) -> String {
        guard hint.isMaterial else {
            // Stating the state the learner themselves controls (§12 has exactly three),
            // not grading them for it.
            let name = hint.titleJA ?? hint.grammarKey ?? "有个语法点"
            return "\(name) 撞见过，还没弄懂"
        }
        let position: String
        if hint.materialKind == "reading", let number = hint.sentenceNumber {
            position = "上次读到第 \(number) 句"
        } else {
            position = "上次停在 \(clockText(hint.positionMS ?? 0))"
        }
        guard let title = hint.title, !title.isEmpty else { return position }
        return "\(position) · \(shortened(title))"
    }

    private func resumeDestination(_ hint: ResumeHint) -> HomeDestination? {
        if hint.isMaterial {
            return hint.materialID.map(HomeDestination.material)
        }
        guard let key = hint.grammarKey else { return nil }
        // Falling back to the 积累 page rather than nowhere: one more tap is still better
        // than a line that does not respond.
        guard let point = grammarPoints.first(where: { $0.key == key }) else { return .accumulation }
        return .grammar(point)
    }

    private func clockText(_ milliseconds: Int) -> String {
        let total = max(0, milliseconds) / 1_000
        let hours = total / 3_600
        let minutes = (total % 3_600) / 60
        let seconds = total % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, seconds)
        }
        return String(format: "%d:%02d", minutes, seconds)
    }

    /// Titles are derived from the opening words of the material, so they can run long.
    private func shortened(_ title: String) -> String {
        title.count <= 14 ? title : String(title.prefix(14)) + "…"
    }

    @MainActor private func loadCounts() async {
        guard let endpoint = configuration.endpoint else { return }
        // Counts are decoration on a working launcher: a failure here must leave the
        // rows tappable, so nothing is surfaced as an error.
        let client = APIClient(baseURL: endpoint)
        async let materials = try? client.materials()
        async let vocabulary = try? client.listVocabulary()
        async let grammar = try? client.listGrammar()
        // §5.18 rides along in the same batch. Same failure policy as the counts: if it
        // does not come back the line simply is not there.
        async let hint = try? client.resumeHint()
        let points = await grammar
        let loaded = HomeCounts(
            materials: await materials?.count,
            vocabulary: await vocabulary?.count,
            grammarNeedsAttention: points?.filter(\.requiresAttention).count
        )
        let loadedHint = (await hint) ?? nil
        grammarPoints = points ?? []
        withAnimation(.easeOut(duration: 0.28)) {
            counts = loaded
            resume = loadedHint
        }
    }
}

/// Fade plus a small rise, staggered by position. Deliberately short and without any
/// bounce or scale: §1.5 wants motion that explains where something came from, not motion
/// that draws attention to itself.
private struct EntranceModifier: ViewModifier {
    let isVisible: Bool
    let order: Int

    func body(content: Content) -> some View {
        content
            .opacity(isVisible ? 1 : 0)
            .offset(y: isVisible ? 0 : 8)
            .animation(
                .easeOut(duration: 0.34).delay(Double(order) * 0.05),
                value: isVisible
            )
    }
}

private extension View {
    func entrance(_ isVisible: Bool, order: Int) -> some View {
        modifier(EntranceModifier(isVisible: isVisible, order: order))
    }
}

/// Press feedback for rows that have no background of their own: the text warms toward the
/// accent and settles back. iOS's default is to grey the whole block, which on a screen
/// made only of text reads as the text breaking rather than as a press.
private struct SoftPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.55 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

enum HomeDestination: Hashable {
    case materials
    case chat
    case accumulation
    case journal
    /// §5.18 opens the material itself rather than the list, so the line actually takes
    /// you back to where you stopped. Not `Int` as its own destination type: the material
    /// list already claims `Int` in this same stack.
    case material(Int)
    case grammar(GrammarPoint)
    case settings
    /// §16: the flagged-questions list for one material.
    case questions(materialID: Int, materialTitle: String)
    /// §16: "去问老师" — a chat session pre-loaded with one material's flagged questions.
    case chatForMaterial(Int)
}

struct HomeCounts {
    var materials: Int?
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
