"""字幕编辑器：时间 / 文本编辑、合并 / 拆分 / 删除、逐词开关、词对面板。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.subtitles import (
    Segment,
    format_srt_time,
    merge_segments,
    parse_time,
    split_segment,
)
from ..core.align import realign_after_edit

__all__ = ["SubtitleEditor", "WordPairPanel"]


def _parse_time_input(text: str) -> float:
    """解析用户输入的时间：支持 12.5、01:23.4、00:01:23,456 三种写法。"""
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        pass
    if text.count(":") == 1:
        minutes, rest = text.split(":")
        return int(minutes) * 60 + float(rest)
    return parse_time(text)


class WordPairPanel(QWidget):
    """词对面板：选中一段字幕后显示原文词 ↔ 译文词，可改译文词。"""

    pair_edited = pyqtSignal(int, str)  # 行号, 新译文词

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("词对（原文词 ↔ 译文词，双击译文词可修改）："))
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["原文词", "译文词", "颜色"])
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)
        self._loading = False
        self._segment: Segment | None = None

    def show_segment(self, segment: Segment | None) -> None:
        """显示某条字幕的词对。"""
        self._segment = segment
        self._loading = True
        self.table.setRowCount(0)
        if segment is None:
            self._loading = False
            return
        # 行：按源词顺序，每行一个词对；未对齐的源词译文词为空。
        for index, word in enumerate(segment.words):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(word.text))
            self.table.item(row, 0).setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            self.table.setItem(row, 1, QTableWidgetItem(word.translation))
            color_name = ""
            if word.color_index >= 0:
                from ..core.subtitles import WORD_COLORS

                color_name = WORD_COLORS[word.color_index % len(WORD_COLORS)][0]
            color_item = QTableWidgetItem(color_name)
            color_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            self.table.setItem(row, 2, color_item)
        self._loading = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 1:
            return
        self.pair_edited.emit(item.row(), item.text())


class SubtitleEditor(QWidget):
    """字幕表格编辑器。"""

    segments_changed = pyqtSignal()
    segment_selected = pyqtSignal(int)  # 选中行的下标

    COLUMNS = ["序号", "开始", "结束", "原文", "译文", "启用", "词标"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[Segment] = []
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        self.merge_button = QPushButton("合并选中", self)
        self.merge_button.clicked.connect(self.merge_selected)
        self.split_button = QPushButton("拆分选中", self)
        self.split_button.clicked.connect(lambda: self.split_selected())
        self.delete_button = QPushButton("删除选中", self)
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(self.merge_button)
        buttons.addWidget(self.split_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    # -- 数据载入与回读 ----------------------------------------------------
    def load_segments(self, segments: list[Segment]) -> None:
        self._segments = list(segments)
        self._refresh_table()

    def segments(self) -> list[Segment]:
        return self._segments

    def _refresh_table(self) -> None:
        self._loading = True
        self.table.setRowCount(0)
        for seg in self._segments:
            row = self.table.rowCount()
            self.table.insertRow(row)
            index_item = QTableWidgetItem(str(seg.index))
            index_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            self.table.setItem(row, 0, index_item)
            self.table.setItem(row, 1, QTableWidgetItem(format_srt_time(seg.start)))
            self.table.setItem(row, 2, QTableWidgetItem(format_srt_time(seg.end)))
            self.table.setItem(row, 3, QTableWidgetItem(seg.text))
            self.table.setItem(row, 4, QTableWidgetItem(seg.translation))
            enabled_item = QTableWidgetItem()
            enabled_item.setCheckState(
                Qt.CheckState.Checked if seg.enabled else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 5, enabled_item)
            mark_item = QTableWidgetItem()
            mark_item.setCheckState(
                Qt.CheckState.Checked if seg.word_mark else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 6, mark_item)
        self._loading = False

    def _reindex(self) -> None:
        for index, seg in enumerate(self._segments, start=1):
            seg.index = index

    # -- 编辑 --------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if row < 0 or row >= len(self._segments):
            return
        seg = self._segments[row]
        try:
            if item.column() == 1:
                seg.start = _parse_time_input(item.text())
            elif item.column() == 2:
                seg.end = _parse_time_input(item.text())
            elif item.column() == 3:
                seg.text = item.text()
            elif item.column() == 4:
                if seg.translation != item.text():
                    seg.translation = item.text()
                    # 改了译文：启发式重对齐
                    realign_after_edit(seg)
            elif item.column() == 5:
                seg.enabled = item.checkState() == Qt.CheckState.Checked
            elif item.column() == 6:
                seg.word_mark = item.checkState() == Qt.CheckState.Checked
        except ValueError:
            # 时间解析失败：恢复显示原值
            self._refresh_table()
            return
        self.segments_changed.emit()

    def _on_selection_changed(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if selected:
            self.segment_selected.emit(selected[0].row())

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    # -- 合并 / 拆分 / 删除 --------------------------------------------------
    def merge_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) < 2:
            return
        rows = sorted(rows)
        merged = self._segments[rows[0]]
        for row in rows[1:]:
            merged = merge_segments(merged, self._segments[row])
        new_segments = [
            seg for i, seg in enumerate(self._segments) if i not in rows[1:]
        ]
        new_segments[rows[0]] = merged
        self._segments = new_segments
        self._reindex()
        self._refresh_table()
        self.segments_changed.emit()

    def split_selected(self, at_seconds: float | None = None) -> None:
        rows = self.selected_rows()
        if len(rows) != 1:
            return
        row = rows[0]
        seg = self._segments[row]
        point = at_seconds
        if point is None or not (seg.start < point < seg.end):
            point = (seg.start + seg.end) / 2
        try:
            left, right = split_segment(seg, point)
        except ValueError:
            return
        self._segments[row:row + 1] = [left, right]
        self._reindex()
        self._refresh_table()
        self.segments_changed.emit()

    def delete_selected(self) -> None:
        rows = set(self.selected_rows())
        if not rows:
            return
        self._segments = [
            seg for i, seg in enumerate(self._segments) if i not in rows
        ]
        self._reindex()
        self._refresh_table()
        self.segments_changed.emit()
