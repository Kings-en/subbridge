"""字幕模型与 SRT / VTT / ASS 解析、写出测试（纯逻辑，不联网、不依赖 GUI）。"""

from subbridge.core.subtitles import (
    Segment,
    Word,
    format_ass_time,
    format_srt_time,
    merge_segments,
    parse_ass,
    parse_srt,
    parse_time,
    parse_vtt,
    split_segment,
    write_ass,
    write_srt,
    write_vtt,
)

SRT_SAMPLE = """1
00:00:01,000 --> 00:00:04,000
Hello world
你好，世界

2
00:00:05,500 --> 00:00:08,000
Good morning
早上好
"""

VTT_SAMPLE = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello world
你好，世界

00:00:05.500 --> 00:00:08.000
Good morning
"""

ASS_SAMPLE = """[Script Info]
Title: Test
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H00FFFFFF,&H000000FF,&H80000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,Hello {\\b1}world{\\r}
Dialogue: 0,0:00:05.50,0:00:08.00,Default,,0,0,0,,Good morning
"""


def test_parse_time():
    assert parse_time("00:00:01,000") == 1.0
    assert parse_time("01:02:03.456") == 3723.456
    assert parse_time("00:00:05,500") == 5.5


def test_format_times():
    assert format_srt_time(3723.456) == "01:02:03,456"
    assert format_srt_time(1.0) == "00:00:01,000"
    assert format_ass_time(65.5) == "0:01:05.50"
    assert format_ass_time(3723.456) == "1:02:03.46"


def test_parse_srt_bilingual():
    segments = parse_srt(SRT_SAMPLE)
    assert len(segments) == 2
    assert segments[0].start == 1.0
    assert segments[0].end == 4.0
    assert segments[0].text == "Hello world"
    assert segments[0].translation == "你好，世界"
    assert segments[1].start == 5.5


def test_srt_roundtrip_bilingual():
    segments = parse_srt(SRT_SAMPLE)
    out = write_srt(segments, bilingual=True)
    again = parse_srt(out)
    assert len(again) == 2
    assert again[0].text == "Hello world"
    assert again[0].translation == "你好，世界"
    assert again[1].translation == "早上好"


def test_srt_monolingual_skips_translation():
    segments = parse_srt(SRT_SAMPLE)
    out = write_srt(segments, bilingual=False)
    assert "你好" not in out
    assert "Hello world" in out


def test_parse_vtt():
    segments = parse_vtt(VTT_SAMPLE)
    assert len(segments) == 2
    assert segments[0].text == "Hello world"
    assert segments[0].translation == "你好，世界"
    assert segments[1].start == 5.5


def test_vtt_roundtrip():
    segments = parse_vtt(VTT_SAMPLE)
    out = write_vtt(segments, bilingual=True)
    assert out.startswith("WEBVTT")
    again = parse_vtt(out)
    assert len(again) == 2
    assert again[1].text == "Good morning"


def test_parse_ass_strips_tags():
    segments = parse_ass(ASS_SAMPLE)
    assert len(segments) == 2
    assert segments[0].text == "Hello world"
    assert segments[0].start == 1.0
    assert segments[0].end == 4.0
    assert segments[1].start == 5.5


def test_write_ass_word_mark_colors():
    seg = Segment(
        index=1,
        start=1.0,
        end=4.0,
        text="Hello world",
        translation="你好世界",
        words=[
            Word(text="Hello", start=1.0, end=2.0, translation="你好", color_index=0),
            Word(text="world", start=2.0, end=3.5, translation="世界", color_index=1),
        ],
        translation_words=[
            Word(text="你好", color_index=0),
            Word(text="世界", color_index=1),
        ],
    )
    out = write_ass([seg], bilingual=True, word_mark=True)
    # 词对颜色标记：红（0000FF）与橙（00A5FF）成对出现
    assert "\\1c&H0000FF&" in out
    assert "\\1c&H00A5FF&" in out
    assert "\\N" in out  # 双语换行
    # 能再解析回来（剥离标记后文本一致）
    parsed = parse_ass(out)
    assert len(parsed) == 1
    assert "Hello" in parsed[0].text and "world" in parsed[0].text


def test_write_ass_bilingual_plain():
    segments = parse_srt(SRT_SAMPLE)
    out = write_ass(segments, bilingual=True, word_mark=False)
    assert "[Script Info]" in out
    assert "[Events]" in out
    assert "Hello world\\N你好，世界" in out


def test_merge_segments():
    a = Segment(index=1, start=1.0, end=2.0, text="Hello", translation="你好",
                words=[Word(text="Hello", start=1.0, end=2.0)])
    b = Segment(index=2, start=2.0, end=3.0, text="world", translation="世界",
                words=[Word(text="world", start=2.0, end=3.0)])
    merged = merge_segments(a, b)
    assert merged.start == 1.0
    assert merged.end == 3.0
    assert merged.text == "Hello world"
    # 中文之间不加空格（join_tokens 的中文习惯）
    assert merged.translation == "你好世界"
    assert len(merged.words) == 2


def test_split_segment_by_words():
    seg = Segment(
        index=1,
        start=0.0,
        end=4.0,
        text="Hello world",
        translation="你好世界",
        words=[
            Word(text="Hello", start=0.0, end=2.0),
            Word(text="world", start=2.0, end=4.0),
        ],
    )
    left, right = split_segment(seg, 2.0)
    assert left.end == 2.0
    assert right.start == 2.0
    assert left.text == "Hello"
    assert right.text == "world"
    assert len(left.words) == 1 and len(right.words) == 1


def test_split_segment_without_words():
    seg = Segment(index=1, start=0.0, end=4.0, text="Hello world", translation="你好世界")
    left, right = split_segment(seg, 2.0)
    assert left.translation == "你好"
    assert right.translation == "世界"


def test_disabled_segment_skipped_on_export():
    seg = Segment(index=1, start=1.0, end=2.0, text="Hello", enabled=False)
    assert write_srt([seg]) == ""
    assert write_ass([seg]).count("Dialogue:") == 0
