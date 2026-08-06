import SwiftUI
import UniformTypeIdentifiers

private enum MaterialStatusFilter: String, CaseIterable, Identifiable {
    case library
    case all
    case ready
    case processing
    case downloaded
    case failed

    var id: String { rawValue }
    var label: String {
        switch self {
        case .library: "素材库"
        case .all: "全部"
        case .ready: "可学习"
        case .processing: "处理中"
        case .downloaded: "待转录"
        case .failed: "需要处理"
        }
    }
}

private enum MaterialKindFilter: String, CaseIterable, Identifiable {
    case all
    case reading
    case video

    var id: String { rawValue }
    var label: String {
        switch self {
        case .all: "全部类型"
        case .reading: "阅读"
        case .video: "视频"
        }
    }
}

private enum MaterialSort: String, CaseIterable, Identifiable {
    case newest
    case oldest
    case longest
    case shortest

    var id: String { rawValue }
    var label: String {
        switch self {
        case .newest: "最近导入"
        case .oldest: "最早导入"
        case .longest: "时长从长到短"
        case .shortest: "时长从短到长"
        }
    }
}

struct MaterialListView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var materials: [Material] = []
    @State private var errorMessage: String?
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var statusFilter: MaterialStatusFilter = .library
    @State private var kindFilter: MaterialKindFilter = .all
    @State private var sort: MaterialSort = .newest
    @State private var actionMaterialIDs: Set<Int> = []
    @State private var reasonMaterial: Material?

    var body: some View {
        Group {
            if isLoading && materials.isEmpty {
                WarmEmptyState(title: "正在翻开素材库", systemImage: "book")
            } else if let errorMessage, materials.isEmpty {
                WarmEmptyState(
                    title: "暂时连不上素材库",
                    systemImage: "wifi.exclamationmark",
                    message: errorMessage,
                    actionTitle: "再试一次"
                ) {
                    Task { await load() }
                }
            } else {
                libraryContent
            }
        }
        .navigationDestination(for: Int.self) { materialID in
            ReaderView(materialID: materialID)
        }
        .navigationTitle("素材库")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $searchText, placement: .navigationBarDrawer(displayMode: .automatic), prompt: "搜索标题或来源")
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                filterMenu
                importMenu
            }
        }
        .sheet(item: $reasonMaterial) { material in
            FailureReasonSheet(material: material)
                .presentationDetents([.medium])
        }
        .alert("操作没有完成", isPresented: Binding(
            get: { errorMessage != nil && !materials.isEmpty },
            set: { if !$0 { errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "未知错误")
        }
        .task(id: configuration.endpoint) {
            await load()
            // Poll only after the first paint finishes, and only while jobs are active.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(4))
                guard materials.contains(where: { $0.status == "pending" || $0.status == "processing" }) else {
                    continue
                }
                await load(showingProgress: false)
            }
        }
    }

    private var libraryContent: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                librarySummary
                if statusFilter == .library, failedCount > 0, searchText.isEmpty {
                    Button {
                        statusFilter = .failed
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "wrench.and.screwdriver")
                            Text("\(failedCount) 个素材需要处理")
                            Spacer()
                            Text("查看")
                            Image(systemName: "chevron.right")
                        }
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(DesignTokens.muted)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 11)
                        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(DesignTokens.separator))
                    }
                    .buttonStyle(.plain)
                }

                if visibleMaterials.isEmpty {
                    WarmEmptyState(
                        title: searchText.isEmpty ? "这里还没有素材" : "没有找到匹配素材",
                        systemImage: "text.magnifyingglass",
                        message: searchText.isEmpty ? "点右上角 + 导入文字、网页、视频或照片。" : "换一个关键词或筛选条件试试。"
                    )
                } else {
                    ForEach(visibleMaterials) { material in
                        materialRow(material)
                    }
                }
            }
            .padding(.horizontal, DesignTokens.pageInset)
            .padding(.top, 6)
            .padding(.bottom, 28)
        }
        .background(DesignTokens.canvas)
        .refreshable { await load(showingProgress: false) }
    }

    private var librarySummary: some View {
        HStack(spacing: 8) {
            Label(statusFilter.label, systemImage: "line.3.horizontal.decrease.circle")
            if kindFilter != .all {
                Text("· \(kindFilter.label)")
            }
            Spacer()
            Text("\(visibleMaterials.count) 项")
        }
        .font(.caption)
        .foregroundStyle(DesignTokens.muted)
        .padding(.horizontal, 2)
    }

    @ViewBuilder
    private func materialRow(_ material: Material) -> some View {
        let card = MaterialCard(
            material: material,
            endpoint: configuration.endpoint,
            isActing: actionMaterialIDs.contains(material.id),
            onRetry: { Task { await retry(material) } },
            onReason: { reasonMaterial = material },
            onStartTranscription: { Task { await startTranscription(material) } }
        )
        if material.status == "ready" {
            NavigationLink(value: material.id) { card }
                .buttonStyle(.plain)
        } else {
            card
        }
    }

    private var filterMenu: some View {
        Menu {
            Picker("状态", selection: $statusFilter) {
                ForEach(MaterialStatusFilter.allCases) { Text($0.label).tag($0) }
            }
            Picker("类型", selection: $kindFilter) {
                ForEach(MaterialKindFilter.allCases) { Text($0.label).tag($0) }
            }
            Divider()
            Picker("排序", selection: $sort) {
                ForEach(MaterialSort.allCases) { Text($0.label).tag($0) }
            }
            Button("刷新") { Task { await load() } }
        } label: {
            Image(systemName: "line.3.horizontal.decrease.circle")
                .foregroundStyle(DesignTokens.ink)
        }
        .accessibilityLabel("筛选与排序")
    }

    private var importMenu: some View {
        Menu {
            NavigationLink { MaterialImportView(kind: .text) } label: {
                Label("粘贴文本", systemImage: "doc.on.clipboard")
            }
            NavigationLink { MaterialImportView(kind: .webpage) } label: {
                Label("网页链接", systemImage: "link")
            }
            NavigationLink { MaterialImportView(kind: .videoLink) } label: {
                Label("视频链接", systemImage: "play.rectangle")
            }
            NavigationLink { LocalVideoImportView() } label: {
                Label("本地视频", systemImage: "square.and.arrow.up")
            }
            NavigationLink { PhotoReadingView() } label: {
                Label("拍照或照片", systemImage: "camera")
            }
        } label: {
            Image(systemName: "plus")
                .font(.body.weight(.semibold))
                .foregroundStyle(DesignTokens.ink)
        }
        .accessibilityLabel("添加素材")
    }

    private var failedCount: Int { materials.count { $0.status == "failed" } }

    private var visibleMaterials: [Material] {
        var result = materials.filter { material in
            let statusMatches: Bool = switch statusFilter {
            case .library: material.status != "failed"
            case .all: true
            case .ready: material.status == "ready"
            case .processing: material.status == "pending" || material.status == "processing"
            case .downloaded: material.status == "downloaded"
            case .failed: material.status == "failed"
            }
            let kindMatches = kindFilter == .all || material.kind == kindFilter.rawValue
            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let searchMatches = query.isEmpty
                || material.title.lowercased().contains(query)
                || (material.sourceRef?.lowercased().contains(query) == true)
            return statusMatches && kindMatches && searchMatches
        }
        result.sort { lhs, rhs in
            switch sort {
            case .newest: return (lhs.createdAt ?? "") > (rhs.createdAt ?? "")
            case .oldest: return (lhs.createdAt ?? "") < (rhs.createdAt ?? "")
            case .longest: return (lhs.durationMs ?? -1) > (rhs.durationMs ?? -1)
            case .shortest:
                if lhs.durationMs == nil { return false }
                if rhs.durationMs == nil { return true }
                return (lhs.durationMs ?? 0) < (rhs.durationMs ?? 0)
            }
        }
        return result
    }

    @MainActor
    private func retry(_ material: Material) async {
        guard let endpoint = configuration.endpoint else { return }
        actionMaterialIDs.insert(material.id)
        defer { actionMaterialIDs.remove(material.id) }
        do {
            _ = try await APIClient(baseURL: endpoint).retryMaterial(id: material.id)
            await load(showingProgress: false)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func startTranscription(_ material: Material) async {
        guard let endpoint = configuration.endpoint else { return }
        actionMaterialIDs.insert(material.id)
        defer { actionMaterialIDs.remove(material.id) }
        do {
            _ = try await APIClient(baseURL: endpoint).startTranscription(id: material.id)
            await load(showingProgress: false)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func load(showingProgress: Bool = true) async {
        guard let endpoint = configuration.endpoint else { return }
        if showingProgress { isLoading = true }
        defer { if showingProgress { isLoading = false } }
        do {
            materials = try await APIClient(baseURL: endpoint).materials()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct MaterialCard: View {
    let material: Material
    let endpoint: URL?
    let isActing: Bool
    let onRetry: () -> Void
    let onReason: () -> Void
    let onStartTranscription: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack(alignment: .top, spacing: 12) {
                MaterialThumbnail(material: material, endpoint: endpoint)
                VStack(alignment: .leading, spacing: 7) {
                    Text(material.title)
                        .font(.system(.headline, design: .serif))
                        .foregroundStyle(DesignTokens.ink)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    HStack(spacing: 6) {
                        Label(durationText, systemImage: "clock")
                        Text("·")
                        Text(sourceText).lineLimit(1)
                    }
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
                    HStack(spacing: 6) {
                        Label(material.kind == "video" ? "视频" : "阅读", systemImage: material.kind == "video" ? "film" : "text.book.closed")
                        Text("·")
                        Text(relativeImportTime(material.createdAt))
                    }
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            if material.status == "pending" || material.status == "processing" {
                processingState
            } else if material.status == "failed" {
                failureState
            } else if material.status == "downloaded" {
                downloadedState
            }
        }
        .padding(13)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 15))
        .overlay(RoundedRectangle(cornerRadius: 15).stroke(DesignTokens.separator))
    }

    private var processingState: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(material.progressLabel ?? "正在生成素材")
                Spacer()
                Text("\(material.progressPercent ?? 0)%").monospacedDigit()
            }
            .font(.footnote.weight(.semibold))
            .foregroundStyle(DesignTokens.ink)
            ProgressView(value: Double(material.progressPercent ?? 0), total: 100)
                .tint(DesignTokens.accent)
            if let eta = material.etaMinutes {
                Text("预计还需要约 \(eta) 分钟")
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
            }
        }
    }

    private var failureState: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(material.failureTitle ?? "素材处理失败")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(DesignTokens.ink)
            Text(material.failureSummary ?? "后台处理未能完成")
                .font(.caption)
                .foregroundStyle(DesignTokens.muted)
            HStack(spacing: 14) {
                Button(isActing ? "正在重试" : "重新尝试", action: onRetry)
                    .disabled(isActing || material.retryable == false)
                Button("查看原因", action: onReason)
            }
            .font(.footnote.weight(.semibold))
            .foregroundStyle(DesignTokens.accent)
        }
        .padding(10)
        .background(DesignTokens.accentWash.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
    }

    private var downloadedState: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("视频已在 Mac 上准备好")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DesignTokens.ink)
                Text("开始转录后会上传并调用字幕服务")
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
            }
            Spacer()
            Button(isActing ? "正在开始" : "开始转录", action: onStartTranscription)
                .disabled(isActing)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(DesignTokens.accent)
        }
    }

    private var durationText: String {
        guard let duration = material.durationMs, duration > 0 else { return "时长准备中" }
        let seconds = duration / 1_000
        if seconds >= 3_600 { return String(format: "%d:%02d:%02d", seconds / 3_600, seconds / 60 % 60, seconds % 60) }
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }

    private var sourceText: String {
        switch material.sourceType {
        case "paste": "粘贴文本"
        case "photo": "照片"
        case "file": material.sourceRef ?? "本地文件"
        case "url":
            if let value = material.sourceRef, let host = URL(string: value)?.host { host.replacingOccurrences(of: "www.", with: "") }
            else { "链接" }
        default: material.sourceRef ?? material.sourceType
        }
    }
}

private struct MaterialThumbnail: View {
    let material: Material
    let endpoint: URL?

    var body: some View {
        Group {
            if let thumbnailURL {
                AsyncImage(url: thumbnailURL) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFill()
                    } else {
                        placeholder
                    }
                }
            } else {
                placeholder
            }
        }
        .frame(width: 94, height: 76)
        .clipShape(RoundedRectangle(cornerRadius: 11))
        .overlay(alignment: .bottomTrailing) {
            Image(systemName: material.kind == "video" ? "film.fill" : "text.book.closed.fill")
                .font(.caption2)
                .foregroundStyle(Color.white)
                .padding(5)
                .background(Color.black.opacity(0.48), in: Circle())
                .padding(5)
        }
    }

    private var placeholder: some View {
        ZStack {
            LinearGradient(
                colors: [DesignTokens.accentWash, DesignTokens.surface],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Image(systemName: material.kind == "video" ? "play.rectangle" : "text.quote")
                .font(.title2)
                .foregroundStyle(DesignTokens.accent.opacity(0.72))
        }
    }

    private var thumbnailURL: URL? {
        guard let endpoint, let path = material.thumbnailPath else { return nil }
        return endpoint.appending(path: path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }
}

private struct FailureReasonSheet: View {
    let material: Material
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(material.failureTitle ?? "素材处理失败")
                        .font(.system(.title3, design: .serif, weight: .semibold))
                    Text(material.failureSummary ?? "后台处理未能完成")
                        .foregroundStyle(DesignTokens.muted)
                    Divider().overlay(DesignTokens.separator)
                    Text("技术原因")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(DesignTokens.muted)
                    Text(material.errorMessage ?? "没有更多错误信息。")
                        .font(.footnote.monospaced())
                        .textSelection(.enabled)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(DesignTokens.pageInset)
            }
            .background(DesignTokens.canvas)
            .navigationTitle("失败原因")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { Button("完成") { dismiss() } }
        }
    }
}

enum MaterialImportKind {
    case text
    case webpage
    case videoLink

    var title: String {
        switch self {
        case .text: "粘贴文本"
        case .webpage: "导入网页"
        case .videoLink: "导入视频链接"
        }
    }
}

struct MaterialImportView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @Environment(\.dismiss) private var dismiss
    let kind: MaterialImportKind
    @State private var title = ""
    @State private var content = ""
    @State private var isSubmitting = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(title: kind.title, caption: hint)
                CardView {
                    VStack(alignment: .leading, spacing: 14) {
                        TextField("标题（可选）", text: $title)
                            .textFieldStyle(.roundedBorder)
                        if kind == .text {
                            TextEditor(text: $content)
                                .frame(minHeight: 220)
                                .scrollContentBackground(.hidden)
                                .padding(8)
                                .background(DesignTokens.canvas, in: RoundedRectangle(cornerRadius: 10))
                        } else {
                            TextField(kind == .webpage ? "https://example.com/article" : "https://…/video", text: $content)
                                .keyboardType(.URL)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .textFieldStyle(.roundedBorder)
                        }
                        if let errorMessage {
                            Text(errorMessage).font(.footnote).foregroundStyle(DesignTokens.accent)
                        }
                        Button(isSubmitting ? "正在提交" : "添加到素材库") {
                            Task { await submit() }
                        }
                        .buttonStyle(PrimaryButtonStyle())
                        .disabled(isSubmitting || content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
            .padding(DesignTokens.pageInset)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(kind.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var hint: String {
        switch kind {
        case .text: "粘贴日语正文，后台会生成朗读和词级时间轴。"
        case .webpage: "Mac 提取网页正文后进入阅读流水线。"
        case .videoLink: "默认下载不高于 720p，完成本地处理后再手动开始转录。"
        }
    }

    @MainActor
    private func submit() async {
        guard let endpoint = configuration.endpoint else { return }
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            let client = APIClient(baseURL: endpoint)
            switch kind {
            case .text:
                _ = try await client.createReading(title: title, text: content)
            case .webpage:
                _ = try await client.createReading(title: title, url: content)
            case .videoLink:
                _ = try await client.createVideoLink(title: title, url: content)
            }
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct LocalVideoImportView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var videoURL: URL?
    @State private var isChoosingFile = false
    @State private var isSubmitting = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(title: "导入本地视频", caption: "视频会流式上传到 Mac，不会整段载入 iPhone 内存。")
                CardView {
                    VStack(alignment: .leading, spacing: 14) {
                        TextField("标题（可选）", text: $title)
                            .textFieldStyle(.roundedBorder)
                        Button(videoURL == nil ? "选择视频文件" : "重新选择") { isChoosingFile = true }
                            .buttonStyle(SecondaryButtonStyle())
                        if let videoURL {
                            Label(videoURL.lastPathComponent, systemImage: "film")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                                .lineLimit(2)
                        }
                        if let errorMessage {
                            Text(errorMessage).font(.footnote).foregroundStyle(DesignTokens.accent)
                        }
                        Button(isSubmitting ? "正在上传" : "添加到素材库") {
                            Task { await submit() }
                        }
                        .buttonStyle(PrimaryButtonStyle())
                        .disabled(isSubmitting || videoURL == nil)
                    }
                }
            }
            .padding(DesignTokens.pageInset)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("本地视频")
        .navigationBarTitleDisplayMode(.inline)
        .fileImporter(isPresented: $isChoosingFile, allowedContentTypes: [.movie]) { result in
            switch result {
            case .success(let url): videoURL = url; errorMessage = nil
            case .failure(let error): errorMessage = error.localizedDescription
            }
        }
    }

    @MainActor
    private func submit() async {
        guard let endpoint = configuration.endpoint, let videoURL else { return }
        isSubmitting = true
        defer { isSubmitting = false }
        let accessed = videoURL.startAccessingSecurityScopedResource()
        defer { if accessed { videoURL.stopAccessingSecurityScopedResource() } }
        do {
            _ = try await APIClient(baseURL: endpoint).uploadVideo(videoURL, title: title)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

func relativeImportTime(_ value: String?, now: Date = .now) -> String {
    guard let value, let date = parseAPIDate(value) else { return "时间未知" }
    let formatter = RelativeDateTimeFormatter()
    formatter.locale = Locale(identifier: "zh_CN")
    formatter.unitsStyle = .full
    return formatter.localizedString(for: date, relativeTo: now)
}

private func parseAPIDate(_ value: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = formatter.date(from: value) { return date }
    formatter.formatOptions = [.withInternetDateTime]
    return formatter.date(from: value)
}
