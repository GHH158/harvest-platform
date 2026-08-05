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
                        MainTabView()
                    }
                }
            }
            .environmentObject(configuration)
            .environmentObject(offlineLibrary)
            .tint(DesignTokens.accent)
            .task { offlineLibrary.resumeIncompleteDownloads() }
        }
    }
}

struct MainTabView: View {
    var body: some View {
        TabView {
            NavigationStack { MaterialListView() }
                .tabItem { Label("素材", systemImage: "text.book.closed") }
            NavigationStack { ChatView() }
                .tabItem { Label("聊天", systemImage: "bubble.left.and.bubble.right") }
            NavigationStack { DownloadsView() }
                .tabItem { Label("下载", systemImage: "arrow.down.circle") }
            NavigationStack { SettingsView(isOnboarding: false) }
                .tabItem { Label("设置", systemImage: "gearshape") }
        }
        .tint(DesignTokens.accent)
    }
}
