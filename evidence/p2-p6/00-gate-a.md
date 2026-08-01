# P2–P6 闸 A：本地代码、状态机与构建证据

日期：2026-08-01

仓库：[GHH158/harvest-platform](https://github.com/GHH158/harvest-platform)，本文件与本阶段代码位于同一提交。

## 环境

```text
Python 3.12.13
Xcode 26.6
Build version 17F113
iOS Deployment Target 18.0
iPhone 17 Pro Simulator / iOS 26.5
PostgreSQL 17
```

## 实际输出

### 静态检查与完整 Python 回归

```text
All checks passed!
..................................................                       [100%]
50 passed in 1.55s
```

这次完整回归显式提供了 `HARVEST_TEST_DATABASE_URL`，3 个 PostgreSQL 集成测试没有跳过。数据库集成测试单独执行的输出为：

```text
...                                                                      [100%]
3 passed, 44 deselected in 0.49s
```

### iOS 实际测试

```text
Test suite 'HarvestTests' started on 'Clone 1 of iPhone 17 Pro - Harvest'
Test case 'HarvestTests/hlsPlaylistResolvesSegmentsAndDurations()' passed
Test case 'HarvestTests/voiceTeacherUsesWebSocketThroughTheMacEndpoint()' passed
Test case 'HarvestTests/shadowingAttemptDecodesAsyncStatus()' passed
Test case 'HarvestTests/materialDecodesSentenceTimeline()' passed
Test case 'HarvestTests/photoSubmissionDecodesMaterialContract()' passed
Test case 'HarvestTests/offlineEntryOnlyExposesContiguousDownloadedPrefix()' passed
Test case 'HarvestTests/segmentedPlayerAppendsNewlyDownloadedParts()' passed
Test case 'HarvestTests/segmentedDownloadResumesWithoutRefetchingStoredParts()' passed
```

`xcodebuild test` 退出码为 0；App 与 `HarvestTests` 均实际构建，上述 8 项测试均由模拟器执行。构建中只有 Xcode 的 AppIntents 元数据提示，没有 Swift 代码告警。

### 无密钥 API

`GET /health`：

```json
{"status":"ok"}
```

`GET /voice-teacher/status`：

```json
{"configured":false,"model":"qwen3.5-omni-flash-realtime"}
```

这里的 `configured:false` 是预期结果：本机没有百炼 Key，也没有填写工作空间 WebSocket 地址。

`POST /videos/link` 的真实响应：

```json
{"material_id":22,"job_id":36,"status":"pending"}
```

对应 PostgreSQL 查询原文：

```text
 id |        title        | source_type | status
----+---------------------+-------------+---------
 22 | 闸A视频链接契约验收 | url         | pending
(1 row)

 id | material_id |      kind      | status  | attempts
----+-------------+----------------+---------+----------
 36 |          22 | download_video | pending |        0
(1 row)
```

验收时没有启动 worker，所以这条链接没有被下载或产生云调用；核对后已删除该测试 job 与 material。

### PostgreSQL schema

```text
     tablename
-------------------
 chat_message
 companion_message
 job
 material
 media_asset
 segment
 shadowing_attempt
 token
 voice_profile
(9 rows)
```

```text
 column_name |        data_type         | is_nullable
-------------+--------------------------+-------------
 id          | bigint                   | NO
 name        | text                     | NO
 provider    | text                     | NO
 voice_id    | text                     | NO
 is_default  | boolean                  | NO
 created_at  | timestamp with time zone | NO
(6 rows)
```

### 网页实际可见文字

摄入页：

```text
粘贴日语文本
网页链接
本地视频
视频链接
```

设置页：

```text
服务设置
聊天模型路由
自动：Qwen 失败后切 DeepSeek
语音聊天 WebSocket 地址
日语声音复刻
上传本人或已获授权的 3–30 秒日语录音。
清除现有百炼 Key
清除现有 DeepSeek Key
```

## 阶段范围对照

| 阶段 | 闸 A 已完成并有本地测试的部分 | 必须留到闸 B 的部分 |
|---|---|---|
| P2 | ASR 异步封装、词/字级时间轴对齐与低覆盖率降级；逐单位高亮；阅读音频离线入口；HLS 分片时长持久化、连续前缀部分播放与缺片续传 | 真实 Fun-ASR 返回结构与对齐精度；真机断网、锁屏和蜂窝网络播放 |
| P3 | Qwen 优先、DeepSeek 备用及手动路由；错误自动降级；陪读携带材料上下文和最近历史；阅读页有句子与字词入口；独立聊天历史持久化 | Qwen/DeepSeek 的真实回答、额度切换和输出质量 |
| P4 | 录音流式上传；attempt 与 job 原子创建；状态/错误/轮询契约；逐单位 diff 与评分；麦克风权限说明 | 真机录音格式；OSS 上传；Fun-ASR 评分结果 |
| P5 | 本地视频和视频链接摄入；`download_video → transcode → upload_video → asr_video → translate_video` 状态机；真实 ffmpeg 生成两套 6 秒 HLS；字幕随播放高亮、自动滚动和点句跳转；分片离线续传；OSS 生命周期规则合并逻辑 | 真实外部站点下载；OSS 上传/公网 HLS；真实视频 ASR/翻译；真机部分下载播放；控制台生命周期规则截图或 JSON |
| P6 | 相机与照片选择入口；照片流式上传和 `vision → tts → asr` 状态机；iPhone 16 kHz PCM → Mac WebSocket → 百炼中继 → 24 kHz PCM/双方转录协议；iOS 不持有云 Key | 真机相机；Qwen-VL 识别；Qwen-Omni 实时握手、打断、转录与音频播放 |

## 本轮针对 Review 的实装结果

```text
ASR 增强失败不再降低 material.ready：已实现并测试
视频流水线缺失分支：已补齐并测试完整状态机
离线材料无法打开：下载列表已有消费入口；阅读优先使用本地音频
跟读只查询一次：iOS 轮询 attempt；失败状态和错误可见
跟读提交非原子：上传成功后才在同一事务创建 attempt + job
拍照返回契约不一致：统一使用 MaterialSubmission
控制面暴露局域网：API 只绑定 127.0.0.1，由 Tailscale Serve 暴露
每次请求创建 Engine：FastAPI lifespan 只创建一个 Engine/Repository
整视频进内存：视频、照片、跟读和声音样本均流式落盘并限制大小
```

## 偏离说明与未验证声明

- 本轮按 `PROJECT.md` §6.3 只完成 P2–P6 **闸 A**；没有把这些阶段声明为云链路完成。
- 没有注册、调用或消耗百炼、DeepSeek、OSS；没有伪造 `ready` 音频、字幕、评分、视觉识别或聊天回答。
- 视频链接只验证了 yt-dlp 的本地封装、参数和状态机 mock，没有下载真实外部平台内容。
- Qwen-Omni 的事件名、PCM 规格和工作空间 URL 已按官方协议实现，但没有 Key 时无法证明云端握手、真机音频路由和模型行为。
- 声音复刻在上传层限制大小，在 worker 调云前真实读取媒体时长并强制 3–30 秒；未用伪造录音调用百炼。
- OSS 当前按 `PROJECT.md` 使用稳定公开媒体 URL；私有 Bucket、签名 URL 与 CDN 不在当前设计范围。

## 闸 B 开始前只需完成的注册与配置

1. 注册百炼并打开“免费额度用完即停”。
2. 在 Mac 设置页填写百炼 Key、北京工作空间 HTTP/Realtime WebSocket 地址，并上传本人或已授权的日语声音样本。
3. 创建 OSS Bucket，填写 Endpoint、Bucket、Access Key 和公网前缀，再显式应用两条生命周期规则。
4. 先按 `PROJECT.md` §2.5 的顺序验证 TTS → ASR 回读，再依次验证 P3、P4、P5、P6；每一步另交闸 B 的真实 JSON、SQL 和真机可播证据。
5. 百炼免费文本额度耗尽后，再在设置页填写 DeepSeek Key；在此之前保持 `LLM_PROVIDER=auto` 即可。
