import AVFoundation
import SwiftUI

@MainActor
final class ShadowingRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?

    func toggle() async throws -> URL? {
        if isRecording {
            recorder?.stop(); recorder = nil; isRecording = false
            return recordingURL
        }
        let permitted = await AVAudioApplication.requestRecordPermission()
        guard permitted else { throw ShadowingError.microphoneDenied }
        let url = FileManager.default.temporaryDirectory.appending(path: "shadowing-\(UUID().uuidString).m4a")
        try AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .spokenAudio)
        try AVAudioSession.sharedInstance().setActive(true)
        let next = try AVAudioRecorder(url: url, settings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 44_100, AVNumberOfChannelsKey: 1])
        next.record(); recorder = next; recordingURL = url; isRecording = true
        return nil
    }
}

enum ShadowingError: LocalizedError { case microphoneDenied; var errorDescription: String? { "需要麦克风权限才能录下跟读。" } }

struct ShadowingView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    let segment: Segment
    @StateObject private var recorder = ShadowingRecorder()
    @State private var attempt: ShadowingAttempt?
    @State private var errorMessage: String?
    @State private var isUploading = false

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Text(segment.textJA).font(.system(size: DesignTokens.readingSize, design: .serif)).foregroundStyle(DesignTokens.ink)
            Button(recorder.isRecording ? "结束录音" : "开始跟读") { Task { await record() } }
                .buttonStyle(PrimaryButtonStyle())
            if isUploading { ProgressView("正在交给后台评分") }
            if let attempt, let score = attempt.score {
                Text("识别度 \(Int(score * 100))%") .font(.system(.title2, design: .serif)).foregroundStyle(DesignTokens.ink)
                if let diff = attempt.diff { Text(diff.filter { !$0.recognized }.map(\.surface).joined()).foregroundStyle(DesignTokens.accent) }
            } else { Text("评分依赖 ASR；未配置百炼时会保留明确的等待/失败状态。") .font(.footnote).foregroundStyle(DesignTokens.muted) }
            if let errorMessage { Text(errorMessage).font(.footnote).foregroundStyle(DesignTokens.accent) }
            Spacer()
        }.padding(DesignTokens.pageInset).background(DesignTokens.canvas.ignoresSafeArea()).navigationTitle("跟读")
    }

    @MainActor private func record() async {
        do { if let url = try await recorder.toggle() { await upload(url) } } catch { errorMessage = error.localizedDescription }
    }
    @MainActor private func upload(_ url: URL) async {
        guard let endpoint = configuration.endpoint else { return }; isUploading = true; defer { isUploading = false }
        do { let submission = try await APIClient(baseURL: endpoint).uploadShadowing(segmentID: segment.id, audioURL: url); attempt = try await APIClient(baseURL: endpoint).shadowing(id: submission.attemptID) } catch { errorMessage = error.localizedDescription }
    }
}
