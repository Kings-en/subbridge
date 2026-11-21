"""NLLB 直达翻译测试（纯逻辑，不联网、不下载模型）。

模型加载用假的 ctranslate2 / sentencepiece 对象代替；
真实模型直达翻译已在沙箱实测（日/韩/法/德/英 → 中文均正常，短句约 1 秒）。
"""

import pytest

from subbridge.core.nllb import (
    NLLB_LANGUAGE_CODES,
    NLLB_MODEL_FILES,
    NLLBConfig,
    NLLBError,
    NLLBTranslator,
)
from subbridge.core.subtitles import Segment
from subbridge.core.translate import (
    SUPPORTED_LANGUAGES,
    TranslateConfig,
    Translator,
)


# -- 语言代码 ---------------------------------------------------------------


def test_nllb_covers_all_supported_languages():
    for code in SUPPORTED_LANGUAGES:
        assert code in NLLB_LANGUAGE_CODES, f"缺少 NLLB 代码：{code}"
    assert NLLB_LANGUAGE_CODES["ja"] == "jpn_Jpan"
    assert NLLB_LANGUAGE_CODES["zh"] == "zho_Hans"
    assert NLLB_LANGUAGE_CODES["en"] == "eng_Latn"


def test_model_files_complete():
    assert "model.bin" in NLLB_MODEL_FILES
    assert "sentencepiece.bpe.model" in NLLB_MODEL_FILES
    assert "config.json" in NLLB_MODEL_FILES


# -- 假的 ctranslate2 / sentencepiece ----------------------------------------


class _FakeResult:
    def __init__(self, hypotheses):
        self.hypotheses = [hypotheses]


class _FakeCTranslator:
    """记录调用参数，输出里回显目标语言码（与真实 CTranslate2 行为一致）。"""

    def __init__(self):
        self.calls = []

    def translate_batch(self, batch, target_prefix=None, beam_size=1):
        self.calls.append(
            {"batch": batch, "target_prefix": target_prefix, "beam_size": beam_size}
        )
        target_code = target_prefix[0][0]
        # 回显目标语言码 + 假译文（“世界”不带 ▁，与真实模型输出一致）。
        return [_FakeResult([target_code, "▁你好", "，", "世界"])]


class _FakeSP:
    def encode(self, text, out_type=str):
        return ["▁" + text]

    def decode(self, tokens):
        return "".join(tokens).replace("▁", " ").strip()


@pytest.fixture
def _fake_nllb(monkeypatch):
    fake_translator = _FakeCTranslator()
    fake_sp = _FakeSP()
    monkeypatch.setattr(
        NLLBTranslator,
        "_load",
        lambda self: (fake_translator, fake_sp),
    )
    return fake_translator


# -- 翻译 -------------------------------------------------------------------


def test_translate_direct_input_format_and_prefix_stripped(_fake_nllb):
    translator = NLLBTranslator(NLLBConfig(source_lang="ja", target_lang="zh"))
    assert translator.translate("こんにちは") == "你好，世界"
    call = _fake_nllb.calls[0]
    # 输入格式：["<s>", 源语言码] + 分词 + ["</s>"]。
    assert call["batch"][0][:2] == ["<s>", "jpn_Jpan"]
    assert call["batch"][0][-1] == "</s>"
    assert call["target_prefix"] == [["zho_Hans"]]
    assert call["beam_size"] == 4


def test_translate_same_language_returns_text_unchanged(_fake_nllb):
    translator = NLLBTranslator(NLLBConfig(source_lang="zh", target_lang="zh"))
    assert translator.translate("你好") == "你好"
    assert _fake_nllb.calls == []


def test_translate_empty_returns_empty(_fake_nllb):
    translator = NLLBTranslator(NLLBConfig(source_lang="ja", target_lang="zh"))
    assert translator.translate("   ") == ""
    assert _fake_nllb.calls == []


def test_translate_unsupported_language_raises(_fake_nllb):
    translator = NLLBTranslator(NLLBConfig(source_lang="xx", target_lang="zh"))
    with pytest.raises(NLLBError):
        translator.translate("hello")


def test_translate_segments_fills_translations(monkeypatch):
    translator = NLLBTranslator(NLLBConfig(source_lang="en", target_lang="zh"))
    monkeypatch.setattr(
        translator, "translate", lambda text: f"译：{text}"
    )
    segments = [
        Segment(index=1, start=0.0, end=1.0, text="Hello"),
        Segment(index=2, start=1.0, end=2.0, text="World"),
    ]
    progress = []
    out = translator.translate_segments(
        segments, progress_callback=lambda p, m: progress.append((p, m))
    )
    assert [s.translation for s in out] == ["译：Hello", "译：World"]
    assert progress[-1][0] == 1.0


# -- 引擎切换 -----------------------------------------------------------------


def test_translator_delegates_to_nllb(monkeypatch):
    translator = Translator(
        TranslateConfig(source_lang="ja", target_lang="zh", engine="nllb")
    )
    seen = {}

    class _FakeNLLB:
        def translate(self, text):
            seen["text"] = text
            return "直达译文"

        def translate_segments(self, segments, progress_callback=None):
            seen["segments"] = len(segments)
            return segments

    monkeypatch.setattr(translator, "_get_nllb", lambda: _FakeNLLB())
    assert translator.translate("こんにちは") == "直达译文"
    assert seen["text"] == "こんにちは"
    assert translator.route_description() == "NLLB 直达：日语 → 中文"


def test_translator_argos_route_unchanged():
    translator = Translator(TranslateConfig(source_lang="ja", target_lang="zh"))
    assert translator.route_description() == "日语 → 英语 → 中文（经英语中转）"
