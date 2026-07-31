# P5 闸 A：HLS 分片、续传与部分播放实际输出

日期：2026-07-31

## 真实 ffmpeg 输出

输入为本地生成的 7 秒 H.264/AAC 测试视频，调用项目的 `VideoProcessor.create_hls`。测试原文：

```text
.                                                                        [100%]
1 passed in 0.87s
```

实际产生文件：

```text
audio/index.m3u8
audio/segment-00000.ts
audio/segment-00001.ts
video/index.m3u8
video/segment-00000.ts
video/segment-00001.ts
```

观看清单原文：

```text
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-INDEPENDENT-SEGMENTS
#EXTINF:6.000000,
segment-00000.ts
#EXTINF:1.000000,
segment-00001.ts
#EXT-X-ENDLIST
```

纯音频清单原文：

```text
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:6.013967,
segment-00000.ts
#EXTINF:1.021778,
segment-00001.ts
#EXT-X-ENDLIST
```

实际文件大小：

```text
audio/index.m3u8            183 B
audio/segment-00000.ts       74 KB
audio/segment-00001.ts       12 KB
video/index.m3u8            211 B
video/segment-00000.ts      785 KB
video/segment-00001.ts      200 KB
```

## iOS 续传与部分播放

`HarvestTests` 使用拦截的真实 `URLSession` 请求分别验证两种模式。观看模式首次只请求视频清单和两个视频分片，不请求跟读音频；再次下载同一模式时只刷新视频清单，两个已落盘分片不再请求。切到跟读模式后才请求音频清单和两个音频分片。

```text
Test case 'HarvestTests/hlsPlaylistResolvesSegmentsAndDurations()' passed
Test case 'HarvestTests/segmentedPlayerAppendsNewlyDownloadedParts()' passed
Test case 'HarvestTests/offlineEntryOnlyExposesContiguousDownloadedPrefix()' passed
Test case 'HarvestTests/segmentedDownloadResumesWithoutRefetchingStoredParts()' passed
```

界面新增文字原样：

```text
视频分片 N/M，已有部分可以观看
跟读音频分片 N/M，已有部分可以播放
继续下载缺失分片
只下载跟读音频到本机
已下载的连续分片可以观看；播放到尚未下载的位置会停止。
跟读模式只读取纯音频 HLS，不重复消耗视频流量。
```

## 闸 B 未验证

- 尚未配置 OSS，未验证真实 Bucket 的 `.m3u8` / `.ts` 公网播放与 Range/CDN 行为
- 尚未用真机验证下载过程中切换飞行模式、杀进程后恢复、蜂窝网络禁用行为
- 尚未调用真实 ASR 与字幕翻译服务

因此本文件只证明本地 HLS 产物、下载契约、续传请求行为和 iOS 构建测试，不把云端或真机链路记为通过。
