"""SubBridge 主窗口：导入视频、转录 / 翻译、模式切换、导出与烧录。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..core.align import align_segment, realign_after_edit
from ..core.media import MediaError, MediaInfo, burn_subtitles, extract_audio, probe_media
from ..core.subtitles import (
    Segment,
    join_tokens,
    parse_subtitle_file,
    write_ass,
    write_srt,
    write_vtt,
)
from ..core.transcribe import AVAILABLE_MODELS, TranscribeConfig, Transcriber
from ..core.translate import SUPPORTED_LANGUAGES, TranslateConfig, Translator
from ..platform import get_platform
from .dialogs import AboutDialog, ImportSubtitleDialog, SettingsDialog
from .editor import SubtitleEditor, WordPairPanel
from .player import PlayerWidget

__all__ = ["MainWindow"]


# ---------------------------------------------------------------------------
# 后台工作线程（耗时操作不阻塞界面）
# ---------------------------------------------------------------------------
class TranscribeWorker(QThread):
    """提取音频 + 转录。"""

    progress = pyqtSignal(float, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        ffmpeg_path: str,
        video_path: str,
        config: TranscribeConfig,
        cache_dir: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ffmpeg_path = ffmpeg_path
        self.video_path = video_path
        self.config = config
        self.cache_dir = cache_dir

    def run(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            audio_path = self.cache_dir / (
                Path(self.video_path).stem + "_16k.wav"
            )
            extract_audio(
                self.ffmpeg_path,
                self.video_path,
                str(audio_path),
                progress_callback=lambda p, m: self.progress.emit(p * 0.2, m),
            )
            transcriber = Transcriber(self.config)
            segments = transcriber.transcribe(
                str(audio_path),
                progress_callback=lambda p, m: self.progress.emit(
                    0.2 + p * 0.8, m
                ),
            )
            self.finished.emit(segments)
        except Exception as exc:  # noqa: BLE001 - 错误统一转成界面提示
            self.error.emit(str(exc))


class TranslateWorker(QThread):
    """翻译全部字幕段。"""

    progress = pyqtSignal(float, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        segments: list[Segment],
        config: TranslateConfig,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.segments = segments
        self.config = config

    def run(self) -> None:
        try:
            translator = Translator(self.config)
            result = translator.translate_segments(
                self.segments,
                progress_callback=lambda p, m: self.progress.emit(p, m),
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class BurnWorker(QThread):
    """ffmpeg 烧录硬字幕。"""

    progress = pyqtSignal(float, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        ffmpeg_path: str,
        video_path: str,
        subtitle_path: str,
        output_path: str,
        font_name: str,
        font_size: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ffmpeg_path = ffmpeg_path
        self.video_path = video_path
        self.subtitle_path = subtitle_path
        self.output_path = output_path
        self.font_name = font_name
        self.font_size = font_size

    def run(self) -> None:
        try:
            result = burn_subtitles(
                self.ffmpeg_path,
                self.video_path,
                self.subtitle_path,
                self.output_path,
                font_name=self.font_name,
                font_size=self.font_size,
                progress_callback=lambda p, m: self.progress.emit(p, m),
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    """SubBridge 主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SubBridge - 视频翻译字幕工具")
        self.resize(1100, 760)

        self.settings = QSettings("SubBridge", "SubBridge")
        self.platform = get_platform()
        self.video_path: str | None = None
        self.media_info: MediaInfo | None = None
        self.segments: list[Segment] = []
        self._worker: QThread | None = None

        self._build_ui()
        self._apply_settings_to_controls()
        self._update_action_state()

    # -- 界面搭建 ------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 操作行
        controls = QHBoxLayout()
        self.import_video_button = QPushButton("导入视频", self)
        self.import_video_button.clicked.connect(self.import_video)
        controls.addWidget(self.import_video_button)

        self.import_sub_button = QPushButton("导入字幕", self)
        self.import_sub_button.clicked.connect(self.import_subtitle)
        controls.addWidget(self.import_sub_button)

        controls.addWidget(QLabel("源语言：", self))
        self.source_combo = QComboBox(self)
        for code, name in SUPPORTED_LANGUAGES.items():
            self.source_combo.addItem(f"{name} ({code})", code)
        controls.addWidget(self.source_combo)

        controls.addWidget(QLabel("目标语言：", self))
        self.target_combo = QComboBox(self)
        for code, name in SUPPORTED_LANGUAGES.items():
            self.target_combo.addItem(f"{name} ({code})", code)
        controls.addWidget(self.target_combo)

        controls.addWidget(QLabel("模型：", self))
        self.model_combo = QComboBox(self)
        self.model_combo.addItems(AVAILABLE_MODELS)
        controls.addWidget(self.model_combo)

        controls.addWidget(QLabel("字幕模式：", self))
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("普通双语", "bilingual")
        self.mode_combo.addItem("单词标记（学习）", "wordmark")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        controls.addWidget(self.mode_combo)

        self.transcribe_button = QPushButton("开始转录", self)
        self.transcribe_button.clicked.connect(self.start_transcribe)
        controls.addWidget(self.transcribe_button)

        self.translate_button = QPushButton("翻译", self)
        self.translate_button.clicked.connect(self.start_translate)
        controls.addWidget(self.translate_button)

        self.realign_button = QPushButton("重新对齐", self)
        self.realign_button.clicked.connect(self.realign_all)
        controls.addWidget(self.realign_button)

        self.export_button = QPushButton("导出 ▾", self)
        export_menu = QMenu(self)
        export_menu.addAction("导出 SRT（双语）", lambda: self.export_file("srt"))
        export_menu.addAction("导出 VTT（双语）", lambda: self.export_file("vtt"))
        export_menu.addAction("导出 ASS", lambda: self.export_file("ass"))
        export_menu.addSeparator()
        export_menu.addAction("烧录硬字幕视频…", self.burn_video)
        self.export_button.setMenu(export_menu)
        controls.addWidget(self.export_button)

        self.settings_button = QPushButton("设置", self)
        self.settings_button.clicked.connect(self.open_settings)
        controls.addWidget(self.settings_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        # 视频信息行
        self.info_label = QLabel("未导入视频", self)
        layout.addWidget(self.info_label)

        # 上：播放器；下：编辑器 + 词对面板
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.player = PlayerWidget(self)
        self.player.position_changed.connect(self._on_player_position)
        splitter.addWidget(self.player)

        bottom = QSplitter(Qt.Orientation.Horizontal, self)
        self.editor = SubtitleEditor(self)
        self.editor.segments_changed.connect(self._on_segments_changed)
        self.editor.segment_selected.connect(self._on_segment_selected)
        bottom.addWidget(self.editor)

        self.word_panel = WordPairPanel(self)
        self.word_panel.pair_edited.connect(self._on_pair_edited)
        bottom.addWidget(self.word_panel)
        bottom.setSizes([720, 360])
        splitter.addWidget(bottom)
        splitter.setSizes([380, 380])
        layout.addWidget(splitter, stretch=1)

        # 状态栏
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        status.addPermanentWidget(self.progress_bar)

        # 菜单
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        file_menu.addAction("导入视频…", self.import_video)
        file_menu.addAction("导入字幕…", self.import_subtitle)
        file_menu.addSeparator()
        file_menu.addAction("导出 SRT（双语）", lambda: self.export_file("srt"))
        file_menu.addAction("导出 VTT（双语）", lambda: self.export_file("vtt"))
        file_menu.addAction("导出 ASS", lambda: self.export_file("ass"))
        file_menu.addSeparator()
        file_menu.addAction("烧录硬字幕视频…", self.burn_video)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)
        settings_menu = menu.addMenu("设置")
        settings_menu.addAction("设置…", self.open_settings)
        help_menu = menu.addMenu("帮助")
        help_menu.addAction("关于 SubBridge", self._show_about)

    # -- 设置 ---------------------------------------------------------------
    def _apply_settings_to_controls(self) -> None:
        self._set_combo(self.source_combo, str(self.settings.value("source_lang", "en")))
        self._set_combo(self.target_combo, str(self.settings.value("target_lang", "zh")))
        self._set_combo(self.model_combo, str(self.settings.value("model_size", "base")))
        mode = str(self.settings.value("mode", "bilingual"))
        self._set_combo(self.mode_combo, mode)
        self.player.set_word_mark_mode(mode == "wordmark")

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _save_control_settings(self) -> None:
        self.settings.setValue("source_lang", self.source_combo.currentData())
        self.settings.setValue("target_lang", self.target_combo.currentData())
        self.settings.setValue("model_size", self.model_combo.currentText())
        self.settings.setValue("mode", self.mode_combo.currentData())
        self.settings.sync()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            dialog.save()
            self._apply_settings_to_controls()

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    # -- ffmpeg --------------------------------------------------------------
    def _ffmpeg_path(self) -> str | None:
        configured = str(self.settings.value("ffmpeg_path", "") or "").strip()
        if configured:
            return configured
        return self.platform.find_ffmpeg()

    def _require_ffmpeg(self) -> str | None:
        path = self._ffmpeg_path()
        if path:
            return path
        QMessageBox.warning(self, "未找到 ffmpeg", self.platform.ffmpeg_search_hint())
        return None

    # -- 导入 -----------------------------------------------------------------
    def import_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.mkv *.mov *.avi *.webm *.flv *.wmv *.m4v *.ts);;所有文件 (*)",
        )
        if not path:
            return
        ffmpeg = self._require_ffmpeg()
        if not ffmpeg:
            return
        try:
            self.media_info = probe_media(ffmpeg, path)
        except MediaError as exc:
            QMessageBox.warning(self, "读取视频失败", str(exc))
            return
        self.video_path = path
        info = self.media_info
        duration = f"{int(info.duration // 60):02d}:{int(info.duration % 60):02d}"
        self.info_label.setText(
            f"视频：{Path(path).name}  |  时长 {duration}  |  "
            f"分辨率 {info.width}×{info.height}  |  "
            f"编码 {info.video_codec or '未知'}  |  "
            f"{'有音频' if info.has_audio else '无音频'}"
        )
        self.player.load_video(path)
        self._update_action_state()
        self.statusBar().showMessage("视频已导入，可以开始转录或导入已有字幕")

    def import_subtitle(self) -> None:
        dialog = ImportSubtitleDialog(self)
        if not dialog.exec():
            return
        path = dialog.subtitle_path()
        if not path:
            return
        try:
            segments = parse_subtitle_file(path, encoding=dialog.encoding())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导入字幕失败", str(exc))
            return
        if not segments:
            QMessageBox.warning(self, "导入字幕失败", "文件中没有解析到任何字幕")
            return
        self.segments = segments
        self.editor.load_segments(segments)
        self._update_action_state()
        self.statusBar().showMessage(f"已导入 {len(segments)} 条字幕")

    # -- 转录 / 翻译 -----------------------------------------------------------
    def start_transcribe(self) -> None:
        if not self.video_path:
            QMessageBox.information(self, "提示", "请先导入视频")
            return
        ffmpeg = self._require_ffmpeg()
        if not ffmpeg:
            return
        if self.media_info and not self.media_info.has_audio:
            QMessageBox.warning(self, "无法转录", "该视频没有音轨，无法转录")
            return
        self._save_control_settings()
        config = TranscribeConfig(
            model_size=self.model_combo.currentText(),
            language=self.source_combo.currentData(),
        )
        self._set_busy(True, "正在准备转录…")
        worker = TranscribeWorker(
            ffmpeg, self.video_path, config, self.platform.cache_dir(), self
        )
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_transcribe_finished)
        worker.error.connect(self._on_worker_error)
        self._worker = worker
        worker.start()

    def _on_transcribe_finished(self, segments: list[Segment]) -> None:
        self._set_busy(False)
        self.segments = segments
        self.editor.load_segments(segments)
        self._update_action_state()
        self.statusBar().showMessage(f"转录完成，共 {len(segments)} 条字幕，请点“翻译”")

    def start_translate(self) -> None:
        if not self.segments:
            QMessageBox.information(self, "提示", "没有可翻译的字幕，请先转录或导入字幕")
            return
        self._save_control_settings()
        config = TranslateConfig(
            source_lang=str(self.source_combo.currentData()),
            target_lang=str(self.target_combo.currentData()),
        )
        self._set_busy(True, "正在翻译…")
        worker = TranslateWorker(self.segments, config, self)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_translate_finished)
        worker.error.connect(self._on_worker_error)
        self._worker = worker
        worker.start()

    def _on_translate_finished(self, segments: list[Segment]) -> None:
        self.segments = segments
        self.editor.load_segments(segments)
        if self.mode_combo.currentData() == "wordmark":
            self.realign_all()
        self._set_busy(False)
        self._update_action_state()
        self.statusBar().showMessage("翻译完成")

    def realign_all(self) -> None:
        """对全部字幕做词对齐（学习模式）。"""
        if not self.segments:
            return
        target_lang = str(self.target_combo.currentData())
        aligned = 0
        for segment in self.segments:
            if segment.translation and segment.words:
                align_segment(segment, target_lang=target_lang)
                aligned += 1
        self.editor.load_segments(self.segments)
        self.statusBar().showMessage(
            f"词对齐完成（启发式近似对齐）：{aligned} 条字幕已标注词对"
        )

    def _on_worker_error(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.warning(self, "操作失败", message)

    # -- 导出与烧录 -------------------------------------------------------------
    def export_file(self, kind: str) -> None:
        if not self.segments:
            QMessageBox.information(self, "提示", "没有可导出的字幕")
            return
        filters = {
            "srt": "SRT 字幕 (*.srt)",
            "vtt": "WebVTT 字幕 (*.vtt)",
            "ass": "ASS 字幕 (*.ass)",
        }
        default_name = ""
        if self.video_path:
            default_name = Path(self.video_path).stem + f".{kind}"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出字幕", default_name, filters[kind]
        )
        if not path:
            return
        word_mark = self.mode_combo.currentData() == "wordmark"
        try:
            if kind == "srt":
                content = write_srt(self.segments, bilingual=True)
            elif kind == "vtt":
                content = write_vtt(self.segments, bilingual=True)
            else:
                content = write_ass(
                    self.segments, bilingual=True, word_mark=word_mark
                )
            Path(path).write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"已导出：{path}")

    def burn_video(self) -> None:
        if not self.video_path:
            QMessageBox.information(self, "提示", "请先导入视频")
            return
        if not self.segments:
            QMessageBox.information(self, "提示", "没有字幕可烧录，请先转录或导入字幕")
            return
        ffmpeg = self._require_ffmpeg()
        if not ffmpeg:
            return
        default_name = str(
            Path(self.video_path).with_name(Path(self.video_path).stem + "_字幕版.mp4")
        )
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存烧录后的视频", default_name, "MP4 视频 (*.mp4)"
        )
        if not output_path:
            return
        word_mark = self.mode_combo.currentData() == "wordmark"
        ass_text = write_ass(self.segments, bilingual=True, word_mark=word_mark)
        cache_dir = self.platform.cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        subtitle_path = cache_dir / "burn_temp.ass"
        subtitle_path.write_text(ass_text, encoding="utf-8")
        self._save_control_settings()
        self._set_busy(True, "正在烧录字幕…")
        worker = BurnWorker(
            ffmpeg,
            self.video_path,
            str(subtitle_path),
            output_path,
            font_name=str(self.settings.value("font_name", "Microsoft YaHei")),
            font_size=int(self.settings.value("font_size", 24)),
            parent=self,
        )
        worker.progress.connect(self._on_progress)
        worker.finished.connect(
            lambda path: (
                self._set_busy(False),
                self.statusBar().showMessage(f"烧录完成：{path}"),
            )
        )
        worker.error.connect(self._on_worker_error)
        self._worker = worker
        worker.start()

    # -- 界面状态 ---------------------------------------------------------------
    def _on_mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        self.player.set_word_mark_mode(mode == "wordmark")
        self._save_control_settings()
        if mode == "wordmark" and self.segments:
            self.realign_all()

    def _on_player_position(self, milliseconds: int) -> None:
        position_s = milliseconds / 1000.0
        current = None
        for segment in self.segments:
            if segment.start <= position_s < segment.end:
                current = segment
                break
        self.player.update_subtitle(current, milliseconds)

    def _on_segments_changed(self) -> None:
        self.segments = self.editor.segments()
        self._update_action_state()

    def _on_segment_selected(self, row: int) -> None:
        if 0 <= row < len(self.segments):
            self.word_panel.show_segment(self.segments[row])

    def _on_pair_edited(self, row: int, new_text: str) -> None:
        """词对面板里改了译文词：同步回字幕段并重建整句译文。"""
        selected = self.editor.selected_rows()
        if not selected:
            return
        segment = self.segments[selected[0]]
        if row < 0 or row >= len(segment.words):
            return
        word = segment.words[row]
        word.translation = new_text
        # 同步译文词列表中同色的词，再拼回整句译文。
        for target in segment.translation_words:
            if (
                target.color_index == word.color_index
                and word.color_index >= 0
                and target.translation == word.text
            ):
                target.text = new_text
                break
        if segment.translation_words:
            segment.translation = join_tokens(
                [w.text for w in segment.translation_words]
            )
        self.editor.load_segments(self.segments)
        self.word_panel.show_segment(segment)

    def _on_progress(self, ratio: float, message: str) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(int(ratio * 100))
        self.statusBar().showMessage(message)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.progress_bar.setVisible(busy)
        if not busy:
            self.progress_bar.setValue(0)
        for button in (
            self.transcribe_button,
            self.translate_button,
            self.realign_button,
            self.export_button,
            self.import_video_button,
            self.import_sub_button,
        ):
            button.setEnabled(not busy)
        if message:
            self.statusBar().showMessage(message)

    def _update_action_state(self) -> None:
        has_video = self.video_path is not None
        has_segments = len(self.segments) > 0
        self.transcribe_button.setEnabled(has_video)
        self.translate_button.setEnabled(has_segments)
        self.realign_button.setEnabled(has_segments)
        self.export_button.setEnabled(has_segments)
