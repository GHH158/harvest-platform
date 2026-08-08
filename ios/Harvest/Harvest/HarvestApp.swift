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
            // Do not compete with first paint / material list for bandwidth.
            .task {
                try? await Task.sleep(for: .seconds(1.5))
                guard !Task.isCancelled else { return }
                offlineLibrary.resumeIncompleteDownloads()
            }
        }
    }
}

private enum MainTab: Hashable {
    case materials
    case chat
    case downloads
    case vocabulary
    case settings
}

struct MainTabView: View {
    @State private var selectedTab: MainTab = .materials

    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack { MaterialListView() }
                .tabItem { Label("素材", systemImage: "text.book.closed") }
                .tag(MainTab.materials)
            NavigationStack { ChatView(isActive: selectedTab == .chat) }
                .tabItem { Label("聊天", systemImage: "bubble.left.and.bubble.right") }
                .tag(MainTab.chat)
            NavigationStack { DownloadsView() }
                .tabItem { Label("下载", systemImage: "arrow.down.circle") }
                .tag(MainTab.downloads)
            NavigationStack { AccumulationView(isActive: selectedTab == .vocabulary) }
                .tabItem { Label("积累", systemImage: "square.stack.3d.up") }
                .tag(MainTab.vocabulary)
            NavigationStack { SettingsView(isOnboarding: false) }
                .tabItem { Label("设置", systemImage: "gearshape") }
                .tag(MainTab.settings)
        }
        .tint(DesignTokens.accent)
    }
}
