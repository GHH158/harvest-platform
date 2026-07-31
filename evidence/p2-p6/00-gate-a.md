# P2–P6 闸 A：本地代码、状态机与构建证据

日期：2026-07-31

## 实际输出

```text
All checks passed!
................ss............                                           [100%]
28 passed, 2 skipped in 1.42s
```

上面两项跳过的是需要显式提供 `HARVEST_TEST_DATABASE_URL` 的 PostgreSQL 集成测试；连接本机数据库后单独执行的实际结果为：

```text
..                                                                       [100%]
2 passed, 28 deselected in 0.42s
```

```text
** TEST SUCCEEDED **

Test case 'HarvestTests/shadowingAttemptDecodesAsyncStatus()' passed
Test case 'HarvestTests/photoSubmissionDecodesMaterialContract()' passed
Test case 'HarvestTests/materialDecodesSentenceTimeline()' passed
Test case 'HarvestTests/hlsPlaylistResolvesSegmentsAndDurations()' passed
Test case 'HarvestTests/segmentedPlayerAppendsNewlyDownloadedParts()' passed
Test case 'HarvestTests/offlineEntryOnlyExposesContiguousDownloadedPrefix()' passed
Test case 'HarvestTests/segmentedDownloadResumesWithoutRefetchingStoredParts()' passed
```

iOS 测试目标为 iPhone 17 Pro Simulator（iOS 26.5）；部署目标为 iOS 18.0，App 与 `HarvestTests` 均实际构建，7 个测试均实际执行。

仓库：[GHH158/harvest-platform](https://github.com/GHH158/harvest-platform)。环境：Python 3.12.13、Xcode 26.6（17F113）。

真实启动后，本机和 Tailscale HTTPS 的 health 均返回：

```json
{"status":"ok"}
```

设置页实际可见文字：

```text
服务设置
视觉模型
本地视频保护
```

PostgreSQL schema 实际查询：

```text
  column_name  | data_type | is_nullable
---------------+-----------+-------------
 job_id        | bigint    | YES
 status        | text      | NO
 error_message | text      | YES
(3 rows)
```

## 范围对照

| 阶段 | 已实际完成并测试的闸 A 部分 | 未完成 / 闸 B 未验证 |
|---|---|---|
| P2 | ASR 任务封装、词级时间戳解析/对齐、逐词高亮；已下载阅读材料可从下载列表进入并优先播放本地音频 | 未配置百炼/OSS；未验证真实 ASR 对齐和真机断网播放 |
| P3 | 百炼 Qwen 优先/DeepSeek 备用封装；陪读携带最近历史，阅读页有句子级入口；独立聊天页与持久化接口 | 未验证真实聊天输出；未做词级陪读入口 |
| P4 | 录音上传、job/attempt 异步状态与错误、轮询、差异计算、麦克风用途说明；成功/失败契约有测试 | 未验证真实 ASR 评分与真机录音链路 |
| P5 | 真实 ffmpeg 生成 6 秒 HLS；观看/纯音频跟读两套清单；OSS 目录上传与 MIME；逐片持久化、缺片续传、连续前缀部分播放、下载进度及继续入口；完整视频状态机 | 未验证真实 OSS/ASR/翻译和真机蜂窝/断网播放；视频链接摄入尚未完成 |
| P6 | 照片提交契约、vision → tts → asr 本地状态机、iOS 拍照入口 | 未验证 Qwen-VL；语音老师仍是配置状态/界面占位，尚无 Qwen-Omni 实时对话 |

因此，本文件只证明上述代码骨架、数据契约和测试结果；**不声明 P3、P5、P6 功能阶段已完成，也不声明任何云链路已通过。**

## 自检声明

```text
- 未调用百炼、OSS、DeepSeek：是
- 未伪造 ready 音频、字幕、评分或聊天输出：是
- 云端实调：有意延期，按 PROJECT.md §2.5、§6.3、§7.2 的闸 B 执行
```
