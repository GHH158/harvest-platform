import AVFoundation
import Foundation

@MainActor
final class AudioPlayer: ObservableObject {
    @Published private(set) var isPlaying = false
    @Published private(set) var positionMs = 0
    @Published private(set) var durationMs = 0

    private var player: AVPlayer?
    private var timeObserver: Any?
    private var loadedURL: URL?

    func prepare(url: URL) async {
        if loadedURL == url { return }
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        let nextPlayer = AVPlayer(url: url)
        player = nextPlayer
        loadedURL = url
        positionMs = 0
        durationMs = 0
        timeObserver = nextPlayer.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.1, preferredTimescale: 600),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor in
                self?.positionMs = max(0, Int(time.seconds * 1_000))
                if let duration = self?.player?.currentItem?.duration.seconds, duration.isFinite {
                    self?.durationMs = Int(duration * 1_000)
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
            player.play()
            isPlaying = true
        }
    }

    func seek(to milliseconds: Int) {
        player?.seek(to: CMTime(value: CMTimeValue(milliseconds), timescale: 1_000))
        positionMs = milliseconds
    }

    func stop() {
        player?.pause()
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        self.timeObserver = nil
        player = nil
        loadedURL = nil
        isPlaying = false
    }
}
