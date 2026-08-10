import AVFoundation
import Foundation

@MainActor
final class AudioPlayer: ObservableObject {
    @Published private(set) var isPlaying = false
    @Published private(set) var positionMs = 0
    @Published private(set) var durationMs = 0
    @Published private(set) var errorMessage: String?
    @Published private(set) var rate: Float = 1.0

    private var player: AVPlayer?
    private var timeObserver: Any?
    private var itemObserver: NSKeyValueObservation?
    private var endObserver: NSObjectProtocol?
    private var loadedURL: URL?
    /// A seek requested before the item could serve it (resuming right after `prepare`).
    /// Until it lands, the periodic observer must not report the item's 0 position —
    /// that would look like the listener rewound and overwrite the saved resume point.
    private var pendingSeekMs: Int?

    func prepare(url: URL) async {
        if loadedURL == url { return }
        AudioSessionSupport.activatePlayback()
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        itemObserver?.invalidate()
        itemObserver = nil
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = nil

        let item = AVPlayerItem(url: url)
        let nextPlayer = AVPlayer(playerItem: item)
        player = nextPlayer
        loadedURL = url
        positionMs = 0
        durationMs = 0
        errorMessage = nil

        itemObserver = item.observe(\.status) { [weak self] observedItem, _ in
            let isFailed = observedItem.status == .failed
            let isReady = observedItem.status == .readyToPlay
            let message = observedItem.error?.localizedDescription
            Task { @MainActor in
                guard let self else { return }
                if isFailed {
                    self.errorMessage = message ?? "朗读播放失败"
                } else if isReady, self.loadedURL == url {
                    self.errorMessage = nil
                    self.applyPendingSeek()
                }
            }
        }
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemFailedToPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] notification in
            let message = (notification.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey] as? Error)?.localizedDescription ?? "播放中断"
            Task { @MainActor in self?.errorMessage = message }
        }
        timeObserver = nextPlayer.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.1, preferredTimescale: 600),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor in
                guard let self else { return }
                // Hold the resume target until the seek lands, otherwise the item's
                // pre-seek 0 would be mistaken for real playback progress. Retrying here
                // rather than only on the status change keeps this independent of KVO
                // timing — the observer can miss a transition that already happened.
                if self.pendingSeekMs == nil {
                    self.positionMs = max(0, Int(time.seconds * 1_000))
                } else {
                    self.applyPendingSeek()
                }
                if let duration = self.player?.currentItem?.duration.seconds, duration.isFinite {
                    self.durationMs = Int(duration * 1_000)
                    if duration > 0 && time.seconds >= duration {
                        self.isPlaying = false
                    }
                }
            }
        }
    }

    /// Pause without tearing the player down, so the position survives — `stop()`
    /// releases the item and the resume point with it.
    func pause() {
        guard let player, isPlaying else { return }
        player.pause()
        isPlaying = false
    }

    func toggle() {
        guard let player else { return }
        if isPlaying {
            player.pause()
            isPlaying = false
        } else {
            // Last chance to honour a resume point the item was not ready to accept.
            applyPendingSeek()
            player.rate = rate
            isPlaying = true
        }
    }

    func setRate(_ newRate: Float) {
        rate = newRate
        if isPlaying { player?.rate = newRate }
    }

    func seek(to milliseconds: Int) {
        let target = max(0, milliseconds)
        positionMs = target
        pendingSeekMs = target
        applyPendingSeek()
    }

    /// Applies the outstanding seek, and only forgets it once AVFoundation reports the
    /// seek actually finished. Clearing it on request instead let a seek issued before
    /// the item was ready get dropped: the display stayed at the resume point while the
    /// player sat at 0, so pressing play restarted from the first sentence.
    private func applyPendingSeek() {
        guard let target = pendingSeekMs,
              let player,
              player.currentItem?.status == .readyToPlay else { return }
        player.seek(
            to: CMTime(value: CMTimeValue(target), timescale: 1_000),
            toleranceBefore: .zero,
            toleranceAfter: .zero
        ) { [weak self] finished in
            guard finished else { return }
            Task { @MainActor in
                guard let self, self.pendingSeekMs == target else { return }
                self.pendingSeekMs = nil
            }
        }
    }

    func stop() {
        player?.pause()
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        timeObserver = nil
        itemObserver?.invalidate()
        itemObserver = nil
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = nil
        player = nil
        loadedURL = nil
        isPlaying = false
        errorMessage = nil
    }
}

/// Shared audio-session activation for plain `.playback` (reading audio, video audio,
/// offline queues). Shadowing / voice teacher configure their own `.playAndRecord` and
/// must NOT call this so the recorder keeps priority.
enum AudioSessionSupport {
    static func activatePlayback() {
        try? AVAudioSession.sharedInstance().setCategory(.playback)
        try? AVAudioSession.sharedInstance().setActive(true)
    }
}
