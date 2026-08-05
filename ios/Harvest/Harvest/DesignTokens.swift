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
}
