# §5.18 首页的一句「上次到哪儿了」—— 验收材料

日期：2026-08-10 · 分支 `codex/m2-stable-roles` · 设计：`docs/PROJECT.md` §5.18

## 1. 范围

| 层 | 落地内容 |
|---|---|
| 查询 | `repository.resume_hint()` + 两个常量 `RESUME_MIN_RATIO=0.02` / `RESUME_MAX_RATIO=0.80` |
| API | `GET /home/resume` → `{"hint": <对象>|null}` |
| iOS | `ResumeHint` / `ResumeHintEnvelope` 模型、`APIClient.resumeHint()`、`HomeView` 的 `resumeLine`（可点） |
| 数据 | **零新表、零新事实**，全部由既有 `material_playback_state` / `segment` / `grammar_encounter` 派生 |

## 2. 阈值不是拍的 —— 先查真实库再定

2026-08-10 查真实库（只读），4 条播放位置：

```
 id |  kind   |      标题      | position_ms | duration_ms | 内部比例 | 第几句 |        上次
 37 | reading | しいカフェ     |       47959 |       54456 |     88%  |      9 | 08-10 11:58
 39 | video   | せっかく○○のに |       43050 |      576340 |      7%  |      9 | 08-10 11:21
 33 | video   | 日本で人気     |      341906 |      390050 |     88%  |     38 | 08-08 13:52
 36 | video   | どこよりも…    |       46650 |       55030 |     85%  |     18 | 08-07 01:15
```

**3 条在 85–88%（那是读完了），1 条在 7%（那才是真的中断）。**

所以上界取 **80%** 而不是 90%——取 90% 会把三条已经读完的材料全变成提醒，那就是唠叨。下界 2% 排除「刚打开就退出」。

> 顺带核对了一处可能看起来矛盾的地方：`VideoLearningView.swift` 里已有的 `normalizedResumePosition` 用 **0.95** 判「视为看完、从头开始」。两个数字回答的是不同问题——0.95 决定**播放器要不要从头播**，0.80 决定**这件事值不值得在首页说一句**。88% 的材料会正常续播到接近结尾，但不该被当成「中断了」拿出来提醒。

## 3. 真实库验证：这一句实际会说什么

对真实库跑 `resume_hint()`（该方法只有 SELECT，未 `apply_schema`、未写入）：

```json
{
  "kind": "material",
  "material_id": 39,
  "material_kind": "video",
  "title": "せっかく○○のに",
  "position_ms": 43050,
  "sentence_number": null,
  "at": "2026-08-10 11:21:35+08:00"
}
```

首页那一句渲染为：

```
上次停在 0:43 · せっかく○○のに          >
```

**选中的正是那条 7% 的**，三条 85–88% 的都没有被选上。诊断成立。

## 4. 判据守住了吗

| §5.18 的要求 | 实际 |
|---|---|
| 陈述，不是评判 | 「上次停在 0:43」。**代码里没有任何一处产生「你已经 N 天没…」这类文案** |
| 不显示百分比 | 比例只在 `repository.py` 内部作筛选条件，**payload 里没有任何 progress/ratio/percent 字段**（有测试断言） |
| 阅读说句号、视频说时间 | reading → `sentence_number=5`；video → `sentence_number=null` + 时间戳（各有测试） |
| 最多一句，取不到就不显示 | `hint=null` → iOS 的 `@ViewBuilder` 整行不渲染 |
| 必须可点，回到那个位置 | `HomeDestination.material(Int)` → `ReaderView(materialID:)`；语法点 → `GrammarDetailView(point:)` |
| 失败不报错 | 与计数同一策略（`try?`），并入同一批并行请求 |
| 只取「撞见过、还没弄懂」 | `status='encountered'`，`understood` 的点不出现（有测试） |

## 5. 自动化

```
ruff check backend/            All checks passed!
pytest（全新持久库 harvest_e1_test）
  第 1 次   223 passed
  第 2 次   223 passed
test_resume_hint.py            7 passed（6 项 integration 未跳过）
iOS  xcodebuild build          ** BUILD SUCCEEDED **
iOS  xcodebuild test           ** TEST SUCCEEDED **
```

新增 7 项测试，覆盖：两端边界（88% 与 1% 都不提供）、优先级（可续播的材料压过语法点）、阅读给句号 / 视频给时间、`understood` 不出现、空状态返回 None、以及两个阈值常量本身。

## 6. 偏离说明

**一处接口形状与文档初稿不同，已同步改文档。** §5.18 初稿写「返回一条或空对象」，实际改为 `{"hint": …|null}` 的信封——**顶层 JSON `null` 在 Swift 里解不进 Optional**。这一层不是设计上的层次，只是客户端解码的现实，已在 §5.18 写明理由。

**一处实现选择：** `HomeDestination` 新增 `case material(Int)` 而不是直接用 `Int` 作导航类型——`MaterialListView` 在同一个 `NavigationStack` 里已经声明了 `navigationDestination(for: Int.self)`，两处同类型会互相盖住。

## 7. 按 §5.18 的可证伪判据

> **如果它从不被点，它就是装饰。**

它唯一的产出是「把你带回上次停下的地方」。用一段时间后，如果这一句出现过很多次但从没点进去，按 §14.6 同样的态度删掉，不因为「首页看起来更聪明」留着它。

**不做任何自动埋点来回答这个问题**——这一句本身的价值就是不被考核。你自己知道有没有点过。
