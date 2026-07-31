import Combine
import SwiftUI
import UIKit

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
    private let statusRefresh = Timer.publish(every: 4, on: .main, in: .common).autoconnect()

    var body: some View {
        Group {
            if isLoading {
                ProgressView("正在打开材料")
                    .foregroundStyle(DesignTokens.muted)
            } else if let errorMessage {
                ContentUnavailableView {
                    Label("暂时无法打开", systemImage: "exclamationmark.bubble")
                } description: {
                    Text(errorMessage)
                } actions: {
                    Button("再试一次") { Task { await load() } }
                }
            } else if let material {
                reader(material)
            }
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .task { await load() }
        .onReceive(statusRefresh) { _ in
            guard let material, material.status != "ready", material.status != "failed" else { return }
            Task { await load(showingProgress: false) }
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
                    Text(material.title)
                        .font(.system(size: 31, weight: .regular, design: .serif))
                        .tracking(-0.5)
                        .foregroundStyle(DesignTokens.ink)
                        .padding(.bottom, 18)
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
                    if let current = currentSegment(in: material) {
                        NavigationLink("跟读这一句") { ShadowingView(segment: current) }
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(DesignTokens.accent)
                    }
                    if let downloadError {
                        Text(downloadError)
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.accent)
                    }
                    ForEach(material.segments) { segment in
                        SentenceButton(
                            segment: segment,
                            tokens: tokens(for: segment, in: material),
                            currentTokenID: currentToken(in: material)?.id,
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

    private func currentToken(in material: MaterialDetail) -> Token? {
        material.tokens.first { token in
            player.positionMs >= token.startMs && player.positionMs < token.endMs
        }
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

private struct SentenceButton: View {
    let segment: Segment
    let tokens: [Token]
    let currentTokenID: Int?
    let isCurrent: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            Text(attributedText)
                .font(.system(size: DesignTokens.readingSize, weight: .regular))
                .foregroundStyle(DesignTokens.ink)
                .lineSpacing(DesignTokens.readingLineSpacing)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(isCurrent ? DesignTokens.accentWash : .clear, in: RoundedRectangle(cornerRadius: 7))
                .animation(.easeInOut(duration: 0.24), value: isCurrent)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("跳转到：\(segment.textJA)")
    }

    private var attributedText: AttributedString {
        guard !tokens.isEmpty else { return AttributedString(segment.textJA) }
        var result = AttributedString()
        var tokenIndex = 0
        for character in segment.textJA {
            var part = AttributedString(String(character))
            if !isIgnorable(character), tokenIndex < tokens.count {
                if tokens[tokenIndex].surface == String(character) {
                    if tokens[tokenIndex].id == currentTokenID {
                        part.backgroundColor = UIColor(DesignTokens.accentWash)
                    }
                    tokenIndex += 1
                }
            }
            result += part
        }
        return result
    }

    private func isIgnorable(_ character: Character) -> Bool {
        character.isWhitespace || "、。！？!?，,.…ー・『』「」（）()[]{}".contains(character)
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
        .background(.ultraThinMaterial)
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
