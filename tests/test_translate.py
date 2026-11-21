"""翻译器测试：翻译路线（直达 / 英语中转 / 同语言）与语言排序。

纯逻辑测试，不联网、不依赖 argostranslate 是否安装：
凡是需要走加载链的用例，都用假的 argostranslate 模块 + 假的翻译对象。
"""

import sys
import types

import pytest

from subbridge.core.translate import (
    SUPPORTED_LANGUAGES,
    TranslateConfig,
    Translator,
    _NoPackageError,
    ordered_languages,
    translation_path,
)


# -- 翻译路线 ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("source", "target"),
    [("en", "zh"), ("zh", "en"), ("en", "ja"), ("ja", "en"), ("es", "pt"), ("pt", "es")],
)
def test_translation_path_direct(source, target):
    assert translation_path(source, target) == [(source, target)]


@pytest.mark.parametrize(
    ("source", "target"),
    [("ja", "zh"), ("ko", "zh"), ("fr", "zh"), ("de", "zh"), ("fr", "de"), ("ja", "ko")],
)
def test_translation_path_pivot_via_english(source, target):
    assert translation_path(source, target) == [
        (source, "en"),
        ("en", target),
    ]


def test_translation_path_same_language():
    assert translation_path("zh", "zh") == []
    assert translation_path("en", "en") == []


def test_ordered_languages_featured_first():
    ordered = ordered_languages()
    assert [code for code, _ in ordered[:6]] == ["zh", "en", "ja", "ko", "fr", "de"]
    assert [code for code, _ in ordered] == list(
        dict.fromkeys(["zh", "en", "ja", "ko", "fr", "de"] + list(SUPPORTED_LANGUAGES))
    )


# -- 翻译链（假 argos） ------------------------------------------------------


class _FakeTranslation:
    """假的单语言对翻译对象：在文本后打上语言对标记。"""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def translate(self, text: str) -> str:
        return f"{text}{self.tag}"


@pytest.fixture
def _fake_argos(monkeypatch):
    """往 sys.modules 里塞假的 argostranslate 模块，让懒加载 import 能成功。"""
    for name in ("argostranslate", "argostranslate.package", "argostranslate.translate"):
        module = types.ModuleType(name)
        sys.modules[name] = module
        monkeypatch.setattr(sys, "modules", sys.modules)
    yield
    for name in ("argostranslate", "argostranslate.package", "argostranslate.translate"):
        sys.modules.pop(name, None)


def _fake_load_pair(self, package, translate, from_code, to_code):
    return _FakeTranslation(f"[{from_code}-{to_code}]")


def test_translate_pivot_applies_two_steps_in_order(monkeypatch, _fake_argos):
    monkeypatch.setattr(Translator, "_load_pair", _fake_load_pair)
    translator = Translator(TranslateConfig(source_lang="ja", target_lang="zh"))
    assert translator.translate("こんにちは") == "こんにちは[ja-en][en-zh]"
    assert translator.route_description() == "日语 → 英语 → 中文（经英语中转）"


def test_translate_direct_applies_one_step(monkeypatch, _fake_argos):
    monkeypatch.setattr(Translator, "_load_pair", _fake_load_pair)
    translator = Translator(TranslateConfig(source_lang="en", target_lang="zh"))
    assert translator.translate("Hello") == "Hello[en-zh]"
    assert translator.route_description() == "英语 → 中文"


def test_translate_same_language_returns_text_unchanged():
    # 同语言不需要 argos：即使没装 argostranslate 也不报错。
    translator = Translator(TranslateConfig(source_lang="zh", target_lang="zh"))
    assert translator.translate("你好") == "你好"
    assert translator.route_description() == "源语言与目标语言相同，无需翻译"


def test_load_chain_falls_back_to_pivot_when_direct_missing(monkeypatch, _fake_argos):
    """直达包突然没了（索引有变）时，自动改走英语中转。"""
    import subbridge.core.translate as translate_module

    monkeypatch.setattr(
        translate_module, "translation_path", lambda s, t: [(s, t)]
    )

    def _flaky_load_pair(self, package, translate, from_code, to_code):
        if (from_code, to_code) == ("ja", "zh"):
            raise _NoPackageError("argos 官方索引中没有 ja → zh 的语言包")
        return _FakeTranslation(f"[{from_code}-{to_code}]")

    monkeypatch.setattr(Translator, "_load_pair", _flaky_load_pair)
    translator = Translator(TranslateConfig(source_lang="ja", target_lang="zh"))
    assert translator.translate("こんにちは") == "こんにちは[ja-en][en-zh]"
