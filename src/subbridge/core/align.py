"""词对齐：原文词与译文词的对应关系（学习模式的核心）。

v1 使用启发式对齐（位置比例 + 数字 / 标点 / 专名匹配 + 小型常用词词典），
不引入任何神经网络依赖，保持包体小、离线可用。对齐结果是近似的，
界面与文档中都会如实说明。

扩展口子：:class:`WordAligner` 是一个 Protocol，之后接入神经对齐器
（如 simalign / awesome-align）时只需实现同一接口并在设置里切换，
调用方代码不需要改动。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .subtitles import Segment, Word

__all__ = [
    "AlignmentPair",
    "Alignment",
    "WordAligner",
    "HeuristicAligner",
    "tokenize",
    "align_segment",
    "realign_after_edit",
    "EN_ZH_COMMON",
]

# ---------------------------------------------------------------------------
# 对齐结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AlignmentPair:
    """一对词的对应关系：源词下标 -> 译文词下标。"""

    source_index: int
    target_index: int


@dataclass
class Alignment:
    """一组词对。"""

    pairs: list[AlignmentPair]

    def targets_for(self, source_index: int) -> list[int]:
        """源词下标对应的全部译文词下标。"""
        return [p.target_index for p in self.pairs if p.source_index == source_index]

    def sources_for(self, target_index: int) -> list[int]:
        """译文词下标对应的全部源词下标。"""
        return [p.source_index for p in self.pairs if p.target_index == target_index]


class WordAligner(Protocol):
    """词对齐器协议。实现者只需实现 :meth:`align`。

    入参是已分词的源词与译文词列表；返回的词对下标按源词顺序排列，
    译文下标应尽量保持单调不减（允许一对多、多对一）。
    """

    def align(self, source_words: list[str], target_words: list[str]) -> Alignment:
        ...


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------
_CJK_RE = re.compile(r"[\u2e80-\u9fff]")
_TOKEN_RE_LATIN = re.compile(r"[A-Za-z0-9']+|[^\sA-Za-z0-9]")
_TOKEN_RE_CJK = re.compile(r"[A-Za-z0-9]+|[\u2e80-\u9fff]|[^\s\w]")


def tokenize(text: str, lang: str = "en") -> list[str]:
    """把文本切成词。

    - 中文（zh）：每个汉字一个词，拉丁字母/数字按连续串切分；
    - 其他语言：按空白与标点切分，保留标点为独立词（用于标点对应）。
    """
    if not text:
        return []
    pattern = _TOKEN_RE_CJK if lang.lower().startswith("zh") else _TOKEN_RE_LATIN
    return [m.group(0) for m in pattern.finditer(text) if m.group(0).strip()]


# ---------------------------------------------------------------------------
# 小型常用词词典（英 <-> 中），用于锚点匹配
# ---------------------------------------------------------------------------
EN_ZH_COMMON: dict[str, str] = {
    "hello": "你好",
    "hi": "你好",
    "goodbye": "再见",
    "bye": "再见",
    "thank": "谢谢",
    "thanks": "谢谢",
    "you": "你",
    "i": "我",
    "we": "我们",
    "he": "他",
    "she": "她",
    "they": "他们",
    "it": "它",
    "this": "这",
    "that": "那",
    "good": "好",
    "morning": "早上",
    "night": "晚上",
    "day": "天",
    "today": "今天",
    "tomorrow": "明天",
    "yesterday": "昨天",
    "yes": "是",
    "no": "不",
    "please": "请",
    "sorry": "对不起",
    "welcome": "欢迎",
    "love": "爱",
    "time": "时间",
    "people": "人",
    "world": "世界",
    "water": "水",
    "food": "食物",
    "house": "房子",
    "school": "学校",
    "work": "工作",
    "money": "钱",
    "friend": "朋友",
    "family": "家庭",
    "mother": "妈妈",
    "father": "爸爸",
    "child": "孩子",
    "book": "书",
    "cat": "猫",
    "dog": "狗",
    "big": "大",
    "small": "小",
    "new": "新",
    "old": "旧",
    "hot": "热",
    "cold": "冷",
    "happy": "高兴",
    "name": "名字",
    "one": "一",
    "two": "二",
    "three": "三",
    "four": "四",
    "five": "五",
    "man": "男人",
    "woman": "女人",
    "boy": "男孩",
    "girl": "女孩",
    "eat": "吃",
    "drink": "喝",
    "go": "去",
    "come": "来",
    "see": "看",
    "know": "知道",
    "think": "想",
    "want": "想",
    "like": "喜欢",
}

ZH_EN_COMMON: dict[str, str] = {v: k for k, v in EN_ZH_COMMON.items()}

# 中英文标点对应表
PUNCT_EQUIV: dict[str, str] = {
    "，": ",",
    "。": ".",
    "！": "!",
    "？": "?",
    "；": ";",
    "：": ":",
    "、": ",",
    "（": "(",
    "）": ")",
    "《": '"',
    "》": '"',
    "「": '"',
    "」": '"',
    "『": "'",
    "』": "'",
    "·": ".",
    "…": "...",
    "—": "-",
    "～": "~",
}


def _normalize_token(token: str) -> str:
    """用于比较的归一化形式：小写、去首尾空白、中文标点转英文标点。"""
    token = token.strip().lower()
    return PUNCT_EQUIV.get(token, token)


def _is_number(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", token))


def _is_punct(token: str) -> bool:
    return len(token) == 1 and not token.isalnum() and not _CJK_RE.match(token)


# ---------------------------------------------------------------------------
# 启发式对齐器
# ---------------------------------------------------------------------------
class HeuristicAligner:
    """启发式词对齐器（v1 近似对齐）。

    步骤：
    1. 锚点匹配：数字、标点、相同词、专名、常用词词典——这些高置信度词对先定下来；
    2. 位置比例填充：其余源词按 ``源词下标 / 源词总数 ≈ 译文下标 / 译文总数``
       映射到最近的未占用译文词，并强制保持单调不减；
    3. 仍未对上的源词允许与最近的译文词共享（多对一），保证每个源词都有归属。
    """

    def __init__(self, dictionary: dict[str, str] | None = None) -> None:
        self.dictionary = dict(EN_ZH_COMMON)
        if dictionary:
            self.dictionary.update(dictionary)

    def align(self, source_words: list[str], target_words: list[str]) -> Alignment:
        n_src = len(source_words)
        n_tgt = len(target_words)
        if n_src == 0 or n_tgt == 0:
            return Alignment(pairs=[])

        taken_tgt: set[int] = set()
        pairs: dict[int, int] = {}

        # -- 步骤 1：锚点匹配 ---------------------------------------------
        for src_idx, src in enumerate(source_words):
            src_norm = _normalize_token(src)
            best: int | None = None
            best_score = 0.0
            expected = src_idx * n_tgt / max(1, n_src)
            for tgt_idx, tgt in enumerate(target_words):
                if tgt_idx in taken_tgt:
                    continue
                tgt_norm = _normalize_token(tgt)
                score = 0.0
                if _is_number(src) and _is_number(tgt) and src == tgt:
                    score = 100.0  # 数字相同：最强锚点
                elif _is_punct(src) and _is_punct(tgt) and src_norm == tgt_norm:
                    score = 90.0  # 标点对应
                elif src_norm and src_norm == tgt_norm:
                    score = 80.0  # 相同词 / 专名
                elif self.dictionary.get(src_norm) == tgt or self.dictionary.get(src_norm) == tgt_norm:
                    score = 70.0  # 词典命中
                elif (
                    self.dictionary.get(src_norm)
                    and len(tgt) == 1
                    and tgt in self.dictionary[src_norm]
                ):
                    # 词典译文是多字词、目标按单字切分时：单字属于该译文
                    # 如 hello -> 你好，目标词“你”是“你好”的一部分
                    score = 60.0
                elif ZH_EN_COMMON.get(src) == tgt_norm:
                    score = 70.0
                if score == 0:
                    continue
                # 距离期望位置越近越优先（同分时取最近）
                score -= abs(tgt_idx - expected) * 0.5
                if score > best_score:
                    best_score = score
                    best = tgt_idx
            if best is not None:
                pairs[src_idx] = best
                taken_tgt.add(best)

        # -- 步骤 2：位置比例填充 -----------------------------------------
        last_tgt = -1
        for src_idx in range(n_src):
            if src_idx in pairs:
                last_tgt = max(last_tgt, pairs[src_idx])
                continue
            if n_src > 1:
                expected = int(round(src_idx * (n_tgt - 1) / (n_src - 1)))
            else:
                expected = 0
            expected = max(expected, last_tgt)  # 保持单调不减
            # 在期望位置附近找最近的空闲译文词
            chosen: int | None = None
            for offset in range(0, n_tgt):
                for cand in (expected + offset, expected - offset):
                    if 0 <= cand < n_tgt and cand not in taken_tgt and cand >= last_tgt:
                        chosen = cand
                        break
                if chosen is not None:
                    break
            if chosen is None:
                # 全部被占：与最近的译文词共享（多对一）
                chosen = min(max(expected, 0), n_tgt - 1)
            pairs[src_idx] = chosen
            taken_tgt.add(chosen)
            last_tgt = chosen

        ordered = [AlignmentPair(s, pairs[s]) for s in sorted(pairs)]
        return Alignment(pairs=ordered)


# ---------------------------------------------------------------------------
# 对整条字幕做词对齐（填充 Word.translation / color_index）
# ---------------------------------------------------------------------------
def align_segment(
    segment: Segment,
    target_lang: str = "zh",
    aligner: WordAligner | None = None,
) -> Segment:
    """对一条字幕做词对齐，就地填充词对颜色与译文词并返回该段。

    - 源词：segment.words（转录得到的词级时间戳；若为空，则从原文分词）；
    - 译文词：对 segment.translation 分词后生成 translation_words；
    - 颜色：按词对顺序 8 色循环。
    """
    aligner = aligner or HeuristicAligner()
    if not segment.translation:
        return segment

    if segment.words:
        source_texts = [w.text for w in segment.words]
    else:
        source_texts = tokenize(
            segment.text, "zh" if _looks_chinese(segment.text) else "en"
        )
    target_texts = tokenize(segment.translation, target_lang)
    if not source_texts or not target_texts:
        return segment

    alignment = aligner.align(source_texts, target_texts)

    # 若源词来自转录（带时间戳），直接在其上标注；否则新建 Word 列表。
    if segment.words:
        words = segment.words
    else:
        words = [Word(text=t) for t in source_texts]
        segment.words = words
    translation_words = [Word(text=t) for t in target_texts]

    for ordinal, pair in enumerate(alignment.pairs):
        color = ordinal % 8
        if 0 <= pair.source_index < len(words):
            words[pair.source_index].translation = target_texts[pair.target_index]
            words[pair.source_index].color_index = color
        if 0 <= pair.target_index < len(translation_words):
            translation_words[pair.target_index].color_index = color
            translation_words[pair.target_index].translation = source_texts[
                pair.source_index
            ]
    segment.translation_words = translation_words
    return segment


def _looks_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def realign_after_edit(
    segment: Segment,
    target_lang: str = "zh",
    aligner: WordAligner | None = None,
) -> Segment:
    """用户改了译文后调用：清空旧词对，用启发式重对齐。"""
    for word in segment.words:
        word.translation = ""
        word.color_index = -1
    segment.translation_words = []
    return align_segment(segment, target_lang=target_lang, aligner=aligner)
