"""词对齐测试（纯逻辑，不联网、不依赖 GUI）。"""

from subbridge.core.align import (
    HeuristicAligner,
    align_segment,
    realign_after_edit,
    tokenize,
)
from subbridge.core.subtitles import Segment, Word


def test_tokenize_english():
    assert tokenize("Hello, world!", "en") == ["Hello", ",", "world", "!"]
    assert tokenize("", "en") == []


def test_tokenize_chinese():
    # 中文按字切分，拉丁串保持整体
    assert tokenize("你好，世界", "zh") == ["你", "好", "，", "世", "界"]
    assert tokenize("你好World", "zh") == ["你", "好", "World"]


def test_align_empty_inputs():
    aligner = HeuristicAligner()
    assert aligner.align([], ["你好"]).pairs == []
    assert aligner.align(["Hello"], []).pairs == []


def test_align_numbers_anchor():
    aligner = HeuristicAligner()
    alignment = aligner.align(
        ["I", "have", "3", "apples"], ["我", "有", "3", "个", "苹", "果"]
    )
    # 数字 3 必须对上数字 3
    assert alignment.targets_for(2) == [2]
    # 每个源词都有归属
    assert len(alignment.pairs) == 4


def test_align_punctuation_equivalent():
    aligner = HeuristicAligner()
    alignment = aligner.align(["Hello", ",", "world"], ["你", "好", "，", "世", "界"])
    # 英文逗号对上中文逗号
    assert alignment.targets_for(1) == [2]


def test_align_dictionary_match():
    aligner = HeuristicAligner()
    alignment = aligner.align(["Hello", "world"], ["你", "好", "世", "界"])
    # hello 在词典里对应“你好”，应落在前两个字之一
    assert alignment.targets_for(0) in ([0], [1])


def test_align_monotonic():
    aligner = HeuristicAligner()
    src = "one two three four five six seven eight".split()
    tgt = list("一二三四五六七八")
    alignment = aligner.align(src, tgt)
    targets = [p.target_index for p in alignment.pairs]
    assert targets == sorted(targets)  # 译文下标单调不减
    assert len(alignment.pairs) == len(src)


def test_align_identical_tokens():
    aligner = HeuristicAligner()
    alignment = aligner.align(
        ["Python", "is", "great"], ["Python", "很", "棒"]
    )
    # 专名 Python 相同，应优先对上
    assert alignment.targets_for(0) == [0]


def test_align_segment_fills_colors_and_words():
    seg = Segment(
        index=1,
        start=1.0,
        end=4.0,
        text="Hello world",
        translation="你好世界",
        words=[
            Word(text="Hello", start=1.0, end=2.0),
            Word(text="world", start=2.0, end=4.0),
        ],
    )
    align_segment(seg, target_lang="zh")
    assert len(seg.translation_words) == 4  # 你 好 世 界
    # 每个源词都有颜色与译文词
    assert all(w.color_index >= 0 for w in seg.words)
    assert all(w.translation for w in seg.words)
    # 词对颜色按顺序 8 色循环：第一个词对颜色 0，第二个 1
    assert seg.words[0].color_index == 0
    assert seg.words[1].color_index == 1
    # 译文词带上对应颜色
    assert any(w.color_index == 0 for w in seg.translation_words)
    assert any(w.color_index == 1 for w in seg.translation_words)


def test_align_segment_without_translation_is_noop():
    seg = Segment(index=1, start=1.0, end=2.0, text="Hello")
    result = align_segment(seg, target_lang="zh")
    assert result.translation_words == []


def test_realign_after_edit():
    seg = Segment(
        index=1,
        start=1.0,
        end=4.0,
        text="Hello world",
        translation="你好世界",
        words=[
            Word(text="Hello", start=1.0, end=2.0),
            Word(text="world", start=2.0, end=4.0),
        ],
    )
    align_segment(seg, target_lang="zh")
    assert seg.words[0].color_index >= 0
    seg.translation = "你好，朋友"
    realign_after_edit(seg, target_lang="zh")
    # 重对齐后仍有颜色，且译文词按新译文分词
    assert all(w.color_index >= 0 for w in seg.words)
    assert "".join(w.text for w in seg.translation_words) == "你好，朋友"
