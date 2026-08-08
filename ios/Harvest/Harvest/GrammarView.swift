import SwiftUI

/// The grammar skeleton (§12).
///
/// Deliberately not a course: no percentage, no streak, no "next lesson". What it shows
/// is which points you have already run into in your own Japanese and which you have
/// settled — the accumulation itself is the feedback, per §1.4.
struct GrammarView: View {
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var points: [GrammarPoint] = []
    @State private var errorMessage: String?
    @State private var isLoading = false
    @State private var showsUntouched = false
    var isActive: Bool = true

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    /// Points you have met, newest state first. This is the part that grows.
    private var met: [GrammarPoint] { points.filter { $0.status != nil } }
    private var understood: [GrammarPoint] { points.filter(\.isUnderstood) }
    private var encountered: [GrammarPoint] { points.filter(\.isEncountered) }
    private var untouched: [GrammarPoint] { points.filter { $0.status == nil } }

    var body: some View {
        Group {
            if isLoading && points.isEmpty {
                WarmEmptyState(title: "加载中", systemImage: "square.stack.3d.up")
            } else if points.isEmpty {
                WarmEmptyState(
                    title: "还没有语法骨架",
                    systemImage: "square.stack.3d.up",
                    message: "连接服务后会列出语法点；你在聊天里写错的地方会自动登记进来"
                )
            } else {
                list
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DesignTokens.canvas.ignoresSafeArea())
        .task(id: "\(configuration.endpoint?.absoluteString ?? "")-\(isActive)") {
            guard isActive else { return }
            await load()
        }
        .refreshable { await load() }
        .overlay(alignment: .bottom) {
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .padding(.horizontal, DesignTokens.pageInset)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity)
                    .background(DesignTokens.surface.opacity(0.96))
            }
        }
    }

    private var list: some View {
        List {
            if met.isEmpty {
                Section {
                    Text("你还没有撞见过任何语法点。在聊天里用日语写点什么，写错的地方会自动登记到这里。")
                        .font(.subheadline)
                        .foregroundStyle(DesignTokens.muted)
                        .lineSpacing(4)
                        .padding(.vertical, 6)
                        .listRowBackground(DesignTokens.canvas)
                }
            }
            if !understood.isEmpty {
                section("已弄懂", understood)
            }
            if !encountered.isEmpty {
                section("已撞见", encountered)
            }
            Section {
                DisclosureGroup(isExpanded: $showsUntouched) {
                    ForEach(untouched) { point in row(point) }
                } label: {
                    Text("还没接触 · \(untouched.count)")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(DesignTokens.muted)
                }
                .listRowBackground(DesignTokens.canvas)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }

    private func section(_ title: String, _ items: [GrammarPoint]) -> some View {
        Section {
            ForEach(items) { point in row(point) }
        } header: {
            Text("\(title) · \(items.count)")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DesignTokens.muted)
        }
    }

    private func row(_ point: GrammarPoint) -> some View {
        NavigationLink(value: point) {
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(point.titleJA)
                        .font(.system(.body, design: .serif))
                        .foregroundStyle(DesignTokens.ink)
                    if point.isUnderstood {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(Color.green)
                    }
                    Spacer()
                    Text(point.level)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(DesignTokens.muted)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(DesignTokens.surface, in: Capsule())
                }
                Text(point.titleZH)
                    .font(.subheadline)
                    .foregroundStyle(DesignTokens.muted)
                // The learner's own sentence is the whole point of the skeleton:
                // it says "you met this here", not "lesson 12".
                if let note = point.note, !note.isEmpty, point.cameFromMistake {
                    Text("你写过：\(note)")
                        .font(.caption)
                        .foregroundStyle(DesignTokens.accent)
                        .lineLimit(1)
                }
            }
            .padding(.vertical, 3)
        }
        .listRowBackground(DesignTokens.canvas)
    }

    @MainActor
    private func load() async {
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            return
        }
        isLoading = true
        errorMessage = nil
        do {
            points = try await client.listGrammar()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}

/// Explanation for one point, generated on demand by the teaching kernel (§12.3).
struct GrammarDetailView: View {
    let point: GrammarPoint
    @EnvironmentObject private var configuration: AppConfiguration
    @State private var loaded: GrammarPoint?
    @State private var errorMessage: String?
    @State private var isLoading = true
    @State private var isUpdating = false

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    private var current: GrammarPoint { loaded ?? point }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                if isLoading {
                    HStack(spacing: 10) {
                        ProgressView().controlSize(.small).tint(DesignTokens.accent)
                        Text("正在讲解…")
                            .font(.footnote)
                            .foregroundStyle(DesignTokens.muted)
                    }
                    .padding(.top, 8)
                } else if let errorMessage {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(errorMessage)
                            .font(.callout)
                            .foregroundStyle(DesignTokens.muted)
                        Button("重试") { Task { await load() } }
                            .foregroundStyle(DesignTokens.accent)
                    }
                } else if let explanation = current.explanation {
                    MarkdownMessageView(markdown: explanation, style: .teaching)
                }
                if !isLoading && errorMessage == nil { statusButton }
            }
            .padding(DesignTokens.pageInset)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle(point.titleJA)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(current.titleZH)
                .font(.system(.title3, design: .serif, weight: .semibold))
                .foregroundStyle(DesignTokens.ink)
            HStack(spacing: 8) {
                Text(current.level)
                Text(current.category)
            }
            .font(.caption)
            .foregroundStyle(DesignTokens.muted)
            if let note = current.note, !note.isEmpty, current.cameFromMistake {
                Text("你在这里写过「\(note)」")
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .padding(.top, 2)
            }
        }
    }

    @ViewBuilder
    private var statusButton: some View {
        if current.isUnderstood {
            HStack(spacing: 6) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.green)
                Text("已弄懂")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.green)
            }
            .padding(.top, 6)
        } else {
            Button {
                Task { await mark() }
            } label: {
                HStack(spacing: 6) {
                    if isUpdating { ProgressView().controlSize(.small).tint(.white) }
                    Text(isUpdating ? "正在保存…" : "标记为已弄懂")
                }
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(isUpdating)
            .padding(.top, 6)
        }
    }

    @MainActor
    private func load() async {
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            isLoading = false
            return
        }
        isLoading = true
        errorMessage = nil
        do {
            loaded = try await client.grammarPoint(key: point.key)
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    @MainActor
    private func mark() async {
        guard let client else { return }
        isUpdating = true
        defer { isUpdating = false }
        do {
            let updated = try await client.setGrammarStatus(key: point.key, status: "understood")
            // Keep the explanation we already have; the status call does not return it.
            loaded = GrammarPoint(
                id: updated.id,
                key: updated.key,
                titleJA: updated.titleJA,
                titleZH: updated.titleZH,
                level: updated.level,
                category: updated.category,
                status: updated.status,
                firstSource: updated.firstSource,
                note: updated.note,
                hasExplanation: current.hasExplanation,
                explanation: current.explanation
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
