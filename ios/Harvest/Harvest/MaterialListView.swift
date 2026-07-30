import Combine
import SwiftUI

struct MaterialListView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var materials: [Material] = []
    @State private var errorMessage: String?
    @State private var isLoading = true
    private let statusRefresh = Timer.publish(every: 4, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            Group {
                if isLoading && materials.isEmpty {
                    VStack(spacing: 16) {
                        ProgressView()
                        Text("正在翻开材料库")
                            .foregroundStyle(DesignTokens.muted)
                    }
                } else if let errorMessage, materials.isEmpty {
                    ContentUnavailableView {
                        Label("暂时连不上材料库", systemImage: "wifi.exclamationmark")
                    } description: {
                        Text(errorMessage)
                    } actions: {
                        Button("再试一次") { Task { await load() } }
                    }
                } else if materials.isEmpty {
                    ContentUnavailableView {
                        Label("还没有材料", systemImage: "text.book.closed")
                    } description: {
                        Text("在 Mac 的摄入页面粘贴一段日语，朗读会在后台准备。")
                    }
                } else {
                    List {
                        Section {
                            ForEach(materials) { material in
                                NavigationLink(value: material.id) {
                                    MaterialRow(material: material)
                                }
                                .listRowBackground(DesignTokens.surface)
                                .listRowSeparator(.hidden)
                            }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .background(DesignTokens.canvas)
                }
            }
            .navigationDestination(for: Int.self) { materialID in
                ReaderView(materialID: materialID)
            }
            .navigationTitle("材料")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        NavigationLink { SettingsView() } label: {
                            Label("连接设置", systemImage: "gearshape")
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                            .foregroundStyle(DesignTokens.ink)
                    }
                }
            }
        }
        .task(id: configuration.endpoint) { await load() }
        .onReceive(statusRefresh) { _ in
            guard materials.contains(where: { $0.status == "pending" || $0.status == "processing" }) else {
                return
            }
            Task { await load(showingProgress: false) }
        }
    }

    @MainActor
    private func load(showingProgress: Bool = true) async {
        guard let endpoint = configuration.endpoint else { return }
        if showingProgress { isLoading = true }
        defer {
            if showingProgress { isLoading = false }
        }
        do {
            materials = try await APIClient(baseURL: endpoint).materials()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct MaterialRow: View {
    let material: Material

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(alignment: .leading, spacing: 8) {
                Text(material.title)
                    .font(.system(.headline, design: .serif))
                    .foregroundStyle(DesignTokens.ink)
                    .lineLimit(2)
                Text(statusLabel)
                    .font(.footnote)
                    .foregroundStyle(statusColor)
            }
            Spacer()
            if material.status == "ready" {
                Image(systemName: "play.circle.fill")
                    .font(.title3)
                    .foregroundStyle(DesignTokens.accent)
            }
        }
        .padding(.vertical, 14)
    }

    private var statusLabel: String {
        switch material.status {
        case "ready": "朗读已准备好"
        case "failed": material.errorMessage ?? "准备时出了点问题"
        case "processing": "正在准备朗读"
        default: "排队等候中"
        }
    }

    private var statusColor: Color {
        switch material.status {
        case "ready": DesignTokens.muted
        case "failed": DesignTokens.accent
        default: DesignTokens.muted
        }
    }
}
