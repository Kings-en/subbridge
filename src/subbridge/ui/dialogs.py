"""对话框：设置、导入字幕、关于。"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.translate import ordered_languages
from ..core.transcribe import AVAILABLE_MODELS
from ..platform import get_platform

__all__ = ["SettingsDialog", "ImportSubtitleDialog", "AboutDialog"]


class SettingsDialog(QDialog):
    """设置页：语言、模型大小、字体、样式、ffmpeg 路径。"""

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("设置")
        self.setMinimumWidth(480)

        layout = QFormLayout(self)

        self.source_combo = QComboBox(self)
        for code, name in ordered_languages():
            self.source_combo.addItem(f"{name} ({code})", code)
        self.source_combo.setCurrentText("英语 (en)")
        layout.addRow("源语言：", self.source_combo)

        self.target_combo = QComboBox(self)
        for code, name in ordered_languages():
            self.target_combo.addItem(f"{name} ({code})", code)
        self.target_combo.setCurrentText("中文 (zh)")
        layout.addRow("目标语言：", self.target_combo)

        self.model_combo = QComboBox(self)
        self.model_combo.addItems(AVAILABLE_MODELS)
        layout.addRow("转录模型（越大越准、越慢）：", self.model_combo)

        self.font_combo = QComboBox(self)
        from PyQt6.QtGui import QFontDatabase

        self.font_combo.addItems(sorted(QFontDatabase.families()))
        layout.addRow("字幕字体：", self.font_combo)

        self.font_size_spin = QSpinBox(self)
        self.font_size_spin.setRange(12, 72)
        self.font_size_spin.setValue(24)
        layout.addRow("烧录字幕字号：", self.font_size_spin)

        ffmpeg_row = QHBoxLayout()
        self.ffmpeg_edit = QLineEdit(self)
        ffmpeg_row.addWidget(self.ffmpeg_edit, stretch=1)
        browse_button = QPushButton("浏览…", self)
        browse_button.clicked.connect(self._browse_ffmpeg)
        ffmpeg_row.addWidget(browse_button)
        detect_button = QPushButton("自动检测", self)
        detect_button.clicked.connect(self._detect_ffmpeg)
        ffmpeg_row.addWidget(detect_button)
        layout.addRow("ffmpeg 路径：", ffmpeg_row)
        layout.addRow(
            "",
            QLabel("留空表示自动查找；找不到 ffmpeg 时转录与烧录不可用。"),
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._load()

    # -- 载入 / 保存 --------------------------------------------------------
    def _load(self) -> None:
        s = self.settings
        self._set_combo(self.source_combo, s.value("source_lang", "en"))
        self._set_combo(self.target_combo, s.value("target_lang", "zh"))
        self._set_combo(self.model_combo, s.value("model_size", "base"))
        self._set_combo(self.font_combo, s.value("font_name", "Microsoft YaHei"))
        self.font_size_spin.setValue(int(s.value("font_size", 24)))
        self.ffmpeg_edit.setText(str(s.value("ffmpeg_path", "") or ""))

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def save(self) -> None:
        s = self.settings
        s.setValue("source_lang", self.source_combo.currentData())
        s.setValue("target_lang", self.target_combo.currentData())
        s.setValue("model_size", self.model_combo.currentText())
        s.setValue("font_name", self.font_combo.currentText())
        s.setValue("font_size", self.font_size_spin.value())
        s.setValue("ffmpeg_path", self.ffmpeg_edit.text().strip())
        s.sync()

    def _browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ffmpeg 可执行文件", "", "可执行文件 (ffmpeg.exe);;所有文件 (*)"
        )
        if path:
            self.ffmpeg_edit.setText(path)

    def _detect_ffmpeg(self) -> None:
        found = get_platform().find_ffmpeg()
        if found:
            self.ffmpeg_edit.setText(found)
            QMessageBox.information(self, "已找到", f"找到 ffmpeg：\n{found}")
        else:
            QMessageBox.warning(
                self,
                "未找到",
                get_platform().ffmpeg_search_hint(),
            )


class ImportSubtitleDialog(QDialog):
    """导入已有字幕：选择文件与编码。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入字幕")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        path_row.addWidget(self.path_edit, stretch=1)
        browse_button = QPushButton("浏览…", self)
        browse_button.clicked.connect(self._browse)
        path_row.addWidget(browse_button)
        form.addRow("字幕文件（SRT / VTT / ASS）：", path_row)

        self.encoding_combo = QComboBox(self)
        self.encoding_combo.addItems(["utf-8", "utf-8-sig", "gbk", "gb2312"])
        form.addRow("文件编码：", self.encoding_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择字幕文件",
            "",
            "字幕文件 (*.srt *.vtt *.ass *.ssa);;所有文件 (*)",
        )
        if path:
            self.path_edit.setText(path)

    def subtitle_path(self) -> str:
        return self.path_edit.text().strip()

    def encoding(self) -> str:
        return self.encoding_combo.currentText()


class AboutDialog(QDialog):
    """关于 SubBridge。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 SubBridge")
        layout = QVBoxLayout(self)
        label = QLabel(
            "<b>SubBridge 1.0.0</b><br>"
            "视频翻译字幕工具：本地转录（faster-whisper）+ "
            "本地翻译（argos-translate），支持双语字幕与单词标记学习模式。<br><br>"
            "v1 词对齐为启发式近似对齐，详见 README“已知限制”。"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok, self
        )
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
