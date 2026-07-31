import AVKit
import SwiftUI

struct VideoLearningView: View {
    let material: MaterialDetail
    @State private var mode = "观看"

    var body: some View {
        VStack(spacing: 18) {
            Picker("模式", selection: $mode) { Text("观看").tag("观看"); Text("跟读").tag("跟读") }.pickerStyle(.segmented)
            if let videoURL = material.videoURL { VideoPlayer(player: AVPlayer(url: videoURL)).frame(height: 240) }
            else { ContentUnavailableView("视频仍在准备", systemImage: "film", description: Text("转码、字幕与 OSS 分发完成后会出现在这里。")) }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(material.segments) { segment in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(segment.textJA).font(.system(size: DesignTokens.readingSize)).foregroundStyle(DesignTokens.ink)
                            if let translation = segment.textZH {
                                Text(translation).font(.footnote).foregroundStyle(DesignTokens.muted)
                            }
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
        }.padding(DesignTokens.pageInset).background(DesignTokens.canvas.ignoresSafeArea()).navigationTitle(material.title)
    }
}
