import SwiftUI

/// §15.6: the sections of one split video, each transcribed only when you ask.
///
/// A section that has not been transcribed is still watchable — it just has no subtitles.
/// Not transcribing is not the same as not being usable, so those rows stay tappable and
/// carry a button rather than a lock.
struct CollectionDetailView: View {
    let collection: MaterialCollection
    @EnvironmentObject private var configuration: AppConfiguration
    @Environment(\.dismiss) private var dismiss

    @State private var sections: [Material] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var starting: Set<Int> = []
    @State private var pendingDeletion: Material?
    @State private var isConfirmingCollectionDelete = false

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                header
                if isLoading && sections.isEmpty {
                    ProgressView().controlSize(.small).tint(DesignTokens.accent).padding(.top, 24)
                }
                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.accent)
                        .padding(.top, 12)
                }
                ForEach(sections) { section in
                    sectionRow(section)
                }
            }
            .padding(20)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(collection.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(role: .destructive) {
                    isConfirmingCollectionDelete = true
                } label: {
                    Image(systemName: "trash")
                }
                .accessibilityLabel("删掉整个合集")
            }
        }
        .confirmationDialog(
            "删掉「\(collection.title)」的全部 \(collection.sectionCount) 节？",
            isPresented: $isConfirmingCollectionDelete,
            titleVisibility: .visible
        ) {
            Button("删掉", role: .destructive) { Task { await deleteCollection() } }
            Button("算了", role: .cancel) {}
        } message: {
            Text("包括已经转录好的字幕。原片早就不在了，删了就得重新传。")
        }
        .confirmationDialog(
            pendingDeletion.map { "删掉「\($0.title)」？" } ?? "",
            isPresented: Binding(get: { pendingDeletion != nil }, set: { if !$0 { pendingDeletion = nil } }),
            titleVisibility: .visible
        ) {
            Button("删掉这一节", role: .destructive) {
                if let target = pendingDeletion { Task { await delete(target) } }
            }
            Button("算了", role: .cancel) { pendingDeletion = nil }
        }
        .refreshable { await load() }
        .task { await load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            // Facts only: how many, how long, how many are transcribed. No percentage and no
            // progress bar (§15.9, §1.4).
            Text(summary)
                .font(.footnote)
                .foregroundStyle(DesignTokens.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.bottom, 14)
    }

    private var summary: String {
        var parts = ["\(collection.sectionCount) 节"]
        if collection.totalDurationMs > 0 {
            parts.append(clock(collection.totalDurationMs))
        }
        let ready = sections.filter { $0.status == "ready" }.count
        parts.append(ready > 0 ? "转录过 \(ready) 节" : "还没转录")
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private func sectionRow(_ section: Material) -> some View {
        let index = (section.collectionIndex ?? 0) + 1
        HStack(alignment: .center, spacing: 10) {
            NavigationLink(value: section.id) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("第 \(index) 节")
                        .font(.system(size: 17, design: .serif))
                        .foregroundStyle(section.status == "ready" ? DesignTokens.ink : DesignTokens.ink.opacity(0.8))
                    Text(rowCaption(section))
                        .font(.footnote)
                        .foregroundStyle(captionColour(section))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if starting.contains(section.id) || section.status == "processing" {
                ProgressView().controlSize(.small).tint(DesignTokens.accent)
            } else if section.awaitsTranscription {
                Button("转录") { Task { await startTranscription(section) } }
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(DesignTokens.accent)
                    .buttonStyle(.plain)
            } else if section.status == "ready" {
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(DesignTokens.muted.opacity(0.5))
            }
        }
        .padding(.vertical, 11)
        .overlay(alignment: .bottom) {
            Rectangle().fill(DesignTokens.separator).frame(height: 0.5)
        }
        .contextMenu {
            Button("删掉这一节", role: .destructive) { pendingDeletion = section }
        }
    }

    private func rowCaption(_ section: Material) -> String {
        var parts: [String] = []
        if let duration = section.durationMs, duration > 0 {
            // §15.4: the produced length, not the difference between the marked points —
            // HLS segmentation quantises to six seconds and the two differ slightly.
            parts.append(clock(duration))
        }
        if let offset = section.sourceOffsetMs, offset > 0 {
            parts.append("原片 \(clock(offset)) 起")
        }
        switch section.status {
        case "ready": break
        case "downloaded": parts.append("还没转录")
        case "processing": parts.append(section.progressLabel ?? "正在处理")
        case "failed": parts.append(section.failureTitle ?? "失败了")
        default: parts.append("正在切")
        }
        return parts.joined(separator: " · ")
    }

    private func captionColour(_ section: Material) -> Color {
        section.status == "failed" ? DesignTokens.accent : DesignTokens.muted
    }

    @MainActor private func load() async {
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            isLoading = false
            return
        }
        do {
            sections = try await client.collectionDetail(id: collection.id).sections
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    @MainActor private func startTranscription(_ section: Material) async {
        guard let client else { return }
        starting.insert(section.id)
        do {
            _ = try await client.startTranscription(id: section.id)
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
        starting.remove(section.id)
    }

    @MainActor private func delete(_ section: Material) async {
        guard let client else { return }
        pendingDeletion = nil
        do {
            try await client.deleteMaterial(id: section.id)
            withAnimation { sections.removeAll { $0.id == section.id } }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor private func deleteCollection() async {
        guard let client else { return }
        do {
            try await client.deleteCollection(id: collection.id)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func clock(_ milliseconds: Int) -> String {
        let total = max(0, milliseconds) / 1_000
        let hours = total / 3_600
        let minutes = (total % 3_600) / 60
        let seconds = total % 60
        if hours > 0 { return String(format: "%d:%02d:%02d", hours, minutes, seconds) }
        return String(format: "%d:%02d", minutes, seconds)
    }
}
