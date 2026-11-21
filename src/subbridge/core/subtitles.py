"""字幕数据模型与 SRT / VTT / ASS 解析、写出。

本模块是纯 Python，不依赖任何界面库与操作系统专属 API。
时间统一用秒（float）表示；写出时再格式化为各字幕格式的时间串。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "Word",
    "Segment",
    "WORD_COLORS",
    "parse_time",
    "format_srt_time",
    "format_vtt_time",
    "format_ass_time",
    "parse_srt",
    "parse_vtt",
    "parse_ass",
    "parse_subtitle_file",
    "write_srt",
    "write_vtt",
    "write_ass",
    "merge_segments",
    "split_segment",
    "join_tokens",
    "strip_ass_tags",
]

# ---------------------------------------------------------------------------
# 词对颜色：8 色循环（ASS 用 BGR 顺序，界面用 HTML 十六进制）
# 每个颜色元组为 (名称, ASS-BGR, HTML-RGB)。
# ---------------------------------------------------------------------------
WORD_COLORS: list[tuple[str, str, str]] = [
    ("红", "0000FF", "#FF0000"),
    ("橙", "00A5FF", "#FFA500"),
    ("黄", "00FFFF", "#FFFF00"),
    ("绿", "53C800", "#00C853"),
    ("青", "D4BC00", "#00BCD4"),
    ("蓝", "FF8A44", "#448AFF"),
    ("紫", "B0279C", "#9C27B0"),
    ("粉", "631EE9", "#E91E63"),
]


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class Word:
    """一个单词（或一个中文字符）及其时间戳。"""

    text: str
    start: float = 0.0
    end: float = 0.0
    # 对齐到的译文词（学习模式）；未对齐时为空字符串。
    translation: str = ""
    # 词对颜色编号（0-7），-1 表示未着色。
    color_index: int = -1


@dataclass
class Segment:
    """一条字幕。"""

    index: int = 0
    start: float = 0.0
    end: float = 0.0
    text: str = ""  # 原文
    translation: str = ""  # 译文（整句）
    words: list[Word] = field(default_factory=list)  # 原文词级时间戳
    # 译文分词（学习模式下与 words 一一对应着色）；start/end 无意义。
    translation_words: list[Word] = field(default_factory=list)
    enabled: bool = True  # 导出时是否包含本条
    # 本条是否启用词标记（编辑器里可逐条开关）。
    word_mark: bool = True


# ---------------------------------------------------------------------------
# 时间解析与格式化
# ---------------------------------------------------------------------------
_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def parse_time(text: str) -> float:
    """解析 ``HH:MM:SS,mmm`` 或 ``HH:MM:SS.mmm`` 为秒。"""
    match = _TIME_RE.search(text.strip())
    if not match:
        raise ValueError(f"无法解析时间戳：{text!r}")
    hours, minutes, seconds, millis = match.groups()
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def format_srt_time(seconds: float) -> str:
    """格式化为 SRT 时间串 ``HH:MM:SS,mmm``。"""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_time(seconds: float) -> str:
    """格式化为 VTT 时间串 ``HH:MM:SS.mmm``。"""
    return format_srt_time(seconds).replace(",", ".")


def format_ass_time(seconds: float) -> str:
    """格式化为 ASS 时间串 ``H:MM:SS.cc``。"""
    total_cs = max(0, int(round(seconds * 100)))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


# ---------------------------------------------------------------------------
# 文本拼接（中英文混排时正确处理空格）
# ---------------------------------------------------------------------------
_CJK_RE = re.compile(r"[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef]")
_CJK_PUNCT = set("，。、；：？！·…—～（）《》「」『』【】")


def _is_cjk_char(ch: str) -> bool:
    return bool(_CJK_RE.match(ch))


def join_tokens(tokens: list[str]) -> str:
    """把分词结果拼回自然文本：中文字符之间不加空格，拉丁词之间加空格。"""
    result = ""
    for token in tokens:
        if not token:
            continue
        if result:
            prev = result[-1]
            cur = token[0]
            if (
                not _is_cjk_char(prev)
                and not _is_cjk_char(cur)
                and prev not in "([{\"'"
                and cur not in ".,!?;:'\"”’）】」』"
                and prev not in _CJK_PUNCT
            ):
                result += " "
        result += token
    return result


def strip_ass_tags(text: str) -> str:
    """去掉 ASS 行内样式标记 ``{...}`` 与换行符 ``\\N``。"""
    text = re.sub(r"\{[^}]*\}", "", text)
    return text.replace("\\N", " ").replace("\\n", " ").strip()


# ---------------------------------------------------------------------------
# SRT 解析与写出
# ---------------------------------------------------------------------------
_SRT_TIME_LINE_RE = re.compile(r"(.+?)\s*-->\s*(.+)")


def parse_srt(content: str) -> list[Segment]:
    """解析 SRT 文本。译文行：若一条字幕有多行文本，第 2 行视为译文。"""
    segments: list[Segment] = []
    blocks = re.split(r"\r?\n\r?\n", content.strip())
    for block in blocks:
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        # 首行可能是序号
        time_line = lines[0] if "-->" in lines[0] else (lines[1] if len(lines) > 1 else "")
        if "-->" not in time_line:
            continue
        text_lines = lines[1:] if "-->" in lines[0] else lines[2:]
        match = _SRT_TIME_LINE_RE.match(time_line)
        if not match:
            continue
        try:
            start = parse_time(match.group(1))
            end = parse_time(match.group(2))
        except ValueError:
            continue
        if not text_lines:
            continue
        segments.append(
            Segment(
                index=len(segments) + 1,
                start=start,
                end=end,
                text=text_lines[0].strip(),
                translation=text_lines[1].strip() if len(text_lines) > 1 else "",
            )
        )
    return segments


def write_srt(segments: list[Segment], bilingual: bool = True) -> str:
    """写出 SRT。双语模式下每条字幕输出原文行 + 译文行。"""
    out: list[str] = []
    number = 0
    for seg in segments:
        if not seg.enabled:
            continue
        number += 1
        out.append(str(number))
        out.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
        out.append(seg.text)
        if bilingual and seg.translation:
            out.append(seg.translation)
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# VTT 解析与写出
# ---------------------------------------------------------------------------
def parse_vtt(content: str) -> list[Segment]:
    """解析 WebVTT 文本（忽略样式设置与 NOTE 注释块）。"""
    segments: list[Segment] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            i += 1
            continue
        if "-->" in line:
            match = _SRT_TIME_LINE_RE.match(line)
            if not match:
                i += 1
                continue
            try:
                start = parse_time(match.group(1))
                end = parse_time(match.group(2))
            except ValueError:
                i += 1
                continue
            i += 1
            text_lines: list[str] = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            if text_lines:
                segments.append(
                    Segment(
                        index=len(segments) + 1,
                        start=start,
                        end=end,
                        text=text_lines[0],
                        translation=text_lines[1] if len(text_lines) > 1 else "",
                    )
                )
            continue
        i += 1
    return segments


def write_vtt(segments: list[Segment], bilingual: bool = True) -> str:
    """写出 WebVTT。"""
    out = ["WEBVTT", ""]
    for seg in segments:
        if not seg.enabled:
            continue
        out.append(f"{format_vtt_time(seg.start)} --> {format_vtt_time(seg.end)}")
        out.append(seg.text)
        if bilingual and seg.translation:
            out.append(seg.translation)
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# ASS 解析与写出
# ---------------------------------------------------------------------------
def _parse_ass_time(text: str) -> float:
    """解析 ASS 时间 ``H:MM:SS.cc``（百分秒）。"""
    match = re.match(r"(\d+):(\d+):(\d+)\.(\d+)", text.strip())
    if not match:
        raise ValueError(f"无法解析 ASS 时间戳：{text!r}")
    hours, minutes, seconds, centis = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centis) / 100.0


def parse_ass(content: str) -> list[Segment]:
    """解析 ASS 文件的 [Events] 段 Dialogue 行，剥离样式标记。"""
    segments: list[Segment] = []
    in_events = False
    format_fields: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_events = line.lower() == "[events]"
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            format_fields = [f.strip().lower() for f in line[len("format:"):].split(",")]
            continue
        if line.lower().startswith("dialogue:"):
            body = line[len("dialogue:"):].strip()
            # 按 Format 字段顺序取 Start / End / Text；默认顺序兜底。
            if format_fields and "start" in format_fields and "end" in format_fields:
                parts = body.split(",", len(format_fields) - 1)
                if len(parts) < len(format_fields):
                    continue
                values = dict(zip(format_fields, parts))
                start_s, end_s, text_s = values["start"], values["end"], values["text"]
            else:
                parts = body.split(",", 9)
                if len(parts) < 10:
                    continue
                start_s, end_s, text_s = parts[1], parts[2], parts[9]
            try:
                # ASS 时间固定是 H:MM:SS.cc（百分秒），不能走 parse_time（毫秒）。
                start = _parse_ass_time(start_s)
                end = _parse_ass_time(end_s)
            except ValueError:
                continue
            clean = strip_ass_tags(text_s)
            if not clean:
                continue
            segments.append(
                Segment(
                    index=len(segments) + 1,
                    start=start,
                    end=end,
                    text=clean,
                )
            )
    return segments


def _ass_color_fragments(
    words: list[Word],
) -> list[tuple[str, str | None]]:
    """把单词列表转成 ASS 片段：(文本, BGR 颜色或 None)。"""
    fragments: list[tuple[str, str | None]] = []
    for word in words:
        color = None
        if word.color_index >= 0:
            color = WORD_COLORS[word.color_index % len(WORD_COLORS)][1]
        fragments.append((word.text, color))
    return fragments


def _render_ass_fragments(fragments: list[tuple[str, str | None]]) -> str:
    """把带颜色的片段渲染成 ASS 行内文本。"""
    parts: list[str] = []
    prev_text = ""
    for text, color in fragments:
        if not text:
            continue
        if parts:
            prev_char = prev_text[-1]
            cur_char = text[0]
            if (
                not _is_cjk_char(prev_char)
                and not _is_cjk_char(cur_char)
                and prev_char not in "([{\"'"
                and cur_char not in ".,!?;:'\"”’）】」』"
                and prev_char not in _CJK_PUNCT
            ):
                parts.append(" ")
        if color:
            parts.append(f"{{\\1c&H{color}&}}{text}{{\\r}}")
        else:
            parts.append(text)
        prev_text = text
    return "".join(parts)


def write_ass(
    segments: list[Segment],
    bilingual: bool = True,
    word_mark: bool = False,
) -> str:
    """写出 ASS。

    word_mark=True 时按词对颜色标记（8 色循环）：原文词与译文词用相同颜色。
    """
    lines: list[str] = []
    lines.append("[Script Info]")
    lines.append("; SubBridge 生成")
    lines.append("Title: SubBridge")
    lines.append("ScriptType: v4.00+")
    lines.append("PlayResX: 1280")
    lines.append("PlayResY: 720")
    lines.append("WrapStyle: 0")
    lines.append("ScaledBorderAndShadow: yes")
    lines.append("")
    lines.append("[V4+ Styles]")
    lines.append(
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    lines.append(
        "Style: Default,Microsoft YaHei,28,&H00FFFFFF,&H000000FF,&H80000000,"
        "&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1"
    )
    lines.append("")
    lines.append("[Events]")
    lines.append(
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text"
    )
    for seg in segments:
        if not seg.enabled:
            continue
        start = format_ass_time(seg.start)
        end = format_ass_time(seg.end)
        if word_mark and seg.word_mark and seg.words:
            src_text = _render_ass_fragments(_ass_color_fragments(seg.words))
            if bilingual and seg.translation_words:
                tgt_text = _render_ass_fragments(
                    _ass_color_fragments(seg.translation_words)
                )
                text = f"{src_text}\\N{tgt_text}"
            elif bilingual and seg.translation:
                text = f"{src_text}\\N{seg.translation}"
            else:
                text = src_text
        else:
            if bilingual and seg.translation:
                text = f"{seg.text}\\N{seg.translation}"
            else:
                text = seg.text
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 通用入口与编辑操作
# ---------------------------------------------------------------------------
def parse_subtitle_file(path: str, encoding: str = "utf-8") -> list[Segment]:
    """按扩展名解析字幕文件（.srt / .vtt / .ass）。"""
    with open(path, "r", encoding=encoding, errors="replace") as handle:
        content = handle.read()
    lower = path.lower()
    if lower.endswith(".ass") or lower.endswith(".ssa"):
        return parse_ass(content)
    if lower.endswith(".vtt"):
        return parse_vtt(content)
    return parse_srt(content)


def merge_segments(first: Segment, second: Segment) -> Segment:
    """合并两条相邻字幕：时间取并集，文本用空格连接，词级时间戳拼接。"""
    merged_words = list(first.words) + list(second.words)
    merged_translation_words = list(first.translation_words) + list(
        second.translation_words
    )
    return Segment(
        index=first.index,
        start=min(first.start, second.start),
        end=max(first.end, second.end),
        text=join_tokens([first.text, second.text])
        if first.text and second.text
        else (first.text or second.text),
        translation=join_tokens([first.translation, second.translation])
        if first.translation and second.translation
        else (first.translation or second.translation),
        words=merged_words,
        translation_words=merged_translation_words,
        enabled=first.enabled and second.enabled,
        word_mark=first.word_mark and second.word_mark,
    )


def split_segment(segment: Segment, at_seconds: float) -> tuple[Segment, Segment]:
    """在指定时间点拆分一条字幕：词按时间归属，文本按词边界切分。"""
    if not (segment.start < at_seconds < segment.end):
        raise ValueError("拆分点必须在字幕时间范围内")
    left_words = [w for w in segment.words if w.start < at_seconds]
    right_words = [w for w in segment.words if w.start >= at_seconds]
    left = Segment(
        index=segment.index,
        start=segment.start,
        end=at_seconds,
        text=join_tokens([w.text for w in left_words]) if left_words else segment.text,
        words=left_words,
        enabled=segment.enabled,
        word_mark=segment.word_mark,
    )
    right = Segment(
        index=segment.index + 1,
        start=at_seconds,
        end=segment.end,
        text=join_tokens([w.text for w in right_words]) if right_words else segment.text,
        words=right_words,
        enabled=segment.enabled,
        word_mark=segment.word_mark,
    )
    # 拆分后译文无法按词切分，保留在左侧并清空右侧译文，由用户后续补填；
    # 若没有词级时间戳，则译文按字符比例粗分。
    if left_words or right_words:
        left.translation = segment.translation
        right.translation = ""
    else:
        total = max(1, len(segment.translation))
        ratio = (at_seconds - segment.start) / max(
            0.001, segment.end - segment.start
        )
        cut = int(total * ratio)
        left.translation = segment.translation[:cut]
        right.translation = segment.translation[cut:]
    return left, right
