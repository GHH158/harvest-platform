import SwiftUI

struct DownloadsView: View {
    @EnvironmentObject private var offlineLibrary: OfflineLibrary

    var body: some View {
        List {
            if offlineLibrary.entries.isEmpty {
                ContentUnavailableView {
                    Label("还没有已下载材料", systemImage: "arrow.down.circle")
                } description: {
                    Text("打开一篇已准备好的材料，将朗读留在这台 iPhone 上。")
                }
                .listRowBackground(DesignTokens.canvas)
            } else {
                ForEach(offlineLibrary.entries) { entry in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(entry.material.title).font(.system(.headline, design: .serif)).foregroundStyle(DesignTokens.ink)
                        Text("已下载 · \(entry.material.segments.count) 句").font(.footnote).foregroundStyle(DesignTokens.muted)
                    }
                    .padding(.vertical, 8)
                    .swipeActions { Button("移除", role: .destructive) { offlineLibrary.remove(entry) } }
                    .listRowBackground(DesignTokens.surface)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(DesignTokens.canvas)
        .navigationTitle("已下载")
    }
}
