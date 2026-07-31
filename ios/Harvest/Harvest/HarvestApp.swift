import SwiftUI

@main
struct HarvestApp: App {
    @StateObject private var configuration = AppConfiguration()
    @StateObject private var offlineLibrary = OfflineLibrary()

    var body: some Scene {
        WindowGroup {
            Group {
                if configuration.endpoint == nil {
                    SettingsView()
                } else {
                    MaterialListView()
                }
            }
            .environmentObject(configuration)
            .environmentObject(offlineLibrary)
            .tint(DesignTokens.accent)
            .background(DesignTokens.canvas)
            .task { offlineLibrary.resumeIncompleteDownloads() }
        }
    }
}
