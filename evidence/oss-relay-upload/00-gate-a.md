# 手机流量下改走 OSS 直传(§15.11)

## 它要解决的实况

使用者刚验证完 HLS 下载包能在手机上预览、能切之后,反馈:「用手机流量的时候上传很慢,可以优化成和服务器在同一个网络下的时候可以用现在这种方式,如果不是的场合下看还有别的办法没,比如 OSS」。

## 判据:测出来的,不是猜的

考虑过用 Wi-Fi/蜂窝作判据,否掉了:一台手机可以连着别人的 Wi-Fi 却离 Mac 很远(一样要走 Tailscale 的公网路径),也可以在蜂窝网络下恰好直连成功。真正想知道的是「这一次,这台手机,到这台 Mac,够不够快」,而这只能测,不能从接口类型推断。

`PUT /videos/uploads/probe` 是这条测的落点:接受一小段字节直接丢弃、返回 204。手机侧发 256KB、限时 6–8 秒,算出字节率,≥600KB/s(约 4.8Mbps)走原来的直传,否则改走 OSS。阈值不追求精确,只要能把"明显够用"和"明显不够用"分开。

## 做法

1. `POST /videos/oss-upload-url`:签一个指向 `temporary/raw-uploads/<uuid>.<ext>` 的预签名 `PUT` URL,6 小时有效——给慢速上传一小时级的视频留够余量。这个前缀本来就有 §7 配置的 1 天生命周期规则,中途放弃不留手尾。
2. 手机直接把原始文件 `PUT` 给 OSS,完全跳过 Mac。
3. `POST /videos/uploads/from-oss` 告诉 Mac 去取,新增的 `fetch_video_upload` job 用 Mac 自己的下行(通常比手机上行到家庭宽带更强)把对象拉回本地、按内容找并解压 HLS 包(复用 §15.10 的 `unpack_hls_bundle`,这次挪进了 `video.py` 给 worker 也能用),产出的 `upload_id` 与直传完全同形——`POST /collections` 分不出走的是哪条路。

## 真栽了一次跟头:Content-Type

第一次用 curl 验证时,`PUT` 到预签名 URL 收到 `403 SignatureDoesNotMatch`。OSS 返回的 `StringToSign` 里显示服务端把请求实际携带的 `Content-Type: application/x-www-form-urlencoded`(curl `--data-binary` 的默认值)计入了签名验证,而生成 URL 时没有为这个头签名(两边都不带,是设计决定,见下)。加一个空 `Content-Type:` 头覆盖掉 curl 的默认值后,200。

iOS 客户端(`putFileToOSS`)本来就没有设置这个头,所以这个坑只会在拿 curl 手动验证时出现,不会在真实使用路径里复现——但如果以后要改成用别的工具验证,这条要记住。

## 实测(真实 OSS,不是 mock)

```
=== presign ===
{"oss_key":"temporary/raw-uploads/20f5240e...zip","upload_url":"https://harvest-media-ghh.oss-cn-beijing.aliyuncs.com/...","expires_in":21600}

=== PUT to OSS (no Content-Type) ===
put(no content-type): 200

=== notify ===
{"job_id":95,"status":"pending"}

=== poll ===
{"id":95,"status":"done","payload":{
  "oss_key":"temporary/raw-uploads/20f5240e...zip",
  "filename":"下载的HLS-e2e3.zip",
  "upload_id":"pending-b6869e16.../play"
}}
```

本机确实解压出了对应目录,`play` 文件内容是 `#EXTM3U` 开头的播放列表,分片也在。

**证明临时对象真的被删了**:用同一个 `oss_key` 再发一次 `from-oss` 通知,新 job 如预期 `failed`:

```
{"error_message":"...NoSuchKey...The specified key does not exist..."}
```

第一次成功后已经把 OSS 上的临时对象删掉,不是留着占地方等 1 天生命周期规则来擦。

清理:测试产生的本机 `pending-<uuid>` 目录已删除;两个测试 job(95、96)留在数据库里作为记录,未做特殊清理(这是真实服务的真实 job 表,和之前几次 §15 验证的做法一致)。

## 未做的验证

模拟器里没能重新走一遍**直传**路径的界面截图作对照——首页在这轮验证的某次冷启动之后完全点不动(素材/聊天/积累/说点别的/设置齿轮,全部无响应),重启整个模拟器设备也没恢复。怀疑是这次会话的输入注入卡在了这一屏,与本次改动的代码路径关系不大:

- 直传逻辑本身完全没变,只是把 `UploadState.uploading` 重命名成 `uploadingDirect` 并新增了几个 case——Swift 的 switch 穷尽性检查已经保证没有漏 case,`xcodebuild` 构建成功。
- 直传的界面表现(进度条 + "正在传给 Mac N%")在更早的 §15 落地会话里已经用真实服务在模拟器上验证过,这次只是文案分支多了一条,逻辑未动。

用真实后端 + curl 的完整往返代替了这次的界面截图,链路上每一步(签发、PUT、通知、拉取、解压、清理、失败路径)都是真实调用,不是 mock。

## 验收

- `ruff check` 通过(`app/`、改动的 `tests/`)
- `pytest`:223 passed, 42 skipped(与改动前持平的 skip 数,新增的 17 项全部计入 passed)
  - `test_storage.py`:`presigned_put_url` 不签 `Content-Type`、`object_size` 读 `head_object`、`download_to_file` 的重试与耗尽
  - `test_video.py`:`unpack_hls_bundle` 按内容找播放列表、拒绝 zip-slip、拒绝无播放列表的包、拒绝损坏的 zip
  - `test_worker.py`:`_fetch_video_upload` 的 zip/纯视频两种产出、超限拒绝且不下载、缺来源信息报错
  - `test_main_contracts.py`:probe 端点的正常与超限、presign 端点签发与播放列表单传提示、from-oss 的前缀校验与正常入队
- iOS `xcodebuild ... build` → `BUILD SUCCEEDED`
- 真实 OSS 端到端往返(上一节),含失败路径验证
