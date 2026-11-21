"""ffmpeg / ffprobe 封装：探测媒体信息、提取音频、烧录硬字幕。

本模块只调用外部 ffmpeg/ffprobe 可执行文件，不直接做编解码；
ffmpeg 可执行文件的查找由 platform 层负责（见 platform.base）。
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

__all__ = [
    "MediaInfo",
    "MediaError",
    "probe_media",
    "extract_audio",
    "burn_subtitles",
    "escape_filter_path",
]

SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts"}


class MediaError(Exception):
    """媒体处理失败（ffmpeg 缺失、文件损坏、命令执行失败等）。"""


@dataclass
class MediaInfo:
    """视频基本信息。"""

    duration: float = 0.0  # 秒
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    has_audio: bool = False


def _run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=0x08000000 if __import__("os").name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        raise MediaError(f"找不到可执行文件：{cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"命令超时：{' '.join(cmd)}") from exc


def _ffprobe_path(ffmpeg_path: str) -> str:
    """ffprobe 与 ffmpeg 同目录；找不到则直接用 PATH 里的 ffprobe。"""
    candidate = Path(ffmpeg_path).with_name("ffprobe.exe" if ffmpeg_path.lower().endswith(".exe") else "ffprobe")
    if candidate.exists():
        return str(candidate)
    return "ffprobe"


def probe_media(ffmpeg_path: str, file_path: str) -> MediaInfo:
    """探测视频信息：优先用 ffprobe 的 JSON 输出，失败时解析 ffmpeg -i。"""
    info = MediaInfo()
    ffprobe = _ffprobe_path(ffmpeg_path)
    result = _run(
        [
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", file_path,
        ],
        timeout=30,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            info.duration = float(fmt.get("duration", 0.0) or 0.0)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video" and not info.video_codec:
                    info.video_codec = stream.get("codec_name", "")
                    info.width = int(stream.get("width", 0) or 0)
                    info.height = int(stream.get("height", 0) or 0)
                    fps_text = str(stream.get("avg_frame_rate", "0/0"))
                    if "/" in fps_text:
                        num, den = fps_text.split("/", 1)
                        if float(den or 0):
                            info.fps = float(num) / float(den)
                elif stream.get("codec_type") == "audio":
                    info.audio_codec = stream.get("codec_name", "")
                    info.has_audio = True
            return info
        except (ValueError, KeyError, TypeError):
            pass  # 解析失败则回落到 ffmpeg -i 文本解析

    # 回落：解析 `ffmpeg -i` 的 stderr 文本
    result = _run([ffmpeg_path, "-hide_banner", "-i", file_path], timeout=30)
    text = result.stderr or ""
    duration_match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", text)
    if duration_match:
        h, m, s = duration_match.groups()
        info.duration = int(h) * 3600 + int(m) * 60 + float(s)
    video_match = re.search(
        r"Stream #\d+:\d+.*Video: (\w+).*?(\d+)x(\d+)", text
    )
    if video_match:
        info.video_codec, w, h = video_match.groups()
        info.width, info.height = int(w), int(h)
    if re.search(r"Stream #\d+:\d+.*Audio:", text):
        info.has_audio = True
    if info.duration <= 0 and not info.video_codec:
        raise MediaError(f"无法读取媒体信息：{file_path}")
    return info


def extract_audio(
    ffmpeg_path: str,
    video_path: str,
    output_wav: str,
    sample_rate: int = 16000,
    progress_callback: Callable[[float, str], None] | None = None,
) -> str:
    """从视频提取单声道 WAV（Whisper 推荐 16kHz），返回输出路径。"""
    if progress_callback:
        progress_callback(0.0, "正在提取音频…")
    result = _run(
        [
            ffmpeg_path, "-y", "-i", video_path,
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            "-c:a", "pcm_s16le", output_wav,
        ],
        timeout=1800,
    )
    if result.returncode != 0 or not Path(output_wav).exists():
        detail = (result.stderr or "").strip().splitlines()
        raise MediaError(
            "提取音频失败：" + (detail[-1] if detail else "ffmpeg 返回非零退出码")
        )
    if progress_callback:
        progress_callback(1.0, "音频提取完成")
    return output_wav


def escape_filter_path(path: str) -> str:
    """把字幕文件路径转义成 ffmpeg subtitles 滤镜可用的形式。

    Windows 盘符冒号必须转义为 ``\\:``，反斜杠统一为正斜杠。
    """
    posix = path.replace("\\", "/")
    # 冒号（盘符与文件名中的冒号）都要转义；单引号也要转义。
    posix = posix.replace(":", "\\:").replace("'", "\\'")
    return posix


def burn_subtitles(
    ffmpeg_path: str,
    video_path: str,
    subtitle_path: str,
    output_path: str,
    font_name: str = "Microsoft YaHei",
    font_size: int = 24,
    progress_callback: Callable[[float, str], None] | None = None,
) -> str:
    """把 ASS/SRT 字幕烧录进视频（硬字幕），输出新视频文件。"""
    sub = escape_filter_path(str(Path(subtitle_path).resolve()))
    force_style = (
        f"FontName={font_name},FontSize={font_size},"
        "PrimaryColour=&HFFFFFF&,OutlineColour=&H80000000&,"
        "BorderStyle=1,Outline=1,Shadow=0"
    )
    video_filter = f"subtitles='{sub}':force_style='{force_style}'"
    if progress_callback:
        progress_callback(0.0, "正在烧录字幕…")
    result = _run(
        [
            ffmpeg_path, "-y", "-i", video_path,
            "-vf", video_filter,
            "-c:a", "copy", output_path,
        ],
        timeout=7200,
    )
    if result.returncode != 0 or not Path(output_path).exists():
        detail = (result.stderr or "").strip().splitlines()
        raise MediaError(
            "烧录字幕失败：" + (detail[-1] if detail else "ffmpeg 返回非零退出码")
        )
    if progress_callback:
        progress_callback(1.0, "烧录完成")
    return output_path
