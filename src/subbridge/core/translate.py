"""argos-translate 本地离线翻译封装（懒加载）。

首次翻译某语言对时，若本地没有语言包，会自动从 Argos 索引下载安装
（需要联网一次，之后完全离线使用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .subtitles import Segment

__all__ = [
    "FEATURED_LANGUAGES",
    "PIVOT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "TranslateError",
    "Translator",
    "ordered_languages",
    "translation_path",
]

# 界面可选语言：代码 -> 中文名（argos 实际可用的语言包以官方索引为准）。
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "英语",
    "zh": "中文",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "pt": "葡萄牙语",
    "it": "意大利语",
    "ru": "俄语",
    "ar": "阿拉伯语",
    "nl": "荷兰语",
    "pl": "波兰语",
    "tr": "土耳其语",
    "vi": "越南语",
    "id": "印尼语",
    "th": "泰语",
}


# 中国网友最感兴趣的五种外语：英语、日语、韩语、法语、德语
# （年轻网民中最受欢迎的五种外语排名），加中文共六种排在界面前面。
FEATURED_LANGUAGES: list[str] = ["zh", "en", "ja", "ko", "fr", "de"]

# 中转语言：argos 官方语言包索引（2026-11-22 核查，共 100 个包）里，
# 到中文的直达包只有英语 → 中文；日语/韩语/法语/德语等语言到中文
# 都要先译成英语、再由英语译成中文（两跳中转）。
PIVOT_LANGUAGE = "en"

# 除英语外唯一有直达包的语言对（索引核查结果）。
_DIRECT_EXTRA = {frozenset({"es", "pt"})}


def translation_path(source_lang: str, target_lang: str) -> list[tuple[str, str]]:
    """翻译路线：直达返回一跳，否则经英语中转返回两跳；同语言返回空列表。

    直达规则与 argos 官方索引一致：一端是英语即有直达包（另有西 ↔ 葡）。
    """
    if source_lang == target_lang:
        return []
    if (
        source_lang == PIVOT_LANGUAGE
        or target_lang == PIVOT_LANGUAGE
        or frozenset({source_lang, target_lang}) in _DIRECT_EXTRA
    ):
        return [(source_lang, target_lang)]
    return [(source_lang, PIVOT_LANGUAGE), (PIVOT_LANGUAGE, target_lang)]


def ordered_languages() -> list[tuple[str, str]]:
    """界面下拉框用的语言顺序：五种热门语言 + 中文排在前面，其余按原顺序。"""
    ordered = [
        (code, SUPPORTED_LANGUAGES[code])
        for code in FEATURED_LANGUAGES
        if code in SUPPORTED_LANGUAGES
    ]
    ordered.extend(
        (code, name)
        for code, name in SUPPORTED_LANGUAGES.items()
        if code not in FEATURED_LANGUAGES
    )
    return ordered


class TranslateError(Exception):
    """翻译失败（依赖缺失、语言包不可用、下载失败等）。"""


class _NoPackageError(TranslateError):
    """官方索引中没有该语言对的语言包（可改走中转时内部使用）。"""


@dataclass
class TranslateConfig:
    """翻译配置。"""

    source_lang: str = "en"
    target_lang: str = "zh"


class Translator:
    """argos-translate 翻译器（懒加载，自动管理语言包）。"""

    def __init__(self, config: TranslateConfig | None = None) -> None:
        self.config = config or TranslateConfig()
        self._chain: list | None = None  # 已加载的翻译步骤（直达 1 步，中转 2 步）
        self._pair: tuple[str, str] | None = None

    # -- 内部：加载语言包 -------------------------------------------------
    def _load_chain(self) -> list:
        """加载翻译链：直达一跳，否则经英语中转两跳；同语言返回空链。"""
        pair = (self.config.source_lang, self.config.target_lang)
        if self._chain is not None and self._pair == pair:
            return self._chain
        hops = translation_path(*pair)
        if not hops:
            # 同语言：无需翻译，也不依赖 argostranslate。
            self._chain = []
            self._pair = pair
            return []
        try:
            import argostranslate.package as package
            import argostranslate.translate as translate
        except ImportError as exc:
            raise TranslateError(
                "未安装 argostranslate，请先执行 pip install argostranslate"
            ) from exc

        try:
            chain = [
                self._load_pair(package, translate, from_code, to_code)
                for from_code, to_code in hops
            ]
        except _NoPackageError:
            # 直达包不存在（官方索引有变）：改走英语中转再试一次。
            if len(hops) == 1 and pair[0] != PIVOT_LANGUAGE and pair[1] != PIVOT_LANGUAGE:
                chain = [
                    self._load_pair(package, translate, from_code, to_code)
                    for from_code, to_code in [
                        (pair[0], PIVOT_LANGUAGE),
                        (PIVOT_LANGUAGE, pair[1]),
                    ]
                ]
            else:
                raise
        self._chain = chain
        self._pair = pair
        return chain

    def _load_pair(self, package, translate, from_code: str, to_code: str):
        """加载单个语言对的翻译对象：已安装直接取，未安装则下载安装。

        官方索引中没有该语言对时抛 _NoPackageError（调用方可改走中转）。
        """
        installed = translate.get_installed_languages()
        from_lang = next((l for l in installed if l.code == from_code), None)
        to_lang = next((l for l in installed if l.code == to_code), None)
        if from_lang is not None and to_lang is not None:
            translation = from_lang.get_translation(to_lang)
            if translation is not None:
                return translation
        # 语言包未安装：从官方索引下载安装（首次需要联网）。
        return self._install_pair(package, translate, from_code, to_code)

    def _install_pair(self, package, translate, from_code: str, to_code: str):
        try:
            package.update_package_index()
            available = package.get_available_packages()
            candidates = [
                p
                for p in available
                if p.from_code == from_code and p.to_code == to_code
            ]
            if not candidates:
                raise _NoPackageError(
                    f"argos 官方索引中没有 {from_code} → {to_code} 的语言包"
                )
            pkg = candidates[0]
            path = pkg.download()
            package.install_from_path(path)
        except _NoPackageError:
            raise
        except Exception as exc:
            raise TranslateError(
                f"下载语言包 {from_code} → {to_code} 失败：{exc}"
            ) from exc
        installed = translate.get_installed_languages()
        from_lang = next((l for l in installed if l.code == from_code), None)
        to_lang = next((l for l in installed if l.code == to_code), None)
        if from_lang is None or to_lang is None:
            raise TranslateError(f"语言包 {from_code} → {to_code} 安装后仍不可用")
        translation = from_lang.get_translation(to_lang)
        if translation is None:
            raise TranslateError(f"语言包 {from_code} → {to_code} 安装后仍不可用")
        return translation

    # -- 翻译 -------------------------------------------------------------
    def translate(self, text: str) -> str:
        """翻译单段文本（中转语言对会依次过两跳；同语言直接返回原文）。"""
        if not text.strip():
            return ""
        chain = self._load_chain()
        if not chain:
            return text
        try:
            for step in chain:
                text = step.translate(text)
            return text
        except Exception as exc:
            raise TranslateError(f"翻译失败：{exc}") from exc

    def route_description(self) -> str:
        """当前语言对的翻译路线中文描述，如“日语 → 英语 → 中文（经英语中转）”。"""
        hops = translation_path(self.config.source_lang, self.config.target_lang)
        if not hops:
            return "源语言与目标语言相同，无需翻译"
        codes = [hops[0][0]] + [to_code for _, to_code in hops]
        route = " → ".join(SUPPORTED_LANGUAGES.get(code, code) for code in codes)
        if len(hops) > 1:
            route += "（经英语中转）"
        return route

    def translate_segments(
        self,
        segments: list[Segment],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> list[Segment]:
        """逐条翻译字幕段，就地填充 segment.translation。"""
        total = len(segments)
        for index, segment in enumerate(segments, start=1):
            if segment.text.strip():
                segment.translation = self.translate(segment.text)
            if progress_callback:
                progress_callback(
                    index / max(1, total),
                    f"正在翻译 {index} / {total}",
                )
        if progress_callback:
            progress_callback(1.0, f"翻译完成，共 {total} 条")
        return segments

    @staticmethod
    def installed_language_codes() -> list[str]:
        """已安装语言包的语言代码（未安装 argos 时返回空列表）。"""
        try:
            import argostranslate.translate as translate
        except ImportError:
            return []
        return [lang.code for lang in translate.get_installed_languages()]
