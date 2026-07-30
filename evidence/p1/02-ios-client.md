# P1 闸 A：iOS 客户端实际界面

验证方式：Harvest Debug build 安装并启动于 iPhone 17 Pro Simulator（iOS 26.5）；本机 Tailscale HTTPS endpoint 保存于**模拟器钥匙串**后加载材料列表。

## 首次连接页显示文字

```text
HARVEST
先把你和
材料连起来。
输入 Mac 上 Harvest 服务的 Tailscale HTTPS 地址。这个地址只保存在这台 iPhone 的钥匙串中。
服务地址
连接材料库
```

## 材料列表页显示文字

```text
材料
还没有材料
在 Mac 的摄入页面粘贴一段日语，朗读会在后台准备。
```

列表成功连接本机 API；因为本次只验证无密钥失败路径，列表中没有 `ready` 材料。阅读页的播放/暂停、当前句高亮与点句跳转实现已包含在 P1 客户端代码中，但它们需要闸 B 产生真实音频后才可做端到端播放验收，故本文件不将它们误记为已实测播放成功。
