import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var endpoint = ""
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 26) {
            Spacer(minLength: 72)
            Text("HARVEST")
                .font(.caption.weight(.semibold))
                .tracking(2)
                .foregroundStyle(DesignTokens.accent)
            Text("先把你和\n材料连起来。")
                .font(.system(size: 38, weight: .regular, design: .serif))
                .tracking(-1)
                .foregroundStyle(DesignTokens.ink)
            Text("输入 Mac 上 Harvest 服务的 Tailscale HTTPS 地址。这个地址只保存在这台 iPhone 的钥匙串中。")
                .font(.body)
                .foregroundStyle(DesignTokens.muted)
                .lineSpacing(4)
            VStack(alignment: .leading, spacing: 10) {
                Text("服务地址")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(DesignTokens.ink)
                TextField("https://harvest.example.ts.net", text: $endpoint)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .padding(14)
                    .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(DesignTokens.separator))
                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.accent)
                }
            }
            Button("连接材料库") {
                do {
                    try configuration.saveEndpoint(endpoint)
                } catch {
                    errorMessage = error.localizedDescription
                }
            }
            .buttonStyle(PrimaryButtonStyle())
            Spacer()
        }
        .padding(DesignTokens.pageInset)
        .background(DesignTokens.canvas.ignoresSafeArea())
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(Color.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 15)
            .background(DesignTokens.accent.opacity(configuration.isPressed ? 0.82 : 1), in: RoundedRectangle(cornerRadius: 13))
    }
}
