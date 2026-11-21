# SubBridge 架构说明

## 设计目标

1. **Windows 优先**：v1 只在 Windows 上正式支持与打包；
2. **跨平台留口**：所有操作系统差异收敛到 `platform/` 层，`core/` 与 `ui/` 不直接调 OS 专属 API，以后加 macOS / Linux 不用改业务代码；
3. **离线优先**：转录与翻译都用本地模型，首次下载后完全离线；
4. **包体克制**：词对齐 v1 用启发式算法，不引入 torch / simalign，避免包体爆炸。

## 目录结构

```
subbridge/
├── src/subbridge/
│   ├── __init__.py          # 版本号
│   ├── __main__.py          # python -m subbridge 入口
│   ├── main.py              # 创建 QApplication、建配置目录、打开主窗口
│   ├── core/                # 核心层：纯 Python，不依赖界面与 OS
│   │   ├── subtitles.py     # 字幕模型 Segment/Word；SRT/VTT/ASS 解析与写出
│   │   ├── transcribe.py    # faster-whisper 封装（懒加载，词级时间戳）
│   │   ├── translate.py     # argos-translate 封装（懒加载，语言包管理）
│   │   ├── align.py         # 词对齐：WordAligner 协议 + HeuristicAligner
│   │   └── media.py         # ffmpeg/ffprobe 封装：探测、提音频、烧录
│   ├── platform/            # 平台层：所有 OS 差异都在这里
│   │   ├── base.py          # Platform 抽象接口 + GenericPlatform + 工厂
│   │   └── windows.py       # Windows 实现（%APPDATA% 等）
│   └── ui/                  # 界面层：PyQt6
│       ├── main_window.py   # 主窗口 + 后台工作线程（QThread）
│       ├── player.py        # 播放器（QMediaPlayer）+ 逐词高亮同步
│       ├── editor.py        # 字幕编辑器 + 词对面板
│       └── dialogs.py       # 设置、导入字幕、关于
├── build/windows/           # PyInstaller spec 与打包脚本
├── .github/workflows/       # CI：windows-latest 构建 + 打 tag 发 Release
├── tests/                   # 纯逻辑测试（不联网、不依赖 GUI）
└── docs/ARCHITECTURE.md     # 本文档
```

## 分层规则

| 层 | 能依赖什么 | 不能做什么 |
|----|-----------|-----------|
| `core/` | 标准库、faster-whisper、argos-translate | 不 import PyQt6；不直接调 OS 专属 API（如注册表、win32 API）；不读写界面状态 |
| `platform/` | 标准库（os / sys / pathlib / shutil） | 不做业务逻辑；只回答“路径在哪、ffmpeg 在哪”这类问题 |
| `ui/` | core、platform、PyQt6 | 耗时操作必须放 QThread，不阻塞界面；不直接拼 ffmpeg 命令行（走 `core.media`） |

数据流向：

```
视频文件 → media.probe_media（信息）→ media.extract_audio（16k WAV）
        → transcribe.Transcriber（Segment + 词级时间戳）
        → translate.Translator（填充 Segment.translation）
        → align.align_segment（填充词对颜色与译文词）
        → ui 编辑 / 预览
        → write_srt / write_vtt / write_ass 或 media.burn_subtitles
```

字幕是核心数据：`Segment`（一条字幕）包含 `words: list[Word]`（原文词级
时间戳）与 `translation_words`（译文分词），词对颜色存在 `Word.color_index`
（0-7，8 色循环）。SRT / VTT 导出只用整句文本；ASS 单词标记版用
`{\1c&HBBGGRR&}` 行内颜色标记实现词对着色。

## 词对齐（学习模式）

- `WordAligner` 是 `typing.Protocol`：`align(source_words, target_words) -> Alignment`。
- v1 的 `HeuristicAligner`：锚点匹配（数字、标点、相同词、专名、常用词词典）
  + 位置比例填充 + 单调约束。结果是近似对齐，README 已如实说明。
- 之后接入神经对齐器（如 simalign / awesome-align）时：新建一个实现
  `WordAligner` 的类，在设置里加一个“对齐器”选项，调用方（`align_segment`）
  不需要改动。

## 平台层扩展指南（加 macOS / Linux 时要加什么）

1. 新建 `src/subbridge/platform/macos.py`（或 `linux.py`），实现 `Platform`
   的 5 个方法：
   - `config_dir()`：macOS 用 `~/Library/Application Support/SubBridge`；
     Linux 用 `$XDG_CONFIG_HOME/SubBridge`（无 XDG 时 `~/.config/SubBridge`）；
   - `cache_dir()` / `models_dir()`：macOS 用 `~/Library/Caches/SubBridge`；
     Linux 用 `$XDG_CACHE_HOME/SubBridge`；
   - `default_output_dir()`：`~/Movies/SubBridge`（macOS）或 `~/Videos/SubBridge`（Linux）；
   - `find_ffmpeg()`：macOS 优先查 Homebrew 路径（`/opt/homebrew/bin/ffmpeg`、
     `/usr/local/bin/ffmpeg`）再查 PATH；Linux 查 PATH 与 `/usr/bin/ffmpeg`。
2. 在 `platform/base.py` 的 `get_platform()` 里注册：`sys.platform == "darwin"`
   与 `startswith("linux")` 的分支已预留（目前 ImportError 时回退到
   `GenericPlatform`，实现后即可自动启用）。
3. 打包：新增 `build/macos/SubBridge.spec`（PyInstaller，`--windowed`）与
   `build/linux/` 打包脚本；CI 增加 `macos-latest` / `ubuntu-latest` 任务；
   ffmpeg 在 macOS 上建议用 `brew install ffmpeg` 或随包放 `ffmpeg` 二进制。
4. 界面：`ui/` 不需要改；`player.py` 的 Qt Multimedia 在 macOS / Linux 上
   需要系统多媒体后端（macOS 自带 AVFoundation；Linux 需 GStreamer），
   缺失时已自动退化为占位提示。
5. 注意：`core/` 完全不用改；`main.py` 的目录初始化走 `get_platform()`，
   已跨平台。

## 构建与发布

- 本地打包：`build\windows\build.bat`（PyInstaller one-folder 模式）。
- CI（`.github/workflows/build-windows.yml`）：`windows-latest` 上装依赖 →
  PyInstaller 打包 → 下载 gyan.dev ffmpeg 精简版放入 `dist\SubBridge\ffmpeg\bin`
  → 压缩成 zip 上传 artifact；打 tag `v*` 时自动创建 Release 并附上 zip。
- 模型与语言包不进安装包：首次使用时由 faster-whisper / argos-translate
  自动下载到平台缓存目录。

## 测试策略

- `tests/test_subtitles.py`：SRT / VTT / ASS 解析与写出往返、合并 / 拆分、双语与词标导出；
- `tests/test_align.py`：分词、锚点（数字 / 标点 / 词典 / 专名）、单调性、整段对齐与改译文重对齐；
- GUI 目前只做冒烟测试（offscreen 创建主窗口不崩溃），不做交互测试；
- 真实转录 / 翻译需要下载模型与语言包，未纳入自动化测试，需人工验证。
