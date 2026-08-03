# P3 全局日语聊天与个人纠错知识库：闸 A 验收材料

验收日期：2026-08-03

仓库：[GHH158/harvest-platform](https://github.com/GHH158/harvest-platform)。本文件与本次实现位于同一提交。

## 环境信息

```text
Python 3.12.13
Xcode 26.6
Build version 17F113
iOS Deployment Target 18.0
iPhone 17 Pro Simulator / iOS 26.5
PostgreSQL 17.10 (Postgres.app)
```

验收时的云配置状态原文：

```text
DASHSCOPE_API_KEY configured: False
DEEPSEEK_API_KEY configured: False
OSS credentials configured: False
```

因此下文聊天成功响应来自**真实 FastAPI 路由 + 真实 PostgreSQL 17 + 契约 mock 模型**，没有向百炼、DeepSeek 或 OSS 发出请求。

## 自动化测试实际输出

### Python 与 PostgreSQL

```text
All checks passed!
...................................................................      [100%]
67 passed in 1.57s
```

其中 PostgreSQL 集成测试单独执行结果：

```text
.......                                                                  [100%]
7 passed, 59 deselected in 0.55s
```

集成测试实际覆盖旧 `personal` 迁移、会话和消息隔离、事务回滚、纠错筛选与删除、会话级联，以及完整 mock API 流程。

### iOS 模拟器实际测试

命令在 iPhone 17 Pro（iOS 26.5）模拟器执行，退出码为 0。原始逐项结果：

```text
Test case 'HarvestTests/voiceTeacherUsesWebSocketThroughTheMacEndpoint()' passed
Test case 'HarvestTests/materialDecodesSentenceTimeline()' passed
Test case 'HarvestTests/photoSubmissionDecodesMaterialContract()' passed
Test case 'HarvestTests/shadowingAttemptDecodesAsyncStatus()' passed
Test case 'HarvestTests/hlsPlaylistResolvesSegmentsAndDurations()' passed
Test case 'HarvestTests/segmentedPlayerAppendsNewlyDownloadedParts()' passed
Test case 'HarvestTests/offlineEntryOnlyExposesContiguousDownloadedPrefix()' passed
Test case 'HarvestTests/segmentedDownloadResumesWithoutRefetchingStoredParts()' passed
Test case 'HarvestTests/chatModelsDecodeTopicsSessionsAndCorrectionTurns()' passed
Test case 'HarvestTests/topicDeckShowsEveryTopicBeforeRepeatingAndAvoidsImmediateRepeat()' passed
Test case 'HarvestTests/customChineseAndJapaneseTopicsUseTheNewSessionAPI()' passed
Test case 'HarvestTests/transcriptRowsRenderCorrectionOnlyWhenPresent()' passed
Test case 'HarvestTests/failedSendKeepsDraftAndHistoryCanBeRestored()' passed
Test case 'HarvestTests/correctionFiltersAndDeletesUseExpectedRequests()' passed
```

共 14 passed、0 failed、0 skipped。

## 关键 API 返回 JSON 原文

### `GET /chat/topics`

状态码：`200`

```json
[{"id":"daily-happy","category":"日常","title_ja":"最近、ちょっと嬉しかったこと","hint_zh":"最近让你有点开心的事"},{"id":"daily-impression","category":"日常","title_ja":"今日、いちばん印象に残ったこと","hint_zh":"今天印象最深的事"},{"id":"daily-weekend","category":"日常","title_ja":"今週末の予定","hint_zh":"这个周末的计划"},{"id":"daily-habit","category":"日常","title_ja":"最近変えたい習慣","hint_zh":"最近想改变的习惯"},{"id":"interest-screen","category":"兴趣","title_ja":"最近見た映画やドラマ","hint_zh":"最近看的电影或电视剧"},{"id":"interest-music","category":"兴趣","title_ja":"よく聴く音楽","hint_zh":"最近常听的音乐"},{"id":"interest-purchase","category":"兴趣","title_ja":"最近買ってよかったもの","hint_zh":"最近买得很值的东西"},{"id":"interest-place","category":"兴趣","title_ja":"行ってみたい場所","hint_zh":"想去看看的地方"},{"id":"work-trouble","category":"工作学习","title_ja":"最近、仕事で困ったこと","hint_zh":"最近工作上的困扰"},{"id":"work-style","category":"工作学习","title_ja":"理想の働き方","hint_zh":"理想的工作方式"},{"id":"study-again","category":"工作学习","title_ja":"今、学び直したいこと","hint_zh":"现在想重新学习的事"},{"id":"study-focus","category":"工作学习","title_ja":"集中できる環境","hint_zh":"让自己更专注的环境"},{"id":"opinion-alone","category":"观点想象","title_ja":"一人の時間は必要？","hint_zh":"人是否需要独处时间"},{"id":"opinion-city","category":"观点想象","title_ja":"都会と田舎、どちらが好き？","hint_zh":"更喜欢城市还是乡村"},{"id":"imagine-week","category":"观点想象","title_ja":"もし一週間休めたら","hint_zh":"如果能休息一周"},{"id":"imagine-future","category":"观点想象","title_ja":"将来やってみたいこと","hint_zh":"将来想尝试的事"}]
```

### `POST /chat/sessions`

请求使用 `starter_id=daily-weekend`，状态码：`201`

```json
{"session":{"id":"00000000-0000-4000-8000-00000000a803","topic":"今週末の予定","starter_id":"daily-weekend","created_at":"2026-08-03T16:05:19.252401+08:00","updated_at":"2026-08-03T16:05:19.252401+08:00"},"assistant":{"id":32,"session_id":"00000000-0000-4000-8000-00000000a803","role":"assistant","content":"週末について話しましょう。\n\n今週末は何をしたいですか？","created_at":"2026-08-03T16:05:19.252401+08:00"}}
```

### `POST /chat/sessions/{id}/messages`

请求消息为 `昨日映画を見る。`，状态码：`200`

```json
{"user":{"id":33,"session_id":"00000000-0000-4000-8000-00000000a803","role":"user","content":"昨日映画を見る。","created_at":"2026-08-03T16:05:19.255292+08:00"},"correction":{"id":10,"session_id":"00000000-0000-4000-8000-00000000a803","user_message_id":33,"original_text":"昨日映画を見る。","corrected_text":"昨日、映画を見ました。","summary_zh":"已经发生的事情使用过去时。","created_at":"2026-08-03T16:05:19.255292+08:00","items":[{"id":7,"correction_id":10,"idx":0,"original":"見る","replacement":"見ました","reason_zh":"使用过去时。","category":"grammar"}]},"assistant":{"id":34,"session_id":"00000000-0000-4000-8000-00000000a803","role":"assistant","content":"いいですね。映画館で見たんですか？\n\nどんな映画でしたか？","created_at":"2026-08-03T16:05:19.255292+08:00"}}
```

### `GET /chat/corrections?topic=今週末の予定&category=grammar`

状态码：`200`

```json
[{"id":10,"session_id":"00000000-0000-4000-8000-00000000a803","user_message_id":33,"original_text":"昨日映画を見る。","corrected_text":"昨日、映画を見ました。","summary_zh":"已经发生的事情使用过去时。","created_at":"2026-08-03T16:05:19.255292+08:00","topic":"今週末の予定","items":[{"id":7,"correction_id":10,"idx":0,"original":"見る","replacement":"見ました","reason_zh":"使用过去时。","category":"grammar"}]}]
```

### 无 Key 失败与零部分写入

未替换模型服务时调用 `POST /chat/sessions`，完整响应：

```text
HTTP 503
{"detail":"DASHSCOPE_API_KEY 与 DEEPSEEK_API_KEY 均未配置。"}
```

对应查询：

```text
 partial_sessions
------------------
                0
(1 row)
```

## PostgreSQL 查询结果原文

幂等 schema 已实际应用到当前本地 `harvest` 数据库。迁移后的聊天表与现有数据量：

```text
      tablename
----------------------
 chat_correction
 chat_correction_item
 chat_message
 chat_session
(4 rows)

 sessions | messages | corrections
----------+----------+-------------
        0 |        0 |           0
(1 row)
```

当前库原先没有旧聊天记录，因此真实库迁移没有可迁移的 `personal` 行；旧表含 `personal` 的迁移路径已在临时 PostgreSQL schema 集成测试中通过。

```text
                  id                  |    topic     |  starter_id
--------------------------------------+--------------+---------------
 00000000-0000-4000-8000-00000000a803 | 今週末の予定 | daily-weekend
(1 row)
```

```text
 id |              session_id              |   role    |              content
----+--------------------------------------+-----------+------------------------------------
 32 | 00000000-0000-4000-8000-00000000a803 | assistant | 週末について話しましょう。        +
    |                                      |           |                                   +
    |                                      |           | 今週末は何をしたいですか？
 33 | 00000000-0000-4000-8000-00000000a803 | user      | 昨日映画を見る。
 34 | 00000000-0000-4000-8000-00000000a803 | assistant | いいですね。映画館で見たんですか？+
    |                                      |           |                                   +
    |                                      |           | どんな映画でしたか？
(3 rows)
```

```text
 id |  original_text   |     corrected_text     |         summary_zh         | category | original_fragment | replacement
----+------------------+------------------------+----------------------------+----------+-------------------+-------------
 10 | 昨日映画を見る。 | 昨日、映画を見ました。 | 已经发生的事情使用过去时。 | grammar  | 見る              | 見ました
(1 row)
```

该验收样本已从隔离测试库删除。

## iOS 界面文字原文

主题启动页与输入区：

```text
聊天老师
今日は何を話しましょう？
选一个主题，或者直接写下任何想聊的事
正在准备主题
换一批
输入任意中文或日语主题
```

会话、纠错卡与次级入口：

```text
用日语聊下去
老师正在想…
新主题
历史
纠错库
表达调整
原句
更自然
```

历史和纠错库：

```text
聊天历史
读取会话历史
还没有聊天历史
删除
纠错库
读取纠错库
还没有纠错记录
没有符合筛选的记录
搜索原句、修正版或说明
筛选
主题
全部主题
类别
全部类别
删除纠错
完成
```

主题卡的 16 组日语标题与中文提示以 `GET /chat/topics` 原文为准，iOS 每批显示 4 组。

## 逐项完成状态

| 项目 | 状态 | 说明 |
|---|---|---|
| `PROJECT.md` 单文档更新与正式提示词 | 完成 | 主题、提示词、JSON 契约、schema、API、阶段范围均已写入 |
| 主题独立会话与 AI 主动开场 | 闸 A 完成 | 真实 API/PostgreSQL + mock 模型通过；真实模型待闸 B |
| 16 主题、每批 4 个、整轮不重复 | 完成 | iOS 随机牌组测试通过，下一轮首批避开上一批 |
| 中文/日语自定义主题 | 完成 | iOS 请求体测试通过 |
| 严格 JSON、非法类别、1–3 条限制、一次修复 | 完成 | Python 契约测试通过 |
| 失败零部分写入 | 完成 | 模型失败与数据库事务回滚均有自动化测试；无 Key 查询为 0 行 |
| 会话仅携带最近 20 条消息 | 完成 | 上下文截断测试通过，完整历史仍在 PostgreSQL |
| 最近 30 条纠错、最多 3 类、600 字上限 | 完成 | 排名与长度测试通过 |
| 历史恢复与会话删除 | 完成 | iOS 恢复测试、PostgreSQL 级联测试通过 |
| 纠错搜索、主题/类别筛选、单条删除 | 完成 | API、Repository 与 iOS 请求测试通过；单删不删除消息 |
| 旧 `personal` 与其他 session 迁移 | 完成 | 临时 PostgreSQL schema 中从旧表执行真实迁移并验证外键 |
| 旧 `/chat` 兼容接口 | 完成 | 路由保留，继续适配旧 App 数据结构 |
| iPhone 模拟器构建并执行测试 | 完成 | iPhone 17 Pro / iOS 26.5，14 passed |

## 偏离说明与闸 B 边界

实现范围没有偏离本次计划：只改全局文字聊天，没有修改材料陪读和实时语音老师；没有加入 pgvector、Embedding、RAG、SRS、主动复习、流式文本或后台提示词编辑。

本次仅为**闸 A**。以下项目明确未验证，不能据此声称真实聊天功能已经云端通过：

- 未调用真实 Qwen/百炼聊天模型；尚未验证它能长期稳定遵守 JSON、纠错数量与语言规则。
- 未调用 DeepSeek，也未验证百炼额度用尽后的实际切换质量。
- mock 日语回复只用于验证合同、持久化与界面，不代表真实模型回复质量。
- 未做真机网络时延、弱网与长会话体验验证。

配置服务 Key 后须提交闸 B：至少包含真实开场、正确句无纠错、错误句结构化纠错、一次真实模型格式异常/修复观察（若发生）、对应 PostgreSQL 查询和真机界面证据。
