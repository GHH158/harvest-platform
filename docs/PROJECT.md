# Harvest — 日语沉浸学习 App 主文档

> **项目名:Harvest。**

> **本文件是本项目唯一的设计文档。** 所有产品定位、架构决策、数据模型、开发计划、工程约定都在这里。
> 不再拆分成多个文件。

---

## 0. 文档维护约定

### 0.1 唯一性

**本文件是设计与实施之间唯一的沟通通道。**

讨论可以发生在任何地方,但**任何影响实现的决定,只有写进本文件才算数**。没有落到这里的口头约定,对实施方等于不存在。

实施时若发现文档与实际情况冲突,**不要自行决定**,在验收材料的「偏离说明」中提出。

### 0.2 修改方式(重要)

**本文件只做局部替换,禁止凭记忆整份重新生成。**

理由:本文档篇幅较长,整份重造几乎必然静默丢失内容——这个错误在上一个项目里发生过。

与设计方讨论修订时,应先提供本文件当前内容或待改章节的原文,对方只回该章节的替换文本。

### 0.3 编号稳定性

章节编号一旦分配不再变动,新增内容追加新编号。这样跨文档引用(如"见 §5.3")不会失效。

---

## 1. 产品定位

### 1.1 一句话

个人自用的日语沉浸学习工具,核心是**接触真实语料**和**真实产出**,不做课本数字化,不做记忆卡片。

### 1.2 要解决的问题

学了很多年日语,处在「学了忘、忘了学、什么都应用不出来」的状态。知识是碎的,没有串起来。

**判断:缺的不是"记得更牢",而是"接触得不够"和"从来没输出过"。** 因此本项目不做背诵与复习调度,只做输入与输出两件事。

课本内容自己看,软件只做课本做不了的事。

### 1.3 功能全景

```
输入侧
├─ 阅读跟读 ── 粘贴文本 / 网页链接 / 拍照
│              → 生成朗读音频 → 文字随发音逐字高亮
└─ 视频跟读 ── 本地视频 / 视频链接
               → 生成日中双语字幕 → 跟读

理解侧
└─ AI 陪读 ─── 基于当前阅读/观看内容,即时讲解与答疑

输出侧
├─ AI 聊天老师 ── 独立对话上下文,日常聊天中练日语
└─ 跟读评分 ───── 录下自己的跟读,ASR 反向 diff 指出发音不清的词
```

### 1.4 明确不做的事

- 不做 SRS / 记忆卡片 / 复习调度
- 不做课本内容录入
- 不做学习进度、连续天数、成就系统等游戏化设计
- 不做多用户、不做发布上架

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
- 逐字高亮的动效要**柔和渐变**(淡入淡出的背景色块),不要生硬的色块跳变
- 减少界面"装饰性元素"(图标堆砌、渐变背景、强分割线),让文字和朗读内容本身是唯一的主角

**基调**
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
| 语音转文字 | **Fun-ASR / Paraformer** | 阿里云百炼 | **支持词语级时间戳**,全局关键 |
| 大语言模型 | **DeepSeek** | DeepSeek / 百炼 | 陪读 + 聊天 + 字幕翻译 |
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
2. **阅读逐字高亮** —— TTS 生成的音频**不带时间戳**,把它再喂给 ASR,就能反推出每个词的时间点

第 2 点是本方案的核心技巧:**用 ASR 给 TTS 补时间戳**,在同一家服务内闭环,不需要引入日语强制对齐(forced alignment)这类不成熟的组件。

⚠️ 注意:SenseVoice 即将下线,不要使用。

### 2.4 成本

| 项目 | 单价 |
|---|---|
| TTS | 约 **2 元/万字符**(2000 字文章 ≈ **0.4 元**) |
| 音色克隆 | 0.01 元/个,一次性 |
| ASR | 按语音时长计费,**静音不计费**;**具体单价需开通后在控制台确认** |
| LLM(DeepSeek) | 极低,个人用量每月几元 |
| OSS 存储 | 0.09–0.12 元/GB/月 |
| OSS 公网流出 | 闲时 0.25 元/GB,忙时 0.5 元/GB(上传免费) |

**粗略月度估算**:在实施 §3.4 流量控制策略的前提下,预计 **20–40 元/月**。ASR 单价确认后再修正本节。

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
| OSS 外网流出 | 2 GB + 叠加 5 GB/月 | 3 个月 |
| OSS 请求 | 20 万次 | 3 个月 |

**开通后第一件事:打开「免费额度用完即停」开关**(仅限北京地域模型、有效期内),避免额度耗尽后静默转按量付费。

**免费额度不抵扣**:Batch 批量调用、模型调优与部署。所以批量处理长视频时不要用 Batch 模式,否则不走免费额度。

**试用顺序**(按验证价值排序):

1. Qwen-Audio-3.0-TTS-Plus 生成日语朗读 —— **听音色克隆的实际效果**,这决定阅读功能成不成立
2. Fun-ASR 对上一步音频取词级时间戳 —— **验证核心技巧是否可行**
3. Fun-ASR 处理一个真实视频(尤其带 BGM 的动漫)
4. DeepSeek/Qwen 做陪读讲解,横向对比几家(各模型额度独立,多试免费)

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
   │  本地缓存     │        │  DeepSeek API                  │
   │ (离线跟读)   │        │  └─ 陪读 / 聊天 / 字幕翻译      │
   └──────────────┘        └────────────────────────────────┘
```

### 3.2 职责划分:摄入在 Mac,消费在 iPhone

| | 在哪操作 | 为什么 |
|---|---|---|
| 添加材料(粘贴长文本、上传视频、贴链接) | **Mac 网页** | 大屏幕、键盘、文件系统 |
| 阅读、跟读、看视频、对话 | **iPhone** | 随身、通勤场景 |

**不要在 iPhone 上做材料管理界面。** 手机上粘贴长文、上传视频文件都很别扭,而这些操作天然发生在电脑前。

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

**附带好处:播放不再依赖 Mac 在线。** Mac 只需在处理新内容时开机。

### 3.4 流量成本控制(设计前提,非优化项)

**① 上传前转码**

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

**③ 支持下载到手机离线练**

在家 Wi-Fi 下载,出门零流量。对"手机流量播不动"是最彻底的解法,也解决地铁、飞机等无网场景。

**实施三条策略后**:每周 2 个 20 分钟视频、每个看 1 遍 + 跟读 5 次,约 **2.3 GB/月**,免费期内基本覆盖,之后约 1–2 元/月。**不做则是 12 GB/月以上,差 5 倍。**

**可选优化**(第二版再考虑):HLS 切片(起播快、只下载看过的部分)、OSS 生命周期自动清理。

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

-- 词:词语级时间戳,支撑逐字高亮
CREATE TABLE token (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id    BIGINT NOT NULL REFERENCES segment(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    surface       TEXT NOT NULL,        -- 词面,如「食べて」
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
    kind          TEXT NOT NULL,        -- fetch|transcode|tts|asr|translate|upload
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

-- AI 聊天老师(独立上下文,与材料无关)
CREATE TABLE chat_message (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 跟读尝试与评分
CREATE TABLE shadowing_attempt (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id    BIGINT NOT NULL REFERENCES segment(id) ON DELETE CASCADE,
    audio_path    TEXT,
    asr_text      TEXT,
    diff_json     JSONB,                -- 逐词比对结果
    score         REAL,                 -- 命中率
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
```

> **延续上一个项目验证过的约定**:枚举字段一律 TEXT、不加 CHECK 约束(§7.3 已写明);`updated_at` 由触发器统一维护,不要在应用层再手动设置一遍——两套机制并存容易在验收时对不上。

### 4.3 设计约定

- **音视频内部的时间偏移**(时间戳、时长)统一用毫秒整数(`*_ms`),不用浮点秒,避免精度问题
- **记录级别的时间字段**(`created_at` / `updated_at`)统一用 `TIMESTAMPTZ`,由数据库默认值和触发器维护,不在应用层手动赋值;显示时再转本地时区
- **枚举字段一律用 TEXT,不加 CHECK 约束** —— 新增类型时不用改表结构
- **`media_asset.purpose` 区分归档与分发**:原始高码率文件留在 Mac(`archive`),转码后的小文件上传 OSS(`delivery`)
- **`companion_message` 与 `chat_message` 完全分离**,不共享上下文。陪读是"这句什么意思",聊天是"聊聊今天吃了什么",混在一起会四不像

---

## 5. 核心处理流水线

### 5.1 阅读材料

```
① 用户在 Mac 网页粘贴文本 / 输入链接
② Worker:抓取正文(如为链接)
③ Worker:调用 Qwen-Audio-3.0-TTS-Plus(指定克隆音色)→ 音频
④ Worker:音频存本地 + 上传 OSS
⑤ Worker:调用 Fun-ASR(日语,开词语级时间戳)→ 词级时间戳
⑥ Worker:对齐 ASR 结果与原文,写入 segment / token
⑦ material.status = ready
⑧ iPhone 拉取 → 播放音频(OSS)+ 逐字高亮
```

**⑥ 的注意点**:ASR 转写结果可能与原文有出入(识别错字、断句不同)。**以原文为准,ASR 只贡献时间戳**。需要做一次文本对齐,把 ASR 的时间轴映射到原文的词上;对不齐的部分退化为句子级时间戳,不要因此失败。

### 5.2 视频材料

```
① 用户在 Mac 网页上传视频 / 输入链接
② Worker:yt-dlp 下载(如为链接)
③ Worker:ffmpeg 抽音轨(单声道,便于后续说话人分离)
④ Worker:ffmpeg 转码 720p @1.5Mbps → delivery 版本
⑤ Worker:音轨上传 OSS → 调用 Fun-ASR → 日语字幕 + 时间轴
⑥ Worker:调用 LLM 翻译 → 中文字幕
⑦ Worker:转码视频 + 纯音频上传 OSS,删除 OSS 上的临时音轨
⑧ material.status = ready
⑨ iPhone:观看模式拉视频 / 跟读模式只拉音频
```

### 5.3 跟读评分

```
① iPhone 录下用户跟读某一句的音频
② 上传到 Mac(小文件,走 Tailscale 即可)
③ Worker:上传 OSS → Fun-ASR 转写
④ Worker:与该句原文逐词 diff
⑤ 返回:哪些词没被正确识别 = 发音可能有问题
```

**原理**:连 ASR 都听不出你说的是哪个词,母语者大概率也听不清。

**这不是专业发音评分**(不评音调、不评音素),但能精确指出"哪几个词说得不清楚",而且**成本只是多跑一次 ASR,不需要任何新服务**。

### 5.4 AI 陪读

```
iPhone:用户点击某个词 / 某一句,或直接提问
  → Mac:组装上下文(当前句 + 前后各若干句 + 用户问题)
  → DeepSeek → 讲解
  → 写入 companion_message,返回 iPhone
```

**上下文范围要克制**:传整篇文章会浪费 token 且效果未必更好。默认传当前句 + 前后各 2 句。

---

## 6. 开发阶段规划

每个阶段独立可用、独立验收。**上一阶段验收通过后才开始下一阶段。**

| 阶段 | 内容 | 交付后能做什么 |
|---|---|---|
| **P1** | 地基 + 阅读跟读(句子级) | 粘贴文章 → 听朗读 → 句子跟着高亮 |
| **P2** | 逐字高亮 + 离线下载 | 精确到词的高亮;下载后无网可用 |
| **P3** | AI 陪读 + AI 聊天老师 | 读不懂能问;能用日语聊天 |
| **P4** | 跟读评分 | 知道自己哪几个词念不清 |
| **P5** | 视频跟读 | 看视频学日语 |
| **P6** | 拍照读日语 + 语音对话老师 | 漫画随手拍;开口说而不是打字 |

### 6.1 为什么是这个顺序

- **P1 必须先跑通"文本 → 音频 → 播放"整条链路**,这是产品主干,链路不通后面都无从谈起
- **P2 的离线下载先用小音频文件建立模式**,比直接拿大视频调试风险低,P5 直接复用
- **P3 把陪读和聊天放一起**,两者共用 LLM 基础设施,拆开做重复劳动
- **P4 单独一阶段**,因为它引入"iPhone 录音上传"这条新链路
- **P5 视频最晚**,涉及 yt-dlp、ffmpeg、字幕渲染、播放器同步,工程量最大
- **P6 是扩展**,不影响主干

### 6.2 各阶段范围

#### P1 — 地基 + 阅读跟读(句子级)

**后端**
- SQLite 建表(§4.2 全部表一次建好,不分批)
- FastAPI 骨架 + Tailscale 可访问
- Job 表 + worker 轮询循环
- 网页摄入界面:粘贴文本 / 输入链接,提交后创建材料与任务
- TTS 调用 + OSS 上传
- 简单分句(按句号、问号、感叹号切分),句子级时间戳可先用**音频总时长按字符数比例估算**

**iOS**
- 材料列表页
- 阅读播放页:文本 + 播放/暂停 + 当前句高亮 + 点句跳转

**明确不做**:词级时间戳、离线下载、AI、视频

**为什么句子级时间戳先用估算**:P1 的目标是验证整条链路通不通,不是精度。ASR 回读放 P2,这样 P1 能更快跑起来。

#### P2 — 逐字高亮 + 离线下载

**后端**
- ASR 调用 + 词级时间戳提取
- ASR 结果与原文的对齐算法(见 §5.1 ⑥ 注意点)
- 对齐失败时退化为句子级,不报错

**iOS**
- 逐词高亮
- 下载材料到本地(音频 + 分句数据),下载后无网可播
- 已下载材料的管理(查看占用、删除)

#### P3 — AI 陪读 + AI 聊天老师

**后端**
- DeepSeek 接入
- `/companion`:带材料上下文,写入 `companion_message`
- `/chat`:独立会话,写入 `chat_message`

**iOS**
- 阅读页内点词/句 → 陪读面板
- 独立的聊天老师页

#### P4 — 跟读评分

**后端**
- 录音上传接口
- ASR 转写 + 逐词 diff + 评分
- 结果写入 `shadowing_attempt`

**iOS**
- 跟读录音按钮(按句录)
- 评分结果展示:标出没被识别出的词

#### P5 — 视频跟读

**后端**
- yt-dlp 下载
- ffmpeg 抽音轨 / 转码 720p
- ASR 转字幕 + LLM 翻译
- 观看版与跟读版分别上传 OSS

**iOS**
- 视频播放器 + 双语字幕
- 观看模式 / 跟读模式切换
- 视频离线下载

#### P6 — 扩展

- Qwen-VL:拍照 → 文字 → 进入阅读流水线
- Qwen-Omni:语音对话老师

---

## 7. 工程约定

### 7.1 开发与验收流程

```
设计方(本文档) → 实施方(Codex)编码 → 本地验证 → 验收 → 下一阶段
```

### 7.2 验收材料要求

**每个阶段完成后必须提交,不能只说"做完了""没问题":**

1. **GitHub 仓库链接**(私有库需授权),含本阶段 commit
2. **环境信息**:Python 版本、Xcode 版本、iOS 部署目标
3. **实际输出**,不是结论:
   - 关键 API 的返回 JSON 原文
   - 数据库查询结果原文
   - 界面上显示的文字**原样照抄**
   - 报错时的完整错误信息
4. **逐项对照该阶段的验收标准**,标注完成/未完成,未完成说明原因
5. **偏离说明**:任何偏离本文档之处,逐条说明改了什么、为什么

**这套流程存在的原因**:上一个项目出现过"代码完全按规格写对了,但真实数据显示某个层是空的"。**只看代码发现不了这类问题,只有看真实产出才能。**

### 7.3 通用编码约定

- **枚举字段存 TEXT,不加 CHECK 约束,不用数据库 ENUM**
- **时间戳用毫秒整数,不用浮点秒**
- **SwiftUI 渲染分支用 `@ViewBuilder` + `switch`,不要每个分支返回 `AnyView`**(会抹掉类型信息,导致列表滚动时视图无法复用)
- **API Key 通过 `.env` 提供,不进仓库**;仓库只放 `.env.example`
- **iOS 端不硬编码 API Key**,存 Keychain,首次启动时配置
- **所有耗时操作走 job 表异步执行**,API 立即返回任务 ID,前端轮询状态

### 7.4 运维

只需三个脚本,不做服务化:

- `start.sh` —— 先确保 Postgres 在跑(`brew services start postgresql@17`,已在跑则跳过),再启动 API + worker,打印访问地址
- `stop.sh` —— 停止 API + worker(不停 Postgres,它是常驻服务,没必要跟着关);进程不存在时不报错
- `backup.sh` —— `pg_dump` 导出后 gzip,打印路径和大小

**不做开机自启、不做定时备份。** Mac 重启后手动跑一次 `start.sh`(会顺带把 Postgres 一起唤醒)。

---

## 8. 风险与遗留问题

| 问题 | 状态 | 说明 |
|---|---|---|
| **ASR 单价未知** | 待确认 | 影响成本估算,开通后在控制台查 |
| **Qwen-Audio-3.0-TTS 过新** | 已知 | 发布仅 10 天;可随时切回 CosyVoice |
| **TTS 生成慢** | 已知 | 约 16 字符/秒;必须做成后台任务 + 进度提示 |
| **ASR 与原文对齐可能失败** | 待验证 | P2 的核心难点;失败时退化为句子级,不能崩 |
| **Tailscale 不可用于媒体分发** | 已确认 | 实测结论,不要试图绕过 |
| **OSS 成为关键依赖** | 已知 | 支持离线下载后,已下载内容不受影响 |
| **视频链接下载的合规性** | 已知 | 涉及各平台服务条款,个人学习用途自行把握 |
| **音色克隆的合规性** | 已知 | 仅可克隆本人声音或已获授权的声音 |

---

## 9. 一条非技术的提醒

这个项目的失败模式不是"架构不够好",而是**"建工具本身太有成就感,会伪装成学习"**。

写代码、调架构、研究 API,每一样都比开口说日语舒服,但都不产生语言能力。

**建议给自己定一条:每次准备加新功能之前,先确认过去七天有没有真的用它读过、听过、说过。**

如果没有,该做的不是加功能,而是先用起来。

---

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-07-30 | 初版。合并此前分散的技术选型、免费额度、媒体分发等讨论,确立单文档维护 |
| 2026-07-30 | 数据库从 SQLite 改为 PostgreSQL 17。理由:复用上一个项目已验证的运维经验、为未来语义检索(`pgvector`)留余地、`psql` 调试更顺手。schema(§4.2)、运维脚本(§7.4)、架构图(§3.1)已同步更新 |
| 2026-07-30 | 确定项目名为 **Harvest**。新增 §1.5 视觉与交互风格,把"Claude 风格"翻译为具体的色彩/排版/布局判断,要求 P1 起就按此风格实施,不留到后期补 |
