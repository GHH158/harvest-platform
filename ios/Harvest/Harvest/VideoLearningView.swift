import AVKit
import SwiftUI

@MainActor
final class PlayerClock: ObservableObject {
    @Published private(set) var positionMs = 0
    private weak var player: AVPlayer?
    private var observer: Any?

    func observe(_ player: AVPlayer) {
        stop()
        self.player = player
        observer = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 100, timescale: 1_000),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor in self?.positionMs = max(0, Int(time.seconds * 1_000)) }
        }
    }

    func seek(to milliseconds: Int) {
        player?.seek(to: CMTime(value: CMTimeValue(milliseconds), timescale: 1_000))
    }

    func stop() {
        if let observer, let player { player.removeTimeObserver(observer) }
        observer = nil
        player = nil
        positionMs = 0
    }
}

@MainActor
final class SegmentQueuePlayer: ObservableObject {
    let player = AVQueuePlayer()
    @Published private(set) var isPlaying = false
    @Published private(set) var positionMs = 0
    private var knownURLs: [URL] = []
    private var durations: [Double] = []
    private var playedCount = 0
    private var itemObservers: [NSObjectProtocol] = []
    private var timeObserver: Any?

    init() {
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 100, timescale: 1_000),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor in self?.updatePosition(time) }
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
        isPlaying.toggle()
        if isPlaying { player.play() } else { player.pause() }
    }

    func pause() {
        player.pause()
        isPlaying = false
    }

    private func rebuild(startingAt index: Int, offsetMs: Int) {
        player.removeAllItems()
        removeItemObservers()
        playedCount = index
        for itemIndex in index..<knownURLs.count {
            append(knownURLs[itemIndex], duration: durations[itemIndex])
        }
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
            }
        }
        itemObservers.append(observer)
    }

    private func normalizedDurations(_ values: [Double]?, count: Int) -> [Double] {
        guard let values, values.count >= count else { return Array(repeating: 6, count: count) }
        return Array(values.prefix(count)).map { $0 > 0 ? $0 : 6 }
    }

    private func updatePosition(_ time: CMTime) {
        let completed = durations.prefix(playedCount).reduce(0, +)
        positionMs = max(0, Int((completed + time.seconds) * 1_000))
    }

    private func removeItemObservers() {
        for observer in itemObservers { NotificationCenter.default.removeObserver(observer) }
        itemObservers.removeAll()
    }
}

struct VideoLearningView: View {
    @EnvironmentObject private var offlineLibrary: OfflineLibrary
    let material: MaterialDetail
    @State private var mode = "观看"
    @State private var downloadError: String?
    @State private var onlineVideoPlayer = AVPlayer()
    @State private var onlineAudioPlayer = AVPlayer()
    @State private var isOnlineAudioPlaying = false
    @StateObject private var onlineVideoClock = PlayerClock()
    @StateObject private var onlineAudioClock = PlayerClock()
    @StateObject private var offlineVideoPlayer = SegmentQueuePlayer()
    @StateObject private var offlineAudioPlayer = SegmentQueuePlayer()

    var body: some View {
        VStack(spacing: 18) {
            Picker("模式", selection: $mode) {
                Text("观看").tag("观看")
                Text("跟读").tag("跟读")
            }
            .pickerStyle(.segmented)

            if mode == "观看" { watchPlayer } else { shadowingPlayer }
            downloadControls
            subtitleList
        }
        .padding(DesignTokens.pageInset)
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(material.title)
        .onChange(of: mode) { _, newMode in
            if newMode == "观看" {
                onlineAudioPlayer.pause()
                isOnlineAudioPlaying = false
                offlineAudioPlayer.pause()
            } else {
                onlineVideoPlayer.pause()
                offlineVideoPlayer.pause()
            }
        }
        .onDisappear {
            onlineVideoPlayer.pause()
            onlineAudioPlayer.pause()
            offlineVideoPlayer.pause()
            offlineAudioPlayer.pause()
            onlineVideoClock.stop()
            onlineAudioClock.stop()
        }
    }

    @ViewBuilder
    private var watchPlayer: some View {
        if !offlineVideoURLs.isEmpty {
            VideoPlayer(player: offlineVideoPlayer.player)
                .frame(height: 240)
                .task(id: offlineVideoSignature) {
                    onlineVideoPlayer.pause()
                    offlineVideoPlayer.update(offlineVideoURLs, durations: offlineEntry?.videoSegmentDurations)
                }
            if let entry = offlineEntry, entry.totalVideoSegments != nil, !entry.isWatchVideoComplete {
                Text("已下载的连续分片可以观看；播放到尚未下载的位置会停止。")
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
            }
        } else if let videoURL = material.videoURL {
            VideoPlayer(player: onlineVideoPlayer)
                .frame(height: 240)
                .task(id: videoURL) {
                    onlineVideoPlayer.replaceCurrentItem(with: AVPlayerItem(url: videoURL))
                    onlineVideoClock.observe(onlineVideoPlayer)
                }
        } else {
            ContentUnavailableView(
                "视频仍在准备",
                systemImage: "film",
                description: Text("HLS 分片、字幕与 OSS 分发完成后会出现在这里。")
            )
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
                    onlineAudioPlayer.pause()
                    isOnlineAudioPlaying = false
                    offlineAudioPlayer.update(offlineAudioURLs, durations: offlineEntry?.audioSegmentDurations)
                }
            } else if let audioURL = material.audioURL {
                Button(isOnlineAudioPlaying ? "暂停跟读音频" : "播放跟读音频") {
                    isOnlineAudioPlaying.toggle()
                    if isOnlineAudioPlaying { onlineAudioPlayer.play() } else { onlineAudioPlayer.pause() }
                }
                .buttonStyle(PrimaryButtonStyle())
                .task(id: audioURL) {
                    onlineAudioPlayer.replaceCurrentItem(with: AVPlayerItem(url: audioURL))
                    onlineAudioClock.observe(onlineAudioPlayer)
                }
            } else {
                Text("跟读音频仍在准备。")
                    .foregroundStyle(DesignTokens.muted)
            }
            Text("跟读模式只读取纯音频 HLS，不重复消耗视频流量。")
                .font(.footnote)
                .foregroundStyle(DesignTokens.muted)
        }
    }

    @ViewBuilder
    private var downloadControls: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let total = selectedTotalSegmentCount {
                ProgressView(value: Double(downloaded), total: Double(max(1, total)))
                    .tint(DesignTokens.accent)
                Text(downloadProgressText(downloaded: downloaded, total: total))
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
            }
            if !selectedMediaIsComplete {
                Button(offlineLibrary.isDownloading(material.id) ? "正在下载分片" : resumeButtonTitle) {
                    Task { await download() }
                }
                .disabled(offlineLibrary.isDownloading(material.id))
                .font(.footnote.weight(.semibold))
                .foregroundStyle(DesignTokens.accent)
            }
            if let downloadError {
                Text(downloadError).font(.footnote).foregroundStyle(DesignTokens.accent)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var subtitleList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(material.segments) { segment in
                        Button { seek(to: segment.startMs) } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(segment.textJA)
                                    .font(.system(size: DesignTokens.readingSize))
                                    .foregroundStyle(DesignTokens.ink)
                                if let translation = segment.textZH {
                                    Text(translation).font(.footnote).foregroundStyle(DesignTokens.muted)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .background(
                                currentSegment?.id == segment.id ? DesignTokens.accentWash : .clear,
                                in: RoundedRectangle(cornerRadius: 8)
                            )
                        }
                        .buttonStyle(.plain)
                        .id(segment.id)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: currentSegment?.id) { _, identifier in
                guard let identifier else { return }
                withAnimation(.easeInOut(duration: 0.28)) { proxy.scrollTo(identifier, anchor: .center) }
            }
        }
    }

    private var playbackPositionMs: Int {
        if mode == "观看" {
            return offlineVideoURLs.isEmpty ? onlineVideoClock.positionMs : offlineVideoPlayer.positionMs
        }
        return offlineAudioURLs.isEmpty ? onlineAudioClock.positionMs : offlineAudioPlayer.positionMs
    }

    private var currentSegment: Segment? {
        material.segments.first { playbackPositionMs >= $0.startMs && playbackPositionMs < $0.endMs }
    }

    private func seek(to milliseconds: Int) {
        if mode == "观看" {
            if offlineVideoURLs.isEmpty { onlineVideoClock.seek(to: milliseconds) }
            else { offlineVideoPlayer.seek(to: milliseconds) }
        } else if offlineAudioURLs.isEmpty {
            onlineAudioClock.seek(to: milliseconds)
        } else {
            offlineAudioPlayer.seek(to: milliseconds)
        }
    }

    private var offlineEntry: OfflineEntry? { offlineLibrary.entry(for: material.id) }
    private var offlineVideoURLs: [URL] { offlineEntry?.localVideoSegmentURLs ?? [] }
    private var offlineAudioURLs: [URL] { offlineEntry?.localHLSAudioSegmentURLs ?? [] }
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
    private var resumeButtonTitle: String {
        if selectedTotalSegmentCount != nil { return "继续下载缺失分片" }
        return mode == "观看" ? "下载观看视频到本机" : "只下载跟读音频到本机"
    }

    private func downloadProgressText(downloaded: Int, total: Int) -> String {
        if selectedMediaIsComplete {
            return mode == "观看" ? "观看视频已完整下载" : "跟读音频已完整下载"
        }
        return mode == "观看"
            ? "视频分片 \(downloaded)/\(total)，已有部分可以观看"
            : "跟读音频分片 \(downloaded)/\(total)，已有部分可以播放"
    }

    @MainActor
    private func download() async {
        do {
            try await offlineLibrary.download(material, videoMedia: selectedVideoMedia)
            downloadError = nil
        } catch {
            downloadError = error.localizedDescription
        }
    }
}
