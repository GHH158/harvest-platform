import SwiftUI

struct VoiceTeacherView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var message = "正在检查语音老师。"
    var body: some View { VStack(alignment: .leading, spacing: 20) { Text("开口说日语。") .font(.system(size: 32, design: .serif)).foregroundStyle(DesignTokens.ink); Text(message).foregroundStyle(DesignTokens.muted); Spacer() }.padding(DesignTokens.pageInset).background(DesignTokens.canvas.ignoresSafeArea()).navigationTitle("语音老师").task { await load() } }
    @MainActor private func load() async { guard let endpoint = configuration.endpoint else { return }; do { let status = try await APIClient(baseURL: endpoint).voiceTeacherStatus(); message = status.configured ? "\(status.model) 已配置。实时通话将在百炼实调时启用。" : "尚未配置百炼 API Key。" } catch { message = error.localizedDescription } }
}
