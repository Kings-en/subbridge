"""视频预览播放器：QMediaPlayer + 字幕叠加层 + 逐词高亮同步。

Qt Multimedia 在部分精简环境可能不可用：此时退化为占位提示，
字幕叠加层仍可工作，主窗口不会因此崩溃。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtMultimediaWidgets import QVideoWidget

    MULTIMEDIA_AVAILABLE = True
except ImportError:  # 精简版 Qt 或缺少系统多媒体后端
    MULTIMEDIA_AVAILABLE = False
    QMediaPlayer = None  # type: ignore
    QAudioOutput = None  # type: ignore
    QVideoWidget = None  # type: ignore

from ..core.subtitles import WORD_COLORS, Segment, Word

__all__ = ["PlayerWidget", "MULTIMEDIA_AVAILABLE"]


def _format_ms(milliseconds: int) -> str:
    total = max(0, milliseconds // 1000)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def highlight_words_html(words: list[Word], position_ms: int, translation: str = "") -> str:
    """按当前播放位置生成带逐词高亮的 HTML。

    正在读的词用黄色底高亮；已对齐的词按词对颜色着色。
    """
    if not words:
        return ""
    position_s = position_ms / 1000.0
    parts: list[str] = []
    for word in words:
        color = None
        if word.color_index >= 0:
            color = WORD_COLORS[word.color_index % len(WORD_COLORS)][2]
        style = ""
        if word.start <= position_s < word.end:
            style = "background-color:#FFD54A;color:#000000;"
        elif color:
            style = f"color:{color};"
        escaped = (
            word.text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        if style:
            parts.append(f'<span style="{style}">{escaped}</span>')
        else:
            parts.append(escaped)
    html = " ".join(parts)
    if translation:
        escaped_tr = (
            translation.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        html += f"<br>{escaped_tr}"
    return html


class PlayerWidget(QWidget):
    """视频播放器 + 字幕叠加预览。"""

    position_changed = pyqtSignal(int)  # 毫秒
    duration_changed = pyqtSignal(int)  # 毫秒

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = None
        self._duration_ms = 0
        self._current_segment: Segment | None = None
        self._word_mark_mode = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # -- 视频画面 ------------------------------------------------------
        self.video_area = QWidget(self)
        video_layout = QVBoxLayout(self.video_area)
        video_layout.setContentsMargins(0, 0, 0, 0)
        if MULTIMEDIA_AVAILABLE:
            try:
                self._player = QMediaPlayer(self)
                audio = QAudioOutput(self)
                self._player.setAudioOutput(audio)
                self.video_widget = QVideoWidget(self)
                self._player.setVideoOutput(self.video_widget)
                video_layout.addWidget(self.video_widget)
                self._player.positionChanged.connect(self._on_position_changed)
                self._player.durationChanged.connect(self._on_duration_changed)
            except Exception:
                self._player = None
                self._add_placeholder(video_layout)
        else:
            self._add_placeholder(video_layout)
        layout.addWidget(self.video_area, stretch=1)

        # -- 字幕叠加层 ----------------------------------------------------
        self.subtitle_label = QLabel("导入视频后，这里会同步显示字幕", self)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setMinimumHeight(64)
        self.subtitle_label.setStyleSheet(
            "QLabel { background-color: rgba(0,0,0,180); color: white; "
            "font-size: 18px; padding: 6px; border-radius: 4px; }"
        )
        layout.addWidget(self.subtitle_label)

        # -- 播放控制 ------------------------------------------------------
        controls = QHBoxLayout()
        self.play_button = QPushButton("▶ 播放", self)
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)

        self.position_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.position_slider.setEnabled(False)
        self.position_slider.sliderMoved.connect(self.seek)
        controls.addWidget(self.position_slider, stretch=1)

        self.time_label = QLabel("00:00 / 00:00", self)
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

    def _add_placeholder(self, layout: QVBoxLayout) -> None:
        placeholder = QLabel(
            "当前环境不支持视频播放（缺少 Qt Multimedia）\n"
            "仍可转录、翻译、编辑与导出字幕",
            self,
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setMinimumHeight(200)
        layout.addWidget(placeholder)

    # -- 视频加载与播放 ---------------------------------------------------
    def load_video(self, path: str) -> None:
        """载入视频文件。"""
        if self._player is None:
            return
        from PyQt6.QtCore import QUrl

        self._player.setSource(QUrl.fromLocalFile(path))
        self.play_button.setEnabled(True)
        self.position_slider.setEnabled(True)

    def toggle_play(self) -> None:
        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.play_button.setText("▶ 播放")
        else:
            self._player.play()
            self.play_button.setText("⏸ 暂停")

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()
            self.play_button.setText("▶ 播放")

    def seek(self, milliseconds: int) -> None:
        if self._player is not None:
            self._player.setPosition(milliseconds)

    def position_ms(self) -> int:
        if self._player is None:
            return self.position_slider.value()
        return int(self._player.position())

    def duration_ms(self) -> int:
        return self._duration_ms

    # -- 字幕同步 ----------------------------------------------------------
    def set_word_mark_mode(self, enabled: bool) -> None:
        """学习模式开关：开启后按词高亮当前单词。"""
        self._word_mark_mode = enabled

    def update_subtitle(self, segment: Segment | None, position_ms: int) -> None:
        """根据当前播放位置刷新叠加字幕。"""
        self._current_segment = segment
        if segment is None:
            self.subtitle_label.setText("")
            return
        if self._word_mark_mode and segment.words:
            html = highlight_words_html(segment.words, position_ms, segment.translation)
            self.subtitle_label.setText(html)
        else:
            text = segment.text
            if segment.translation:
                text += "\n" + segment.translation
            self.subtitle_label.setText(text)

    # -- 内部槽 ------------------------------------------------------------
    def _on_position_changed(self, milliseconds: int) -> None:
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(milliseconds)
        self.position_slider.blockSignals(False)
        self.time_label.setText(
            f"{_format_ms(milliseconds)} / {_format_ms(self._duration_ms)}"
        )
        self.position_changed.emit(milliseconds)

    def _on_duration_changed(self, milliseconds: int) -> None:
        self._duration_ms = milliseconds
        self.position_slider.setRange(0, milliseconds)
        self.time_label.setText(
            f"{_format_ms(0)} / {_format_ms(milliseconds)}"
        )
        self.duration_changed.emit(milliseconds)
