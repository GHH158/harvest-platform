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
                self?.positionMs = max(0, Int(time.seconds * 1_000))
                if let duration = self?.player?.currentItem?.duration.seconds, duration.isFinite {
                    self?.durationMs = Int(duration * 1_000)
                    if duration > 0 && time.seconds >= duration {
                        self?.isPlaying = false
                    }
                }
            }
        }
    }

    func toggle() {
        guard let player else { return }
        if isPlaying {
            player.pause()
            isPlaying = false
        } else {
            player.rate = rate
            isPlaying = true
        }
    }

    func setRate(_ newRate: Float) {
        rate = newRate
        if isPlaying { player?.rate = newRate }
    }

    func seek(to milliseconds: Int) {
        player?.seek(to: CMTime(value: CMTimeValue(milliseconds), timescale: 1_000))
        positionMs = milliseconds
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
