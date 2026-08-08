import AVFoundation
import Foundation

/// Downloads an HLS stream for offline playback using AVFoundation's own mechanism.
///
/// The previous approach fetched the playlist and stored each `.ts` segment as a plain
/// file, then fed those files to an `AVQueuePlayer` one by one. The download worked, but
/// playback never could: AVFoundation only accepts MPEG-TS inside an HLS stream, so a
/// standalone `.ts` opened as an asset fails with "Cannot Open". Offline video therefore
/// never played, on any build.
///
/// `AVAssetDownloadURLSession` is the supported path. It writes a `.movpkg` bundle that
/// `AVURLAsset` can open directly, and handles playlists, variants and keys itself.
///
/// Two constraints come with it and are worth knowing before changing this file:
/// - the session must use a background configuration, so it is delegate-driven rather
///   than `async` at the URLSession level;
/// - **asset downloading does not work on the iOS Simulator**; this code can only be
///   exercised for real on a device.
@MainActor
final class HLSAssetDownloader: NSObject {
    struct Progress {
        let fraction: Double
    }

    private var session: AVAssetDownloadURLSession!
    private var continuations: [Int: CheckedContinuation<URL, Error>] = [:]
    private var progressHandlers: [Int: (Double) -> Void] = [:]
    private var destinations: [Int: URL] = [:]

    override init() {
        super.init()
        let configuration = URLSessionConfiguration.background(
            withIdentifier: "com.gaohuanhuan.harvest.assetdownload"
        )
        session = AVAssetDownloadURLSession(
            configuration: configuration,
            assetDownloadDelegate: self,
            delegateQueue: .main
        )
    }

    /// Downloads `remoteURL` and returns the on-disk location AVPlayer can open.
    /// `onProgress` receives 0…1 and is called on the main actor.
    func download(
        remoteURL: URL,
        title: String,
        onProgress: @escaping (Double) -> Void
    ) async throws -> URL {
        let asset = AVURLAsset(url: remoteURL)
        guard let task = session.makeAssetDownloadTask(
            asset: asset,
            assetTitle: title,
            assetArtworkData: nil,
            options: nil
        ) else {
            throw OfflineLibraryError.assetDownloadUnavailable
        }
        return try await withCheckedThrowingContinuation { continuation in
            continuations[task.taskIdentifier] = continuation
            progressHandlers[task.taskIdentifier] = onProgress
            task.resume()
        }
    }

    func cancelAll() {
        session.getAllTasks { tasks in
            for task in tasks { task.cancel() }
        }
    }
}

extension HLSAssetDownloader: AVAssetDownloadDelegate {
    nonisolated func urlSession(
        _ session: URLSession,
        assetDownloadTask: AVAssetDownloadTask,
        didFinishDownloadingTo location: URL
    ) {
        // `location` is only valid inside this callback; the caller copies it out.
        let identifier = assetDownloadTask.taskIdentifier
        MainActor.assumeIsolated {
            destinations[identifier] = location
        }
    }

    nonisolated func urlSession(
        _ session: URLSession,
        assetDownloadTask: AVAssetDownloadTask,
        didLoad timeRange: CMTimeRange,
        totalTimeRangesLoaded loadedTimeRanges: [NSValue],
        timeRangeExpectedToLoad: CMTimeRange
    ) {
        let expected = timeRangeExpectedToLoad.duration.seconds
        guard expected > 0 else { return }
        let loaded = loadedTimeRanges
            .map(\.timeRangeValue.duration.seconds)
            .reduce(0, +)
        let identifier = assetDownloadTask.taskIdentifier
        let fraction = min(1, max(0, loaded / expected))
        MainActor.assumeIsolated {
            progressHandlers[identifier]?(fraction)
        }
    }

    nonisolated func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        let identifier = task.taskIdentifier
        MainActor.assumeIsolated {
            guard let continuation = continuations.removeValue(forKey: identifier) else { return }
            progressHandlers[identifier] = nil
            let location = destinations.removeValue(forKey: identifier)
            if let error {
                continuation.resume(throwing: error)
            } else if let location {
                continuation.resume(returning: location)
            } else {
                continuation.resume(throwing: OfflineLibraryError.assetDownloadUnavailable)
            }
        }
    }
}
