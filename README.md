# SubBridge · 视频翻译字幕工具

给视频添加翻译字幕的 Windows 桌面应用（Python + PyQt6）。

- **本地转录**：faster-whisper（离线，带词级时间戳）
- **本地翻译**：argos-translate（离线，首次使用自动下载语言包）
- **双语字幕**：每条字幕同时显示原文 + 译文
- **单词标记（学习模式）**：原文单词与译文单词一一对应，8 色循环标记；播放时高亮正在读的单词，方便学语言
- **导出**：SRT / VTT / ASS（单词标记版），或用 ffmpeg 把字幕烧录成硬字幕视频

> v1 先做 Windows 版；架构已为 macOS / Linux 留出扩展口（见 `docs/ARCHITECTURE.md`）。

## 安装（Windows）

### 方式一：下载打包版（推荐）

1. 打开本仓库右侧 **Releases**，下载最新版 `SubBridge-windows-x64.zip`；
2. 解压到任意目录（不要放在中文路径下），双击 `SubBridge.exe` 即可；
3. 打包版已自带 ffmpeg，无需另外安装。

### 方式二：从源码运行

要求：Python 3.11+、ffmpeg（转录与烧录需要）。

```bat
git clone https://github.com/<你的用户名>/subbridge.git
cd subbridge
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m subbridge
```

ffmpeg 安装（二选一）：

- 下载 https://www.gyan.dev/ffmpeg/builds/ 的 `ffmpeg-release-essentials.zip`，解压后把 `bin` 目录加入系统 PATH；
- 或在 SubBridge 的「设置 → ffmpeg 路径」里直接指定 `ffmpeg.exe` 的位置。

## 使用步骤

1. **导入视频**：点「导入视频」，选择 mp4 / mkv / mov / avi / webm 等文件，界面会显示时长与分辨率；
2. **获取原文台词**（二选一）：
   - 点「开始转录」：自动识别语音生成字幕（首次使用会自动下载 Whisper 模型，`base` 约 150MB，需要联网一次）；
   - 点「导入字幕」：导入已有的 SRT / VTT / ASS 文件；
3. **翻译**：在顶部选择源语言与目标语言（默认英 → 中），点「翻译」；首次翻译某语言对时会自动下载 argos 语言包（需要联网一次）；

## 支持的语言

中国网友最感兴趣的五种外语（英语、日语、韩语、法语、德语）加中文排在语言下拉框最前面，共 17 种语言可选。转录（Whisper）直接支持全部五种语言；翻译（argos）方面：

- **英语 ↔ 中文**：直达，一个语言包；
- **日语 / 韩语 / 法语 / 德语 → 中文**：没有直达语言包，软件自动经英语中转（先译成英语，再译成中文），界面状态栏会显示路线，如“日语 → 英语 → 中文（经英语中转）”；
- 其他语言对同理：只要一端是英语就直达，否则经英语中转（西 ↔ 葡有直达包）。

中转会多过一次模型，译文质量比直达略低，首次使用会依次下载两个语言包（需要联网一次）。
4. **选择字幕模式**：
   - **普通双语**：每条字幕同时显示原文行 + 译文行；
   - **单词标记（学习）**：原文单词与译文单词按 8 色配对标记，播放器里按当前时间高亮正在读的单词；编辑器右侧的词对面板可查看、修改词对；
5. **校对**：在字幕表格里直接改时间与文本；支持合并、拆分、删除；改译文后会自动重对齐；
6. **导出**：点「导出」选择 SRT / VTT / ASS；或选「烧录硬字幕视频」输出带字幕的新视频。

## 设置

「设置」里可以改：源 / 目标语言、转录模型大小（tiny / base / small，越大越准、越慢）、字幕字体与字号、ffmpeg 路径。

## 开发

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
pytest                        # 运行测试
python -m subbridge           # 从源码启动
```

打包 Windows 版：

```bat
build\windows\build.bat
```

产物在 `dist\SubBridge\`（one-folder 模式），把 `ffmpeg\bin` 放进 `dist\SubBridge\ffmpeg\bin` 即可随包分发。GitHub Actions 会在 `windows-latest` 上自动构建，打 tag `v*` 时生成 Release。

## 架构说明

分三层（详见 `docs/ARCHITECTURE.md`）：

- `src/subbridge/core/`：纯 Python 业务逻辑（字幕模型、转录、翻译、词对齐、ffmpeg 封装），不依赖界面与操作系统；
- `src/subbridge/platform/`：平台差异收敛层（配置目录、ffmpeg 查找、默认路径），Windows 实现在 `platform/windows.py`；
- `src/subbridge/ui/`：PyQt6 界面（主窗口、播放器、编辑器、对话框），耗时操作走 QThread。

## v1 已知限制（请先了解）

1. **词对齐是近似对齐**：v1 用启发式算法（位置比例 + 数字 / 标点 / 专名 + 常用词词典），不用神经网络；短句、数字、专名通常能对准，长句、意译、语序差异大的句子可能错位。`core/align.py` 已定义 `WordAligner` 协议，后续可接入神经对齐器替换。
2. **中文按字切分**：学习模式里中文译文按单个汉字分词（没有内置中文分词器），英文等多词语言按词切分。
3. **首次使用需要联网**：Whisper 模型与 argos 语言包首次下载需要联网，之后完全离线。
4. **转录质量取决于音频**：背景噪音大、多人重叠说话、口音重时，转录会有错误，需要人工校对。
5. **烧录需要 ffmpeg**：未找到 ffmpeg 时转录与烧录不可用，界面会给出明确提示；翻译与字幕编辑不受影响。
6. **仅 Windows 正式支持**：macOS / Linux 的平台层接口已预留，但尚未实现与测试。

## 许可证

MIT License，见 `LICENSE`。
