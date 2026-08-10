"""The grammar skeleton's index (§12).

Deliberately an index and nothing more: a stable key, the form itself, a short
Chinese label, a level and a category. There are no explanations and no example
sentences here — §1.4 still rules out transcribing textbook material, and §12.1
puts the explanation in the teaching kernel, generated on demand.

Extending the list is a data change: entries are upserted by key on startup, so a new
one can be inserted where it belongs rather than appended — `sort_order` is recomputed
for everything and `grammar_encounter` hangs off `point_id`, which is stable per key.
Starting at N5–N4 covers every category the learner has actually tripped on so
far (ている, てある, い-adjective past, potential form, は/が).

One rule about growing this list (§11.11): add a point because something already here
structurally requires it, or because the learner really tripped on it — never because a
model reached for a key that did not exist. Filling the list with whatever the model
wants to tag is how an index turns into a worse copy of a textbook (§12.1).
"""

from __future__ import annotations

# (key, title_ja, title_zh, level, category)
GRAMMAR_CATALOGUE: list[tuple[str, str, str, str, str]] = [
    # ── 助词 ───────────────────────────────────────────────
    ("particle-wa", "は", "话题提示", "N5", "助词"),
    ("particle-ga", "が", "主语／新信息", "N5", "助词"),
    ("particle-wo", "を", "动作对象", "N5", "助词"),
    ("particle-ni-time", "に（时间）", "时间点", "N5", "助词"),
    ("particle-ni-place", "に（存在・到达）", "存在或到达点", "N5", "助词"),
    # Added 2026-08-10 (§11.11 → resolved). Not added because a model reached for it, but
    # because three points already in this list structurally require it: giving-receiving
    # (友達にあげる／友達にもらう), verb-passive (先生に褒められた) and verb-causative
    # (子供に食べさせる). Without it the model explained 「友達に…てもらう」 correctly, found
    # no matching key, and tagged the nearest one instead — particle-ni-place, which is
    # wrong. A prompt guard against picking the nearest only worked 1 run in 3; the gap was
    # the actual cause.
    ("particle-ni-agent", "に（相手・動作主）", "给谁／被谁／让谁", "N5", "助词"),
    ("particle-de-place", "で（场所）", "动作发生地", "N5", "助词"),
    ("particle-de-means", "で（手段）", "手段与工具", "N5", "助词"),
    ("particle-e", "へ", "方向", "N5", "助词"),
    ("particle-to", "と", "并列与共同", "N5", "助词"),
    ("particle-mo", "も", "也、同样", "N5", "助词"),
    ("particle-no", "の", "所属与修饰", "N5", "助词"),
    ("particle-kara-made", "から／まで", "起点与终点", "N5", "助词"),
    ("particle-ya", "や", "列举其一", "N4", "助词"),
    ("particle-shika", "しか〜ない", "只有（否定呼应）", "N4", "助词"),
    ("particle-wa-ga-contrast", "は vs が", "两者的分工", "N4", "助词"),
    # ── 动词变形 ────────────────────────────────────────────
    ("verb-masu", "～ます", "礼貌体现在", "N5", "动词变形"),
    ("verb-masen", "～ません", "礼貌体否定", "N5", "动词变形"),
    ("verb-mashita", "～ました", "礼貌体过去", "N5", "动词变形"),
    ("verb-plain-present", "辞书形", "简体现在", "N5", "动词变形"),
    ("verb-nai", "～ない", "简体否定", "N5", "动词变形"),
    ("verb-ta", "～た", "简体过去", "N5", "动词变形"),
    ("verb-te", "～て", "て形与连接", "N5", "动词变形"),
    ("verb-te-iru", "～ている", "进行与状态持续", "N5", "动词变形"),
    ("verb-te-aru", "～てある", "有意留下的状态", "N4", "动词变形"),
    ("verb-te-oku", "～ておく", "预先做好", "N4", "动词变形"),
    ("verb-te-shimau", "～てしまう", "完成／懊悔", "N4", "动词变形"),
    ("verb-potential", "可能形", "能不能做到", "N4", "动词变形"),
    ("verb-volitional", "意向形", "打算与提议", "N4", "动词变形"),
    ("verb-passive", "受身形", "被动", "N4", "动词变形"),
    ("verb-causative", "使役形", "让／使", "N4", "动词变形"),
    ("verb-conditional-tara", "～たら", "假定条件", "N4", "动词变形"),
    ("verb-conditional-ba", "～ば", "条件（书面偏多）", "N4", "动词变形"),
    ("verb-imperative", "命令形", "命令与禁止", "N4", "动词变形"),
    # ── 形容词 ─────────────────────────────────────────────
    ("i-adj-present", "い形容词", "基本形与修饰", "N5", "形容词"),
    ("i-adj-negative", "～くない", "い形否定", "N5", "形容词"),
    ("i-adj-past", "～かった", "い形过去（不接 でした）", "N5", "形容词"),
    ("i-adj-te", "～くて", "い形连接", "N5", "形容词"),
    ("na-adj-present", "な形容词", "修饰名词要加 な", "N5", "形容词"),
    ("na-adj-past", "～でした", "な形与名词的过去", "N5", "形容词"),
    ("adj-comparison", "～より／～のほうが", "比较", "N4", "形容词"),
    ("adj-naru", "～くなる／～になる", "变化", "N4", "形容词"),
    # ── 句型 ───────────────────────────────────────────────
    ("desu-da", "です／だ", "断定与语体", "N5", "句型"),
    ("question-ka", "～か", "疑问句", "N5", "句型"),
    ("existence-aru-iru", "ある／いる", "有生与无生", "N5", "句型"),
    ("want-tai", "～たい", "想做（第一人称）", "N5", "句型"),
    ("want-hoshii", "～がほしい", "想要（物）", "N5", "句型"),
    ("invite-masenka", "～ませんか", "邀请", "N5", "句型"),
    ("request-tekudasai", "～てください", "请求", "N5", "句型"),
    ("permission-temoii", "～てもいい", "许可", "N5", "句型"),
    ("prohibition-tewaikenai", "～てはいけない", "禁止", "N5", "句型"),
    ("obligation-nakereba", "～なければならない", "必须", "N4", "句型"),
    ("experience-takotogaaru", "～たことがある", "有过的经验", "N4", "句型"),
    ("ability-kotogadekiru", "～ことができる", "能力（书面）", "N4", "句型"),
    ("plan-tsumori", "～つもり", "打算", "N4", "句型"),
    ("guess-deshou", "～でしょう", "推测", "N4", "句型"),
    ("hearsay-souda", "～そうだ（传闻）", "据说", "N4", "句型"),
    ("appearance-souda", "～そうだ（样态）", "看起来", "N4", "句型"),
    ("comparison-you", "～ようだ／～みたい", "好像", "N4", "句型"),
    ("purpose-tameni", "～ために", "为了", "N4", "句型"),
    ("reason-node", "～ので", "原因（客气）", "N4", "句型"),
    ("reason-kara", "～から", "原因（主观）", "N5", "句型"),
    ("contrast-ga-kedo", "～が／～けど", "转折", "N5", "句型"),
    ("contrast-noni", "～のに", "明明却", "N4", "句型"),
    ("quote-to-iu", "～という", "引用与称呼", "N4", "句型"),
    ("quote-to-omou", "～と思う", "认为", "N5", "句型"),
    ("giving-receiving", "あげる／くれる／もらう", "授受关系", "N4", "句型"),
    ("honorific-basic", "敬語入门", "尊敬与谦让的分工", "N4", "句型"),
]


def catalogue_rows() -> list[dict[str, object]]:
    return [
        {
            "key": key,
            "title_ja": title_ja,
            "title_zh": title_zh,
            "level": level,
            "category": category,
            "sort_order": index,
        }
        for index, (key, title_ja, title_zh, level, category) in enumerate(GRAMMAR_CATALOGUE)
    ]
