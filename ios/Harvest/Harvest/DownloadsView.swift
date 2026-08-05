import SwiftUI

struct DownloadsView: View {
    @EnvironmentObject private var offlineLibrary: OfflineLibrary
    @State private var isSelecting = false
    @State private var selectedIDs: Set<Int> = []
    @State private var showDeleteConfirmation = false
    @State private var storageInfo = OfflineStorageInfo(usedBytes: 0, availableBytes: 0)
    @State private var cacheMessage: String?

    var body: some View {
        List {
            storageSection
            if offlineLibrary.entries.isEmpty {
                ContentUnavailableView {
                    Label("还没有已下载素材", systemImage: "arrow.down.circle")
                } description: {
                    Text("打开可学习的素材，把朗读、观看视频或跟读音频留在这台 iPhone 上。")
                }
                .listRowBackground(DesignTokens.canvas)
            } else {
                Section("离线素材") {
                    ForEach(offlineLibrary.entries) { entry in
                        downloadRow(entry)
                            .padding(.vertical, 6)
                            .swipeActions {
                                if !isSelecting, !offlineLibrary.isDownloading(entry.id) {
                                    Button("移除", role: .destructive) {
                                        offlineLibrary.remove(entry)
                                        refreshStorage()
                                    }
                                }
                            }
                            .listRowBackground(DesignTokens.surface)
                    }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(DesignTokens.canvas)
        .navigationTitle("下载")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if !offlineLibrary.entries.isEmpty {
                Button(isSelecting ? "完成" : "选择") {
                    isSelecting.toggle()
                    if !isSelecting { selectedIDs.removeAll() }
                }
            }
        }
        .safeAreaInset(edge: .top) {
            VStack(spacing: 8) {
                if let warning = offlineLibrary.loadWarning { banner(warning) }
                if needsWiFi { banner("需要连接 Wi-Fi 才能继续下载") }
            }
            .padding(.horizontal, DesignTokens.pageInset)
            .padding(.top, 6)
        }
        .safeAreaInset(edge: .bottom) {
            if isSelecting {
                Button("删除所选 \(selectedIDs.count) 项", role: .destructive) {
                    showDeleteConfirmation = true
                }
                .disabled(selectedIDs.isEmpty)
                .font(.body.weight(.semibold))
                .foregroundStyle(Color.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(DesignTokens.accent.opacity(selectedIDs.isEmpty ? 0.45 : 1), in: RoundedRectangle(cornerRadius: 13))
                .padding(.horizontal, DesignTokens.pageInset)
                .padding(.vertical, 10)
                .background(DesignTokens.surface)
            }
        }
        .alert("删除所选离线素材？", isPresented: $showDeleteConfirmation) {
            Button("取消", role: .cancel) {}
            Button("删除", role: .destructive) {
                offlineLibrary.remove(ids: selectedIDs)
                selectedIDs.removeAll()
                isSelecting = false
                refreshStorage()
            }
        } message: {
            Text("将从这台 iPhone 删除 \(selectedIDs.count) 项离线内容，不影响服务器素材。")
        }
        .task { refreshStorage() }
        .onChange(of: storageSignature) { _, _ in refreshStorage() }
    }

    private var storageSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("离线存储")
                            .font(.headline)
                            .foregroundStyle(DesignTokens.ink)
                        Text("Harvest 已使用 \(bytes(storageInfo.usedBytes))")
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.muted)
                    }
                    Spacer()
                    Image(systemName: "internaldrive")
                        .font(.title2)
                        .foregroundStyle(DesignTokens.accent)
                }
                Text("iPhone 可用 \(bytes(storageInfo.availableBytes))")
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
                HStack {
                    Button("清理缓存") {
                        let freed = offlineLibrary.clearCache()
                        cacheMessage = freed > 0 ? "已释放 \(bytes(freed))" : "没有需要清理的缓存"
                        refreshStorage()
                    }
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DesignTokens.accent)
                    Spacer()
                    if let cacheMessage {
                        Text(cacheMessage)
                            .font(.caption)
                            .foregroundStyle(DesignTokens.muted)
                    }
                }
            }
            .padding(.vertical, 6)
        }
        .listRowBackground(DesignTokens.surface)
    }

    @ViewBuilder
    private func downloadRow(_ entry: OfflineEntry) -> some View {
        if isSelecting {
            Button {
                if selectedIDs.contains(entry.id) { selectedIDs.remove(entry.id) }
                else if !offlineLibrary.isDownloading(entry.id) { selectedIDs.insert(entry.id) }
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: selectedIDs.contains(entry.id) ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(selectedIDs.contains(entry.id) ? DesignTokens.accent : DesignTokens.muted)
                    rowContent(entry)
                }
            }
            .buttonStyle(.plain)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                NavigationLink { destination(for: entry) } label: { rowContent(entry) }
                if entry.hasIncompleteRequestedVideoMedia {
                    Button(offlineLibrary.isDownloading(entry.id) ? "正在继续下载" : "继续下载") {
                        Task { try? await offlineLibrary.resume(entry) }
                    }
                    .disabled(offlineLibrary.isDownloading(entry.id))
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DesignTokens.accent)
                }
            }
        }
    }

    private func rowContent(_ entry: OfflineEntry) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(entry.material.title)
                .font(.system(.headline, design: .serif))
                .foregroundStyle(DesignTokens.ink)
                .lineLimit(2)
            Text(summary(entry))
                .font(.footnote)
                .foregroundStyle(DesignTokens.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var needsWiFi: Bool {
        guard offlineLibrary.connectivity != .wifi, offlineLibrary.connectivity != .unknown else { return false }
        return offlineLibrary.entries.contains(where: \.hasIncompleteRequestedVideoMedia)
    }

    private var storageSignature: String {
        offlineLibrary.entries.map {
            "\($0.id):\($0.downloadedVideoSegmentCount):\($0.downloadedAudioSegmentCount):\($0.localAudioPath ?? "")"
        }.joined(separator: "|")
    }

    private func refreshStorage() { storageInfo = offlineLibrary.storageInfo() }

    private func banner(_ text: String) -> some View {
        Text(text)
            .font(.footnote.weight(.semibold))
            .foregroundStyle(DesignTokens.accent)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private func destination(for entry: OfflineEntry) -> some View {
        if entry.material.kind == "video" { VideoLearningView(material: entry.material) }
        else { ReaderView(offlineEntry: entry) }
    }

    private func summary(_ entry: OfflineEntry) -> String {
        guard entry.material.kind == "video" else { return "朗读 · \(entry.material.segments.count) 句" }
        var parts: [String] = []
        if let total = entry.totalVideoSegments { parts.append("视频 \(entry.downloadedVideoSegmentCount)/\(total)") }
        if let total = entry.totalAudioSegments { parts.append("跟读音频 \(entry.downloadedAudioSegmentCount)/\(total)") }
        if entry.hasIncompleteRequestedVideoMedia { parts.append("可继续") }
        return parts.isEmpty ? "尚无本地分片" : parts.joined(separator: " · ")
    }

    private func bytes(_ value: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: value, countStyle: .file)
    }
}
