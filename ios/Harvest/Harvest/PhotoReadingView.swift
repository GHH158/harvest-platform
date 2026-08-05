import PhotosUI
import SwiftUI
import UIKit

struct PhotoReadingView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var selection: PhotosPickerItem?
    @State private var isShowingCamera = false
    @State private var isSubmitting = false
    @State private var message = "拍下或选择一张包含日语的照片。"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("把眼前的日语，\n留进材料库。")
                    .font(.system(size: DesignTokens.heroSize, weight: .regular, design: .serif))
                    .tracking(-1)
                    .foregroundStyle(DesignTokens.ink)
                CardView {
                    VStack(spacing: 16) {
                        if UIImagePickerController.isSourceTypeAvailable(.camera) {
                            Button("打开相机") { isShowingCamera = true }
                                .buttonStyle(PrimaryButtonStyle())
                        }
                        PhotosPicker("从照片中选择", selection: $selection, matching: .images)
                            .buttonStyle(SecondaryButtonStyle())
                        if isSubmitting {
                            HStack(spacing: 8) {
                                ProgressView().tint(DesignTokens.accent)
                                Text("正在交给后台识别")
                                    .font(.footnote)
                                    .foregroundStyle(DesignTokens.muted)
                            }
                        }
                        Text(message)
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.muted)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .padding(DesignTokens.pageInset)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("拍照阅读")
        .sheet(isPresented: $isShowingCamera) {
            CameraPicker { image in
                isShowingCamera = false
                Task { await submit(image.jpegData(compressionQuality: 0.9)) }
            }
            .ignoresSafeArea()
        }
        .onChange(of: selection) { _, item in
            Task {
                guard let data = try? await item?.loadTransferable(type: Data.self),
                      let image = UIImage(data: data) else { return }
                await submit(image.jpegData(compressionQuality: 0.9))
            }
        }
    }

    @MainActor
    private func submit(_ data: Data?) async {
        guard let data, let endpoint = configuration.endpoint else { return }
        isSubmitting = true
        defer { isSubmitting = false }
        let url = FileManager.default.temporaryDirectory.appending(path: "photo-\(UUID().uuidString).jpg")
        defer { try? FileManager.default.removeItem(at: url) }
        do {
            try data.write(to: url, options: .atomic)
            _ = try await APIClient(baseURL: endpoint).uploadPhoto(url)
            message = "已交给后台识别。完成后会出现在材料列表。"
        } catch {
            message = error.localizedDescription
        }
    }
}

private struct CameraPicker: UIViewControllerRepresentable {
    let onCapture: (UIImage) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onCapture: onCapture) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let controller = UIImagePickerController()
        controller.sourceType = .camera
        controller.cameraCaptureMode = .photo
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        let onCapture: (UIImage) -> Void
        init(onCapture: @escaping (UIImage) -> Void) { self.onCapture = onCapture }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            if let image = info[.originalImage] as? UIImage { onCapture(image) }
            picker.dismiss(animated: true)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            picker.dismiss(animated: true)
        }
    }
}
