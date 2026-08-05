import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    let isOnboarding: Bool
    @State private var endpoint = ""
    @State private var errorMessage: String?

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
    }

    private func clearConnection() {
        configuration.clearEndpoint()
        endpoint = ""
        errorMessage = nil
    }
}
