import SwiftUI

struct DownloadsView: View {
    @EnvironmentObject private var offlineLibrary: OfflineLibrary

    var body: some View {
        List {
            if offlineLibrary.entries.isEmpty {
                ContentUnavailableView {
                    Label("还没有已下载材料", systemImage: "arrow.down.circle")
                } description: {
                    Text("打开已准备好的材料，把朗读、观看视频或跟读音频留在这台 iPhone 上。")
                }
                .listRowBackground(DesignTokens.canvas)
            } else {
                ForEach(offlineLibrary.entries) { entry in
                    VStack(alignment: .leading, spacing: 8) {
                        NavigationLink {
                            destination(for: entry)
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(entry.material.title).font(.system(.headline, design: .serif)).foregroundStyle(DesignTokens.ink)
                                Text(summary(entry)).font(.footnote).foregroundStyle(DesignTokens.muted)
                            }
                        }
                        if entry.hasIncompleteRequestedVideoMedia {
                            Button(offlineLibrary.isDownloading(entry.id) ? "正在继续下载" : "继续下载") {
                                Task { try? await offlineLibrary.resume(entry) }
                            }
                            .disabled(offlineLibrary.isDownloading(entry.id))
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(DesignTokens.accent)
                        }
                    }
                    .padding(.vertical, 8)
                    .swipeActions {
                        if !offlineLibrary.isDownloading(entry.id) {
                            Button("移除", role: .destructive) { offlineLibrary.remove(entry) }
                        }
                    }
                    .listRowBackground(DesignTokens.surface)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(DesignTokens.canvas)
        .navigationTitle("已下载")
    }

    @ViewBuilder
    private func destination(for entry: OfflineEntry) -> some View {
        if entry.material.kind == "video" {
            VideoLearningView(material: entry.material)
        } else {
            ReaderView(offlineEntry: entry)
        }
    }

    private func summary(_ entry: OfflineEntry) -> String {
        guard entry.material.kind == "video" else {
            return "已下载 · \(entry.material.segments.count) 句"
        }
        var parts: [String] = []
        if let total = entry.totalVideoSegments {
            parts.append("视频 \(entry.downloadedVideoSegmentCount)/\(total)")
        }
        if let total = entry.totalAudioSegments {
            parts.append("跟读音频 \(entry.downloadedAudioSegmentCount)/\(total)")
        }
        if entry.hasIncompleteRequestedVideoMedia { parts.append("可继续") }
        return parts.isEmpty ? "尚无本地分片" : parts.joined(separator: " · ")
    }
}
