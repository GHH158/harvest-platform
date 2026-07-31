# P2–P6 闸 A：本地代码与构建证据

日期：2026-07-31

## 实际输出

```text
All checks passed!
....s..........                                                          [100%]
14 passed, 1 skipped in 0.64s
```

```text
** BUILD SUCCEEDED **
```

构建目标为 iPhone 17 Pro Simulator（iOS 26.5）；iOS 部署目标仍为 18.0。

## 范围对照

| 阶段 | 本地闸 A 交付 | 云端闸 B 状态 |
|---|---|---|
| P2 | ASR 任务封装、词级时间戳解析/对齐、逐词高亮、离线材料存储 | 未配置百炼；未验证真实 ASR/OSS |
| P3 | 百炼 Qwen 优先/DeepSeek 备用的聊天封装、陪读/聊天持久化、iOS 聊天页 | 未验证真实聊天输出 |
| P4 | 本地录音上传、后台评分任务、差异计算、iOS 跟读页 | 未验证真实 ASR 评分 |
| P5 | 项目内 ffmpeg/yt-dlp 依赖、视频摄入/转码任务、iOS 视频页面 | 未验证真实视频下载、OSS、字幕和翻译 |
| P6 | 照片摄入/视觉任务、语音老师配置状态、iOS 拍照与语音入口 | 未验证 Qwen-VL / Qwen Omni |

## 自检声明

```text
- 未调用百炼、OSS、DeepSeek：是
- 未伪造 ready 音频、字幕、评分或聊天输出：是
- 云端实调：有意延期，按 PROJECT.md §2.5、§6.3、§7.2 的闸 B 执行
```
