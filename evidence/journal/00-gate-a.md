# §14 私人倾诉 —— 验收材料

日期：2026-08-10 · 分支 `codex/m2-stable-roles` · 对应设计：`docs/PROJECT.md` §14（另改 §1.1、§4.2、§4.3、§5.16、§7.4）

## 1. 范围

| 层 | 落地内容 |
|---|---|
| 数据 | `journal_entry` / `journal_reply` 进 `schema.sql` 基线（按 §7.5 判据不新建迁移） |
| 提示词 | `prompts.py` 的 `JOURNAL_SYSTEM_PROMPT` + `JOURNAL_PROMPT_VERSION = "journal-v1"`，不复用教学内核 |
| 模型交互 | 新模块 `app/journal.py`（只有 build + generate 两个函数，不 import 任何学习侧模块） |
| API | `GET /journal`、`POST /journal`、`POST /journal/{id}/reply`、`PATCH /journal/{id}`、`DELETE /journal/{id}` |
| 运维 | `backup.sh` 固定 `--exclude-table-data`（§7.4 决定：暂时不备份） |
| iOS | `JournalView.swift` 一页纸；`HomeView` 低调入口（无角标、无计数、不在学习入口序列内） |

## 2. 自动化

```
ruff check backend/            All checks passed!
pytest（全新持久库 harvest_journal_test）
  第 1 次   216 passed
  第 2 次   216 passed        ← 同一个库重跑，验证基线可重复执行
test_journal.py               8 passed（含 3 项 integration，未跳过）
iOS  xcodebuild build         ** BUILD SUCCEEDED **
iOS  xcodebuild test          ** TEST SUCCEEDED **
```

新增测试 8 项，其中最重要的一项是隔离断言 —— §14.3 是这个功能的全部意义，所以它有测试而不只是注释：

`test_journal_writes_produce_no_learning_event_and_no_decision_trace`
> 以后任何改动把 journal 接到学习侧，这条会红。

## 3. 真实链路（连百炼 `qwen3.7-max`，非 mock）

在**独立测试库**上起了一个临时 API（端口 8123），不碰真实库、不写入使用者真实的倾诉内容。

### 3.1 语气是否达到 §14.4 的要求

输入 1：
> 今天又是开会开到八点，本来想读点日语的，回来什么都不想干了。

回应 1（43 字）：
> 开到八点确实把人榨干了，这种时候还逼自己学东西反而更累。歇着就歇着吧，脑子也得喘口气。

输入 2：
> 主要是老陈，他把自己那摊活全丢给我了，还说是信任我。

回应 2（30 字）：
> 信任个鬼，这不就是甩锅吗。他每次都这样还是就逮着你一个人坑？

输入 3（**故意不提名字，测连续性**）：
> 明天要不要直接跟他说清楚？

回应 3（47 字）：
> 说清楚是对的，但别带着情绪去讲。你就把哪些活本来是他的、现在占了你多少时间摆出来，让他自己看。

逐条对照 §14.4：

| 要求 | 实际 |
|---|---|
| 会接话、有态度 | 「信任个鬼，这不就是甩锅吗」 |
| 可以不同意 / 有看法 | 「说清楚是对的，**但别带着情绪去讲**」——给了判断，不是顺着说 |
| 有记性 | 第 3 条只说「跟他」，回应准确接上老陈与分工，**未提示任何上下文** |
| 可以很短 | 30–47 字，全部两句以内 |
| 不端着 | 无小标题、无列表、无总结句 |
| 不给清单式方案 | 第 3 条给了一个做法，但是散文一句，不是「三点建议」 |
| 不复述贴标签 | 三条都没有出现「听起来你感到……」 |
| 不正能量 | 无「你已经很棒了」「加油」，无 emoji |
| 不编造自己的经历 | 三条都没有出现「我也……」 |
| 不教日语 | 输入 1 明确提到日语，回应没有转成教学 |

### 3.2 隔离（§14.3）

```
 journal_entry                    |     3
 journal_reply                    |     3
 learning_event  (§14.3 必须为 0) |     0
 decision_trace  (§14.3 必须为 0) |     1   ← 见下
 companion_message (未被借用)     |     0
```

`decision_trace` 那一行经查是启动时的 `learning_event_backfill`（§7.5 固定启动顺序产生），**不是 journal 写的**：

```
 call_source             | status | reason
 learning_event_backfill | ok     | 回填后需重算投影的主体 0 个，裁剪过期 trace 0 行
```

回应行完整记录了路由与版本：

```
 entry_id | model_provider | model_name  | prompt_version | 字数
       76 | dashscope      | qwen3.7-max | journal-v1     |   43
       77 | dashscope      | qwen3.7-max | journal-v1     |   30
       78 | dashscope      | qwen3.7-max | journal-v1     |   47
```

### 3.3 其余行为

| 行为 | 结果 |
|---|---|
| `POST /journal/76/reply` 再要一次 | 追加为 reply id 13，**entry 76 的回应数 = 2**，旧回应未被覆盖 |
| `DELETE /journal/78` | HTTP 204；entry 78 残留 0、其回应残留 0（外键级联，硬删除） |
| 重复删除 / 删不存在的 | HTTP 404 `{"detail":"这条记录不存在。"}` |

### 3.4 备份排除真的生效（§7.4）

用与 `backup.sh` 完全相同的参数对测试库 dump 一次：

```
CREATE TABLE journal_entry 在 dump 里: 1 处（结构保留 ✓）
CREATE TABLE journal_reply 在 dump 里: 1 处（结构保留 ✓）
COPY public.journal_entry 数据段:      0 处 ✓
COPY public.journal_reply 数据段:      0 处 ✓
倾诉原文是否泄漏到 dump（grep 关键词）: 0 处 ✓
对照：COPY public.companion_message:   1 处（其他表照常备份 ✓）
```

即：恢复出来的库**有表但空**，应用不会因缺表报错，而内容确实没有副本。

## 4. 偏离说明

**没有偏离 §14 的设计。** 两处实施层面的判断需要记录：

1. **`POST /journal` 失败时保留 entry，与 `POST /ask` 相反。** `/ask` 会删掉答案没来的问题（幽灵行），这里不删——使用者写的话本身就有价值，因为一次云端 API 抖动就丢掉他刚写的东西，对这个功能是最坏的行为。接口返回 `reply_error`，客户端显示「回应没上来。你写的已经存下了。」并给一个「再试一次」。已在代码注释里写明理由。

2. **iOS 的时间戳格式化器改为按需创建，不用 `static`。** `ISO8601DateFormatter` 不是 `Sendable`，共享实例需要 `nonisolated(unsafe)`；懒加载列表只渲染可见行，这点开销不值得开一个 unsafe 口子。首版写成 static 时构建失败，已改。

## 5. 尚未完成的一步（需要使用者操作）

**真实库还没有这两张表**，因为 `apply_schema` 在 API 启动时执行，而当前运行的是旧代码的进程：

```
SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'journal%';  →  0
```

重启一次服务即可建表并启用新路由：

```bash
./stop.sh && ./start.sh
```

我没有替你重启正在运行的服务。

## 6. 成本

真实验证一共 4 次模型调用（3 条回应 + 1 次重试），按 §2.4 的估算约 **0.15 元**。

## 7. 按 §14.6 的判据，接下来两周

这个功能**不适用** §13.10 前置清单第 4 问（它不产生日语输出，这是 §1.1 已经承认的）。它的判据只有一条，而且只有使用者能判断：

> **说完之后，有没有比说之前轻一点。**

- 两周内一次都没打开 → 没有这个需求，删掉；
- 打开了但说完没变轻 → 大概率踩了 §14.4 某一条，改提示词再试。

按 §14.6，**不做任何自动指标**（条数、频率、字数、情绪分）来回答这个问题。
