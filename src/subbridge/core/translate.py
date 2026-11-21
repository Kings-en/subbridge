"""argos-translate 本地离线翻译封装（懒加载）。

首次翻译某语言对时，若本地没有语言包，会自动从 Argos 索引下载安装
（需要联网一次，之后完全离线使用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .subtitles import Segment

__all__ = [
    "SUPPORTED_LANGUAGES",
    "TranslateError",
    "Translator",
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


class TranslateError(Exception):
    """翻译失败（依赖缺失、语言包不可用、下载失败等）。"""


@dataclass
class TranslateConfig:
    """翻译配置。"""

    source_lang: str = "en"
    target_lang: str = "zh"


class Translator:
    """argos-translate 翻译器（懒加载，自动管理语言包）。"""

    def __init__(self, config: TranslateConfig | None = None) -> None:
        self.config = config or TranslateConfig()
        self._translation = None  # 已加载的语言对翻译对象
        self._pair: tuple[str, str] | None = None

    # -- 内部：加载语言包 -------------------------------------------------
    def _load_translation(self):
        pair = (self.config.source_lang, self.config.target_lang)
        if self._translation is not None and self._pair == pair:
            return self._translation
        try:
            import argostranslate.package as package
            import argostranslate.translate as translate
        except ImportError as exc:
            raise TranslateError(
                "未安装 argostranslate，请先执行 pip install argostranslate"
            ) from exc

        installed = translate.get_installed_languages()
        from_lang = next((l for l in installed if l.code == pair[0]), None)
        to_lang = next((l for l in installed if l.code == pair[1]), None)
        translation = None
        if from_lang is not None and to_lang is not None:
            translation = from_lang.get_translation(to_lang)
        if translation is None:
            # 语言包未安装：从官方索引下载安装（首次需要联网）。
            translation = self._install_package(package, translate, pair)
        self._translation = translation
        self._pair = pair
        return translation

    def _install_package(self, package, translate, pair):
        try:
            package.update_package_index()
            available = package.get_available_packages()
            candidates = [
                p for p in available if p.from_code == pair[0] and p.to_code == pair[1]
            ]
            if not candidates:
                raise TranslateError(
                    f"argos 官方索引中没有 {pair[0]} → {pair[1]} 的语言包，"
                    "请换一对语言再试"
                )
            pkg = candidates[0]
            path = pkg.download()
            package.install_from_path(path)
        except TranslateError:
            raise
        except Exception as exc:
            raise TranslateError(f"下载语言包 {pair[0]} → {pair[1]} 失败：{exc}") from exc
        installed = translate.get_installed_languages()
        from_lang = next((l for l in installed if l.code == pair[0]), None)
        to_lang = next((l for l in installed if l.code == pair[1]), None)
        if from_lang is None or to_lang is None:
            raise TranslateError(f"语言包 {pair[0]} → {pair[1]} 安装后仍不可用")
        return from_lang.get_translation(to_lang)

    # -- 翻译 -------------------------------------------------------------
    def translate(self, text: str) -> str:
        """翻译单段文本。"""
        if not text.strip():
            return ""
        translation = self._load_translation()
        try:
            return translation.translate(text)
        except Exception as exc:
            raise TranslateError(f"翻译失败：{exc}") from exc

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
