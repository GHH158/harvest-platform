# P1 闸 A：环境与交付元信息

验收日期：2026-07-30

## 仓库与提交

- GitHub：`https://github.com/GHH158/harvest-platform`
- 本次 P1 实现提交：
  - `7460c96 Initialize Harvest P1 foundation`
  - `24fb688 Support local PostgreSQL 17 runtime`
  - `74ced0f Show ingest job progress`
  - `17d00dd Harden P1 processing workflow`

## 本地环境实际输出

```text
Python 3.12.13
Xcode 26.6
Build version 17F113
```

- iOS 部署目标：`18.0`（Debug、Release、测试 target 均为 18.0）。
- 数据库：本机 PostgreSQL 17；仅用作本地 P1 验证。
- iOS 验证设备：iPhone 17 Pro Simulator，iOS 26.5。
- API 验证地址：`http://127.0.0.1:8000`；iOS 验证经私有 Tailscale HTTPS 地址访问控制面。

## 实际检查输出

```text
All checks passed!
s.......                                                                 [100%]
7 passed, 1 skipped in 0.57s
```

```text
.                                                                        [100%]
1 passed, 7 deselected in 0.43s
```

第二段为使用本地 PostgreSQL 的 integration 标记测试。iOS Simulator Debug build 已实际构建成功。
