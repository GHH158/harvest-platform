# P1 闸 A：自检清单

基准：`docs/PROJECT.md` §6.2、§7.2 与 `docs/reviews/P1-acceptance-report.md` §11。

| 项目 | 结果 | 证据 / 说明 |
|---|---|---|
| PostgreSQL §4.2 全表与本地访问 | 完成 | integration 测试通过；见 `00-env.md` |
| FastAPI 骨架与私有控制面访问 | 完成 | 健康检查及 iOS 列表已实际访问本机 API |
| Job 表与 worker | 完成 | 创建 pending job、worker claim 后 failed 的真实 JSON；见 `01-local-api-and-db.md` |
| 网页摄入（粘贴 / URL 输入） | 完成 | `POST /materials` 真实 202 输出；网页界面已本地验证 |
| 无密钥时的明确失败 | 完成 | worker 原文与 material/job JSON；见 `01-local-api-and-db.md` |
| 简单分句 / 估算句级时间轴 | 完成（代码与测试） | 云音频未生成，真实 segment 时间轴归闸 B |
| iOS 列表 / 连接页 | 完成 | 实际界面文字；见 `02-ios-client.md` |
| iOS 阅读播放 / 句级高亮 / 点句跳转 | 实现完成，云端到端实测延期 | 需要闸 B 的真实音频，不能提前宣称已播放成功 |
| P1-01 至 P1-05 | 代码侧关闭 | 依据验收报告 §10.2：超时 running 回收、幂等媒体写入、URL 标题回写、trafilatura 抽取、iOS 状态刷新 |
| P2+ 范围 | 未引入 | 未做词级高亮、离线下载、AI、视频 |

## 自检声明

```text
P1 自检：
- 未引入 P2+ 范围：是
- 真实 TTS + OSS 已跑通：否（按 PROJECT.md §2.5 / §7.2 有意延期至闸 B）
- 本地闸 A 证据路径：evidence/p1/
- 申请闸 A 复核日期：2026-07-30
```
