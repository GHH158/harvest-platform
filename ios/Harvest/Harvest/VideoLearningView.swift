import AVKit
import SwiftUI

struct StoredPlayback: Codable, Equatable {
    let positionMs: Int
    let updatedAt: Date
}

struct PlaybackProgressStore {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load(materialID: Int) -> StoredPlayback? {
        guard let data = defaults.data(forKey: key(materialID)) else { return nil }
        return try? JSONDecoder().decode(StoredPlayback.self, from: data)
    }

    func save(materialID: Int, positionMs: Int, updatedAt: Date = Date()) {
        let state = StoredPlayback(positionMs: max(0, positionMs), updatedAt: updatedAt)
        guard let data = try? JSONEncoder().encode(state) else { return }
        defaults.set(data, forKey: key(materialID))
    }

    private func key(_ materialID: Int) -> String {
        // Kept on the original prefix although reading materials use this store too:
        // renaming it would orphan every resume point already on disk.
        "harvest.video.playback.\(materialID)"
    }
}

/// Server timestamps arrive with or without fractional seconds depending on the row.
///
/// PostgreSQL renders microseconds ("…:28.905934+08:00") but `ISO8601DateFormatter`
/// only accepts up to milliseconds, so the raw string fails both parsers and the
/// caller silently concludes the server copy is not newer — which kept every resume
/// point pinned to whatever was cached locally. Trim the fraction to 3 digits first.
func parseServerTimestamp(_ value: String?) -> Date? {
    guard let value else { return nil }
    let withFractions = ISO8601DateFormatter()
    withFractions.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let parsed = withFractions.date(from: value) { return parsed }
    if let parsed = ISO8601DateFormatter().date(from: value) { return parsed }

    if let range = value.range(of: #"\.\d{4,9}"#, options: .regularExpression) {
        let clamped = value.replacingCharacters(in: range, with: String(value[range].prefix(4)))
        if let parsed = withFractions.date(from: clamped) { return parsed }
    }
    // Last resort: drop the fraction entirely.
    let withoutFraction = value.replacingOccurrences(
        of: #"\.\d+"#,
        with: "",
        options: .regularExpression
    )
    return ISO8601DateFormatter().date(from: withoutFraction)
}

func normalizedResumePosition(_ positionMs: Int, durationMs: Int?) -> Int {
    let position = max(0, positionMs)
    guard position >= 1_000 else { return 0 }
    guard let durationMs, durationMs > 0 else { return position }
    if position >= durationMs - 5_000 || Double(position) / Double(durationMs) >= 0.95 {
        return 0
    }
    return min(position, durationMs)
}

func sentenceLoopRestartPosition(
    segments: [Segment],
    targetSegmentID: Int,
    oldPositionMs: Int,
    newPositionMs: Int,
    isPlaying: Bool
) -> Int? {
    guard isPlaying,
          let index = segments.firstIndex(where: { $0.id == targetSegmentID }) else { return nil }
    let segment = segments[index]
    var boundary = max(segment.startMs + 100, segment.endMs)
    if segments.indices.contains(index + 1) {
        boundary = min(boundary, segments[index + 1].startMs)
    }
    guard oldPositionMs < boundary, newPositionMs >= boundary else { return nil }
    return segment.startMs
}

func shouldRestartCompletedPlayback(isPlaying: Bool, hasReachedEnd: Bool) -> Bool {
    !isPlaying && hasReachedEnd
}

func segmentForCurrentQuestion(segments: [Segment], positionMs: Int) -> Segment? {
    segments.last(where: { $0.startMs <= positionMs }) ?? segments.first
}

/// Online (streamed) media player. Owns its AVPlayer, observes status errors and
/// surfaces them so a silent failure never looks like a hang.
@MainActor
final class OnlineMediaPlayer: ObservableObject {
    let player = AVPlayer()
    @Published private(set) var isPlaying = false
    @Published private(set) var positionMs = 0
    @Published private(set) var errorMessage: String?

    private var timeObserver: Any?
    private var itemObserver: NSKeyValueObservation?
    private var playbackObserver: NSKeyValueObservation?
    private var endObserver: NSObjectProtocol?
    private(set) var hasReachedEnd = false

    init() {
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 50, timescale: 1_000),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor in self?.positionMs = max(0, Int(time.seconds * 1_000)) }
        }
        playbackObserver = player.observe(\.timeControlStatus, options: [.initial, .new]) { [weak self] player, _ in
            let isPlaying = player.timeControlStatus == .playing
            Task { @MainActor in self?.isPlaying = isPlaying }
        }
    }

    func prepare(url: URL) {
        AudioSessionSupport.activatePlayback()
        let item = AVPlayerItem(url: url)
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.hasReachedEnd = true
                self?.isPlaying = false
            }
        }
        itemObserver?.invalidate()
        itemObserver = item.observe(\.status) { [weak self] observedItem, _ in
            let isFailed = observedItem.status == .failed
            let isReady = observedItem.status == .readyToPlay
            let message = observedItem.error?.localizedDescription
            Task { @MainActor in
                if isFailed {
                    self?.errorMessage = message ?? "播放失败"
                } else if isReady {
                    self?.errorMessage = nil
                }
            }
        }
        player.replaceCurrentItem(with: item)
        positionMs = 0
        hasReachedEnd = false
        errorMessage = nil
    }

    func toggle() {
        if isPlaying {
            pause()
            return
        }
        if shouldRestartCompletedPlayback(isPlaying: isPlaying, hasReachedEnd: hasReachedEnd) {
            restartAndPlay()
            return
        }
        player.play()
        isPlaying = true
    }

    func pause() {
        player.pause()
        isPlaying = false
    }

    func seek(to milliseconds: Int) {
        hasReachedEnd = false
        positionMs = max(0, milliseconds)
        player.seek(to: CMTime(value: CMTimeValue(milliseconds), timescale: 1_000))
    }

    private func restartAndPlay() {
        hasReachedEnd = false
        positionMs = 0
        player.seek(to: .zero, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
            guard finished else { return }
            Task { @MainActor in
                self?.player.play()
                self?.isPlaying = true
            }
        }
    }
}

@MainActor
final class SegmentQueuePlayer: ObservableObject {
    let player = AVQueuePlayer()
    @Published private(set) var isPlaying = false
    @Published private(set) var positionMs = 0
    @Published private(set) var errorMessage: String?
    private var knownURLs: [URL] = []
    private var durations: [Double] = []
    private var playedCount = 0
    /// MPEG-TS segments carry absolute presentation timestamps, so a standalone `.ts`
    /// does not start at zero — segment 20 of this material reports ~121 s the moment it
    /// opens. Adding the elapsed durations on top counted that offset twice and ran the
    /// timeline at roughly double speed: subtitles desynced and, once the position shot
    /// past the end, no sentence was current so word highlighting vanished entirely.
    /// Calibrate an origin from the first observed time instead, re-doing it at each
    /// item boundary so a stream whose timestamps reset is handled too.
    private var timelineOrigin: Double?
    private var calibratedPlayedCount = -1
    private var pendingCalibrationOffset = 0.0
    private var itemObservers: [NSObjectProtocol] = []
    private var itemStatusObservations: [NSKeyValueObservation] = []
    private var timeObserver: Any?
    private var playbackObserver: NSKeyValueObservation?

    init() {
        AudioSessionSupport.activatePlayback()
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 50, timescale: 1_000),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor in self?.updatePosition(time) }
        }
        playbackObserver = player.observe(\.timeControlStatus, options: [.initial, .new]) { [weak self] player, _ in
            let isPlaying = player.timeControlStatus == .playing
            Task { @MainActor in self?.isPlaying = isPlaying }
        }
    }

    func update(_ urls: [URL], durations newDurations: [Double]? = nil) {
        let normalized = normalizedDurations(newDurations, count: urls.count)
        guard urls != knownURLs || normalized != durations else { return }
        if urls.starts(with: knownURLs), normalized.starts(with: durations) {
            for (index, url) in urls.enumerated().dropFirst(knownURLs.count) {
                append(url, duration: normalized[index])
            }
            knownURLs = urls
            durations = normalized
        } else {
            knownURLs = urls
            durations = normalized
            rebuild(startingAt: 0, offsetMs: 0)
        }
        if isPlaying { player.play() }
    }

    func seek(to milliseconds: Int) {
        guard !knownURLs.isEmpty else { return }
        let seconds = max(0, Double(milliseconds) / 1_000)
        var elapsed = 0.0
        var target = knownURLs.count - 1
        for index in knownURLs.indices {
            if seconds < elapsed + durations[index] {
                target = index
                break
            }
            elapsed += durations[index]
        }
        rebuild(startingAt: target, offsetMs: Int((seconds - elapsed) * 1_000))
        if isPlaying { player.play() }
    }

    func toggle() {
        if isPlaying {
            pause()
            return
        }
        if shouldRestartCompletedPlayback(isPlaying: isPlaying, hasReachedEnd: hasReachedEnd) {
            rebuild(startingAt: 0, offsetMs: 0)
        }
        isPlaying = true
        player.play()
    }

    func pause() {
        player.pause()
        isPlaying = false
    }

    private func rebuild(startingAt index: Int, offsetMs: Int) {
        player.removeAllItems()
        removeItemObservers()
        playedCount = index
        // Force re-calibration: the new first item brings its own timestamp base.
        timelineOrigin = nil
        calibratedPlayedCount = -1
        pendingCalibrationOffset = Double(offsetMs) / 1_000
        for itemIndex in index..<knownURLs.count {
            append(knownURLs[itemIndex], duration: durations[itemIndex])
        }
        let completed = durations.prefix(index).reduce(0, +)
        positionMs = max(0, Int(completed * 1_000) + offsetMs)
        if offsetMs > 0 {
            player.seek(to: CMTime(value: CMTimeValue(offsetMs), timescale: 1_000))
        }
    }

    private func append(_ url: URL, duration: Double) {
        let item = AVPlayerItem(url: url)
        player.insert(item, after: player.items().last)
        let observer = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.playedCount = min(self.playedCount + 1, self.knownURLs.count)
                if self.playedCount >= self.knownURLs.count {
                    self.positionMs = max(0, Int(self.durations.reduce(0, +) * 1_000))
                    self.isPlaying = false
                }
            }
        }
        itemObservers.append(observer)
        let statusObservation = item.observe(\.status) { [weak self] observedItem, _ in
            let isFailed = observedItem.status == .failed
            let message = observedItem.error?.localizedDescription
            Task { @MainActor in
                if isFailed { self?.errorMessage = message ?? "离线播放失败" }
            }
        }
        itemStatusObservations.append(statusObservation)
    }

    private func normalizedDurations(_ values: [Double]?, count: Int) -> [Double] {
        guard let values, values.count >= count else { return Array(repeating: 6, count: count) }
        return Array(values.prefix(count)).map { $0 > 0 ? $0 : 6 }
    }

    private func updatePosition(_ time: CMTime) {
        let seconds = time.seconds
        guard seconds.isFinite else { return }
        if calibratedPlayedCount != playedCount || timelineOrigin == nil {
            let expected = durations.prefix(playedCount).reduce(0, +) + pendingCalibrationOffset
            timelineOrigin = seconds - expected
            calibratedPlayedCount = playedCount
            pendingCalibrationOffset = 0
        }
        positionMs = max(0, Int((seconds - (timelineOrigin ?? 0)) * 1_000))
    }

    var hasReachedEnd: Bool {
        !knownURLs.isEmpty && (playedCount >= knownURLs.count || (player.items().isEmpty && positionMs > 0))
    }

    private func removeItemObservers() {
        for observer in itemObservers { NotificationCenter.default.removeObserver(observer) }
        itemObservers.removeAll()
        for observation in itemStatusObservations { observation.invalidate() }
        itemStatusObservations.removeAll()
    }
}

private struct VideoSubtitleRow: Identifiable {
    let segment: Segment
    let units: [JapaneseReadingUnit]

    var id: Int { segment.id }
}

private struct VideoPlaybackHighlight {
    let segmentID: Int?
    let unitID: Int?
}

struct VideoLearningView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @EnvironmentObject private var configuration: AppConfiguration
    @EnvironmentObject private var offlineLibrary: OfflineLibrary
    let material: MaterialDetail
    @State private var mode = "观看"
    @State private var downloadError: String?
    @State private var isSentenceLoopEnabled = false
    @State private var loopSegmentID: Int?
    @State private var pendingResumePositionMs: Int?
    /// Last real playback position seen, used to carry the position across a switch
    /// between the online and offline players.
    @State private var lastWatchPositionMs = 0
    @State private var didRestorePlayback = false
    @State private var lastSavedPositionMs = 0
    @State private var questionSegment: Segment?
    @StateObject private var onlineVideo = OnlineMediaPlayer()
    @StateObject private var onlineAudio = OnlineMediaPlayer()
    @StateObject private var offlineVideoPlayer = SegmentQueuePlayer()
    @StateObject private var offlineAudioPlayer = SegmentQueuePlayer()
    private let subtitleRows: [VideoSubtitleRow]
    private let playbackSegments: [Segment]

    init(material: MaterialDetail) {
        self.material = material
        playbackSegments = material.segments
        let tokensBySegmentID = Dictionary(grouping: material.tokens, by: \.segmentID)
        subtitleRows = material.segments.map { segment in
            VideoSubtitleRow(
                segment: segment,
                units: japaneseReadingUnits(
                    text: segment.textJA,
                    tokens: tokensBySegmentID[segment.id] ?? []
                )
            )
        }
    }

    var body: some View {
        VStack(spacing: 12) {
            compactHeader
            playerSection
            if let playbackError {
                Text("播放失败：\(playbackError)")
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let downloadError {
                downloadErrorPanel(downloadError)
            }
            subtitleList
        }
        .padding(.horizontal, DesignTokens.pageInset)
        .padding(.top, 4)
        .padding(.bottom, 8)
        .background(DesignTokens.canvas.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .safeAreaInset(edge: .bottom) {
            if mode == "观看" { learningControlBar }
        }
        .navigationDestination(item: $questionSegment) { segment in
            CompanionView(materialID: material.id, segment: segment)
        }
        .task { await restorePlaybackPosition() }
        .onChange(of: watchPlaybackPositionMs) { oldPosition, newPosition in
            handleSentenceLoop(from: oldPosition, to: newPosition)
            savePlaybackPositionIfNeeded(newPosition)
            if newPosition > 0 { lastWatchPositionMs = newPosition }
        }
        .onChange(of: usesOfflineVideo) { _, _ in
            // Silence whichever player is being left — otherwise its audio keeps running
            // underneath the new one — and hand the position over so the swap is not felt.
            onlineVideo.pause()
            offlineVideoPlayer.pause()
            pendingResumePositionMs = lastWatchPositionMs
        }
        .onChange(of: usesOfflineAudio) { _, _ in
            onlineAudio.pause()
            offlineAudioPlayer.pause()
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase != .active { savePlaybackPosition(force: true) }
        }
        .onChange(of: mode) { oldMode, newMode in
            downloadError = nil
            if oldMode == "观看" { savePlaybackPosition(force: true) }
            if newMode == "观看" {
                onlineAudio.pause()
                offlineAudioPlayer.pause()
            } else {
                onlineVideo.pause()
                offlineVideoPlayer.pause()
            }
        }
        .onDisappear {
            savePlaybackPosition(force: true)
            onlineVideo.pause()
            onlineAudio.pause()
            offlineVideoPlayer.pause()
            offlineAudioPlayer.pause()
        }
    }

    private var compactHeader: some View {
        HStack(spacing: 10) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(DesignTokens.ink)
                    .frame(width: 34, height: 34)
                    .background(DesignTokens.surface, in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Text(material.title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(DesignTokens.ink)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)

            Picker("模式", selection: $mode) {
                Text("观看").tag("观看")
                Text("跟读").tag("跟读")
            }
            .labelsHidden()
            .pickerStyle(.segmented)
            .tint(DesignTokens.accent)
            .frame(width: 132)
        }
        .frame(height: 36)
    }

    private var playerSection: some View {
        ZStack(alignment: .topTrailing) {
            if mode == "观看" { watchPlayer } else { shadowingPlayer }
            downloadStatusButton
                .padding(9)
        }
    }

    private var learningControlBar: some View {
        VStack(spacing: 7) {
            HStack(spacing: 12) {
                Text(currentSubtitleIndex.map { "第 \($0 + 1) / \(subtitleRows.count) 句" } ?? "准备开始")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(DesignTokens.muted)
                Spacer()
                Button(action: askCurrentSentence) {
                    Label("提问本句", systemImage: "questionmark.bubble")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(DesignTokens.accent)
                        .padding(.horizontal, 10)
                        .frame(minHeight: 30)
                        .background(DesignTokens.accentWash, in: Capsule())
                }
                .buttonStyle(.plain)
                .disabled(subtitleRows.isEmpty)
                .accessibilityLabel("提问当前播放句子")
            }
            HStack(spacing: 18) {
                learningButton("backward.end.fill", label: "上一句", action: previousSentence)
                learningButton("arrow.counterclockwise", label: "重播本句", action: replaySentence)
                Button(action: toggleWatchPlayback) {
                    Image(systemName: isWatchPlaying ? "pause.fill" : "play.fill")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(Color.white)
                        .frame(width: 48, height: 40)
                        .background(DesignTokens.accent, in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(isWatchPlaying ? "暂停" : "播放")
                learningButton("forward.end.fill", label: "下一句", action: nextSentence)
                learningButton(
                    "repeat.1",
                    label: isSentenceLoopEnabled ? "关闭单句循环" : "开启单句循环",
                    isSelected: isSentenceLoopEnabled,
                    action: toggleSentenceLoop
                )
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 9)
        .padding(.bottom, 7)
        .background(DesignTokens.surface)
        .overlay(alignment: .top) { Divider().overlay(DesignTokens.separator) }
    }

    private func learningButton(
        _ systemImage: String,
        label: String,
        isSelected: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.body.weight(.semibold))
                .foregroundStyle(isSelected ? DesignTokens.accent : DesignTokens.ink)
                .frame(width: 42, height: 40)
                .background(isSelected ? DesignTokens.accent.opacity(0.12) : Color.clear, in: Capsule())
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    @ViewBuilder
    private var watchPlayer: some View {
        Group {
            if usesOfflineVideo {
                VideoPlayer(player: offlineVideoPlayer.player)
                    .task(id: offlineVideoSignature) {
                        offlineVideoPlayer.update(offlineVideoURLs, durations: offlineEntry?.videoSegmentDurations)
                        applyPendingResumePosition()
                    }
            } else if let videoURL = material.videoURL {
                VideoPlayer(player: onlineVideo.player)
                    .task(id: videoURL) {
                        onlineVideo.prepare(url: videoURL)
                        applyPendingResumePosition()
                    }
            } else {
                ContentUnavailableView(
                    "视频仍在准备",
                    systemImage: "film",
                    description: Text("HLS 分片、字幕与 OSS 分发完成后会出现在这里。")
                )
            }
        }
        .frame(maxWidth: .infinity)
        .aspectRatio(16 / 9, contentMode: .fit)
        .background(Color.black)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(DesignTokens.ink.opacity(0.08), lineWidth: 1)
        }
    }

    @ViewBuilder
    private var shadowingPlayer: some View {
        VStack(spacing: 12) {
            if !offlineAudioURLs.isEmpty {
                Button(offlineAudioPlayer.isPlaying ? "暂停跟读音频" : "播放跟读音频") {
                    offlineAudioPlayer.toggle()
                }
                .buttonStyle(PrimaryButtonStyle())
                .task(id: offlineAudioSignature) {
                    offlineAudioPlayer.update(offlineAudioURLs, durations: offlineEntry?.audioSegmentDurations)
                }
            } else if let audioURL = material.audioURL {
                Button(onlineAudio.isPlaying ? "暂停跟读音频" : "播放跟读音频") {
                    onlineAudio.toggle()
                }
                .buttonStyle(PrimaryButtonStyle())
                .task(id: audioURL) {
                    onlineAudio.prepare(url: audioURL)
                }
            } else {
                Text("跟读音频仍在准备。")
                    .foregroundStyle(DesignTokens.muted)
            }
            Text("跟读模式只读取纯音频 HLS，不重复消耗视频流量。")
                .font(.footnote)
                .foregroundStyle(DesignTokens.muted)
        }
        .frame(maxWidth: .infinity, minHeight: 112)
        .padding(.horizontal, 16)
        .padding(.top, 14)
        .padding(.bottom, 12)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(DesignTokens.ink.opacity(0.08), lineWidth: 1)
        }
    }

    private var downloadStatusButton: some View {
        let isDownloading = offlineLibrary.isDownloading(material.id)
        return Button {
            guard !selectedMediaIsComplete, !isDownloading else { return }
            Task { await download() }
        } label: {
            HStack(spacing: 5) {
                if isDownloading {
                    ProgressView()
                        .controlSize(.mini)
                        .tint(DesignTokens.accent)
                } else {
                    Image(systemName: selectedMediaIsComplete ? "checkmark.circle.fill" : "arrow.down.circle.fill")
                }
                if let total = selectedTotalSegmentCount {
                    Text(selectedMediaIsComplete ? "已下载" : "\(downloaded)/\(total)")
                        .monospacedDigit()
                } else if selectedMediaIsComplete {
                    Text("已下载")
                }
            }
            .font(.caption2.weight(.semibold))
            .foregroundStyle(selectedMediaIsComplete ? DesignTokens.muted : DesignTokens.accent)
            .padding(.horizontal, 9)
            .frame(minHeight: 30)
            .background(DesignTokens.surface.opacity(0.94), in: Capsule())
            .overlay {
                Capsule().stroke(DesignTokens.ink.opacity(0.1), lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
        .disabled(selectedMediaIsComplete || isDownloading)
        .accessibilityLabel(downloadAccessibilityLabel)
    }

    private func downloadErrorPanel(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(DesignTokens.accent)
            Text("下载失败：\(message)")
                .font(.footnote)
                .foregroundStyle(DesignTokens.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button("重试") { Task { await download() } }
                .font(.footnote.weight(.semibold))
                .foregroundStyle(DesignTokens.accent)
        }
        .padding(10)
        .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: 10))
    }

    private var subtitleList: some View {
        let highlight = playbackHighlight
        return ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(subtitleRows) { row in
                        ReadingSentenceView(
                            materialID: material.id,
                            segment: row.segment,
                            units: row.units,
                            activeUnitID: highlight.segmentID == row.id ? highlight.unitID : nil,
                            isCurrent: highlight.segmentID == row.id,
                            onSelect: { seek(to: row.segment.startMs) }
                        )
                        .equatable()
                        .id(row.id)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: playbackHighlight.segmentID) { _, identifier in
                guard let identifier else { return }
                withAnimation(.easeInOut(duration: 0.28)) { proxy.scrollTo(identifier, anchor: .center) }
            }
        }
    }

    private var playbackError: String? {
        if mode == "观看" {
            return usesOfflineVideo ? offlineVideoPlayer.errorMessage : onlineVideo.errorMessage
        }
        return usesOfflineAudio ? offlineAudioPlayer.errorMessage : onlineAudio.errorMessage
    }

    private var playbackPositionMs: Int {
        if mode == "观看" {
            return watchPlaybackPositionMs
        }
        return usesOfflineAudio ? offlineAudioPlayer.positionMs : onlineAudio.positionMs
    }

    private var watchPlaybackPositionMs: Int {
        usesOfflineVideo ? offlineVideoPlayer.positionMs : onlineVideo.positionMs
    }

    /// Sentence and word highlights use start boundaries rather than strict ASR
    /// end times. This avoids blank highlighting during natural pauses while the
    /// next word or sentence has not begun yet.
    private var playbackHighlight: VideoPlaybackHighlight {
        let position = playbackPositionMs
        guard let row = subtitleRows.last(where: { $0.segment.startMs <= position }) else {
            return VideoPlaybackHighlight(segmentID: nil, unitID: nil)
        }
        return VideoPlaybackHighlight(
            segmentID: row.id,
            unitID: activeReadingUnitID(in: row.units, at: position)
        )
    }

    private var currentSubtitleIndex: Int? {
        guard !subtitleRows.isEmpty else { return nil }
        return subtitleRows.lastIndex { $0.segment.startMs <= playbackPositionMs }
    }

    private var isWatchPlaying: Bool {
        usesOfflineVideo ? offlineVideoPlayer.isPlaying : onlineVideo.isPlaying
    }

    private func toggleWatchPlayback() {
        if !usesOfflineVideo { onlineVideo.toggle() }
        else { offlineVideoPlayer.toggle() }
    }

    private func askCurrentSentence() {
        guard let segment = segmentForCurrentQuestion(
            segments: playbackSegments,
            positionMs: watchPlaybackPositionMs
        ) else { return }
        onlineVideo.pause()
        offlineVideoPlayer.pause()
        questionSegment = segment
    }

    private func toggleSentenceLoop() {
        isSentenceLoopEnabled.toggle()
        guard isSentenceLoopEnabled else {
            loopSegmentID = nil
            return
        }
        let index = currentWatchSubtitleIndex ?? 0
        guard subtitleRows.indices.contains(index) else {
            isSentenceLoopEnabled = false
            return
        }
        loopSegmentID = subtitleRows[index].id
        if currentWatchSubtitleIndex == nil { seekWatch(to: subtitleRows[index].segment.startMs) }
    }

    private func handleSentenceLoop(from oldPosition: Int, to newPosition: Int) {
        guard isSentenceLoopEnabled,
              let loopSegmentID,
              let target = sentenceLoopRestartPosition(
                  segments: playbackSegments,
                  targetSegmentID: loopSegmentID,
                  oldPositionMs: oldPosition,
                  newPositionMs: newPosition,
                  isPlaying: isWatchPlaying
              ) else { return }
        seekWatch(to: target)
    }

    private func replaySentence() {
        guard let index = currentSubtitleIndex else {
            if let first = subtitleRows.first { seek(to: first.segment.startMs) }
            return
        }
        seek(to: subtitleRows[index].segment.startMs)
    }

    private func previousSentence() {
        guard let index = currentSubtitleIndex else {
            if let first = subtitleRows.first { seek(to: first.segment.startMs) }
            return
        }
        let currentStart = subtitleRows[index].segment.startMs
        let target = playbackPositionMs - currentStart > 2_500 ? index : max(0, index - 1)
        seek(to: subtitleRows[target].segment.startMs)
    }

    private func nextSentence() {
        let target = min((currentSubtitleIndex ?? -1) + 1, subtitleRows.count - 1)
        guard subtitleRows.indices.contains(target) else { return }
        seek(to: subtitleRows[target].segment.startMs)
    }

    private func seek(to milliseconds: Int) {
        if mode == "观看" {
            updateLoopTarget(for: milliseconds)
            seekWatch(to: milliseconds)
        } else if offlineAudioURLs.isEmpty {
            onlineAudio.seek(to: milliseconds)
        } else {
            offlineAudioPlayer.seek(to: milliseconds)
        }
    }

    private func seekWatch(to milliseconds: Int) {
        if !usesOfflineVideo { onlineVideo.seek(to: milliseconds) }
        else { offlineVideoPlayer.seek(to: milliseconds) }
    }

    private func updateLoopTarget(for milliseconds: Int) {
        guard isSentenceLoopEnabled else { return }
        loopSegmentID = subtitleRows.last(where: { $0.segment.startMs <= milliseconds })?.id
            ?? subtitleRows.first?.id
    }

    private var currentWatchSubtitleIndex: Int? {
        guard !subtitleRows.isEmpty else { return nil }
        return subtitleRows.lastIndex { $0.segment.startMs <= watchPlaybackPositionMs }
    }

    private func applyPendingResumePosition() {
        guard let position = pendingResumePositionMs else { return }
        pendingResumePositionMs = nil
        seekWatch(to: position)
    }

    private func restorePlaybackPosition() async {
        guard !didRestorePlayback else { return }
        let store = PlaybackProgressStore()
        let local = store.load(materialID: material.id)
        if let local {
            let position = normalizedResumePosition(local.positionMs, durationMs: material.durationMs)
            pendingResumePositionMs = position
            lastSavedPositionMs = position
            applyPendingResumePosition()
        }
        didRestorePlayback = true

        guard let endpoint = configuration.endpoint,
              let remote = try? await APIClient(baseURL: endpoint).playbackState(materialID: material.id) else { return }
        let remoteDate = parseServerTimestamp(remote.updatedAt)
        if local == nil || (remoteDate != nil && remoteDate! > local!.updatedAt) {
            let position = normalizedResumePosition(remote.positionMs, durationMs: material.durationMs)
            store.save(materialID: material.id, positionMs: position, updatedAt: remoteDate ?? Date())
            lastSavedPositionMs = position
            pendingResumePositionMs = position
            applyPendingResumePosition()
        }
    }

    private func savePlaybackPositionIfNeeded(_ positionMs: Int) {
        guard didRestorePlayback, abs(positionMs - lastSavedPositionMs) >= 5_000 else { return }
        savePlaybackPosition(force: false)
    }

    private func savePlaybackPosition(force: Bool) {
        guard didRestorePlayback else { return }
        let rawPosition = pendingResumePositionMs ?? watchPlaybackPositionMs
        let position = normalizedResumePosition(rawPosition, durationMs: material.durationMs)
        guard force || abs(position - lastSavedPositionMs) >= 5_000 else { return }
        lastSavedPositionMs = position
        PlaybackProgressStore().save(materialID: material.id, positionMs: position)
        guard let endpoint = configuration.endpoint else { return }
        Task {
            _ = try? await APIClient(baseURL: endpoint).savePlaybackState(
                materialID: material.id,
                positionMs: position
            )
        }
    }

    private var offlineEntry: OfflineEntry? { offlineLibrary.entry(for: material.id) }
    private var offlineVideoURLs: [URL] { offlineEntry?.localVideoSegmentURLs ?? [] }
    private var offlineAudioURLs: [URL] { offlineEntry?.localHLSAudioSegmentURLs ?? [] }

    /// Whether playback should read from disk rather than the network.
    ///
    /// The contiguous prefix grows one file at a time while a download runs, so keying
    /// the source off "any local segment exists" swapped the player out from under an
    /// active online session: the picture went black on a one-segment offline player,
    /// the online player kept its audio running because nothing paused it, subtitles
    /// froze on the new player's position and the error surfaced as "Cannot Open".
    /// §5.2 does allow watching a partially downloaded video — just not by hot-swapping
    /// mid-download, so wait until this material is no longer downloading.
    private var usesOfflineVideo: Bool {
        !offlineVideoURLs.isEmpty && !offlineLibrary.isDownloading(material.id)
    }

    private var usesOfflineAudio: Bool {
        !offlineAudioURLs.isEmpty && !offlineLibrary.isDownloading(material.id)
    }
    private var offlineVideoSignature: String { offlineVideoURLs.map(\.path).joined(separator: "|") }
    private var offlineAudioSignature: String { offlineAudioURLs.map(\.path).joined(separator: "|") }
    private var selectedVideoMedia: VideoOfflineMedia { mode == "观看" ? .watch : .shadowing }
    private var selectedTotalSegmentCount: Int? {
        mode == "观看" ? offlineEntry?.totalVideoSegments : offlineEntry?.totalAudioSegments
    }
    private var downloaded: Int {
        mode == "观看"
            ? offlineEntry?.downloadedVideoSegmentCount ?? 0
            : offlineEntry?.downloadedAudioSegmentCount ?? 0
    }
    private var selectedMediaIsComplete: Bool {
        mode == "观看"
            ? offlineEntry?.isWatchVideoComplete == true
            : offlineEntry?.isShadowingAudioComplete == true
    }
    private var downloadAccessibilityLabel: String {
        if selectedMediaIsComplete { return mode == "观看" ? "观看视频已下载" : "跟读音频已下载" }
        if offlineLibrary.isDownloading(material.id) { return "正在下载" }
        if let total = selectedTotalSegmentCount { return "继续下载，已完成 \(downloaded) 个，共 \(total) 个分片" }
        return mode == "观看" ? "下载观看视频" : "下载跟读音频"
    }

    @MainActor
    private func download() async {
        downloadError = nil
        do {
            try await offlineLibrary.download(material, videoMedia: selectedVideoMedia)
            downloadError = nil
        } catch {
            downloadError = error.localizedDescription
        }
    }
}
