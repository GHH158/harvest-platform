import SwiftUI

/// Designed empty / loading / error state: soft symbol circle, serif title, muted body.
/// Replaces system `ContentUnavailableView` and dead-centered loading stacks.
struct WarmEmptyState: View {
    let title: String
    let systemImage: String
    var message: String?
    var actionTitle: String?
    var action: (() -> Void)?

    init(title: String, systemImage: String, message: String? = nil, actionTitle: String? = nil, action: (() -> Void)? = nil) {
        self.title = title
        self.systemImage = systemImage
        self.message = message
        self.actionTitle = actionTitle
        self.action = action
    }

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: systemImage)
                .font(.system(size: 30))
                .foregroundStyle(DesignTokens.accent)
                .frame(width: 64, height: 64)
                .background(DesignTokens.accentWash, in: Circle())
            Text(title)
                .font(.system(.title3, design: .serif))
                .foregroundStyle(DesignTokens.ink)
                .multilineTextAlignment(.center)
            if let message {
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.muted)
                    .multilineTextAlignment(.center)
                    .lineSpacing(4)
            }
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(PrimaryButtonStyle())
                    .padding(.top, 6)
            }
        }
        .padding(DesignTokens.pageInset)
        .padding(.top, 48)
        .frame(maxWidth: .infinity)
    }
}

/// Warm status capsule. Maps material / job status strings to a restrained chip.
struct StatusChip: View {
    let status: String
    var showSpinner = false

    var body: some View {
        HStack(spacing: 6) {
            if showSpinner { ProgressView().controlSize(.mini).tint(foregroundColor) }
            Text(label)
                .font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(backgroundColor, in: Capsule())
        .foregroundStyle(foregroundColor)
    }

    private var label: String {
        switch status {
        case "ready": "已就绪"
        case "processing": "处理中"
        case "downloaded": "待转录"
        case "failed": "失败"
        case "running": "执行中"
        case "done": "完成"
        case "pending": "待处理"
        default: status
        }
    }

    private var foregroundColor: Color {
        switch status {
        case "ready", "failed": DesignTokens.accent
        default: DesignTokens.muted
        }
    }

    private var backgroundColor: Color {
        switch status {
        case "ready", "failed": DesignTokens.accentWash
        default: DesignTokens.surface
        }
    }
}

/// Warm card container used across screens.
struct CardView<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: DesignTokens.cardRadius))
            .overlay(RoundedRectangle(cornerRadius: DesignTokens.cardRadius).stroke(DesignTokens.separator))
            .shadow(color: DesignTokens.cardShadow, radius: 8, y: 2)
    }
}

/// Small section kicker: serif title + optional accent caption.
struct SectionHeader: View {
    let title: String
    var caption: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(.headline, design: .serif))
                .foregroundStyle(DesignTokens.ink)
            if let caption {
                Text(caption)
                    .font(.caption)
                    .foregroundStyle(DesignTokens.muted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(Color.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 15)
            .background(DesignTokens.accent.opacity(configuration.isPressed ? 0.82 : 1), in: RoundedRectangle(cornerRadius: 13))
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(DesignTokens.ink)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 15)
            .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13).stroke(DesignTokens.separator))
            .opacity(configuration.isPressed ? 0.72 : 1)
    }
}

/// Minimal wrapping flow layout used to render ruby (furigana) inline.
struct FlowLayout: Layout {
    var spacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: maxWidth, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

/// A single ruby unit: optional kana reading above the surface text. Non-ruby
/// units keep an empty reading slot so all surfaces align on one baseline.
struct RubyUnit: View {
    let text: String
    let reading: String?
    var fontSize: CGFloat = 17
    var textColor: Color = DesignTokens.ink
    var readingColor: Color = DesignTokens.accent

    private var readingHeight: CGFloat { max(9, fontSize * 0.42) * 1.25 }

    var body: some View {
        VStack(spacing: 0) {
            if let reading, !reading.isEmpty {
                Text(reading)
                    .font(.system(size: max(9, fontSize * 0.42)))
                    .foregroundStyle(readingColor)
                    .lineLimit(1)
            } else {
                Color.clear.frame(height: readingHeight)
            }
            Text(text)
                .font(.system(size: fontSize))
                .foregroundStyle(textColor)
                .lineLimit(1)
        }
    }
}

/// Renders Japanese text with furigana: kana reading above each kanji word,
/// wrapping naturally.
struct FuriganaText: View {
    let segments: [FuriganaSegment]
    var fontSize: CGFloat = 17
    var textColor: Color = DesignTokens.ink
    var readingColor: Color = DesignTokens.accent

    var body: some View {
        FlowLayout(spacing: 2) {
            ForEach(Array(segments.enumerated()), id: \.offset) { _, segment in
                RubyUnit(
                    text: segment.surface,
                    reading: segment.reading,
                    fontSize: fontSize,
                    textColor: textColor,
                    readingColor: readingColor
                )
            }
        }
    }
}
