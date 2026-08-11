import SwiftUI
import UIKit

enum DesignTokens {
    static let canvas = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.125, green: 0.118, blue: 0.102, alpha: 1)
            : UIColor(red: 0.980, green: 0.976, blue: 0.961, alpha: 1)
    })
    static let surface = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.165, green: 0.153, blue: 0.130, alpha: 1)
            : UIColor(red: 1.0, green: 0.996, blue: 0.980, alpha: 1)
    })
    static let ink = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.949, green: 0.929, blue: 0.875, alpha: 1)
            : UIColor(red: 0.239, green: 0.224, blue: 0.161, alpha: 1)
    })
    static let muted = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.710, green: 0.671, blue: 0.600, alpha: 1)
            : UIColor(red: 0.467, green: 0.443, blue: 0.380, alpha: 1)
    })
    static let accent = Color(red: 0.722, green: 0.396, blue: 0.259)
    static let accentWash = Color(red: 0.722, green: 0.396, blue: 0.259, opacity: 0.15)
    static let separator = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.290, green: 0.267, blue: 0.224, alpha: 1)
            : UIColor(red: 0.902, green: 0.878, blue: 0.831, alpha: 1)
    })

    static let cardShadow = Color.black.opacity(0.05)
    static let heroSize: CGFloat = 40

    static let pageInset: CGFloat = 24
    static let cardRadius: CGFloat = 18
    static let readingSize: CGFloat = 22
    static let readingLineSpacing: CGFloat = 12

    /// §1.5 allows a serif for titles to get a published feel, and after the home screen
    /// was rebuilt in serif (2026-08-10) the navigation bar's heavy sans-serif "Harvest"
    /// was the only thing left on screen that did not belong to that typography.
    /// Set once at launch because UIKit owns the bar's fonts, not SwiftUI.
    static func applyNavigationBarAppearance() {
        let inkColor = UIColor { traits in
            traits.userInterfaceStyle == .dark
                ? UIColor(red: 0.949, green: 0.929, blue: 0.875, alpha: 1)
                : UIColor(red: 0.239, green: 0.224, blue: 0.161, alpha: 1)
        }
        let titleAttributes: [NSAttributedString.Key: Any] = [
            .font: serifFont(size: 17, weight: .semibold),
            .foregroundColor: inkColor,
        ]
        let largeTitleAttributes: [NSAttributedString.Key: Any] = [
            .font: serifFont(size: 34, weight: .semibold),
            .foregroundColor: inkColor,
        ]

        // §18.3: transparent only while the content sits at the top. That state is what
        // gives the screen its clean paper look with no rule under the title, and it was
        // the reason this whole thing was configured transparent — but it had been applied
        // to all three states, so anything scrolled *under* the bar showed straight
        // through it. Real symptom: in a chat, a user bubble slid up and overlapped the
        // title, with another bubble visible behind the status bar. Reading and watching
        // pages had it too. The bottom composer has always been opaque; this is the top
        // finally matching it.
        let atTop = UINavigationBarAppearance()
        atTop.configureWithTransparentBackground()
        atTop.titleTextAttributes = titleAttributes
        atTop.largeTitleTextAttributes = largeTitleAttributes

        // Scrolled: a blur rather than a flat fill, so the bar still reads as paper and
        // the text passing beneath it stays faintly sensed instead of being clipped by a
        // hard edge — but never legible enough to compete with the title.
        let scrolled = UINavigationBarAppearance()
        scrolled.configureWithOpaqueBackground()
        scrolled.backgroundColor = UIColor { traits in
            traits.userInterfaceStyle == .dark
                ? UIColor(red: 0.125, green: 0.118, blue: 0.102, alpha: 1)
                : UIColor(red: 0.980, green: 0.976, blue: 0.961, alpha: 1)
        }
        scrolled.shadowColor = .clear
        scrolled.titleTextAttributes = titleAttributes
        scrolled.largeTitleTextAttributes = largeTitleAttributes

        UINavigationBar.appearance().scrollEdgeAppearance = atTop
        UINavigationBar.appearance().standardAppearance = scrolled
        UINavigationBar.appearance().compactAppearance = scrolled
    }

    private static func serifFont(size: CGFloat, weight: UIFont.Weight) -> UIFont {
        let base = UIFont.systemFont(ofSize: size, weight: weight)
        guard let descriptor = base.fontDescriptor.withDesign(.serif) else { return base }
        return UIFont(descriptor: descriptor, size: size)
    }
}
