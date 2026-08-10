import SwiftUI

@main
struct HarvestApp: App {
    @StateObject private var configuration = AppConfiguration()
    @StateObject private var offlineLibrary = OfflineLibrary()

    var body: some Scene {
        WindowGroup {
            ZStack {
                DesignTokens.canvas.ignoresSafeArea()

                Group {
                    if configuration.endpoint == nil {
                        SettingsView(isOnboarding: true)
                    } else {
                        NavigationStack { HomeView() }
                    }
                }
            }
            .environmentObject(configuration)
            .environmentObject(offlineLibrary)
            .tint(DesignTokens.accent)
            // Do not compete with first paint / material list for bandwidth.
            .task {
                try? await Task.sleep(for: .seconds(1.5))
                guard !Task.isCancelled else { return }
                offlineLibrary.resumeIncompleteDownloads()
            }
        }
    }
}

// The bottom tab bar is gone: the app opens on HomeView and everything is reached by
// pushing from there. `isActive` on ChatView / AccumulationView existed to pause work
// for tabs that were built but not on screen; with push navigation a view only exists
// while it is visible, so the parameter is left at its default.
