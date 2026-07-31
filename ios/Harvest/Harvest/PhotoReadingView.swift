import PhotosUI
import SwiftUI

struct PhotoReadingView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var selection: PhotosPickerItem?
    @State private var message = "选一张包含日语的照片。"

    var body: some View {
        VStack(spacing: 22) {
            Text("把眼前的日语，\n留进材料库。") .font(.system(size: 32, design: .serif)).foregroundStyle(DesignTokens.ink)
            PhotosPicker("选择照片", selection: $selection, matching: .images).buttonStyle(PrimaryButtonStyle())
            Text(message).font(.footnote).foregroundStyle(DesignTokens.muted)
            Spacer()
        }.padding(DesignTokens.pageInset).background(DesignTokens.canvas.ignoresSafeArea()).navigationTitle("拍照阅读")
        .onChange(of: selection) { _, item in Task { await submit(item) } }
    }
    @MainActor private func submit(_ item: PhotosPickerItem?) async {
        guard let item, let data = try? await item.loadTransferable(type: Data.self), let endpoint = configuration.endpoint else { return }
        let url = FileManager.default.temporaryDirectory.appending(path: "photo-\(UUID().uuidString).jpg")
        do { try data.write(to: url); _ = try await APIClient(baseURL: endpoint).uploadPhoto(url); message = "已交给后台识别日语。" } catch { message = error.localizedDescription }
    }
}
