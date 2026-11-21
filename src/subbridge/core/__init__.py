"""SubBridge 核心层：纯 Python 业务逻辑，不依赖界面与操作系统。"""

from .align import Alignment, AlignmentPair, HeuristicAligner, WordAligner, align_segment, realign_after_edit, tokenize
from .media import MediaError, MediaInfo, burn_subtitles, extract_audio, probe_media
from .subtitles import Segment, Word, merge_segments, parse_subtitle_file, split_segment, write_ass, write_srt, write_vtt
from .transcribe import AVAILABLE_MODELS, TranscribeConfig, TranscribeError, Transcriber
from .translate import SUPPORTED_LANGUAGES, TranslateConfig, TranslateError, Translator

__all__ = [
    "Alignment",
    "AlignmentPair",
    "WordAligner",
    "HeuristicAligner",
    "align_segment",
    "realign_after_edit",
    "tokenize",
    "MediaError",
    "MediaInfo",
    "burn_subtitles",
    "extract_audio",
    "probe_media",
    "Segment",
    "Word",
    "merge_segments",
    "parse_subtitle_file",
    "split_segment",
    "write_ass",
    "write_srt",
    "write_vtt",
    "AVAILABLE_MODELS",
    "TranscribeConfig",
    "TranscribeError",
    "Transcriber",
    "SUPPORTED_LANGUAGES",
    "TranslateConfig",
    "TranslateError",
    "Translator",
]
