import AVKit
import SwiftUI

@MainActor
final class SegmentQueuePlayer: ObservableObject {
    let player = AVQueuePlayer()
    @Published private(set) var isPlaying = false
    private var knownURLs: [URL] = []

    func update(_ urls: [URL]) {
        guard urls != knownURLs else { return }
        if urls.starts(with: knownURLs) {
            for url in urls.dropFirst(knownURLs.count) {
                player.insert(AVPlayerItem(url: url), after: player.items().last)
            }
        } else {
            player.removeAllItems()
            for url in urls {
                player.insert(AVPlayerItem(url: url), after: player.items().last)
            }
        }
        knownURLs = urls
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
}

struct VideoLearningView: View {
    @EnvironmentObject private var offlineLibrary: OfflineLibrary
    let material: MaterialDetail
    @State private var mode = "观看"
    @State private var downloadError: String?
    @State private var onlineVideoPlayer = AVPlayer()
    @State private var onlineAudioPlayer = AVPlayer()
    @State private var isOnlineAudioPlaying = false
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
            subtitles
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
        }
    }

    @ViewBuilder
    private var watchPlayer: some View {
        if !offlineVideoURLs.isEmpty {
            VideoPlayer(player: offlineVideoPlayer.player)
                .frame(height: 240)
                .task(id: offlineVideoSignature) {
                    onlineVideoPlayer.pause()
                    offlineVideoPlayer.update(offlineVideoURLs)
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
                    offlineAudioPlayer.update(offlineAudioURLs)
                }
            } else if let audioURL = material.audioURL {
                Button(isOnlineAudioPlaying ? "暂停跟读音频" : "播放跟读音频") {
                    isOnlineAudioPlaying.toggle()
                    if isOnlineAudioPlaying { onlineAudioPlayer.play() } else { onlineAudioPlayer.pause() }
                }
                .buttonStyle(PrimaryButtonStyle())
                .task(id: audioURL) {
                    onlineAudioPlayer.replaceCurrentItem(with: AVPlayerItem(url: audioURL))
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

    private var subtitles: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(material.segments) { segment in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(segment.textJA)
                            .font(.system(size: DesignTokens.readingSize))
                            .foregroundStyle(DesignTokens.ink)
                        if let translation = segment.textZH {
                            Text(translation).font(.footnote).foregroundStyle(DesignTokens.muted)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
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
