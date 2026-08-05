# App「问 AI」提示词归档

> **来源**：Grok 会话中从早期 `backend/app/services/chat_service.py` 抽出并归档的版本。  
> **背景**：你曾反馈手机 App「问 AI」提示词「特别不错」，并要求单独落盘保存。  
> **说明**：这是历史设计资产，不等于当前 `harvest-platform` 运行时的 companion / chat 提示词。其核心教学原则已于 2026-08-04 提炼进入 `docs/PROJECT.md` §5.8；当前正式实现仍以 `docs/PROJECT.md` 与代码为准。

## 入口对照（旧版产品）

| 入口 | 提示词文件 | 说明 |
|------|------------|------|
| iOS **问 AI** Tab（全局对话） | [02-global-full.md](./02-global-full.md) | 日常随时提问 |
| 学习会话内陪练 | [03-session-full.md](./03-session-full.md) | 带本课句子上下文 |
| 共用基础人设 | [01-global-base.md](./01-global-base.md) | 全局 / 会话共用前半段 |
| 句子分析（非聊天） | [04-analysis-system.md](./04-analysis-system.md) | Transformer 式关系分析 |

## 运行时约定（旧版）

- 发送给模型：`system` + 最近约 12 条 `user` / `assistant` 消息
- LLM 经本机 Cockpit（OpenAI 兼容）
- 会话陪练会动态注入本课最多约 8 句目标句

## 文件列表

| 文件 | 用途 |
|------|------|
| `01-global-base.md` | 基础人设 |
| `02-global-full.md` | 「问 AI」Tab 完整 system |
| `03-session-full.md` | 本课陪练完整 system 模板 |
| `04-analysis-system.md` | 句子分析 system（顺带归档） |
