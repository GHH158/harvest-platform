import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    let isOnboarding: Bool
    @State private var endpoint = ""
    @State private var errorMessage: String?
    @State private var memories: [LearnerMemory] = []
    @State private var isLoadingMemories = false
    @State private var memoryErrorMessage: String?
    @State private var updatingMemoryIDs: Set<Int> = []

    init(isOnboarding: Bool) {
        self.isOnboarding = isOnboarding
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                if isOnboarding {
                    Text("HARVEST")
                        .font(.caption.weight(.semibold))
                        .tracking(2)
                        .foregroundStyle(DesignTokens.accent)
                    Text("先把你和\n材料连起来。")
                        .font(.system(size: DesignTokens.heroSize, weight: .regular, design: .serif))
                        .tracking(-1)
                        .foregroundStyle(DesignTokens.ink)
                    Text("输入 Mac 上 Harvest 服务的 Tailscale HTTPS 地址。地址只保存在这台 iPhone 的钥匙串中。")
                        .font(.body)
                        .foregroundStyle(DesignTokens.muted)
                        .lineSpacing(4)
                } else {
                    SectionHeader(title: "连接", caption: "管理 Harvest 服务的连接地址。")
                }

                CardView {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("服务地址")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(DesignTokens.ink)
                        TextField("https://harvest.example.ts.net", text: $endpoint)
                            .textInputAutocapitalization(.never)
                            .keyboardType(.URL)
                            .autocorrectionDisabled()
                            .foregroundStyle(DesignTokens.ink)
                            .padding(14)
                            .background(DesignTokens.canvas, in: RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(DesignTokens.separator))
                        if let errorMessage {
                            Text(errorMessage)
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.accent)
                        }
                    }
                }

                Button(isOnboarding ? "连接材料库" : "保存并连接") {
                    do {
                        try configuration.saveEndpoint(endpoint)
                    } catch {
                        errorMessage = error.localizedDescription
                    }
                }
                .buttonStyle(PrimaryButtonStyle())

                if !isOnboarding, let host = configuration.endpoint?.host {
                    HStack(spacing: 8) {
                        StatusChip(status: "ready")
                        Text("已连接：\(host)")
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.muted)
                    }
                    Button("清除连接", role: .destructive) {
                        clearConnection()
                    }
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                }

                if !isOnboarding, configuration.endpoint != nil {
                    memorySection
                }
            }
            .padding(DesignTokens.pageInset)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(isOnboarding ? "" : "连接设置")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if endpoint.isEmpty {
                endpoint = configuration.endpoint?.absoluteString ?? ""
            }
        }
        .task(id: configuration.endpoint) {
            guard !isOnboarding else { return }
            await loadMemories()
        }
    }

    @ViewBuilder
    private var memorySection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(
                title: "系统记住的内容",
                caption: "这些有依据的判断会轻量影响聊天，你可以随时停用。"
            )
            CardView {
                VStack(alignment: .leading, spacing: 14) {
                    if isLoadingMemories {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small).tint(DesignTokens.accent)
                            Text("正在读取…")
                                .font(.footnote)
                                .foregroundStyle(DesignTokens.muted)
                        }
                    } else if let memoryErrorMessage {
                        Text(memoryErrorMessage)
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.muted)
                        Button("重试") { Task { await loadMemories() } }
                            .font(.footnote.weight(.medium))
                            .foregroundStyle(DesignTokens.accent)
                    } else if memories.isEmpty {
                        Text("暂时没有需要长期保留的学习倾向。")
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.muted)
                    } else {
                        ForEach(memories) { memory in
                            memoryRow(memory)
                            if memory.id != memories.last?.id {
                                Divider().overlay(DesignTokens.separator)
                            }
                        }
                    }
                }
            }
        }
    }

    private func memoryRow(_ memory: LearnerMemory) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(memory.content)
                .font(.subheadline)
                .foregroundStyle(memory.isDismissed ? DesignTokens.muted : DesignTokens.ink)
            Text("\(memory.reason) · \(memory.evidenceCount) 条依据")
                .font(.caption)
                .foregroundStyle(DesignTokens.muted)
            Button(memory.isDismissed ? "重新用于聊天" : "不再用于聊天") {
                Task { await toggleMemory(memory) }
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(DesignTokens.accent)
            .disabled(updatingMemoryIDs.contains(memory.id))
            .opacity(updatingMemoryIDs.contains(memory.id) ? 0.5 : 1)
        }
    }

    @MainActor
    private func loadMemories() async {
        guard let endpoint = configuration.endpoint else {
            memories = []
            return
        }
        isLoadingMemories = true
        memoryErrorMessage = nil
        defer { isLoadingMemories = false }
        do {
            memories = try await APIClient(baseURL: endpoint).learnerMemories()
        } catch {
            memoryErrorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func toggleMemory(_ memory: LearnerMemory) async {
        guard let endpoint = configuration.endpoint else { return }
        updatingMemoryIDs.insert(memory.id)
        memoryErrorMessage = nil
        defer { updatingMemoryIDs.remove(memory.id) }
        do {
            let client = APIClient(baseURL: endpoint)
            let updated = if memory.isDismissed {
                try await client.restoreLearnerMemory(id: memory.id)
            } else {
                try await client.dismissLearnerMemory(id: memory.id)
            }
            if let index = memories.firstIndex(where: { $0.id == updated.id }) {
                memories[index] = updated
            }
        } catch {
            memoryErrorMessage = error.localizedDescription
        }
    }

    private func clearConnection() {
        configuration.clearEndpoint()
        endpoint = ""
        errorMessage = nil
        memories = []
        memoryErrorMessage = nil
    }
}
