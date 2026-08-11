import AVKit
import SwiftUI

/// §15: pick a long video on the phone, watch it, and cut it into sections.
///
/// The whole point is that you never wait: the file is played from the phone itself, so
/// scrubbing is instant and costs no traffic (§3.3 measured that streaming the Mac's copy
/// over Tailscale does not work on cellular), and the upload runs in the background while
/// you cut. A one-hour video takes minutes to upload — those are the minutes you spend
/// marking points.
struct VideoSplitView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @Environment(\.dismiss) private var dismiss

    @State private var source: SplitSource?
    @State private var player: AVPlayer?
    @State private var duration: Double = 0
    @State private var position: Double = 0
    @State private var isPlaying = false
    /// Interior cut points in milliseconds, kept sorted. Neither 0 nor the end is in here.
    @State private var cuts: [Int] = []
    @State private var title = ""
    @State private var upload: UploadState = .idle
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var isChoosingFile = false
    @State private var isConfirmingSave = false
    @State private var timeObserver: Any?
    @State private var statusObserver: NSKeyValueObservation?
    /// §15.10: HLS needs an HTTP origin, so a bundle is served from loopback while this
    /// screen is open. Held here so releasing the state also closes the socket.
    @State private var server: LocalMediaServer?
    @Environment(\.scenePhase) private var scenePhase

    enum UploadState: Equatable {
        case idle
        case preparing
        case uploadingDirect(Double)
        /// §15.11: chosen instead of `uploadingDirect` when a quick probe finds the
        /// direct-to-Mac path too slow (measured, not guessed from Wi-Fi vs. cellular).
        case uploadingViaOSS(Double)
        /// The phone is done sending bytes; the Mac is now pulling the object back from
        /// OSS and unpacking it. No fraction to show — only that it is still happening.
        case processingOnMac
        case ready(String)
        case failed(String)

        var handle: String? { if case let .ready(id) = self { id } else { nil } }
        var fraction: Double? {
            switch self {
            case let .uploadingDirect(value), let .uploadingViaOSS(value): value
            default: nil
            }
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            uploadStrip
            if source == nil {
                picker
            } else {
                splitter
            }
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("拆分长视频")
        .navigationBarTitleDisplayMode(.inline)
        // §15.10: a downloaded video is often a playlist plus hundreds of segments, so a
        // folder has to be selectable — restricting this to `.movie` is what made those
        // downloads impossible to import.
        .fileImporter(
            isPresented: $isChoosingFile,
            allowedContentTypes: [.movie, .folder],
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case let .success(urls): adopt(urls.first)
            case let .failure(error): errorMessage = error.localizedDescription
            }
        }
        .confirmationDialog(
            "存成合集之后，原片会被删除",
            isPresented: $isConfirmingSave,
            titleVisibility: .visible
        ) {
            Button("存成合集 · \(cuts.count + 1) 节") { Task { await save() } }
            Button("再改改", role: .cancel) {}
        } message: {
            Text("切错了就得从手机重新传一遍。要留原片的话现在取消。")
        }
        .onDisappear { teardown() }
        // iOS suspends the process in the background and the listener stops accepting, so
        // coming back would otherwise show a frame that silently never plays again — the same
        // class of quiet failure that cost an hour to find in the first place.
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active, let source, case .hlsBundle = source.kind else { return }
            guard server?.isRunning != true else { return }
            let resumeAt = position
            Task { await attachPlayback(for: source, resumingAt: resumeAt) }
        }
    }

    // MARK: - Upload strip

    /// A hairline at the top, never a modal: the upload must not block the cutting (§15.8).
    @ViewBuilder private var uploadStrip: some View {
        switch upload {
        case .idle:
            EmptyView()
        case .preparing:
            stripLabel("正在打包…", fraction: nil)
        case let .uploadingDirect(fraction):
            stripLabel("正在传给 Mac \(Int(fraction * 100))%", fraction: fraction)
        case let .uploadingViaOSS(fraction):
            // §15.11: honest about the detour — "传给 Mac" would be wrong here, and
            // silently keeping the old label would hide why this run is slower to start.
            stripLabel("网络不够快，改走云端 \(Int(fraction * 100))%", fraction: fraction)
        case .processingOnMac:
            stripLabel("已传到云端，Mac 正在取回…", fraction: nil)
        case .ready:
            stripLabel("已传完，可以存了", fraction: 1)
        case let .failed(message):
            HStack(spacing: 8) {
                Text("上传失败：\(message)")
                    .font(.caption)
                    .foregroundStyle(DesignTokens.accent)
                Button("重试") { Task { await beginUpload() } }
                    .font(.caption.weight(.medium))
                    .buttonStyle(.plain)
                    .foregroundStyle(DesignTokens.accent)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 6)
        }
    }

    private func stripLabel(_ text: String, fraction: Double?) -> some View {
        VStack(spacing: 4) {
            HStack {
                Text(text)
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
                Spacer(minLength: 0)
            }
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Rectangle().fill(DesignTokens.separator).frame(height: 2)
                    Rectangle()
                        .fill(DesignTokens.accent)
                        .frame(width: geometry.size.width * (fraction ?? 0.08), height: 2)
                        .animation(.easeOut(duration: 0.25), value: fraction)
                }
            }
            .frame(height: 2)
        }
        .padding(.horizontal, 20)
        .padding(.top, 6)
    }

    // MARK: - Picker

    private var picker: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("挑一个长视频")
                .font(.system(size: 22, design: .serif))
                .foregroundStyle(DesignTokens.ink)
            Text("一个视频文件，或者从网页下载下来的那种文件夹（里面是一个播放列表加很多分片）。")
                .font(.subheadline)
                .foregroundStyle(DesignTokens.muted)
                .lineSpacing(5)
            Button("选文件或文件夹") { isChoosingFile = true }
                .buttonStyle(PrimaryButtonStyle())
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
    }

    // MARK: - Splitter

    private var splitter: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if let player {
                    VideoPlayer(player: player)
                        .aspectRatio(16 / 9, contentMode: .fit)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.accent)
                        .fixedSize(horizontal: false, vertical: true)
                }
                transport
                timeline
                cutButton
                sectionList
                TextField("给这个合集起个名字", text: $title)
                    .font(.system(size: 17, design: .serif))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 14))
                    .overlay {
                        RoundedRectangle(cornerRadius: 14).stroke(DesignTokens.separator, lineWidth: 0.5)
                    }
                saveButton
            }
            .padding(20)
        }
    }

    private var transport: some View {
        HStack(spacing: 0) {
            Text(clock(position))
                .font(.system(size: 15, design: .monospaced))
                .foregroundStyle(DesignTokens.ink)
            Spacer(minLength: 8)
            transportButton("gobackward", label: "后退 0.5 秒") { nudge(-0.5) }
            transportButton("chevron.left.2", label: "上一帧") { step(-1) }
            Button {
                togglePlayback()
            } label: {
                Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                    .font(.title3)
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .background(DesignTokens.accent, in: Circle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 6)
            transportButton("chevron.right.2", label: "下一帧") { step(1) }
            transportButton("goforward", label: "前进 0.5 秒") { nudge(0.5) }
            Spacer(minLength: 8)
            Text(clock(duration))
                .font(.system(size: 15, design: .monospaced))
                .foregroundStyle(DesignTokens.muted)
        }
    }

    private func transportButton(_ symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.subheadline)
                .foregroundStyle(DesignTokens.ink)
                .frame(width: 34, height: 34)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    /// The cut points as upright lines on a bar. Tap the bar to seek, drag a line to move
    /// it — precision is entirely the learner's here (§15.8), so it has to be adjustable.
    private var timeline: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            ZStack(alignment: .leading) {
                Capsule().fill(DesignTokens.separator).frame(height: 6)
                Capsule()
                    .fill(DesignTokens.accent.opacity(0.35))
                    .frame(width: width * progressFraction, height: 6)
                ForEach(cuts, id: \.self) { cut in
                    Rectangle()
                        .fill(DesignTokens.accent)
                        .frame(width: 2, height: 26)
                        .offset(x: width * fraction(ofMilliseconds: cut) - 1)
                        .gesture(
                            DragGesture()
                                .onChanged { value in move(cut: cut, to: value.location.x, width: width) }
                        )
                }
                Rectangle()
                    .fill(DesignTokens.ink)
                    .frame(width: 1.5, height: 20)
                    .offset(x: width * progressFraction - 0.75)
            }
            .frame(height: 30)
            .contentShape(Rectangle())
            // One gesture for tapping and for dragging (`minimumDistance: 0`), for two
            // reasons. Tapping alone made dragging feel dead, and dragging is the gesture you
            // reach for when you want to land on an exact moment. And a drag that starts near
            // the left edge — which is where the playhead sits at 0:00 — was being taken by
            // the system's back swipe: the screen popped and every cut went with it. Claiming
            // the touch here keeps that from happening.
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in seek(to: duration * Double(value.location.x / max(1, width))) }
            )
        }
        .frame(height: 30)
    }

    private var cutButton: some View {
        Button {
            addCut()
        } label: {
            Label("在这里切一刀", systemImage: "scissors")
                .font(.subheadline.weight(.medium))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(DesignTokens.accentWash, in: RoundedRectangle(cornerRadius: 14))
                .overlay {
                    RoundedRectangle(cornerRadius: 14).stroke(DesignTokens.accent.opacity(0.4), lineWidth: 0.5)
                }
        }
        .buttonStyle(.plain)
        .disabled(!canCutHere)
        .opacity(canCutHere ? 1 : 0.4)
    }

    private var sectionList: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("\(cuts.count + 1) 节")
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
                Spacer()
                if !cuts.isEmpty {
                    Button("全部去掉") { withAnimation { cuts = [] } }
                        .font(.footnote)
                        .foregroundStyle(DesignTokens.accent)
                        .buttonStyle(.plain)
                }
            }
            .padding(.bottom, 6)
            ForEach(Array(sections.enumerated()), id: \.offset) { index, range in
                HStack(spacing: 10) {
                    Text("第 \(index + 1) 节")
                        .font(.system(size: 16, design: .serif))
                        .foregroundStyle(DesignTokens.ink)
                    Spacer(minLength: 8)
                    Text("\(clock(Double(range.lowerBound) / 1000)) – \(clock(Double(range.upperBound) / 1000))")
                        .font(.system(size: 13, design: .monospaced))
                        .foregroundStyle(DesignTokens.muted)
                    // §15.8: "merge into the previous section" describes the result. "delete
                    // this cut point" makes you do the arithmetic yourself.
                    Button {
                        withAnimation { mergeIntoPrevious(index: index) }
                    } label: {
                        Image(systemName: "arrow.up")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(index == 0 ? .clear : DesignTokens.muted)
                            .frame(width: 26, height: 26)
                    }
                    .buttonStyle(.plain)
                    .disabled(index == 0)
                    .accessibilityLabel("并到上一节")
                }
                .padding(.vertical, 9)
                .overlay(alignment: .bottom) {
                    if index < sections.count - 1 {
                        Rectangle().fill(DesignTokens.separator).frame(height: 0.5)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture { seek(to: Double(range.lowerBound) / 1000) }
            }
        }
    }

    private var saveButton: some View {
        Button {
            isConfirmingSave = true
        } label: {
            Text(isSaving ? "正在建合集…" : "存成合集")
        }
        .buttonStyle(PrimaryButtonStyle())
        .disabled(upload.handle == nil || isSaving)
        .opacity(upload.handle == nil || isSaving ? 0.5 : 1)
    }

    // MARK: - Derived

    private var sections: [Range<Int>] {
        let total = max(1, Int(duration * 1000))
        var result: [Range<Int>] = []
        var previous = 0
        for cut in cuts {
            result.append(previous..<cut)
            previous = cut
        }
        result.append(previous..<total)
        return result
    }

    private var progressFraction: Double {
        duration > 0 ? min(1, max(0, position / duration)) : 0
    }

    private func fraction(ofMilliseconds value: Int) -> Double {
        duration > 0 ? min(1, max(0, Double(value) / 1000 / duration)) : 0
    }

    /// Two cuts closer than a second would produce a section nobody wants, and a cut at the
    /// very start or end produces an empty one.
    private var canCutHere: Bool {
        let candidate = Int(position * 1000)
        guard candidate > 1_000, Double(candidate) < duration * 1000 - 1_000 else { return false }
        return !cuts.contains { abs($0 - candidate) < 1_000 }
    }

    // MARK: - Actions

    private func adopt(_ url: URL?) {
        guard let url else { return }
        do {
            let resolved = try SplitSource.resolve(url)
            source = resolved
            title = resolved.suggestedTitle
            errorMessage = nil
            Task {
                await attachPlayback(for: resolved, resumingAt: 0)
                await beginUpload()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// A single file plays straight from disk; a bundle goes through loopback HTTP because
    /// `AVPlayer` will not open an HLS playlist over `file://` (§15.10). The plain path is
    /// deliberately left alone — giving the working case a new dependency buys nothing.
    @MainActor private func attachPlayback(for resolved: SplitSource, resumingAt seconds: Double) async {
        switch resolved.kind {
        case .movie:
            attachPlayer(to: resolved.playbackURL, resumingAt: seconds)
        case let .hlsBundle(playlist):
            do {
                let running = server ?? LocalMediaServer()
                server = running
                let base = try await running.start(serving: playlist.deletingLastPathComponent())
                attachPlayer(to: base.appendingPathComponent(playlist.lastPathComponent), resumingAt: seconds)
            } catch {
                errorMessage = "本机播放服务起不来：\(error.localizedDescription)"
            }
        }
    }

    private func attachPlayer(to url: URL, resumingAt seconds: Double = 0) {
        let item = AVPlayerItem(url: url)
        let created = AVPlayer(playerItem: item)
        player = created
        // Without this the failure mode was a black rectangle and no explanation — the
        // learner could not tell a broken bundle from a slow one.
        statusObserver = item.observe(\.status, options: [.new]) { observed, _ in
            guard observed.status == .failed else { return }
            let reason = observed.error?.localizedDescription ?? "这个视频播不出来。"
            Task { @MainActor in
                errorMessage = "播不出来：\(reason)"
            }
        }
        timeObserver = created.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.05, preferredTimescale: 600),
            queue: .main
        ) { time in
            position = time.seconds
            if let total = created.currentItem?.duration.seconds, total.isFinite, total > 0 {
                duration = total
            }
        }
        if seconds > 0 {
            created.seek(to: CMTime(seconds: seconds, preferredTimescale: 600))
            position = seconds
        }
        Task {
            // Duration for an HLS playlist is not available synchronously.
            do {
                let total = try await item.asset.load(.duration).seconds
                if total.isFinite, total > 0 {
                    await MainActor.run { duration = total }
                    return
                }
                await MainActor.run {
                    errorMessage = "读不到这个视频的时长，没法按时间切。"
                }
            } catch {
                await MainActor.run {
                    errorMessage = "播不出来：\(error.localizedDescription)"
                }
            }
        }
    }

    private func togglePlayback() {
        guard let player else { return }
        if isPlaying { player.pause() } else { player.play() }
        isPlaying.toggle()
    }

    private func nudge(_ seconds: Double) {
        seek(to: position + seconds)
    }

    private func step(_ frames: Int) {
        player?.pause()
        isPlaying = false
        player?.currentItem?.step(byCount: frames)
    }

    private func seek(to seconds: Double) {
        let clamped = min(max(0, seconds), duration)
        player?.seek(
            to: CMTime(seconds: clamped, preferredTimescale: 600),
            toleranceBefore: .zero,
            toleranceAfter: .zero
        )
        position = clamped
    }

    private func addCut() {
        let candidate = Int(position * 1000)
        guard canCutHere else { return }
        withAnimation(.easeOut(duration: 0.18)) {
            cuts = (cuts + [candidate]).sorted()
        }
    }

    private func mergeIntoPrevious(index: Int) {
        guard index > 0, index - 1 < cuts.count else { return }
        cuts.remove(at: index - 1)
    }

    private func move(cut: Int, to x: CGFloat, width: CGFloat) {
        guard duration > 0, let existing = cuts.firstIndex(of: cut) else { return }
        let target = Int(min(max(0, Double(x / max(1, width))), 1) * duration * 1000)
        var updated = cuts
        updated[existing] = target
        updated = Array(Set(updated)).sorted()
        // Dragging one line past another would silently reorder the sections.
        guard zip(updated, updated.dropFirst()).allSatisfy({ $1 - $0 >= 1_000 }) else { return }
        guard target > 1_000, Double(target) < duration * 1000 - 1_000 else { return }
        cuts = updated
    }

    @MainActor private func beginUpload() async {
        guard let source, let endpoint = configuration.endpoint else { return }
        upload = .preparing
        do {
            let uploadURL = try await source.uploadableCopy()
            let client = APIClient(baseURL: endpoint)
            let handle: VideoUploadHandle
            // §15.11: measured, not guessed — a phone can be on Wi-Fi far from the Mac and
            // still be the slow case, or on cellular with a good direct connection.
            if await client.probeUploadSpeedIsAdequate() {
                upload = .uploadingDirect(0)
                handle = try await client.uploadVideoForSplit(uploadURL) { fraction in
                    Task { @MainActor in upload = .uploadingDirect(fraction) }
                }
            } else {
                handle = try await uploadViaOSS(client: client, fileURL: uploadURL)
            }
            if uploadURL != source.playbackURL {
                try? FileManager.default.removeItem(at: uploadURL)
            }
            upload = .ready(handle.uploadID)
        } catch {
            upload = .failed(error.localizedDescription)
        }
    }

    /// The detour when the direct path measured too slow: `PUT` straight to OSS, tell the
    /// Mac what to go fetch, then wait for it to come back with the same `upload_id` shape
    /// the direct path would have produced (§15.11).
    @MainActor private func uploadViaOSS(client: APIClient, fileURL: URL) async throws -> VideoUploadHandle {
        let filename = fileURL.lastPathComponent.isEmpty ? "video.mp4" : fileURL.lastPathComponent
        let ticket = try await client.requestOSSUploadURL(filename: filename)
        upload = .uploadingViaOSS(0)
        try await client.putFileToOSS(fileURL, to: ticket.uploadURL) { fraction in
            Task { @MainActor in upload = .uploadingViaOSS(fraction) }
        }
        let jobID = try await client.notifyOSSUpload(ossKey: ticket.ossKey, filename: filename)
        upload = .processingOnMac
        return try await pollFetchJob(client: client, jobID: jobID, fallbackFilename: filename)
    }

    /// The Mac's downlink is usually far better than the phone's uplink through Tailscale
    /// was, but it is still a real download-then-unpack step, not instant — polled rather
    /// than pushed because nothing here needs to be faster than "check back in a couple
    /// seconds" (§15.11).
    private func pollFetchJob(
        client: APIClient,
        jobID: Int,
        fallbackFilename: String
    ) async throws -> VideoUploadHandle {
        // 900 × 2s = 30 minutes — generous for an hour-long bundle on a home downlink,
        // which is the side doing the work once OSS already has the bytes.
        for _ in 0..<900 {
            let status = try await client.fetchUploadJobStatus(id: jobID)
            switch status.status {
            case "done":
                guard let uploadID = status.payload?.uploadID else {
                    throw APIClientError.server("Mac 处理完了，但没有给出上传编号。")
                }
                return VideoUploadHandle(uploadID: uploadID, filename: status.payload?.filename ?? fallbackFilename)
            case "failed":
                throw APIClientError.server(status.errorMessage ?? "Mac 取回上传失败。")
            default:
                try await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
        throw APIClientError.server("Mac 处理超时，请稍后在素材库确认是否已到。")
    }

    @MainActor private func save() async {
        guard let uploadID = upload.handle, let endpoint = configuration.endpoint else { return }
        isSaving = true
        errorMessage = nil
        do {
            _ = try await APIClient(baseURL: endpoint).createCollection(
                uploadID: uploadID,
                title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                cuts: cuts,
                sourceName: source?.rootURL.lastPathComponent
            )
            teardown()
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
        isSaving = false
    }

    private func teardown() {
        if let timeObserver, let player {
            player.removeTimeObserver(timeObserver)
        }
        timeObserver = nil
        statusObserver?.invalidate()
        statusObserver = nil
        // Explicit stop, and dropping the reference runs `deinit` as a second line of
        // defence in case SwiftUI never delivers `onDisappear`. Either way the socket cannot
        // outlive the process (§15.10).
        server?.stop()
        server = nil
        player?.pause()
        player = nil
        source?.releaseAccess()
    }

    private func clock(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0 else { return "0:00" }
        let total = Int(seconds.rounded())
        let hours = total / 3_600
        let minutes = (total % 3_600) / 60
        let remainder = total % 60
        if hours > 0 { return String(format: "%d:%02d:%02d", hours, minutes, remainder) }
        return String(format: "%d:%02d", minutes, remainder)
    }
}
