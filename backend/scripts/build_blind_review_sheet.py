from __future__ import annotations

import argparse
import glob
import html
import json
import os
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR
from app.role_blind import BLIND_WITHHELD_FIELDS

ROLE_CHOICES = ("葵", "圭", "林")
CLAIM_LABELS = {
    "language_fact": "语言事实",
    "usage_tendency": "使用倾向",
    "context_inference": "语境推断",
    "preference": "个人偏好",
    "uncertain": "不确定",
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render an anonymous blind-review page from a *-blind.json run artifact. "
            "Reads only the blind sheet — never the answer key."
        )
    )
    parser.add_argument("--blind", type=Path, default=None, help="Blind sheet (default: newest).")
    parser.add_argument("--output", type=Path, default=None, help="Output .html path.")
    return parser.parse_args()


def _newest_blind_sheet() -> Path:
    matches = sorted(glob.glob(str(ROOT_DIR / "backend/data/role-evaluations/*-blind.json")))
    if not matches:
        raise SystemExit("没有找到 *-blind.json，先运行 run_role_blind_evaluation.py。")
    return Path(matches[-1])


def _candidate_block(label: str, candidate: dict[str, Any], case_index: int) -> str:
    if candidate.get("status") != "ok":
        return (
            f'<div class="cand failed"><div class="cand-head"><span class="tag">{label}</span>'
            f'<span class="failed-note">这位候选没有产生可评审的结构化观点</span></div></div>'
        )
    p = candidate["perspective"]
    claim = CLAIM_LABELS.get(str(p.get("claim_type")), str(p.get("claim_type")))
    reusable = p.get("reusable_ja")
    uncertainty = p.get("uncertainty_zh")
    radios = "".join(
        f'<label class="pick"><input type="radio" name="c{case_index}{label}" value="{role}">'
        f"<span>{role}</span></label>"
        for role in ROLE_CHOICES
    )
    extra = ""
    if reusable:
        extra += f'<p class="ja"><span class="lbl">可复用</span>{html.escape(str(reusable))}</p>'
    if uncertainty:
        extra += f'<p class="unc"><span class="lbl">不确定</span>{html.escape(str(uncertainty))}</p>'
    return f"""<div class="cand">
      <div class="cand-head"><span class="tag">{label}</span><span class="claim">{claim}</span></div>
      <p class="head">{html.escape(str(p.get("headline_zh", "")))}</p>
      <p class="analysis">{html.escape(str(p.get("analysis_zh", "")))}</p>
      {extra}
      <div class="guess"><span class="lbl">这是谁</span>{radios}</div>
    </div>"""


def build_page(blind: dict[str, Any]) -> str:
    cases = blind["cases"]
    blocks = []
    for index, case in enumerate(cases, start=1):
        candidates = "".join(
            _candidate_block(label, case["candidates"].get(label, {}), index)
            for label in ("A", "B", "C")
        )
        context = html.escape(str(case.get("context_zh") or "（未给出语境）"))
        blocks.append(f"""<section class="case">
      <header class="case-head">
        <span class="num">第 {index} 题 / 共 {len(cases)}</span>
        <h2 lang="ja">{html.escape(str(case["sentence_ja"]))}</h2>
        <p class="q">{html.escape(str(case["question"]))}</p>
        <p class="ctx">语境：{context}</p>
      </header>
      <div class="cands">{candidates}</div>
      <label class="dup"><input type="checkbox" name="dup{index}">
        这三份基本只是换措辞重复同一个答案</label>
      <textarea name="note{index}" rows="2"
        placeholder="可选：事实冲突 / 已经自然却被强行纠错 / 证据不足却断言关系、地域、范围"></textarea>
    </section>""")

    withheld = "、".join(BLIND_WITHHELD_FIELDS)
    return f"""<h1>M2 去署名盲测评审表</h1>
<p class="meta">协议 {blind["protocol_version"]} · 提示词 {blind["prompt_version"]} ·
  设定集 {blind["manifest_version"]} · {blind["successful_calls"]}/{blind["completed_calls"]} 有结构</p>
<div class="brief">
  <p><strong>怎么判断。</strong>每题三位匿名候选，恰好是葵、圭、林各一位，顺序每题都不同。
    只依据<strong>关注角度与表达方式</strong>判断谁是谁——<code>{withheld}</code>
    已移入答案键，因为服务端会强制它匹配角色，看到它等于直接看答案。</p>
  <p class="lens">葵＝自然表达与听感、语体　圭＝语法关系与信息结构　林＝中文母语迁移</p>
  <p><strong>判完先点最下方按钮保存，再打开答案键。</strong>顺序反了这一轮就不算数。</p>
</div>
{"".join(blocks)}
<div class="done">
  <button id="save" type="button">保存评审结果</button>
  <p class="hint">保存后会下载一个 JSON，把它交给 Claude 对答案；答案键在那之前不要打开。</p>
  <pre id="out" hidden></pre>
</div>
<script>
document.getElementById('save').addEventListener('click', function () {{
  var total = {len(cases)}, picks = {{}}, dups = [], notes = {{}}, missing = 0;
  for (var i = 1; i <= total; i++) {{
    ['A','B','C'].forEach(function (l) {{
      var sel = document.querySelector('input[name="c' + i + l + '"]:checked');
      if (sel) {{ picks[i + l] = sel.value; }} else {{ missing++; }}
    }});
    if (document.querySelector('input[name="dup' + i + '"]').checked) {{ dups.push(i); }}
    var n = document.querySelector('textarea[name="note' + i + '"]').value.trim();
    if (n) {{ notes[i] = n; }}
  }}
  var payload = {{
    run_id: {json.dumps(blind["run_id"])},
    protocol_version: {json.dumps(blind["protocol_version"])},
    unanswered: missing,
    guesses: picks,
    rephrasing_only_cases: dups,
    notes: notes
  }};
  var text = JSON.stringify(payload, null, 2);
  var out = document.getElementById('out');
  out.hidden = false;
  out.textContent = (missing ? '还有 ' + missing + ' 个候选没有选择。\\n\\n' : '') + text;
  var blob = new Blob([text], {{type: 'application/json'}});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'blind-review-' + payload.run_id + '.json';
  a.click();
}});
</script>"""


STYLE = """<style>
:root{color-scheme:light dark;--bg:#fbf9f6;--fg:#221d18;--muted:#6d6257;--line:#e3dcd2;
--card:#fff;--accent:#b4593a;--soft:#f3ede5}
@media (prefers-color-scheme:dark){:root{--bg:#191614;--fg:#ece6df;--muted:#a09488;
--line:#332d28;--card:#221e1b;--accent:#e08a68;--soft:#2a2521}}
:root[data-theme=dark]{--bg:#191614;--fg:#ece6df;--muted:#a09488;--line:#332d28;
--card:#221e1b;--accent:#e08a68;--soft:#2a2521}
:root[data-theme=light]{--bg:#fbf9f6;--fg:#221d18;--muted:#6d6257;--line:#e3dcd2;
--card:#fff;--accent:#b4593a;--soft:#f3ede5}
*{box-sizing:border-box}
body{margin:0 auto;padding:2rem 1.25rem 4rem;max-width:56rem;background:var(--bg);color:var(--fg);
font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans",sans-serif}
h1{font-size:1.5rem;margin:0 0 .3rem}
.meta{color:var(--muted);font-size:.85rem;margin:0 0 1.5rem}
.brief{background:var(--soft);border-left:3px solid var(--accent);padding:.9rem 1.1rem;
border-radius:0 8px 8px 0;margin-bottom:2rem;font-size:.92rem}
.brief p{margin:.4rem 0}
.lens{color:var(--muted)}
code{background:var(--card);padding:.1em .35em;border-radius:4px;font-size:.9em}
.case{border:1px solid var(--line);border-radius:12px;padding:1.2rem;margin-bottom:1.6rem;
background:var(--card)}
.num{color:var(--muted);font-size:.8rem;letter-spacing:.04em}
.case-head h2{font-size:1.25rem;margin:.35rem 0 .5rem;font-weight:600}
.q{margin:.2rem 0;font-weight:500}
.ctx{margin:.2rem 0 1rem;color:var(--muted);font-size:.9rem}
.cands{display:grid;gap:.9rem}
.cand{border:1px solid var(--line);border-radius:9px;padding:.9rem 1rem;background:var(--bg)}
.cand-head{display:flex;align-items:center;gap:.6rem;margin-bottom:.5rem}
.tag{background:var(--accent);color:#fff;width:1.7rem;height:1.7rem;border-radius:50%;
display:grid;place-items:center;font-weight:700;font-size:.85rem}
.claim{color:var(--muted);font-size:.8rem;border:1px solid var(--line);
padding:.05rem .5rem;border-radius:99px}
.failed-note{color:var(--muted);font-size:.9rem}
.head{font-weight:600;margin:.2rem 0 .45rem}
.analysis{margin:.3rem 0;white-space:pre-wrap}
.ja{margin:.5rem 0;font-size:1.02rem}
.unc{margin:.5rem 0;color:var(--muted);font-size:.9rem}
.lbl{display:inline-block;font-size:.72rem;color:var(--muted);border:1px solid var(--line);
padding:.05rem .4rem;border-radius:4px;margin-right:.5rem;vertical-align:.1em}
.guess{margin-top:.8rem;padding-top:.7rem;border-top:1px dashed var(--line)}
.pick{display:inline-flex;align-items:center;gap:.3rem;margin-right:1rem;cursor:pointer}
.dup{display:block;margin:1rem 0 .6rem;font-size:.92rem;cursor:pointer}
textarea{width:100%;padding:.6rem;border:1px solid var(--line);border-radius:7px;
background:var(--bg);color:var(--fg);font:inherit;font-size:.9rem;resize:vertical}
.done{text-align:center;margin-top:2.5rem}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:.7rem 1.6rem;
font:inherit;font-weight:600;cursor:pointer}
.hint{color:var(--muted);font-size:.85rem;margin-top:.6rem}
pre{text-align:left;background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:1rem;overflow-x:auto;font-size:.8rem}
</style>"""


def main() -> int:
    arguments = _arguments()
    blind_path = arguments.blind or _newest_blind_sheet()
    blind = json.loads(blind_path.read_text(encoding="utf-8"))
    leaked = sorted(
        {
            field
            for case in blind["cases"]
            for candidate in case["candidates"].values()
            for field in candidate.get("perspective", {})
            if field in BLIND_WITHHELD_FIELDS
        }
    )
    if leaked:
        raise SystemExit(f"这份匿名表本身就含答案键字段 {leaked}，不能用于盲评。")

    output = arguments.output or blind_path.with_name(blind_path.stem + "-review.html")
    page = (
        "<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>M2 盲测评审 · {blind['run_id']}</title>{STYLE}</head><body>"
        f"{build_page(blind)}</body></html>"
    )
    output.write_text(page, encoding="utf-8")
    os.chmod(output, 0o600)
    print(f"Review page: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
