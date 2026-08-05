import NaturalLanguage
import SwiftUI

struct ReaderView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @EnvironmentObject private var offlineLibrary: OfflineLibrary
    let materialID: Int
    @StateObject private var player = AudioPlayer()
    @State private var material: MaterialDetail?
    @State private var errorMessage: String?
    @State private var isLoading = true
    @State private var downloadError: String?
    @State private var isDownloading = false
    private let startsOffline: Bool

    init(materialID: Int) {
        self.materialID = materialID
        startsOffline = false
    }

    init(offlineEntry: OfflineEntry) {
        materialID = offlineEntry.id
        startsOffline = true
        _material = State(initialValue: offlineEntry.material)
        _isLoading = State(initialValue: false)
    }

    var body: some View {
        Group {
            if isLoading {
                WarmEmptyState(title: "正在打开材料", systemImage: "book")
            } else if let errorMessage {
                WarmEmptyState(
                    title: "暂时无法打开",
                    systemImage: "exclamationmark.bubble",
                    message: errorMessage,
                    actionTitle: "再试一次"
                ) {
                    Task { await load() }
                }
            } else if let material {
                reader(material)
            }
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(material?.title ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .task { if !startsOffline { await load() } }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(4))
                guard let material, material.status != "ready", material.status != "failed" else { continue }
                await load(showingProgress: false)
            }
        }
        .onDisappear { player.stop() }
    }

    @ViewBuilder
    private func reader(_ material: MaterialDetail) -> some View {
        if material.status == "failed" {
            ContentUnavailableView {
                Label("这份材料没有准备好", systemImage: "exclamationmark.triangle")
            } description: {
                Text(material.errorMessage ?? "请在 Mac 的摄入页面重新提交。")
            }
        } else if material.status != "ready" || material.audioURL == nil {
            VStack(spacing: 16) {
                ProgressView()
                Text("朗读正在后台准备，稍后再来。")
                    .foregroundStyle(DesignTokens.muted)
            }
        } else {
            if material.kind == "video" { VideoLearningView(material: material) } else { readyReader(material) }
        }
    }

    private func readyReader(_ material: MaterialDetail) -> some View {
        ScrollViewReader { scrollProxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack {
                        if offlineLibrary.localAudioURL(for: material.id) != nil {
                            Label("已下载", systemImage: "arrow.down.circle.fill")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                        } else {
                            Button(isDownloading ? "正在下载" : "下载朗读") {
                                Task { await download(material) }
                            }
                            .disabled(isDownloading)
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(DesignTokens.accent)
                        }
                        Spacer()
                    }
                    if let playbackError = player.errorMessage {
                        Text("朗读播放失败：\(playbackError)")
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.accent)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    if let current = currentSegment(in: material) {
                        HStack(spacing: 18) {
                            NavigationLink("问这一句") {
                                CompanionView(materialID: material.id, segment: current)
                            }
                            NavigationLink("跟读这一句") { ShadowingView(segment: current) }
                        }
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(DesignTokens.accent)
                    }
                    if let downloadError {
                        Text(downloadError)
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.accent)
                    }
                    ForEach(material.segments) { segment in
                        ReadingSentenceView(
                            materialID: material.id,
                            segment: segment,
                            tokens: tokens(for: segment, in: material),
                            playbackPositionMs: player.positionMs,
                            isCurrent: isCurrent(segment),
                            onSelect: { player.seek(to: segment.startMs) }
                        )
                        .id(segment.id)
                    }
                }
                .padding(.horizontal, DesignTokens.pageInset)
                .padding(.top, 28)
                .padding(.bottom, 118)
            }
            .onChange(of: currentSegment(in: material)?.id) { _, currentID in
                guard let currentID else { return }
                withAnimation(.easeInOut(duration: 0.3)) {
                    scrollProxy.scrollTo(currentID, anchor: .center)
                }
            }
            .safeAreaInset(edge: .bottom) {
                PlayerBar(player: player, durationMs: material.durationMs ?? player.durationMs)
            }
        }
        .task(id: playbackURL(for: material)) {
            if let audioURL = playbackURL(for: material) { await player.prepare(url: audioURL) }
        }
    }

    private func playbackURL(for material: MaterialDetail) -> URL? {
        offlineLibrary.localAudioURL(for: material.id) ?? material.audioURL
    }

    @MainActor
    private func download(_ material: MaterialDetail) async {
        isDownloading = true
        defer { isDownloading = false }
        do {
            try await offlineLibrary.download(material)
            downloadError = nil
        } catch {
            downloadError = error.localizedDescription
        }
    }

    private func currentSegment(in material: MaterialDetail) -> Segment? {
        for (index, segment) in material.segments.enumerated() {
            let isLast = index == material.segments.count - 1
            if player.positionMs >= segment.startMs
                && (player.positionMs < segment.endMs || (isLast && player.positionMs <= segment.endMs)) {
                return segment
            }
        }
        return nil
    }

    private func isCurrent(_ segment: Segment) -> Bool {
        guard let material else { return false }
        return currentSegment(in: material)?.id == segment.id
    }

    private func tokens(for segment: Segment, in material: MaterialDetail) -> [Token] {
        material.tokens.filter { $0.segmentID == segment.id }
    }

    @MainActor
    private func load(showingProgress: Bool = true) async {
        guard let endpoint = configuration.endpoint else { return }
        if showingProgress { isLoading = true }
        defer {
            if showingProgress { isLoading = false }
        }
        do {
            material = try await APIClient(baseURL: endpoint).material(id: materialID)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct JapaneseReadingUnit: Identifiable, Equatable {
    let id: Int
    let text: String
    let reading: String?
    let isWord: Bool
    let startMs: Int?
    let endMs: Int?

    func isActive(at milliseconds: Int) -> Bool {
        guard let startMs, let endMs else { return false }
        return milliseconds >= startMs && milliseconds < endMs
    }
}

/// Keeps the most recently-started word active across natural ASR gaps. The
/// containing transcript decides when the sentence stops being current, so a
/// sentence-final word can remain highlighted until the next sentence begins.
func activeReadingUnitID(in units: [JapaneseReadingUnit], at milliseconds: Int) -> Int? {
    units.last { unit in
        unit.isWord && unit.startMs.map { $0 <= milliseconds } == true
    }?.id
}

private struct TimedSourceRange {
    let range: Range<String.Index>
    let token: Token
}

private struct ReadingBoundary {
    let range: Range<String.Index>
    let token: Token?
}

func japaneseReadingUnits(text: String, tokens: [Token]) -> [JapaneseReadingUnit] {
    let tokenizer = NLTokenizer(unit: .word)
    tokenizer.string = text
    tokenizer.setLanguage(.japanese)

    var timedRanges: [TimedSourceRange] = []
    var searchStart = text.startIndex
    for token in tokens {
        guard !token.surface.isEmpty,
              searchStart < text.endIndex,
              let range = text.range(of: token.surface, range: searchStart..<text.endIndex)
        else { continue }
        timedRanges.append(TimedSourceRange(range: range, token: token))
        searchStart = range.upperBound
    }

    var wordRanges: [Range<String.Index>] = []
    tokenizer.enumerateTokens(in: text.startIndex..<text.endIndex) { range, _ in
        wordRanges.append(range)
        return true
    }

    let usesServerWordBoundaries = timedRanges.contains { $0.token.reading != nil }
    var boundaries: [ReadingBoundary]
    if usesServerWordBoundaries {
        boundaries = timedRanges.map { ReadingBoundary(range: $0.range, token: $0.token) }
        boundaries += wordRanges
            .filter { wordRange in !timedRanges.contains(where: { $0.range.overlaps(wordRange) }) }
            .map { ReadingBoundary(range: $0, token: nil) }
        boundaries.sort { $0.range.lowerBound < $1.range.lowerBound }
    } else {
        boundaries = wordRanges.map { ReadingBoundary(range: $0, token: nil) }
    }

    var units: [JapaneseReadingUnit] = []
    var cursor = text.startIndex
    func appendGap(until end: String.Index) {
        guard cursor < end else { return }
        let value = String(text[cursor..<end])
        if !value.isEmpty {
            units.append(
                JapaneseReadingUnit(
                    id: units.count,
                    text: value,
                    reading: nil,
                    isWord: false,
                    startMs: nil,
                    endMs: nil
                )
            )
        }
    }

    for boundary in boundaries {
        let range = boundary.range
        appendGap(until: range.lowerBound)
        let value = String(text[range])
        let matching = timedRanges.filter { $0.range.overlaps(range) }
        let exact = boundary.token ?? matching.first { $0.range == range && $0.token.surface == value }?.token
        units.append(
            JapaneseReadingUnit(
                id: units.count,
                text: value,
                reading: exact?.reading,
                isWord: true,
                startMs: matching.map(\.token.startMs).min(),
                endMs: matching.map(\.token.endMs).max()
            )
        )
        cursor = range.upperBound
    }
    appendGap(until: text.endIndex)
    return units
}

struct ReadingSentenceView: View, Equatable {
    let materialID: Int
    let segment: Segment
    let units: [JapaneseReadingUnit]
    let activeUnitID: Int?
    let isCurrent: Bool
    let onSelect: () -> Void

    init(
        materialID: Int,
        segment: Segment,
        units: [JapaneseReadingUnit],
        activeUnitID: Int?,
        isCurrent: Bool,
        onSelect: @escaping () -> Void
    ) {
        self.materialID = materialID
        self.segment = segment
        self.units = units
        self.activeUnitID = activeUnitID
        self.isCurrent = isCurrent
        self.onSelect = onSelect
    }

    init(
        materialID: Int,
        segment: Segment,
        tokens: [Token],
        playbackPositionMs: Int,
        isCurrent: Bool,
        onSelect: @escaping () -> Void
    ) {
        let units = japaneseReadingUnits(text: segment.textJA, tokens: tokens)
        self.init(
            materialID: materialID,
            segment: segment,
            units: units,
            activeUnitID: isCurrent ? activeReadingUnitID(in: units, at: playbackPositionMs) : nil,
            isCurrent: isCurrent,
            onSelect: onSelect
        )
    }

    nonisolated static func == (lhs: ReadingSentenceView, rhs: ReadingSentenceView) -> Bool {
        lhs.materialID == rhs.materialID
            && lhs.segment == rhs.segment
            && lhs.units == rhs.units
            && lhs.activeUnitID == rhs.activeUnitID
            && lhs.isCurrent == rhs.isCurrent
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ReadingFlowLayout(horizontalSpacing: 2, verticalSpacing: 9) {
                ForEach(units) { unit in
                    if unit.isWord {
                        NavigationLink {
                            CompanionView(materialID: materialID, segment: segment, focusText: unit.text)
                        } label: {
                            ReadingWordLabel(
                                unit: unit,
                                isActive: unit.id == activeUnitID
                            )
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("询问词语：\(unit.text)")
                    } else {
                        ReadingPunctuationLabel(text: unit.text)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if let translation = segment.textZH, !translation.isEmpty {
                Text(translation)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
                    .lineSpacing(3)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 10)
        .background {
            Button(action: onSelect) {
                RoundedRectangle(cornerRadius: 10)
                    .fill(isCurrent ? DesignTokens.accentWash.opacity(0.45) : .clear)
                    .contentShape(RoundedRectangle(cornerRadius: 10))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("从本句开始播放")
        }
        .animation(.easeInOut(duration: 0.24), value: isCurrent)
    }
}

private struct ReadingWordLabel: View {
    let unit: JapaneseReadingUnit
    let isActive: Bool

    var body: some View {
        VStack(spacing: 2) {
            Group {
                if let reading = displayedReading {
                    Text(reading)
                } else {
                    Text("あ").hidden()
                }
            }
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(DesignTokens.muted)

            Text(unit.text)
                .font(.system(size: DesignTokens.readingSize, weight: .regular))
                .foregroundStyle(DesignTokens.ink)
        }
        .padding(.horizontal, 4)
        .padding(.vertical, 3)
        .background(
            isActive ? DesignTokens.accentWash : .clear,
            in: RoundedRectangle(cornerRadius: 7)
        )
        .overlay(alignment: .bottom) {
            Capsule()
                .fill(isActive ? DesignTokens.accent : DesignTokens.accent.opacity(0.18))
                .frame(height: 3)
                .padding(.horizontal, 3)
        }
        .animation(.easeInOut(duration: 0.07), value: isActive)
    }

    private var displayedReading: String? {
        guard unit.text.unicodeScalars.contains(where: { scalar in
            (0x3400...0x4DBF).contains(scalar.value) || (0x4E00...0x9FFF).contains(scalar.value)
        }) else { return nil }
        return unit.reading?.isEmpty == false ? unit.reading : nil
    }
}

private struct ReadingPunctuationLabel: View {
    let text: String

    var body: some View {
        VStack(spacing: 2) {
            Text("あ").font(.system(size: 10)).hidden()
            Text(text)
                .font(.system(size: DesignTokens.readingSize, weight: .regular))
                .foregroundStyle(DesignTokens.ink)
        }
        .padding(.vertical, 3)
    }
}

private struct ReadingFlowLayout: Layout {
    let horizontalSpacing: CGFloat
    let verticalSpacing: CGFloat

    func sizeThatFits(
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) -> CGSize {
        let availableWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var requiredWidth: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > availableWidth {
                y += rowHeight + verticalSpacing
                x = 0
                rowHeight = 0
            }
            requiredWidth = max(requiredWidth, x + size.width)
            x += size.width + horizontalSpacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: proposal.width ?? requiredWidth, height: y + rowHeight)
    }

    func placeSubviews(
        in bounds: CGRect,
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                y += rowHeight + verticalSpacing
                x = bounds.minX
                rowHeight = 0
            }
            subview.place(
                at: CGPoint(x: x, y: y),
                anchor: .topLeading,
                proposal: ProposedViewSize(size)
            )
            x += size.width + horizontalSpacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

private struct PlayerBar: View {
    @ObservedObject var player: AudioPlayer
    let durationMs: Int

    var body: some View {
        VStack(spacing: 12) {
            ProgressView(value: progress)
                .tint(DesignTokens.accent)
            HStack(spacing: 16) {
                Text(time(player.positionMs))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(DesignTokens.muted)
                Spacer()
                Button(action: player.toggle) {
                    Label(player.isPlaying ? "暂停" : "播放", systemImage: player.isPlaying ? "pause.fill" : "play.fill")
                        .font(.body.weight(.semibold))
                        .frame(minWidth: 98)
                }
                .buttonStyle(PrimaryButtonStyle())
                Spacer()
                Text(time(durationMs))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(DesignTokens.muted)
            }
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.top, 14)
        .padding(.bottom, 10)
        .background(DesignTokens.surface)
        .overlay(alignment: .top) { Divider().overlay(DesignTokens.separator) }
    }

    private var progress: Double {
        guard durationMs > 0 else { return 0 }
        return min(1, max(0, Double(player.positionMs) / Double(durationMs)))
    }

    private func time(_ milliseconds: Int) -> String {
        let totalSeconds = max(0, milliseconds / 1_000)
        return String(format: "%d:%02d", totalSeconds / 60, totalSeconds % 60)
    }
}
