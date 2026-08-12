# Harvest — 日语沉浸学习 App 主文档

> **项目名:Harvest。**

> **本文件是本项目唯一的设计文档,只保留技术参考。** 架构决策、数据模型、工程约定与视觉原则在这里;
> 产品定位、流水线细节、开发计划与变更叙事已于 2026-08-12 删除,见 §0。

---

## 0. 这份文档只留技术参考(2026-08-12)

**本文档只维护「从代码里推不回来」的东西**:视觉与交互原则(§1.5)、技术选型(§2)、架构(§3)、数据模型(§4)、工程约定(§7)。改完代码不再写叙事章节,也不再写变更记录——那些信息 `git log` 里已经有了,重复维护一份只是拖慢开发。

**章节编号沿用历史编号,没有重排**(代码注释里有大量 `§4.1`、`§7.5` 这类引用,重排会让它们集体失效)。因此编号有缺口是正常的。**指向已删章节的引用**(如 §5.x、§15.x)意味着那段原文在 git 历史里:`git log -p -- docs/PROJECT.md`,或 `git show 69890f8:docs/PROJECT.md`。

**要改这份文档时只做局部替换,不整篇重写。**

## 1. 产品定位

只保留 §1.5。产品定位、要解决的问题、功能全景与「明确不做的事」(原 §1.1–§1.4)都已删除——那些是当初说服自己开工的材料,现在 App 已经在用了,不再需要一份文字版。

### 1.5 视觉与交互风格

**目标:接近 Claude.ai 那种克制、温暖、以内容为中心的设计感**,不是常见的"科技感深色 + 高饱和强调色"移动应用样式。翻译成具体、可执行的判断:

**色彩**
- 底色用**暖白/米色**(如 `#FAF9F5` 一类),不用纯白 `#FFFFFF`——纯白配合大段日文文字阅读久了刺眼
- 正文文字用**暖灰**(深棕灰,如 `#3D3929`),不用纯黑——纯黑对比度过硬,长时间阅读疲劳
- 强调色用**一个克制的陶土色/暖橙色**作为品牌色,大面积场景中只用作点缀(按钮、当前高亮词、进度指示),不做大色块背景
- 深色模式对称设计:暖黑(不是纯黑)+ 暖白文字,同样避免死板的纯黑纯白对比

**排版**
- 界面主体用 iOS 系统字体(SF Pro / 苹方),保证输入法和系统组件观感一致
- 标题类文字可以引入一个**衬线字体**(如系统自带的 New York)做出版物感,和正文的无衬线体形成对比——这是"内容感"而非"工具感"的关键差异之一
- 日语正文字号要比中文习惯的偏大一档,行距放宽——这是阅读类 App 的常见问题,字挤在一起会显著增加阅读疲劳

**布局与交互**
- **大量留白**,不要把功能按钮堆满一屏。阅读页尤其要克制:核心是文字和音频,其余功能(陪读入口、跟读按钮)收进次要位置,只在需要时出现
- 卡片和容器用**柔和圆角 + 极淡的阴影**,不用生硬直角或强投影
- 逐词高亮的动效要**柔和渐变**(淡入淡出的背景色块),不要生硬的色块跳变
- 减少界面"装饰性元素"(图标堆砌、渐变背景、强分割线),让文字和朗读内容本身是唯一的主角
- 遵守「结构自显」:不再新增仅为强调而存在的左侧竖线、彩色边框或标签条;优先用排版、留白、底色与位置表达层级。**遗留的 Markdown 标题强调条已于 2026-08-09 的 UI 复核中清除**(连同引用块的竖线),该条待办关闭。
- **长文不套卡片。**教学回答动辄几百字,外面再包一层卡片会从两侧各吃掉一次内边距,而卡片本身不提供任何结构信息——结构已经由标题、列表和留白表达了。短的东西(使用者的提问、纠错卡)可以是卡片,长的正文就是页面本身。
- **不在卡片里再套卡片。**一次嵌套要付两次内边距,中文正文因此会缩短到每行十三四个字,长解释被迫反复折行。判据很直接:**如果去掉这个框,信息还读得懂吗?** 读得懂就去掉。
- **中日文正文的行距要比拉丁文大。**中日文没有词间空格、字面墨量高,同样字号下需要更多行距才不会读成一堵墙;当前正文取 `lineSpacing` 7–8,日语例句 8。
- **最该读的内容不能用最小最淡的字。**说明性文字(如纠错理由)是使用者真正要看的部分,应当是正文级别;分类标签这类元信息才用小字。
- **表格按列数选形态。**三列以内在手机上仍是真正的表格;**四列以上转成每行一张卡片**(首列作标题,其余按「表头:内容」竖排)。实测四列时每列只剩约 85pt,中日文每三四个字就折行,「ときどきジョギングをする」被拆成四段。横向滚动不是解法——它恰好藏起你正在对照的那一列。
- 状态切换要有时间连续性:列表展开、内容替换、加载完成和错误恢复至少保持淡入淡出或位置连续;动效用于解释状态从哪里来、到哪里去,不用作无意义装饰

**基调**
**2026-08-10 两条修订(均来自使用者实际用过之后的反馈):**

**① 「可爱」进入口味轴,但兴奋语气仍然出局。** 使用者明确要求文案「可爱一些」。这与本节反对的东西不冲突——反对的是「太棒了!」「连续打卡 N 天!」这类**营销号式的兴奋与游戏化**,不是亲切。可爱的实现方式限定为:**口语化的说法、留白与衬线排版**;**不用 emoji、不用装饰符号、不加吉祥物**(§14.7 同源,理由也一样:标语和吉祥物会变成演戏)。落地例子见 §5.15 的四个角度文案与首页文案。

**② 本节要求的「时间连续性」此前一处都没实现,现已补在首页。** 原文写着「状态切换要有时间连续性…动效用于解释状态从哪里来、到哪里去,不用作无意义装饰」,而首页在此之前**一个动效都没有**:计数异步到达就硬弹出来。现在是错开淡入 + 轻微上移(280–340ms、ease-out、间隔 50ms、**不弹跳不缩放**),计数与「上次到哪儿了」到达时淡入,按下用轻微透明度变化而不是 iOS 默认的整块变灰——在一屏纯文字上,整块变灰读起来像文字坏了而不像按下。

**③ 一屏之内不要出现三种以上视觉形式。** 首页曾长出四种:描边大卡片、带底色块的入口行、两行裸文字。**最糟的是那两行裸文字长得一模一样,却一个是「继续学习」、另一个是与日语无关的私人入口(§14)**——两次都选了「最低调的形式」,结果撞在一起。判据:**同形必须同义;不同义就必须不同形**(现在用分隔线、右对齐、无 chevron 把 §14 的入口明确分出去)。

- 文案(按钮文字、空状态提示、错误提示)保持**平实、克制、略带人情味**,不要用"太棒了!""连续打卡 N 天!"这类营销号式的兴奋语气——这和 §7.1 记录的"不做游戏化"是同一种品味取向
- 空状态、加载中这些容易被忽略的角落也要花心思,不要用系统默认的转圈图标应付了事

**实施约定**

- iOS 端建立一个统一的 `DesignTokens`(颜色、字号、间距、圆角的命名常量),所有页面从这里取值,不允许硬编码颜色/字号——这样以后调整整体观感只需要改一处
- P1 阶段就要按这套风格做,不要"先随便搭个能用的界面,以后再美化"——界面基调一旦定型,后面每加一个页面都会不自觉沿用老风格,返工成本高



## 2. 技术选型

### 2.1 选型总表

| 环节 | 选型 | 供应商 | 说明 |
|---|---|---|---|
| 文字转语音 | **Qwen-Audio-3.0-TTS-Plus** | 阿里云百炼 | 主力,生成朗读音频 |
| 实时语音(后期) | Qwen-Audio-3.0-TTS-Flash | 阿里云百炼 | 约 300ms 首包延迟,语音对话时用 |
| 音色克隆 | 声音复刻(voice-enrollment) | 阿里云百炼 | 一次性,近乎免费 |
| 视频人声分离 | Demucs `htdemucs` | 本地 | 从带背景音乐的视频提取人声后再做声音复刻 |
| 语音转文字 | **Fun-ASR / Paraformer** | 阿里云百炼 | **支持词语级时间戳**,全局关键 |
| 大语言模型 | **Qwen3.7-Max 主力，DeepSeek 备用** | 阿里云百炼 / DeepSeek | 所有文本问答统一先用 Max；额度耗尽或调用失败后切换备用模型 |
| 视觉理解(后期) | Qwen-VL | 阿里云百炼 | 拍照读日语 |
| 语音对话(后期) | Qwen-Omni | 阿里云百炼 | 语音聊天老师 |
| 对象存储 | **OSS** | 阿里云 | 双重角色,见 §3.3 |
| 音视频处理 | ffmpeg | 本地 | 免费 |
| 视频下载 | yt-dlp | 本地 | 免费 |
| 网页正文抓取 | readability 类库 | 本地 | 免费 |

### 2.2 为什么 TTS 选 Qwen-Audio-3.0-TTS-Plus

- **价格与 CosyVoice 基本持平**($27.6/百万字符 ≈ 2 元/万字符)
- **质量领先一档**:2026 年 7 月在 Artificial Analysis TTS 竞技场排名第一(Elo 1237),领先 Gemini 3.1 Flash TTS、MiniMax Speech 2.8 HD、ElevenLabs Eleven v3;后两者定价约为其 3.6 倍
- **日语是被点名优化的语种**
- **抗噪克隆**:普通录音环境采集的参考音频即可复刻

**已知缺点:慢。** 约 16 字符/秒,一篇 2000 字文章约需 2 分钟。

**但对本项目不构成问题** —— 生成朗读是"每篇做一次、之后反复听"的后台任务,不是实时交互。**必须设计成后台任务 + 进度提示,不能让用户干等。**

**风险**:该模型 2026 年 7 月 20 日发布,较新,可能有配额/稳定性问题。缓解:CosyVoice 在同一平台,切换只需改 model 参数。

### 2.3 ASR 是全局关键

Fun-ASR / Paraformer 提供**句子级 + 词语级时间戳**,并有 `timestamp_alignment_enabled` 校准参数让识别结果与播放同步。支持日语,兼容 aac/wav/mp3 等格式,单文件上限 12 小时 / 2GB。

这一条同时解决两个问题:

1. **视频字幕** —— ASR 输出天然是「文字 + 时间轴」,即字幕
2. **阅读逐词高亮** —— TTS 生成的音频**不带时间戳**,把它再喂给 ASR,就能反推出每个词的时间点

第 2 点是本方案的核心技巧:**用 ASR 给 TTS 补时间戳**,在同一家服务内闭环,不需要引入日语强制对齐(forced alignment)这类不成熟的组件。

⚠️ 注意:SenseVoice 即将下线,不要使用。

### 2.4 成本

| 项目 | 单价 |
|---|---|
| TTS | 北京原价 **1.4 元/万字符**(2000 字文章 ≈ **0.28 元**) |
| 音色克隆 | 0.01 元/个,一次性 |
| ASR | Fun-ASR 北京原价 **0.00022 元/秒**(约 0.792 元/小时) |
| LLM(Qwen3.7-Max) | 北京标准价输入 **12 元/百万 Token**、输出 **36 元/百万 Token**;先使用独立 100 万 Token 免费额度,促销折扣以控制台为准 |
| LLM(DeepSeek) | Max 额度耗尽或失败后的备用;以届时所选模型价格为准 |
| OSS 存储 | 0.09–0.12 元/GB/月 |
| OSS 公网流出 | 闲时 0.25 元/GB,忙时 0.5 元/GB(上传免费) |

**粗略月度估算**:在 Max 免费额度仍有效时,典型个人用量预计 **10–20 元/月**;免费额度用完后的文字问答按每次 2,000 输入 + 400 输出估算约 **0.0384 元/次**,每天 50 次约 57.6 元/月(未计临时促销),再叠加 TTS / ASR / OSS。实际以控制台账单为准。

### 2.5 免费额度策略

**⚠️ 不要现在注册。** 免费额度从开通起 90 天计时,**用不用都不暂停**,过期作废,且**同一实名主体重新注册无法再次领取**。

**等到能开始实际调 API 的那一周再注册。**

**"7000 万 tokens"是误导性数字**:每个模型独立 100 万 tokens,不能合并转移;带日期的快照版本算独立模型。单模型重度使用实际只有 100 万(聊天约 2000 轮)。

**免费额度的正确用途是选型和验证,不是省下生产开销。**

| 服务 | 免费额度 | 有效期 |
|---|---|---|
| 百炼模型推理 | 每模型 100 万 tokens,总计 7000 万+ | 90 天 |
| 知识库(RAG) | 一次性 720 小时 | **仅 30 天**,多库翻倍扣减 |
| OSS 存储 | 20 GB | 3 个月 |
| OSS 外网流出 | 北京地域 2 GB | 3 个月 |
| OSS 请求 | 20 万次 | 3 个月 |

**开通后第一件事:打开「免费额度用完即停」开关**(仅限北京地域模型、有效期内),避免额度耗尽后静默转按量付费。

**免费额度不抵扣**:Batch 批量调用、模型调优与部署。所以批量处理长视频时不要用 Batch 模式,否则不走免费额度。

**试用顺序**(按验证价值排序):

1. Qwen-Audio-3.0-TTS-Plus 生成日语朗读 —— **听音色克隆的实际效果**,这决定阅读功能成不成立
2. Fun-ASR 对上一步音频取词级时间戳 —— **验证核心技巧是否可行**
3. Fun-ASR 处理一个真实视频(尤其带 BGM 的动漫)
4. Qwen3.7-Max 做陪读与聊天,确认免费额度和真实回答质量;额度耗尽后再验证 DeepSeek 备用

**第 1、2 步最关键**:若音色效果差或时间戳对不齐,整个阅读跟读的设计前提不成立,必须及早知道。

---

## 3. 整体架构

### 3.1 架构图

```
┌──────────────────────────────────────────────────────────────┐
│                  MacBook Air M5(常驻服务器)                   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  FastAPI 应用服务                                        │  │
│  │  ├─ /materials     材料列表 / 详情 / 状态                │  │
│  │  ├─ /segments      分句文本 + 时间戳                      │  │
│  │  ├─ /companion     AI 陪读(带材料上下文)                │  │
│  │  ├─ /chat          AI 聊天老师(独立上下文)              │  │
│  │  ├─ /shadowing     跟读录音上传与评分                      │  │
│  │  └─ /ingest-web    网页摄入界面(粘贴文本 / 上传视频)     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Worker(轮询任务表)                                     │  │
│  │  ├─ 网页抓取 / yt-dlp 下载                               │  │
│  │  ├─ ffmpeg 转码 / 抽音轨                                 │  │
│  │  ├─ 调用 TTS / ASR / LLM                                │  │
│  │  └─ 上传 OSS / 清理临时文件                              │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  本地存储                                                │  │
│  │  ├─ PostgreSQL    材料/分句/时间戳/对话/任务             │  │
│  │  └─ 文件系统       原始视频、原始音频(归档用)            │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────┬───────────────────────────────┬───────────────────┘
           │                               │
   Tailscale 私有网络                  公网 HTTPS
   (仅小流量:API/对话/进度)          (上传媒体 + 调用云 API)
           │                               │
           ↓                               ↓
   ┌──────────────┐        ┌────────────────────────────────┐
   │    iPhone    │        │  阿里云                         │
   │              │        │  ├─ 百炼 Qwen-Audio-3.0-TTS    │
   │  阅读跟读     │        │  ├─ 百炼 Fun-ASR/Paraformer    │
   │  视频跟读     │◄───────┤  └─ OSS                        │
   │  AI 陪读      │  公网   │      ├─ 云 API 文件中转         │
   │  AI 聊天      │  下载   │      └─ 媒体分发(音频/视频)   │
   │  跟读评分     │  媒体   └────────────────────────────────┘
   │              │        ┌────────────────────────────────┐
   │  本地缓存     │        │  百炼 Qwen3.7-Max               │
   │ (离线跟读)   │        │  └─ 陪读 / 聊天 / 字幕翻译      │
   └──────────────┘        └────────────────────────────────┘
```

### 3.2 职责划分:摄入在 Mac,消费在 iPhone

| | 在哪操作 | 为什么 |
|---|---|---|
| 添加材料(粘贴长文本、上传视频、贴链接) | **Mac 网页** | 大屏幕、键盘、文件系统 |
| 阅读、跟读、看视频、对话 | **iPhone** | 随身、通勤场景 |

**2026-08-10 修订(原文是「不要在 iPhone 上做材料管理界面。手机上粘贴长文、上传视频文件都很别扭,而这些操作天然发生在电脑前」)。**

原文有两个问题:①**它早就和实现不一致**——iOS 素材库的 `+` 里一直有本地视频导入(§5.2.1);②**它的理由被真实使用推翻**:使用者 2026-08-10 明确说「我发现 Mac 端的后台我不太经常用」。「手机上传别扭」成立的前提是「反正你会去 Mac 前面」,前提不成立,这条约束就从保护变成了阻碍——与 §1.4 当初换轴同理。

**判据换成:这一步需不需要键盘和文件系统。**

- **仍然在 Mac 更顺**:粘贴长文、批量管理、贴一串链接。
- **手机反而更顺**:从相册或文件里挑一个视频,看着画面把它切成几节(§15)——片子本来就在手机上,而 Mac 拿不到它。

「消费在 iPhone」不变。

### 3.3 OSS 的两个角色

**角色一:云端 API 的文件中转站**

阿里云的录音文件识别**不支持本地文件直传,不支持 base64,输入必须是公网可访问 URL**;声音复刻的参考音频同样如此。而 **Tailscale 是私有网络,阿里云访问不到 Mac 上的文件**。

**角色二:媒体分发层**

> **已实测的坑**:手机用蜂窝流量经 Tailscale 播放 Mac 上的视频,基本播不动。
>
> **原因**:手机蜂窝网络处于运营商级 NAT(CGNAT)之后,Tailscale 经常无法建立点对点直连,退回 DERP 中继转发。而 DERP 节点大多不在中国大陆,流量绕到境外再回来——延迟高、带宽受限。家庭上行带宽是次要因素,通常不是主因。

| | Tailscale(走中继时) | OSS |
|---|---|---|
| 路径 | 手机 → 境外中继 → 家里 Mac | 手机 → 阿里云北京 |
| 带宽 | 受中继限制 | 基本无上限 |
| NAT 穿透 | 蜂窝网络下经常失败 | 不涉及,普通 HTTPS |
| 进度条拖动 | 差 | 支持 Range 请求,正常 |

**上传方向不受影响**:Mac 上传到 OSS 走家庭上行,慢一点无所谓——那是一次性后台任务。

**由此确立的架构原则:**

```
Tailscale  →  小流量控制通道(API 调用、AI 对话、进度同步)
OSS        →  大流量媒体分发(朗读音频、视频)
```

**当前媒体访问策略:**iPhone 和百炼文件识别都直接消费 `OSS_PUBLIC_BASE_URL` 下的对象 URL，因此 `materials/`、`temporary/`、`shadowing/` 的对象必须能被持有 URL 的访问方读取。当前版本不使用短期签名 URL或 CDN；这是为了保证 HLS 相对分片、离线续传和百炼异步回读使用同一套稳定 URL。Bucket 与对象键不得用于存放项目之外的私密文件。若以后要改为私有媒体分发，必须先在本文档设计 HLS 清单重写、分片签名与离线过期策略，不能只把 Bucket 改成私有后期待现有客户端继续工作。

**附带好处:播放不再依赖 Mac 在线。** Mac 只需在处理新内容时开机。

**上传可靠性:**HLS 上传必须先传分片、最后传 `index.m3u8`,避免远端清单提前指向尚不存在的分片。单对象网络超时默认最多尝试 4 次,每次使用新连接;重试整个 `upload_video` job 时先列出对应 OSS 前缀,远端已有且字节数一致的对象直接跳过,只补缺失分片。超过 8 MiB 的单文件使用 OSS multipart 断点上传且并发固定为 1,避免家庭上行不稳定时从头重传或并发争抢带宽。

### 3.4 流量成本控制(设计前提,非优化项)

**① 上传前转码**

视频链接下载不得使用站点的无上限 `bestvideo`。默认最高分辨率固定为 720p、最高 30fps,优先选择 H.264/AAC;没有 720p 时向下选择 480p、360p 等较低档,不得为了“最佳画质”下载 1080p/4K 后再丢弃。已是 iPhone 兼容 H.264 且不超过 720p/30fps 的链接视频,本地 HLS 优先直接分片封装,不重新编码画面。只有本地上传、编码不兼容或直接封装失败时才转码;优先使用 VideoToolbox 硬件解码/编码,软件回退默认最多使用 2 个线程。

```
20 分钟 1080p @8Mbps  ≈ 1.2 GB
        ↓ ffmpeg 转 720p @1.5Mbps
20 分钟  720p @1.5Mbps ≈ 225 MB      存储与流量同时降到 1/5
```

手机屏幕不需要 1080p。转码在本地进行,不产生云端费用。

**② 跟读模式只分发音频**

跟读练习不需要画面。第一遍看视频理解剧情,之后反复跟读只需**音频 + 字幕滚动**,而音频约为视频的 1/20。

| 模式 | 内容 | 典型次数 | 单次流量 |
|---|---|---|---|
| 观看模式 | 完整视频 + 双语字幕 | 1 次 | 225 MB |
| 跟读模式 | 纯音频 + 字幕滚动 | 反复多次 | ~12 MB |

这不只省流量,**对跟读本身也更纯粹**——没有画面分散注意力。

**③ HLS 分片下载到手机离线练**

在家 Wi-Fi 下载,出门零流量。对"手机流量播不动"是最彻底的解法,也解决地铁、飞机等无网场景。视频和跟读音频都转为 HLS VOD,每个分片目标时长 6 秒:

- iPhone 按分片顺序下载,每完成一个分片就把进度写入本地清单;中断后只补缺失分片,不重新下载已完成部分
- 连续的首批分片落盘后即可开始观看,不等待整部视频;离线时可播放本机已有的连续区间,到缺失处明确提示
- 观看模式下载含画面的 720p 分片;跟读模式只下载音频分片。两套清单分开,避免为了反复跟读重复消耗视频流量
- 在线播放也直接使用 HLS,由 `AVPlayer` 按需拉取;离线分片播放器消费本机清单

**④ OSS 生命周期自动清理**

云任务成功时由 Worker 主动删除临时文件;失败或进程中断时再由 Bucket 生命周期兜底。对象前缀必须物理隔离,禁止用可能覆盖正式媒体的宽泛规则:

- `temporary/`:ASR 临时完整音轨,最后修改 1 天后删除
- `shadowing/`:跟读评分原始录音,最后修改 7 天后删除;评分文本、diff 和分数仍保存在 PostgreSQL
- `materials/`:正式朗读音频、视频/纯音频 HLS,**不设置自动过期**
- 后端设置页应用规则前先读取 Bucket 现有生命周期,只替换 ID 为 `harvest-temporary-asr` / `harvest-shadowing-recordings` 的两条规则,不得覆盖用户已有规则。保留天数可用 `OSS_TEMPORARY_RETENTION_DAYS` / `OSS_SHADOWING_RETENTION_DAYS` 调整,下限为 1 天

**实施四条策略后**:每周 2 个 20 分钟视频、每个看 1 遍 + 跟读 5 次,约 **2.3 GB/月**,北京地域的新用户 2 GB/3 个月流量额度只能覆盖早期验证的一部分;之后约 1–2 元/月。**不做则是 12 GB/月以上,差 5 倍。**

### 3.5 技术栈决策

| 层 | 选择 | 理由 |
|---|---|---|
| 后端框架 | Python 3.12 + FastAPI | 需要编排 ffmpeg / yt-dlp,且阿里云 SDK 生态在 Python |
| 数据库 | **PostgreSQL 17** | 见下 |
| 任务队列 | **数据库任务表 + 轮询 worker** | 见下 |
| 客户端 | SwiftUI,iOS 18+ | |
| 网页摄入界面 | Jinja2 + 普通表单 | 单人自用,不引入前端框架和构建步骤 |

**为什么用 PostgreSQL(而不是 SQLite)**

上一个项目已经用 Postgres 跑过一整套系统,运维经验(Homebrew 安装、启停脚本、`pg_dump` 备份)是现成的,复用成本低于切换到一个新工具链的学习成本。另外:

- **未来若接入语义检索**(个人语料库、跨材料查找相似句子等),Postgres 有 `pgvector` 可用,SQLite 的向量扩展生态明显不成熟
- **`psql` 的调试与查询能力优于 `sqlite3` CLI**——验收阶段需要贴大量"实际查询结果"作为证据,Postgres 用起来更顺手
- API 进程与 worker 进程并发写入时,Postgres 的并发处理比 SQLite 的单写者模型更从容,即使当前规模下 SQLite 也够用,但留出的余量更大

代价是多一个需要启动的服务(`brew services start postgresql@17`),`start.sh` 需要先确保它在跑。这个代价可以接受。

**为什么不用 Celery/Redis**

个人项目引入消息队列是过度工程。用一张 `job` 表 + 一个轮询循环:

- 任务状态持久化,重启不丢
- 可以直接查数据库看任务卡在哪
- 零额外依赖

---

## 4. 数据模型

### 4.1 核心抽象:材料(Material)

**关键设计:阅读文章和视频是同一种东西。**

两者都是「**一段音频 + 一串带时间戳的分句 + 可选的画面**」。因此:

```
阅读:  文本 → TTS 生成音频 → ASR 取时间戳 → 分句 + 时间轴
视频:  视频 → ffmpeg 抽音频 → ASR 转写   → 分句 + 时间轴
                                              ↓
                                    完全相同的下游结构
                                              ↓
                               同一个播放器、同一套跟读逻辑
```

**两条摄入流水线,一套消费体验。** 这是整个数据模型的地基。

### 4.2 表结构

```sql
-- 通用:updated_at 自动维护
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 材料:阅读文章或视频
CREATE TABLE material (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL,        -- reading | video
    title         TEXT NOT NULL,
    source_type   TEXT NOT NULL,        -- paste | url | file | photo
    source_ref    TEXT,                 -- 原始链接或文件名
    status        TEXT NOT NULL,        -- pending|processing|ready|failed
    error_message TEXT,
    duration_ms   INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_material_updated BEFORE UPDATE ON material
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 合集(§15.5):一个分组,不是一条 material。原片没有分句、不可消费,把它做成
-- material 会让 §4.1「材料 = 音频 + 带时间戳的分句」出现例外。
-- 刻意不存任何聚合状态(几节已转录、总时长)——那些从 material 派生,存下来只会不一致。
CREATE TABLE material_collection (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_material_collection_updated BEFORE UPDATE ON material_collection
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 一节属于哪个合集、是第几节、在原片里从哪儿开始(§15.5)。
-- source_offset_ms 只为界面能说「从 10:21 开始」;原片切完即删,不用于重切。
ALTER TABLE material ADD COLUMN collection_id BIGINT
    REFERENCES material_collection(id) ON DELETE CASCADE;
ALTER TABLE material ADD COLUMN collection_index INTEGER;
ALTER TABLE material ADD COLUMN source_offset_ms INTEGER;
CREATE INDEX idx_material_collection ON material(collection_id, collection_index);

-- 单用户视频观看位置:只表达媒体续播状态,不作为学习打卡或游戏化进度
CREATE TABLE material_playback_state (
    material_id BIGINT PRIMARY KEY REFERENCES material(id) ON DELETE CASCADE,
    position_ms INTEGER NOT NULL DEFAULT 0 CHECK (position_ms >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_material_playback_state_updated BEFORE UPDATE ON material_playback_state
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 分句:带时间戳的句子
CREATE TABLE segment (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   BIGINT NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,     -- 在材料中的顺序
    text_ja       TEXT NOT NULL,
    text_zh       TEXT,                 -- 中文翻译,可后补
    start_ms      INTEGER NOT NULL,
    end_ms        INTEGER NOT NULL,
    UNIQUE (material_id, idx)
);

-- 词:词语级时间戳,支撑逐词高亮
CREATE TABLE token (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id    BIGINT NOT NULL REFERENCES segment(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    surface       TEXT NOT NULL,        -- 词面,如「食べて」
    reading       TEXT,                 -- 平假名读音,如「たべて」;无可用读音时为空
    start_ms      INTEGER NOT NULL,
    end_ms        INTEGER NOT NULL,
    UNIQUE (segment_id, idx)
);

-- 媒体文件:一个材料可有多个(原视频/转码视频/音频)
CREATE TABLE media_asset (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   BIGINT NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,        -- video | audio
    purpose       TEXT NOT NULL,        -- archive(本地归档) | delivery(分发)
    local_path    TEXT,
    oss_key       TEXT,
    bytes         BIGINT,
    duration_ms   INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 任务队列
CREATE TABLE job (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL,        -- fetch|tts|asr|vision|download_video|transcode|upload_video|asr_video|translate_video|shadowing|voice_enrollment|voice_enrollment_video
    material_id   BIGINT REFERENCES material(id) ON DELETE CASCADE,
    status        TEXT NOT NULL,        -- pending|running|done|failed
    payload       JSONB,
    error_message TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_job_updated BEFORE UPDATE ON job
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
-- worker 轮询的核心索引:只挑 pending 的,避免全表扫描
CREATE INDEX idx_job_pending ON job(created_at) WHERE status = 'pending';

-- AI 陪读对话(绑定材料)
CREATE TABLE companion_message (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   BIGINT NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    segment_id    BIGINT REFERENCES segment(id) ON DELETE SET NULL,
    role          TEXT NOT NULL,        -- user | assistant
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- AI 聊天会话(独立上下文,与材料无关)
CREATE TABLE chat_session (
    id            TEXT PRIMARY KEY,     -- 服务端生成 UUID;兼容旧 personal 等文本 ID
    topic         TEXT NOT NULL,
    starter_id    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_chat_session_updated BEFORE UPDATE ON chat_session
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE chat_message (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chat_message_session ON chat_message(session_id, id);

-- 个人纠错知识库:一条用户输入对应至多一条总结,总结下有 1–3 个纠错点
CREATE TABLE chat_correction (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
    user_message_id BIGINT NOT NULL UNIQUE REFERENCES chat_message(id) ON DELETE CASCADE,
    original_text   TEXT NOT NULL,
    corrected_text  TEXT NOT NULL,
    summary_zh      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chat_correction_session ON chat_correction(session_id, created_at DESC);
CREATE INDEX idx_chat_correction_created ON chat_correction(created_at DESC, id DESC);

CREATE TABLE chat_correction_item (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correction_id     BIGINT NOT NULL REFERENCES chat_correction(id) ON DELETE CASCADE,
    idx               INTEGER NOT NULL,
    original_fragment TEXT NOT NULL,
    replacement       TEXT NOT NULL,
    reason_zh         TEXT NOT NULL,
    category          TEXT NOT NULL,    -- grammar|word_choice|naturalness|register|orthography
    grammar_key       TEXT,             -- 可选;关联 grammar_point.key 的稳定目录键
    UNIQUE (correction_id, idx)
);
CREATE INDEX idx_chat_correction_item_category ON chat_correction_item(category);
CREATE INDEX idx_correction_item_grammar ON chat_correction_item(grammar_key);

-- 跟读尝试与评分
CREATE TABLE shadowing_attempt (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id    BIGINT NOT NULL REFERENCES segment(id) ON DELETE CASCADE,
    audio_path    TEXT,
    asr_text      TEXT,
    diff_json     JSONB,                -- 逐词比对结果
    score         REAL,                 -- 命中率
    job_id        BIGINT REFERENCES job(id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'pending', -- pending|processing|ready|failed
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 克隆音色
CREATE TABLE voice_profile (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT NOT NULL,
    provider      TEXT NOT NULL,        -- alibaba
    voice_id      TEXT NOT NULL,
    is_default    BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 生词:用户在真实语料中查过并主动存下的词(§5.9)
CREATE TABLE vocabulary (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    word           TEXT NOT NULL,
    reading        TEXT,
    meaning        TEXT NOT NULL,
    part_of_speech TEXT,
    context        TEXT,                 -- 记忆提示(memory_hint),不是来源句
    example_ja     TEXT,                 -- 挖空复习用的例句,与 example_zh 成对出现或都为空
    example_zh     TEXT,
    box            INT NOT NULL DEFAULT 1,   -- Leitner 盒子等级 1–6
    review_count   INT NOT NULL DEFAULT 0,
    next_review_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 复习尝试:不可变事实表(M1-B,§5.11)。vocabulary.box/review_count/next_review_at
-- 仍是排期用的可变投影,继续被 §5.9 的调度逻辑直接读写;这张表只多加一层历史,
-- 不取代那三列,否则每次复习都要重算调度状态,读路径变慢且没有必要。
-- 上线前发生的复习没有这张表,过去次数无法拆回逐次事实,不做倒推。
CREATE TABLE vocabulary_review_attempt (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vocabulary_id BIGINT NOT NULL REFERENCES vocabulary(id) ON DELETE CASCADE,
    correct       BOOLEAN NOT NULL,
    box_before    INT NOT NULL,
    box_after     INT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_vocabulary_review_attempt_word
    ON vocabulary_review_attempt(vocabulary_id, created_at DESC);

-- 语法目录:索引而非教材内容
CREATE TABLE grammar_point (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    title_ja    TEXT NOT NULL,
    title_zh    TEXT NOT NULL,
    level       TEXT NOT NULL,
    category    TEXT NOT NULL,
    sort_order  INT NOT NULL DEFAULT 0
);

-- 语法状态投影:没有此行即未接触;事实原文仍在来源业务表
CREATE TABLE grammar_encounter (
    point_id          BIGINT PRIMARY KEY REFERENCES grammar_point(id) ON DELETE CASCADE,
    status            TEXT NOT NULL,    -- encountered | understood
    status_source     TEXT NOT NULL DEFAULT 'automatic', -- automatic | manual
    first_source      TEXT,             -- 首次来源,创建后不被后来证据覆盖
    last_source       TEXT,             -- correction | companion | browse | manual
    note              TEXT,             -- 兼容快照,不是事实唯一来源
    last_evidence_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    browsed_at        TIMESTAMPTZ,      -- 主动读过讲解;不被后来来源覆盖
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_grammar_encounter_updated BEFORE UPDATE ON grammar_encounter
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 按需生成的讲解缓存;版本或证据指纹不匹配即可丢弃重建
CREATE TABLE grammar_explanation (
    point_id             BIGINT PRIMARY KEY REFERENCES grammar_point(id) ON DELETE CASCADE,
    content              TEXT NOT NULL,
    prompt_version       TEXT NOT NULL DEFAULT '',
    evidence_fingerprint TEXT NOT NULL DEFAULT '',
    evidence_refs        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_grammar_explanation_updated BEFORE UPDATE ON grammar_explanation
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 用户在陪读中明确问到某语法点:是接触证据,但不是错误
-- 遗留表(M1 之后不再是投影的读取路径,详见 §5.11):写入仍保留供追溯,
-- grammar_encounter 的投影改为读 learning_event。
CREATE TABLE companion_grammar_evidence (
    message_id BIGINT NOT NULL REFERENCES companion_message(id) ON DELETE CASCADE,
    point_id   BIGINT NOT NULL REFERENCES grammar_point(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, point_id)
);
CREATE INDEX idx_companion_grammar_point
    ON companion_grammar_evidence(point_id, created_at DESC);

-- 全局学习事件(M1,§5.11 有完整契约与迁移说明)。薄信封 + 按 kind 校验的载荷,
-- 不是给每种来源发明共享字段;原文仍留在来源业务表,这里只存引用与必要快照。
CREATE TABLE learning_event (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'learning-event-v1',
    kind           TEXT NOT NULL,       -- correction_item | companion_question | vocabulary_saved
                                         -- | vocabulary_reviewed | shadowing_completed(§5.11)
    source_table   TEXT NOT NULL,       -- 原始行所在表,用于追溯与幂等回填
    source_id      BIGINT NOT NULL,
    subject_kind   TEXT NOT NULL,       -- grammar_point | vocabulary_word | segment(§5.11)
    subject_key    TEXT NOT NULL,       -- 如 grammar_point.key、vocabulary.id、segment.id
    actor          TEXT NOT NULL DEFAULT 'user',
    confidence     REAL,                -- 仅存校准过的置信值;当前模型归类没有校准,保持 NULL
    occurred_at    TIMESTAMPTZ NOT NULL,-- 原始事件真实发生时间,不是这行写入时间
    backfilled     BOOLEAN NOT NULL DEFAULT false,
    rejected_at    TIMESTAMPTZ,         -- 用户明确「这条关联标错了」;NULL = 仍是有效证据
    payload        JSONB NOT NULL,      -- 形状按 kind 在应用层校验,不用 JSONB CHECK 约束
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_table, source_id, subject_kind, subject_key)
);
CREATE INDEX idx_learning_event_subject
    ON learning_event(subject_kind, subject_key, occurred_at DESC)
    WHERE rejected_at IS NULL;
CREATE INDEX idx_learning_event_source ON learning_event(source_table, source_id);

-- source_table/source_id 是多态逻辑引用,无法使用单个外键。每新增一个可能产生
-- learning_event 的来源表,都要在该表的删除触发器里调用同一个
-- delete_learning_events_for_source() 函数(schema.sql 定义),让来源行删除时
-- 事件同步收敛。当前已覆盖 chat_correction_item / companion_message / vocabulary /
-- vocabulary_review_attempt / shadowing_attempt。

-- learner_memory / learner_memory_preference 已于 2026-08-09 删除(迁移 0006)。
-- 基线仍保留它们的 DDL,因为迁移 0002/0003 已经在这两张表上跑过、按 §7.5 不可修改,
-- 全新库必须先建出来才能重放;0006 在最后把它们删掉。DDL 原文见 schema.sql。

-- 后台决策记录(M1-D,§5.13 有完整契约)。事件索引、投影重算、记忆推导这些
-- 增强路径按设计失败不阻断主流程,代价是出错时完全无声;这张表就是它们的
-- 唯一交代。只存元数据与引用,永不存原文——要原文顺 evidence_refs 回来源表。
CREATE TABLE decision_trace (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'decision-trace-v1',
    call_source    TEXT NOT NULL,   -- 哪个入口触发,如 chat_correction_index
    status         TEXT NOT NULL,   -- ok | failed
    failure_stage  TEXT,            -- 失败时停在哪一步;成功为 NULL
    reason         TEXT NOT NULL,   -- 一句话说明发生了什么,可直接读
    rule_version   TEXT,            -- 当时用的规则/契约版本
    subject_kind   TEXT,            -- 可选:这次决策关于哪个主体
    subject_key    TEXT,
    model_provider TEXT,            -- 模型参与时,最终实际响应的供应商
    model_name     TEXT,            -- fallback/修复请求之后真正产出结果的模型
    prompt_version TEXT,            -- 该次结构化判断使用的提示词版本
    evidence_refs  JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 相关来源行/事件 id
    duration_ms    INTEGER NOT NULL,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 计数等元数据,不含原文
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_decision_trace_recent ON decision_trace(created_at DESC, id DESC);
CREATE INDEX idx_decision_trace_failed
    ON decision_trace(call_source, created_at DESC) WHERE status = 'failed';

-- 私人倾诉(§14)。与学习侧硬隔离:不接 learning_event、不接任何删除收敛触发器、
-- 不被任何教学提示词读到。只有 updated_at 触发器,别的一律不加。
CREATE TABLE journal_entry (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_journal_entry_updated BEFORE UPDATE ON journal_entry
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_journal_entry_recent ON journal_entry(created_at DESC, id DESC);

-- 每条 entry 写完即自动产生一条 reply(§14.2)。允许多行:重试或再要一次回应时追加,不覆盖。
CREATE TABLE journal_reply (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id       BIGINT NOT NULL REFERENCES journal_entry(id) ON DELETE CASCADE,
    body           TEXT NOT NULL,
    model_provider TEXT,
    model_name     TEXT,
    prompt_version TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_journal_reply_entry ON journal_reply(entry_id, created_at);
```

> **延续上一个项目验证过的约定**:枚举字段一律 TEXT、不加 CHECK 约束(§7.3 已写明);`updated_at` 由触发器统一维护,不要在应用层再手动设置一遍——两套机制并存容易在验收时对不上。

### 4.3 设计约定

- **音视频内部的时间偏移**(时间戳、时长)统一用毫秒整数(`*_ms`),不用浮点秒,避免精度问题
- **记录级别的时间字段**(`created_at` / `updated_at`)统一用 `TIMESTAMPTZ`,由数据库默认值和触发器维护,不在应用层手动赋值;显示时再转本地时区
- **枚举字段一律用 TEXT,不加 CHECK 约束** —— 新增类型时不用改表结构
- **`media_asset.purpose` 区分归档与分发**:原始高码率文件留在 Mac(`archive`),转码后的小文件上传 OSS(`delivery`)
- **`companion_message` 与 `chat_message` 完全分离**,不共享上下文。陪读是"这句什么意思",聊天是"聊聊今天吃了什么",混在一起会四不像
- **`journal_entry` / `journal_reply` 与全部学习表硬隔离**(§14.3):不复用 `companion_message`。理由是具体的——`companion_message` 上已经挂了语法证据路径(`companion_grammar_evidence` → `companion_message.id`)、`companion_question` 事件和删除收敛触发器(§5.16),倾诉内容混进去会**意外流入证据链且很难发现**。隔离是双向的:倾诉不读学习数据,学习侧任何提示词与召回也不得读倾诉数据
- **语法事实、投影与缓存分层**:`chat_correction_item` / `companion_message` 是可追溯事实,`grammar_encounter` 是可重算投影,`grammar_explanation` 是可丢弃缓存。删除纠错或聊天会话后必须重算受影响的投影;不得只删列表项而保留幽灵状态
- **删除收敛由数据库和应用各管一半,这条边界必须是显式的**:`learning_event` 的多态来源引用无法用外键表达,因此**「来源行消失 → 事件消失」由 5 个 `trg_*_learning_event_delete` 触发器在 Postgres 内保证**——它必须留在数据库里,才能覆盖 `material` / `chat_session` 级联删除和直接用 `psql` 操作的情况,这个保证有实际价值,不要为了「逻辑都在 Python」把它搬走。**「事件变化 → 投影与记忆重算」则由应用层负责**(§5.11 / §5.12)。代价是读 Python 代码看不全删一条纠错的后果,必须同时读 `schema.sql`;因此新增任何多态来源表时,两侧都要同步补齐,不得只写一侧。**触发器这条路径不产生 `decision_trace`**:它是数据库事务内的确定性清理,失败会直接让删除本身回滚,不存在 §5.13 所针对的「静默失败」——这是刻意的边界,不是遗漏,不要为它补一个永远不会有内容的 trace 类型
- **全局聊天按主题创建独立 `chat_session`**,完整消息永久保存;模型每轮只携带当前会话最近 20 条消息,避免跨主题污染和上下文无限增长
- **个人知识库第一版就是 PostgreSQL 中的完整聊天与结构化纠错**,不引入 pgvector、Embedding 或 RAG。正确且自然的输入只留在聊天历史,不创建 `chat_correction`。**纠错库本身不做复习调度**——`chat_correction` 只供查阅、搜索和新会话的轻量个性化;§5.9 的复习调度只作用于 `vocabulary`,两者不合并
- **素材库列表 API 是用户状态投影,不是 material 表直出**:`GET /materials` 除时长、来源、创建时间与封面路径外,还要基于当前 job 返回 `progress_percent`、`progress_label`、`eta_minutes`、失败阶段标题、用户可读错误分类、原始错误和 `retryable`;进度是明确的阶段进度,不能伪装成底层云服务未提供的逐字节精度。`POST /materials/{id}/retry` 复用失败 job 的原始 payload 并清空失败状态,不得创建重复 material。
- 视频与照片素材使用 `media_asset(kind='image', purpose='thumbnail')` 保存本机缩略图;视频在本地转码前后生成一张 JPEG,照片直接复用受控上传副本。`GET /materials/{id}/thumbnail` 只读取数据库登记且仍存在的文件。纯文本/网页材料由 iOS 使用一致的排版占位封面,不为装饰额外调用图片或 AI 服务。
- **新会话不注入任何跨会话的个性化。** 曾按纠错类别派生过一层「学习者画像」注入聊天提示词,2026-08-09 删除:它和语法骨架说的是同一件事,但只有模型看得见,无法判断是否真的帮到使用者;可见的那份(§12「需要留意」)保留。
- **`material.status` 只表达用户是否能消费材料**,不表达所有后台增强任务是否都成功:`ready` 表示主媒体与句级时间轴已可用;P2 ASR 这类增强任务失败或低覆盖率时,只把对应 `job` 记为 `failed` / `done`,不得把材料从 `ready` 降级;`downloaded` 表示视频已下载并本地转码完成、等待手动触发转录(此时无 OSS 上传,不可在 iPhone 消费,也不随任务自动推进)
- **异步子流程必须有自己的状态与错误字段**:`job` 表达后台任务状态;`shadowing_attempt` 表达一次跟读提交的状态。客户端不得通过“结果字段是否为空”猜测任务是否结束

---

## 7. 工程约定

### 7.1 开发节奏

改完就跑测试和构建,过了就提交。不写验收材料清单、不写阶段性汇报。**判据只有一条:真实产出对不对**——看真实的 API 返回、真实的数据库行、界面上真实显示的字,而不是"代码看起来是对的"。这一条来自上个项目的实际教训:代码完全按规格写对了,但真实数据显示某一层是空的。

云服务(百炼 / OSS)不为了验收提前注册;未配置密钥时,失败路径与配置提示必须诚实可见,不得把「尚未配置密钥」写成功能已完成。

### 7.3 通用编码约定

- **枚举字段存 TEXT,不加 CHECK 约束,不用数据库 ENUM**
- **时间戳用毫秒整数,不用浮点秒**
- **SwiftUI 渲染分支用 `@ViewBuilder` + `switch`,不要每个分支返回 `AnyView`**(会抹掉类型信息,导致列表滚动时视图无法复用)
- **API Key 通过 `.env` 提供,不进仓库**;仓库只放 `.env.example`
- **iOS 端不硬编码 API Key**,存 Keychain,首次启动时配置
- **iOS 正式 Bundle ID 固定为 `com.gaohuanhuan.harvest.JapaneseLearning`**,调试和真机安装不得另建同名 App 的平行 Bundle。Debug/Release 生成的 Info.plist 必须包含 `UILaunchScreen`,根画布必须覆盖安全区;缺少启动屏声明导致的兼容模式上下黑边属于构建失败
- **所有可收敛的后台耗时操作走 job 表异步执行**,API 立即返回任务 ID,前端轮询状态。文字聊天和实时语音属于持续交互通道,按各自同步请求 / WebSocket 协议执行,不进入 job 表
- **领域模块不得 import `repository`**。当前依赖方向是:`chat` / `companion` / `lenses` / `learning_events` 是不碰数据库的纯规则模块,`repository` 反过来 import 其中的规则模块并负责把规则落到 SQL,只有 `main` 和 `worker` 两个组合根同时持有两侧。这个方向是「186 项测试无需数据库、1.5 秒跑完」的直接原因,也是 `main.py` 至今零裸 SQL 的前提,**不得为了图方便让领域模块直接查库**
- **`Repository` 按领域拆分,存量不动**。当前它是单类约 90 个方法、2700 行;方法名前缀(`grammar_` / `chat_` / `companion_` / `vocabulary_`)已经是事实上的分组,再接入新的学习入口会把它推到 4000 行以上。规则是:**新领域的数据访问不再往 `Repository` 里加**,按领域新建 `GrammarRepository` / `ChatRepository` / `LearnerRepository`,共享同一个 `Engine`;已有 92 个方法**不做一次性搬迁**——没有真实痛点的大重构只会制造一次无法验收的巨型 diff。拆分随新功能渐进发生,旧方法在被相邻改动触及时顺带搬,不单独立项

### 7.4 运维

只需三个脚本,不做服务化:

- `start.sh` —— 先确保 Postgres 在跑(`brew services start postgresql@17`,已在跑则跳过),再启动 API + worker,打印访问地址
- `stop.sh` —— 停止 API + worker(不停 Postgres,它是常驻服务,没必要跟着关);进程不存在时不报错
- `backup.sh` —— `pg_dump` 导出后 gzip,打印路径和大小。**必须排除倾诉内容**(2026-08-10 决定):固定带 `--exclude-table-data=journal_entry --exclude-table-data=journal_reply`,只备份结构不备份行。用 `--exclude-table-data` 而不是 `--exclude-table`,这样恢复出来的库仍然有这两张表,只是空的,应用不会因为缺表而报错

**排除备份的代价要明说**:倾诉内容因此**没有任何副本**——误删就是永久删除,Mac 磁盘坏了也一起没有。这是刻意选的:它同时是最不该留副本的东西。这条与 §14.3 的"不上 OSS、不做云同步"是同一个取向,不是遗漏。想改回来只需去掉这两个参数,但**改之前先想清楚备份文件会躺在哪里**。

**不做开机自启、不做定时备份。** Mac 重启后手动跑一次 `start.sh`(会顺带把 Postgres 一起唤醒)。

FastAPI 只监听 `127.0.0.1:8000`,由 Tailscale Serve 把控制面暴露到私有 Tailnet;不得监听 `0.0.0.0` 让局域网设备绕过 Tailscale。视频上传采用流式落盘,默认最大 2 GB,并始终为本机保留至少 5 GB 可用空间;阈值可用 `MAX_VIDEO_UPLOAD_BYTES` / `MIN_FREE_DISK_BYTES` 调整。链接视频用 `VIDEO_DOWNLOAD_MAX_HEIGHT=720` / `VIDEO_DOWNLOAD_MAX_FPS=30` 限制下载规格,`VIDEO_TRANSCODE_MAX_THREADS=2` 限制硬件不可用时的软件解码、缩放和编码线程;不得通过改回无上限 `bestvideo` 追求当前产品不会保留的画质。OSS 单请求超时与重试次数用 `OSS_UPLOAD_TIMEOUT_SECONDS=90` / `OSS_UPLOAD_MAX_ATTEMPTS=4` 调整;视频分片上传保持串行,不得用高并发掩盖不稳定上行。

OSS 开通后先在后端设置页保存 Endpoint、Bucket、Access Key、公网前缀与保留天数,再点击「应用 OSS 生命周期规则」。该操作是显式的一次性 Bucket 配置,不得在每次 `start.sh` 时自动改写云端规则。

后端设置页同时管理统一文本问答模型、DeepSeek 备用、Omni WebSocket 地址和音色。`DASHSCOPE_CHAT_MODEL=qwen3.7-max` 与 `LLM_PROVIDER=auto` 为默认值;陪读、全局聊天和字幕翻译不得各自硬编码其他文本模型。百炼失败时只有在已填写 `DEEPSEEK_API_KEY` 且 `LLM_FALLBACK_ON_ERROR=true` 时才自动降级。Omni 的正式角色由 §5.8 与代码固定,设置页中的 `DASHSCOPE_OMNI_INSTRUCTIONS` 只允许填写不冲突的会话补充要求,不得替换共同教学内核。设置页必须提供显式清除密钥的操作,空白密码框仍表示保留原值。API 与 worker 在启动时读取配置,保存后需要同时重启。

百炼、DeepSeek 与网页抓取的 `httpx` 请求固定使用 `trust_env=false`,不读取 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`;本项目当前使用系统级 VPN/Tailscale 路由,不依赖进程级 HTTP 代理。这样可避免 macOS 环境中裸 IPv6 `NO_PROXY=::1` 被 httpx 误解析为无效端口 `:1`。若以后确实需要显式 HTTP 代理,必须先在本文档增加合法代理 URL 配置,不能重新无条件信任进程环境。

`qwen-audio-3.0-tts-plus` 的 `longanhuan_v3.6` 系统音色只支持中文/英文,不得作为日语默认音色。未选择日语基础音色或尚未完成声音复刻时,TTS job 必须明确失败。设置页只提供一个声音复刻入口,上传本人或已授权的音频/视频后由服务端自动分流:3–30 秒日语录音经 `voice_enrollment` 与 `temporary/` OSS 中转;带背景音乐的视频必须走 §5.7 的 `voice_enrollment_video` 本地人声分离链路,不得直接把混合音轨提交给百炼。两条链路成功后都创建 `voice_profile` 并设为默认。Demucs 作为体积较大的可选本地依赖安装在项目虚拟环境,缺失时设置页和视频 job 必须给出明确安装提示,但音频路径仍可使用。

### 7.5 数据库结构演进与迁移

#### 为什么现在必须补

到 M2 为止,数据库结构演进的全部手段是「`schema.sql` 每次启动全量重跑」,只有三种表达能力:`CREATE TABLE IF NOT EXISTS`、`ALTER TABLE ADD COLUMN IF NOT EXISTS`(已累计 22 条)、以及直接写在文件里的数据 DML(已有 6 条)。这套做法**只能表达追加**,改名、改类型、拆表和带语义变化的回填一个都表达不了;而 M5 关系记忆与 M7 向量索引必然要改动已有结构。

三个已经发生的症状:

1. **一次性回填被无限重放,其中一条是数据事故的引信。** `UPDATE grammar_encounter SET status_source='manual' WHERE status='understood' AND status_source<>'manual'` 是 M0 时代的历史补齐(当时只有用户显式操作能产生 `understood`),但它没有任何守卫,每次开机重跑。今天写 `understood` 的只有 `/grammar/{key}/status` 且必然 `manual=True`,所以尚未触发;**一旦 M4/M5 出现「从证据自动判定已掌握」,重启一次就会把来源改写成 `manual`,而按 §5.10 手动状态受保护不被自动降级,改错之后还会粘住。**
2. **每次开机 `DROP INDEX` 再 `CREATE INDEX`**(`idx_learner_memory_active`),用重建索引来表达一次索引定义变更。
3. **数据库答不出自己在第几版。** 全项目每个契约都带版本——`learning-event-v1`、`decision-trace-v1`、`companion-lens-v1`——唯独 schema 自己没有。直接后果是 schema 状态完全绑定在「进程有没有重启过」上:2026-08-09 查真实库时它落后代码三个提交、缺 6 张 M1 表,而没有任何地方能查询或断言这件事,当时正在进行的一轮盲测因此整轮作废。

#### 决策:自建版本化迁移,不引入 Alembic

理由与 §3.5「为什么不用 Celery/Redis」是同一条:Alembic 的主要价值在 autogenerate 与多环境管理,而本项目没有 ORM model(全部是裸 SQL)、只有一个单用户单机数据库,autogenerate 无从生成,却要为此长期维护一套 model 定义。用**一张 `schema_migration` 表 + 一个按序执行的 `.sql` 目录**即可,零新依赖,可以直接用 `psql` 查当前版本——与 job 表取代消息队列是同构的判断。

#### 契约

- **`schema.sql` 重新定位为幂等基线**,只负责把任意状态的库带到基线(既有全部 `IF NOT EXISTS` 与 `ADD COLUMN` 保持不变,它仍要能从空库一次建好)。**此后任何结构或数据变更一律进 `backend/app/migrations/`,不再改 `schema.sql`**;两套并存会立刻分叉。确需重做基线时,必须作为一次显式的独立提交,提交信息里写清为什么重做。
- **迁移文件命名 `NNNN_snake_case.sql`**,四位序号严格递增,按序号执行。**只追加,不写 down**:单用户场景下 `backup.sh` 的 `pg_dump` 就是回滚路径,维护一套几乎不会被执行的逆向脚本换不来实际价值。
- **`schema_migration` 表**记录 `version` / `name` / `checksum` / `applied_at` / `duration_ms`。`checksum` 是文件内容的 SHA-256:**已应用的迁移文件内容若被改动,启动必须失败并明确指出是哪一个**——历史迁移一旦跑过就是既成事实,改它只会让文件与真实库不一致而无人察觉。
- **每个迁移在自己的事务里执行**,失败则该迁移整体回滚、启动失败、保留旧库原状,与 `backfill_learning_events()` 既有原则一致(§5.11):不能带着半迁移的库继续提供一个看起来正常的系统。
- **启动顺序固定为:基线 → 未应用的迁移 → `sync_grammar_catalogue()` → `backfill_learning_events()`。** 回填依赖结构已经就位。
- **状态可离线查询**:`python -m scripts.migrate --status` 打印当前版本、已应用列表与待应用列表,不需要启动 API;`--apply` 显式执行。这是「数据库答得出自己在第几版」的落点。

#### 什么必须进迁移

任何**改变已有行含义**的操作:改列名/类型、拆表合表、带语义的回填、清理历史脏数据、索引定义变更。这类操作的共同特征是「对同一批数据只应该做一次」。

反过来,**`CREATE TRIGGER` 前的 `DROP TRIGGER IF EXISTS` 不算**——`CREATE TRIGGER` 没有 `IF NOT EXISTS`,这是让基线可重跑的必要写法,不是版本变更,继续留在 `schema.sql`。判据是:**这条语句在同一个库上跑两次,第二次是否可能改变任何一行数据。** 会,就进迁移;不会,才可以留在基线。

**判据里的「不可能再匹配」允许由数据库约束提供,不必是 `WHERE` 子句。** 实施时发现的唯一例外是 `chat_session` 的历史补齐:它必须在 `fk_chat_message_session` 之前执行(否则加外键时旧 `chat_message` 行无父行,建表即失败),而正是这条 `ON DELETE CASCADE` 外键保证了此后 `chat_message` 不可能再出现没有会话的 `session_id`——第二次运行永远匹配不到任何行。因此它留在基线,并在原地注释说明豁免理由;`backend/tests/test_migrations.py` 用显式豁免名单锁住这一条,**再往基线加任何 DML 都会让测试失败**,必须先修改名单,不能顺手放行。

---
