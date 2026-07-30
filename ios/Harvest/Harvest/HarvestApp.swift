import SwiftUI

@main
struct HarvestApp: App {
    @StateObject private var configuration = AppConfiguration()

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
            .tint(DesignTokens.accent)
            .background(DesignTokens.canvas)
        }
    }
}
