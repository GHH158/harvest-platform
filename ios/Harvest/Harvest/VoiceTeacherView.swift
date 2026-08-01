@preconcurrency import AVFoundation
import Foundation
import SwiftUI

private final class AudioBufferSource: @unchecked Sendable {
    private let buffer: AVAudioPCMBuffer
    private let lock = NSLock()
    private var supplied = false

    init(_ buffer: AVAudioPCMBuffer) { self.buffer = buffer }

    func next(_ status: UnsafeMutablePointer<AVAudioConverterInputStatus>) -> AVAudioBuffer? {
        lock.lock()
        defer { lock.unlock() }
        if supplied {
            status.pointee = .noDataNow
            return nil
        }
        supplied = true
        status.pointee = .haveData
        return buffer
    }
}

func voiceTeacherWebSocketURL(baseURL: URL) -> URL? {
    let url = baseURL.appending(path: "voice-teacher/ws")
    guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
    switch components.scheme {
    case "https": components.scheme = "wss"
    case "http": components.scheme = "ws"
    default: return nil
    }
    return components.url
}

@MainActor
final class VoiceTeacherSession: ObservableObject {
    @Published private(set) var isConnected = false
    @Published private(set) var statusText = "尚未开始。"
    @Published private(set) var userTranscript = ""
    @Published private(set) var teacherTranscript = ""

    private let audioEngine = AVAudioEngine()
    private let outputNode = AVAudioPlayerNode()
    private var socket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var converter: AVAudioConverter?
    private var hasInputTap = false

    func connect(baseURL: URL) async {
        guard !isConnected, let url = voiceTeacherWebSocketURL(baseURL: baseURL) else { return }
        guard await microphonePermission() else {
            statusText = "没有麦克风权限。请在系统设置中允许 Harvest 使用麦克风。"
            return
        }
        do {
            try configureAudio()
            let task = URLSession.shared.webSocketTask(with: url)
            socket = task
            task.resume()
            isConnected = true
            statusText = "正在连接语音老师。"
            receiveTask = Task { [weak self] in await self?.receiveLoop() }
            try startMicrophone()
        } catch {
            disconnect(message: error.localizedDescription)
        }
    }

    func disconnect(message: String = "通话已经结束。") {
        receiveTask?.cancel()
        receiveTask = nil
        socket?.cancel(with: .normalClosure, reason: nil)
        socket = nil
        if hasInputTap {
            audioEngine.inputNode.removeTap(onBus: 0)
            hasInputTap = false
        }
        outputNode.stop()
        audioEngine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        isConnected = false
        statusText = message
    }

    private func microphonePermission() async -> Bool {
        await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { allowed in continuation.resume(returning: allowed) }
        }
    }

    private func configureAudio() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try session.setActive(true)
        if !audioEngine.attachedNodes.contains(outputNode) { audioEngine.attach(outputNode) }
        let outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 24_000,
            channels: 1,
            interleaved: false
        )!
        audioEngine.connect(outputNode, to: audioEngine.mainMixerNode, format: outputFormat)
    }

    private func startMicrophone() throws {
        let input = audioEngine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        guard let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 16_000,
            channels: 1,
            interleaved: false
        ), let converter = AVAudioConverter(from: inputFormat, to: targetFormat) else {
            throw VoiceTeacherError.audioFormat
        }
        self.converter = converter
        input.installTap(onBus: 0, bufferSize: 2_048, format: inputFormat) { [weak self] buffer, _ in
            guard let self else { return }
            let capacity = AVAudioFrameCount(
                ceil(Double(buffer.frameLength) * targetFormat.sampleRate / inputFormat.sampleRate)
            )
            guard let converted = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else { return }
            var conversionError: NSError?
            let source = AudioBufferSource(buffer)
            converter.convert(to: converted, error: &conversionError) { _, status in
                source.next(status)
            }
            guard conversionError == nil, converted.frameLength > 0,
                  let samples = converted.int16ChannelData?.pointee else { return }
            let data = Data(bytes: samples, count: Int(converted.frameLength) * MemoryLayout<Int16>.size)
            Task { @MainActor [weak self] in await self?.sendAudio(data) }
        }
        hasInputTap = true
        audioEngine.prepare()
        try audioEngine.start()
    }

    private func sendAudio(_ data: Data) async {
        guard isConnected, let socket else { return }
        let event: [String: String] = [
            "type": "input_audio_buffer.append",
            "audio": data.base64EncodedString(),
        ]
        guard let payload = try? JSONSerialization.data(withJSONObject: event),
              let text = String(data: payload, encoding: .utf8) else { return }
        do {
            try await socket.send(.string(text))
        } catch {
            disconnect(message: error.localizedDescription)
        }
    }

    private func receiveLoop() async {
        guard let socket else { return }
        do {
            while !Task.isCancelled {
                let message = try await socket.receive()
                guard case .string(let text) = message,
                      let data = text.data(using: .utf8),
                      let event = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                handle(event)
            }
        } catch {
            if !Task.isCancelled { disconnect(message: error.localizedDescription) }
        }
    }

    private func handle(_ event: [String: Any]) {
        let type = event["type"] as? String ?? ""
        switch type {
        case "harvest.ready":
            statusText = "已经连接。直接开口，停顿后老师会回答。"
        case "input_audio_buffer.speech_started":
            outputNode.stop()
            teacherTranscript = ""
            statusText = "正在听。"
        case "input_audio_buffer.speech_stopped":
            statusText = "正在想。"
        case "conversation.item.input_audio_transcription.delta":
            userTranscript = (event["text"] as? String ?? "") + (event["stash"] as? String ?? "")
        case "conversation.item.input_audio_transcription.completed":
            userTranscript = event["transcript"] as? String ?? userTranscript
        case "response.audio_transcript.delta":
            teacherTranscript += event["delta"] as? String ?? ""
        case "response.audio_transcript.done":
            teacherTranscript = event["transcript"] as? String ?? teacherTranscript
        case "response.audio.delta":
            if let encoded = event["delta"] as? String, let audio = Data(base64Encoded: encoded) { play(audio) }
        case "response.done":
            statusText = "可以继续说。"
        case "error":
            disconnect(message: event["message"] as? String ?? "语音服务返回错误。")
        default:
            break
        }
    }

    private func play(_ data: Data) {
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 24_000,
            channels: 1,
            interleaved: false
        ) else { return }
        let frames = AVAudioFrameCount(data.count / MemoryLayout<Int16>.size)
        guard frames > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames),
              let destination = buffer.int16ChannelData?.pointee else { return }
        data.withUnsafeBytes { bytes in
            guard let source = bytes.baseAddress else { return }
            UnsafeMutableRawPointer(destination).copyMemory(from: source, byteCount: data.count)
        }
        buffer.frameLength = frames
        outputNode.scheduleBuffer(buffer)
        if !outputNode.isPlaying { outputNode.play() }
    }
}

enum VoiceTeacherError: LocalizedError {
    case audioFormat
    var errorDescription: String? { "无法准备实时语音需要的 16 kHz 音频格式。" }
}

struct VoiceTeacherView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @StateObject private var session = VoiceTeacherSession()
    @State private var serviceMessage = "正在检查语音老师。"
    @State private var isConfigured = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Text("开口说日语。")
                    .font(.system(size: 32, design: .serif))
                    .foregroundStyle(DesignTokens.ink)
                Text(isConfigured ? session.statusText : serviceMessage)
                    .foregroundStyle(DesignTokens.muted)
                Button(session.isConnected ? "结束通话" : "开始通话") {
                    guard let endpoint = configuration.endpoint else { return }
                    if session.isConnected { session.disconnect() } else { Task { await session.connect(baseURL: endpoint) } }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(!isConfigured)
                transcript("我说的", text: session.userTranscript)
                transcript("老师说的", text: session.teacherTranscript)
            }
            .padding(DesignTokens.pageInset)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("语音老师")
        .task { await loadStatus() }
        .onDisappear { session.disconnect() }
    }

    private func transcript(_ title: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.footnote.weight(.semibold)).foregroundStyle(DesignTokens.muted)
            Text(text.isEmpty ? "等待声音。" : text)
                .font(.system(size: DesignTokens.readingSize))
                .foregroundStyle(DesignTokens.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(18)
        .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(DesignTokens.separator))
    }

    @MainActor
    private func loadStatus() async {
        guard let endpoint = configuration.endpoint else { return }
        do {
            let status = try await APIClient(baseURL: endpoint).voiceTeacherStatus()
            isConfigured = status.configured
            serviceMessage = status.configured
                ? "\(status.model) 已配置。开始后直接开口说日语。"
                : "请先在 Mac 服务设置页配置百炼 Key 和语音 WebSocket 地址。"
        } catch {
            serviceMessage = error.localizedDescription
        }
    }
}
