"""NLLB-200 直达翻译封装（本地离线，CTranslate2 + SentencePiece）。

模型：JustFrederik/nllb-200-distilled-600M-ct2-int8（int8，约 617MB），
首次使用时从 Hugging Face 下载到本地缓存，之后完全离线。
与 argos 不同：NLLB 一个模型直接支持 200 种语言互译，
日语/韩语/法语/德语 → 中文不需要经英语中转。

实测（2026-11-22，沙箱 CPU）：日/韩/法/德/英 → 中文直达均正常，
短句约 1 秒；beam_size=4。

输入格式（NLLB 要求，实测确定）：["<s>", 源语言码] + 分词 + ["</s>"]，
目标语言码作 target_prefix；输出 hypotheses 会回显目标语言码，需去掉。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .subtitles import Segment

__all__ = [
    "NLLB_LANGUAGE_CODES",
    "NLLB_MODEL_FILES",
    "NLLB_MODEL_REPO",
    "NLLBConfig",
    "NLLBError",
    "NLLBTranslator",
]

NLLB_MODEL_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
NLLB_MODEL_FILES = (
    "model.bin",
    "config.json",
    "sentencepiece.bpe.model",
    "shared_vocabulary.txt",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)

# 界面语言代码 -> NLLB 语言代码（NLLB-200 的 200 种语言全覆盖界面 17 种）。
NLLB_LANGUAGE_CODES: dict[str, str] = {
    "en": "eng_Latn",
    "zh": "zho_Hans",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
    "it": "ita_Latn",
    "ru": "rus_Cyrl",
    "ar": "arb_Arab",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "tr": "tur_Latn",
    "vi": "vie_Latn",
    "id": "ind_Latn",
    "th": "tha_Thai",
}


class NLLBError(Exception):
    """NLLB 直达翻译失败（依赖缺失、模型下载失败、语言不支持等）。"""


@dataclass
class NLLBConfig:
    """NLLB 翻译配置。"""

    source_lang: str = "en"
    target_lang: str = "zh"
    # 模型目录；None 表示用默认缓存目录（平台缓存目录下的 nllb-ct2-int8）。
    model_dir: str | None = None
    # beam search 宽度：4 是质量与速度的平衡点（实测短句约 1 秒）。
    beam_size: int = 4


class NLLBTranslator:
    """NLLB 直达翻译器（懒加载模型，首次使用下载模型）。"""

    def __init__(self, config: NLLBConfig | None = None) -> None:
        self.config = config or NLLBConfig()
        self._translator = None
        self._sp = None

    # -- 模型目录与下载 -----------------------------------------------------
    @staticmethod
    def default_model_dir() -> str:
        """默认模型缓存目录。"""
        from ..platform import get_platform

        return os.path.join(get_platform().cache_dir(), "nllb-ct2-int8")

    def model_dir(self) -> str:
        return self.config.model_dir or self.default_model_dir()

    def is_downloaded(self) -> bool:
        model_dir = self.model_dir()
        return all(
            os.path.exists(os.path.join(model_dir, name))
            for name in NLLB_MODEL_FILES
        )

    def ensure_model(self) -> str:
        """确保模型已下载（首次需要联网，约 617MB）；返回模型目录。"""
        model_dir = self.model_dir()
        if self.is_downloaded():
            return model_dir
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise NLLBError(
                "未安装 huggingface_hub，请先执行 pip install huggingface_hub"
            ) from exc
        try:
            os.makedirs(model_dir, exist_ok=True)
            snapshot_download(
                repo_id=NLLB_MODEL_REPO,
                local_dir=model_dir,
                local_dir_use_symlinks=False,
                allow_patterns=list(NLLB_MODEL_FILES),
            )
        except Exception as exc:
            raise NLLBError(f"下载 NLLB 模型失败：{exc}") from exc
        if not self.is_downloaded():
            raise NLLBError("NLLB 模型下载后文件不完整，请删除模型目录后重试")
        return model_dir

    # -- 加载 ----------------------------------------------------------------
    def _load(self):
        if self._translator is not None and self._sp is not None:
            return self._translator, self._sp
        model_dir = self.ensure_model()
        try:
            import ctranslate2
            import sentencepiece as spm
        except ImportError as exc:
            raise NLLBError(
                "未安装 ctranslate2 / sentencepiece，"
                "请先执行 pip install ctranslate2 sentencepiece"
            ) from exc
        try:
            self._translator = ctranslate2.Translator(
                model_dir, device="cpu", compute_type="int8"
            )
            self._sp = spm.SentencePieceProcessor()
            self._sp.load(os.path.join(model_dir, "sentencepiece.bpe.model"))
        except Exception as exc:
            raise NLLBError(f"加载 NLLB 模型失败：{exc}") from exc
        return self._translator, self._sp

    # -- 翻译 ----------------------------------------------------------------
    def translate(self, text: str) -> str:
        """翻译单段文本（直达，无中转；同语言直接返回原文）。"""
        if not text.strip():
            return ""
        source_code = NLLB_LANGUAGE_CODES.get(self.config.source_lang)
        target_code = NLLB_LANGUAGE_CODES.get(self.config.target_lang)
        if source_code is None or target_code is None:
            raise NLLBError(
                f"NLLB 不支持语言 {self.config.source_lang} → {self.config.target_lang}"
            )
        if source_code == target_code:
            return text
        translator, sp = self._load()
        tokens = ["<s>", source_code] + sp.encode(text, out_type=str) + ["</s>"]
        try:
            results = translator.translate_batch(
                [tokens],
                target_prefix=[[target_code]],
                beam_size=self.config.beam_size,
            )
        except Exception as exc:
            raise NLLBError(f"NLLB 翻译失败：{exc}") from exc
        hypotheses = list(results[0].hypotheses[0])
        # CTranslate2 会把目标语言前缀回显在输出开头，去掉它。
        if hypotheses and hypotheses[0] == target_code:
            hypotheses = hypotheses[1:]
        return sp.decode(hypotheses).strip()

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
                    f"NLLB 直达翻译 {index} / {total}",
                )
        if progress_callback:
            progress_callback(1.0, f"NLLB 直达翻译完成，共 {total} 条")
        return segments
