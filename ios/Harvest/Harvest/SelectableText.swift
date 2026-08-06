import SwiftUI
import UIKit

/// UITextView wrapper so Japanese text can be long-pressed, selected, and copied reliably.
/// SwiftUI `Text` + `.textSelection` is easily blocked by parent tap gestures / custom layouts.
struct SelectableText: UIViewRepresentable {
    let text: String
    var font: UIFont = .preferredFont(forTextStyle: .body)
    var textColor: UIColor = .label
    var lineSpacing: CGFloat = 4
    /// Pre-styled content (inline Markdown, ruby, …). When set it wins over `text`,
    /// which then only serves as the plain-text fallback.
    var attributed: NSAttributedString?
    /// Single-tap-a-word shortcut for dictionary lookup, bypassing select→copy→查词.
    /// Nil (default) leaves the view as a plain selectable/copyable text view.
    var onWordTap: ((String) -> Void)?

    /// Text the word tokenizer sees — for styled content the markers are already
    /// stripped, so tapped offsets must be resolved against the rendered string.
    private var lookupText: String { attributed?.string ?? text }

    func makeUIView(context: Context) -> IntrinsicTextView {
        let view = IntrinsicTextView()
        view.backgroundColor = .clear
        view.isEditable = false
        view.isSelectable = true
        view.isScrollEnabled = false
        view.bounces = false
        view.showsVerticalScrollIndicator = false
        view.showsHorizontalScrollIndicator = false
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.dataDetectorTypes = []
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)
        view.setContentHuggingPriority(.required, for: .vertical)
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.handleTap(_:)))
        tap.delegate = context.coordinator
        view.addGestureRecognizer(tap)
        apply(text, to: view)
        return view
    }

    func updateUIView(_ uiView: IntrinsicTextView, context: Context) {
        context.coordinator.text = lookupText
        context.coordinator.onWordTap = onWordTap
        let needsUpdate: Bool
        if let attributed {
            needsUpdate = uiView.attributedText != attributed
        } else {
            needsUpdate = uiView.text != text || uiView.font != font || uiView.textColor != textColor
        }
        if needsUpdate {
            apply(text, to: uiView)
            uiView.invalidateIntrinsicContentSize()
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(text: lookupText, onWordTap: onWordTap)
    }

    /// Bridges the tap gesture to Natural Language word-boundary lookup.
    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        var text: String
        var onWordTap: ((String) -> Void)?

        init(text: String, onWordTap: ((String) -> Void)?) {
            self.text = text
            self.onWordTap = onWordTap
        }

        func gestureRecognizer(
            _ gestureRecognizer: UIGestureRecognizer,
            shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
        ) -> Bool {
            true
        }

        @objc func handleTap(_ gesture: UITapGestureRecognizer) {
            guard let textView = gesture.view as? UITextView, let onWordTap else { return }
            let storage = textView.textStorage
            guard storage.length > 0 else { return }
            let layoutManager = textView.layoutManager
            let textContainer = textView.textContainer
            let point = gesture.location(in: textView)

            let glyphIndex = layoutManager.glyphIndex(for: point, in: textContainer)
            guard glyphIndex < layoutManager.numberOfGlyphs else { return }
            let glyphRect = layoutManager.boundingRect(forGlyphRange: NSRange(location: glyphIndex, length: 1), in: textContainer)
            guard glyphRect.contains(point) else { return }

            let charIndex = layoutManager.characterIndexForGlyph(at: glyphIndex)
            guard let range = japaneseWordRange(at: charIndex, in: text) else { return }
            let word = String(text[range])
            let nsRange = NSRange(range, in: text)
            flashHighlight(in: textView, range: nsRange)
            onWordTap(word)
        }

        private func flashHighlight(in textView: UITextView, range: NSRange) {
            let storage = textView.textStorage
            guard range.location + range.length <= storage.length else { return }
            storage.addAttribute(.backgroundColor, value: UIColor.systemYellow.withAlphaComponent(0.35), range: range)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                guard range.location + range.length <= storage.length else { return }
                storage.removeAttribute(.backgroundColor, range: range)
            }
        }
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        uiView: IntrinsicTextView,
        context: Context
    ) -> CGSize? {
        let width = proposal.width ?? UIScreen.main.bounds.width - 48
        guard width.isFinite, width > 0 else { return nil }
        let fitting = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: width, height: max(ceil(fitting.height), font.lineHeight))
    }

    private func apply(_ text: String, to view: UITextView) {
        if let attributed {
            view.attributedText = attributed
            return
        }
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = lineSpacing
        view.attributedText = NSAttributedString(
            string: text,
            attributes: [
                .font: font,
                .foregroundColor: textColor,
                .paragraphStyle: paragraph,
            ]
        )
    }
}

/// Reports intrinsic height so SwiftUI bubbles size to content without nested scrolling.
final class IntrinsicTextView: UITextView {
    override var intrinsicContentSize: CGSize {
        let width = bounds.width > 0 ? bounds.width : UIScreen.main.bounds.width - 80
        let size = sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: UIView.noIntrinsicMetric, height: ceil(size.height))
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        invalidateIntrinsicContentSize()
    }
}
