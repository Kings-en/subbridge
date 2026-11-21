"""faster-whisper 本地转录封装（懒加载）。

faster-whisper 只在真正转录时才 import，界面启动不依赖它；
模型首次使用时由 faster-whisper 自动从 Hugging Face 下载到本地缓存。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .subtitles import Segment, Word

__all__ = [
    "TranscribeConfig",
    "TranscribeError",
    "Transcriber",
    "AVAILABLE_MODELS",
]

AVAILABLE_MODELS: list[str] = ["tiny", "base", "small", "medium", "large-v3"]


class TranscribeError(Exception):
    """转录失败（依赖缺失、模型下载失败、音频无法读取等）。"""


@dataclass
class TranscribeConfig:
    """转录配置。"""

    model_size: str = "base"
    # None 表示自动检测语言；否则为 faster-whisper 语言代码（如 "en"）。
    language: str | None = None
    device: str = "auto"  # auto / cpu / cuda
    compute_type: str = "auto"  # auto 时 CPU 用 int8、GPU 用 float16
    # 语音活动检测：过滤无语音片段，可减少幻觉字幕。
    vad_filter: bool = True


class Transcriber:
    """faster-whisper 转录器（懒加载模型）。"""

    def __init__(self, config: TranscribeConfig | None = None) -> None:
        self.config = config or TranscribeConfig()
        self._model = None
        self._model_size_loaded: str | None = None

    # -- 模型加载（懒加载） ----------------------------------------------
    def _load_model(self):
        if self._model is not None and self._model_size_loaded == self.config.model_size:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscribeError(
                "未安装 faster-whisper，请先执行 pip install faster-whisper"
            ) from exc
        device = self.config.device
        compute_type = self.config.compute_type
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"
        try:
            self._model = WhisperModel(
                self.config.model_size,
                device=device,
                compute_type=compute_type,
            )
        except Exception as exc:
            raise TranscribeError(
                f"加载 Whisper 模型 {self.config.model_size!r} 失败：{exc}"
            ) from exc
        self._model_size_loaded = self.config.model_size
        return self._model

    # -- 转录 -------------------------------------------------------------
    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> list[Segment]:
        """转录音频，返回带词级时间戳的字幕段列表。

        progress_callback 收到 (进度 0-1, 状态文本)。
        """
        model = self._load_model()
        try:
            segments_iter, info = model.transcribe(
                audio_path,
                language=self.config.language,
                word_timestamps=True,
                vad_filter=self.config.vad_filter,
            )
        except Exception as exc:
            raise TranscribeError(f"转录失败：{exc}") from exc

        duration = getattr(info, "duration", 0.0) or 0.0
        segments: list[Segment] = []
        for index, raw in enumerate(segments_iter, start=1):
            words = [
                Word(text=w.word.strip(), start=w.start, end=w.end)
                for w in (raw.words or [])
                if w.word.strip()
            ]
            segments.append(
                Segment(
                    index=index,
                    start=float(raw.start),
                    end=float(raw.end),
                    text=raw.text.strip(),
                    words=words,
                )
            )
            if progress_callback and duration > 0:
                progress_callback(
                    min(1.0, float(raw.end) / duration),
                    f"正在转录 {index} / …（{raw.end:.0f}s / {duration:.0f}s）",
                )
        if progress_callback:
            progress_callback(1.0, f"转录完成，共 {len(segments)} 条字幕")
        return segments

    def detected_language(self) -> str | None:
        """最近一次转录检测到的语言（转录前返回 None）。"""
        return getattr(self, "_last_language", None)
