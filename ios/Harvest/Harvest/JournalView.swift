import SwiftUI

/// §14: the one page in this app with nothing to do with Japanese. Work, life, whatever
/// you want to say. Write it and something answers — no button to press first (§14.2).
///
/// It is deliberately not the chat teacher wearing a different hat. A thing that corrects
/// your grammar is a thing you do not speak freely to, so the separation has to be
/// *felt*, not just true in the database (§14.3).
struct JournalView: View {
    @EnvironmentObject private var configuration: AppConfiguration

    @State private var entries: [JournalEntry] = []
    @State private var draft = ""
    @State private var isSending = false
    /// Echoed the moment you send, so your own words never vanish into a spinner.
    @State private var pendingBody: String?
    @State private var errorMessage: String?
    /// Entries that were saved but whose reply never arrived, keyed by entry id.
    @State private var replyErrors: [Int: String] = [:]
    @State private var retrying: Set<Int> = []
    @State private var editingID: Int?
    @FocusState private var isInputFocused: Bool

    private var client: APIClient? {
        configuration.endpoint.map { APIClient(baseURL: $0) }
    }

    private var trimmed: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        VStack(spacing: 0) {
            timeline
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DesignTokens.accent)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
            }
            if editingID != nil { editingBar }
            composer
        }
        .background(DesignTokens.canvas.ignoresSafeArea())
        .navigationTitle("说点别的")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    // MARK: - Timeline

    private var timeline: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 34) {
                    if entries.isEmpty && pendingBody == nil { emptyState }
                    ForEach(entries) { entry in
                        entryBlock(entry)
                            .id(entry.id)
                    }
                    if let pendingBody {
                        VStack(alignment: .leading, spacing: 14) {
                            entryText(pendingBody)
                            ProgressView()
                                .controlSize(.small)
                                .tint(DesignTokens.accent)
                        }
                        .id("pending")
                    }
                }
                // No card around any of this: the page *is* the paper (§14.2). This inset
                // is therefore the only thing setting line length, so it stays generous
                // rather than following the wider page gutter.
                .padding(.horizontal, 20)
                .padding(.vertical, 24)
            }
            .onChange(of: entries.count) {
                guard let last = entries.last else { return }
                withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
            }
            .onChange(of: pendingBody) {
                guard pendingBody != nil else { return }
                withAnimation { proxy.scrollTo("pending", anchor: .bottom) }
            }
        }
    }

    private func entryBlock(_ entry: JournalEntry) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(shortTime(entry.createdAt))
                .font(.caption2)
                .foregroundStyle(DesignTokens.muted)
            entryText(entry.body)
            ForEach(entry.replies) { reply in
                replyText(reply.body)
            }
            if retrying.contains(entry.id) {
                ProgressView().controlSize(.small).tint(DesignTokens.accent)
            } else if let failure = replyErrors[entry.id] {
                replyFailure(entry: entry, detail: failure)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contextMenu {
            Button("再要一次回应") { Task { await retryReply(entry) } }
            Button("改一下") { beginEditing(entry) }
            Button("删掉", role: .destructive) { Task { await deleteEntry(entry) } }
        }
    }

    /// Your own words: serif, full size. Theirs: same family, a little smaller and a
    /// shade lighter. Two voices set apart by type rather than by bubbles or rules —
    /// §1.5 rules out decorative left bars, and a chat transcript is not what this is.
    private func entryText(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 19, design: .serif))
            .foregroundStyle(DesignTokens.ink)
            .lineSpacing(8)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func replyText(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 17, design: .serif))
            .foregroundStyle(DesignTokens.ink.opacity(0.85))
            .lineSpacing(7)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 2)
    }

    /// The entry survived; only the reply did not. Say that plainly and offer one action —
    /// the words are already safe, which is the whole reason the server keeps them.
    private func replyFailure(entry: JournalEntry, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("回应没上来。你写的已经存下了。")
                .font(.footnote)
                .foregroundStyle(DesignTokens.muted)
            Text(detail)
                .font(.caption2)
                .foregroundStyle(DesignTokens.muted.opacity(0.8))
            Button("再试一次") { Task { await retryReply(entry) } }
                .font(.footnote.weight(.medium))
                .foregroundStyle(DesignTokens.accent)
                .buttonStyle(.plain)
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("这里只有你和它。")
                .font(.system(size: 21, design: .serif))
                .foregroundStyle(DesignTokens.ink)
            // Saying this out loud is part of the design: the isolation only works if you
            // can feel it (§14.3).
            Text("说工作、说生活、说今天不想学，都行。这里不教日语，也不会纠你。")
                .font(.system(size: 16, design: .serif))
                .foregroundStyle(DesignTokens.muted)
                .lineSpacing(6)
        }
        .padding(.top, 12)
    }

    // MARK: - Composer

    private var editingBar: some View {
        HStack {
            Text("正在改上面那条")
                .font(.footnote)
                .foregroundStyle(DesignTokens.muted)
            Spacer()
            Button("取消") { cancelEditing() }
                .font(.footnote)
                .foregroundStyle(DesignTokens.accent)
                .buttonStyle(.plain)
        }
        .padding(.horizontal, 20)
        .padding(.top, 8)
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("写点什么…", text: $draft, axis: .vertical)
                .font(.system(size: 17, design: .serif))
                .lineLimit(1...8)
                .focused($isInputFocused)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(DesignTokens.surface, in: RoundedRectangle(cornerRadius: 15))
                .overlay {
                    RoundedRectangle(cornerRadius: 15).stroke(DesignTokens.separator, lineWidth: 0.5)
                }

            Button {
                Task { await submit() }
            } label: {
                Image(systemName: editingID == nil ? "arrow.up" : "checkmark")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(
                        DesignTokens.accent.opacity(!isSending && !trimmed.isEmpty ? 1 : 0.45),
                        in: Circle()
                    )
            }
            .disabled(isSending || trimmed.isEmpty)
            .accessibilityLabel(editingID == nil ? "说出来" : "改好了")
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
    }

    // MARK: - Actions

    @MainActor private func load() async {
        guard let client else {
            errorMessage = "请先在设置中填写服务地址。"
            return
        }
        do {
            entries = try await client.journalEntries()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor private func submit() async {
        if editingID != nil {
            await commitEdit()
        } else {
            await send()
        }
    }

    @MainActor private func send() async {
        let value = trimmed
        guard !isSending, !value.isEmpty, let client else { return }
        isSending = true
        pendingBody = value
        draft = ""
        isInputFocused = false
        errorMessage = nil
        do {
            let result = try await client.postJournalEntry(body: value)
            pendingBody = nil
            if let failure = result.replyError {
                replyErrors[result.entry.id] = failure
            }
            // Let the entry settle before the reply appears, so the answer reads as a
            // response instead of landing in the same frame (§5.17's lesson, same idea).
            withAnimation(.easeOut(duration: 0.18)) { entries += [result.entry] }
        } catch {
            // The request never reached the server, so nothing was stored: hand the text
            // back rather than losing it.
            pendingBody = nil
            draft = value
            errorMessage = error.localizedDescription
        }
        isSending = false
    }

    @MainActor private func retryReply(_ entry: JournalEntry) async {
        guard let client, !retrying.contains(entry.id) else { return }
        retrying.insert(entry.id)
        replyErrors[entry.id] = nil
        do {
            _ = try await client.retryJournalReply(id: entry.id)
            await load()
        } catch {
            replyErrors[entry.id] = error.localizedDescription
        }
        retrying.remove(entry.id)
    }

    private func beginEditing(_ entry: JournalEntry) {
        editingID = entry.id
        draft = entry.body
        isInputFocused = true
    }

    private func cancelEditing() {
        editingID = nil
        draft = ""
        isInputFocused = false
    }

    @MainActor private func commitEdit() async {
        guard let client, let id = editingID else { return }
        let value = trimmed
        guard !value.isEmpty else { return }
        isSending = true
        do {
            _ = try await client.updateJournalEntry(id: id, body: value)
            cancelEditing()
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
        isSending = false
    }

    @MainActor private func deleteEntry(_ entry: JournalEntry) async {
        guard let client else { return }
        do {
            try await client.deleteJournalEntry(id: entry.id)
            if editingID == entry.id { cancelEditing() }
            replyErrors[entry.id] = nil
            withAnimation { entries.removeAll { $0.id == entry.id } }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Metadata, so it gets the small muted treatment — unlike the words themselves,
    /// which §1.5 says must never be the faintest thing on the page.
    ///
    /// Formatters are built per call rather than cached in a `static`: `ISO8601DateFormatter`
    /// is not `Sendable`, so a shared instance would need `nonisolated(unsafe)`. A lazy
    /// list only renders the visible rows, so this costs nothing worth an unsafe opt-out.
    private func shortTime(_ iso: String) -> String {
        // Postgres timestamptz arrives with fractional seconds, which the plain parser
        // rejects — try both rather than showing a blank timestamp.
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = withFraction.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else {
            return ""
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = Calendar.current.isDateInToday(date) ? "HH:mm" : "M月d日 HH:mm"
        return formatter.string(from: date)
    }
}
