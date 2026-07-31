# P5 闸 A：OSS 生命周期安全边界实际输出

日期：2026-07-31

## 本地规则输出

`ObjectStorage.configure_lifecycle()` 在 SDK 边界测试中返回：

```text
[
  {"id": "harvest-temporary-asr", "prefix": "temporary/", "days": 1},
  {"id": "harvest-shadowing-recordings", "prefix": "shadowing/", "days": 7}
]
```

测试 Bucket 原先已有一条非 Harvest 规则：

```text
owner-archive-rule  archive/  90 days
```

合并后规则 ID 顺序为：

```text
owner-archive-rule
harvest-temporary-asr
harvest-shadowing-recordings
```

测试还明确断言 Harvest 两条规则均不使用 `materials/` 前缀。正式朗读音频和 HLS 位于 `materials/`，不会被这两条生命周期规则命中。

## 设置页实际文案

```text
OSS 自动清理
先保存上面的 OSS 配置，再应用规则。只匹配 temporary/ 和 shadowing/；materials/ 下的朗读和 HLS 不会自动删除。
应用 OSS 生命周期规则
```

保留天数在 `.env.example` 中的实际默认值：

```text
OSS_TEMPORARY_RETENTION_DAYS=1
OSS_SHADOWING_RETENTION_DAYS=7
```

## 自动化测试原文

```text
All checks passed!
.................ss.............                                         [100%]
30 passed, 2 skipped in 1.34s
```

PostgreSQL 集成测试：

```text
..                                                                       [100%]
2 passed, 30 deselected in 0.46s
```

## 闸 B 未验证

- 尚未配置真实 OSS Endpoint、Bucket 与 Access Key，未向阿里云发送生命周期请求
- 尚未读取真实 Bucket 的现有规则，也未取得真实 `put_bucket_lifecycle` HTTP 结果
- 开通 OSS 后须从后端设置页显式应用，再贴出真实规则列表，证明保留其他规则且 `materials/` 没有过期策略

因此本文件只证明本地规则结构、合并行为、前缀隔离和设置页契约，不把云端生命周期配置记为通过。
