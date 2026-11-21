"""平台抽象层：所有操作系统差异都收敛到这里。

core/ 与 ui/ 只依赖 :class:`Platform` 接口，不直接调用任何 OS 专属 API。
新增 macOS / Linux 支持时，只需在同目录新增 ``macos.py`` / ``linux.py``
实现本接口，并在 :func:`get_platform` 里注册——其余代码不需要改动。
"""

from __future__ import annotations

import os
import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path

__all__ = ["Platform", "GenericPlatform", "get_platform"]


class Platform(ABC):
    """平台能力接口。"""

    #: 人类可读的平台名，如 "Windows" / "macOS" / "Linux"。
    name: str = "未知平台"

    @abstractmethod
    def config_dir(self) -> Path:
        """应用配置目录（设置、语言包索引等）。"""

    @abstractmethod
    def cache_dir(self) -> Path:
        """缓存目录（模型、临时音频等，可被安全清理）。"""

    @abstractmethod
    def models_dir(self) -> Path:
        """Whisper / argos 模型存放目录。"""

    @abstractmethod
    def default_output_dir(self) -> Path:
        """导出视频/字幕的默认目录。"""

    @abstractmethod
    def find_ffmpeg(self) -> str | None:
        """查找 ffmpeg 可执行文件；找不到返回 None。"""

    def find_ffprobe(self) -> str | None:
        """查找 ffprobe（默认与 ffmpeg 同目录）。"""
        ffmpeg = self.find_ffmpeg()
        if not ffmpeg:
            return None
        candidate = Path(ffmpeg).with_name(
            "ffprobe.exe" if ffmpeg.lower().endswith(".exe") else "ffprobe"
        )
        if candidate.exists():
            return str(candidate)
        return shutil.which("ffprobe")

    def ffmpeg_search_hint(self) -> str:
        """找不到 ffmpeg 时在界面里显示的提示文案。"""
        return (
            "未找到 ffmpeg。\n"
            "请安装 ffmpeg 并把它加入系统 PATH，或在“设置 → ffmpeg 路径”里指定 "
            "ffmpeg 可执行文件的位置。\n"
            "Windows 推荐：从 https://www.gyan.dev/ffmpeg/builds/ 下载 "
            "ffmpeg-release-essentials.zip，解压后把 bin 目录加入 PATH。"
        )


class GenericPlatform(Platform):
    """通用 POSIX 平台（Linux / macOS 开发调试用，也作为兜底实现）。"""

    name = "通用平台"

    def config_dir(self) -> Path:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / "SubBridge"

    def cache_dir(self) -> Path:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".cache"
        return base / "SubBridge"

    def models_dir(self) -> Path:
        return self.cache_dir() / "models"

    def default_output_dir(self) -> Path:
        videos = Path.home() / "Videos"
        return videos / "SubBridge" if videos.exists() else Path.home() / "SubBridge"

    def find_ffmpeg(self) -> str | None:
        override = os.environ.get("SUBBRIDGE_FFMPEG")
        if override and Path(override).exists():
            return override
        return shutil.which("ffmpeg")


def get_platform() -> Platform:
    """按当前操作系统返回平台实现。"""
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    if sys.platform == "darwin":
        try:
            from .macos import MacOSPlatform

            return MacOSPlatform()
        except ImportError:
            return GenericPlatform()
    if sys.platform.startswith("linux"):
        try:
            from .linux import LinuxPlatform

            return LinuxPlatform()
        except ImportError:
            return GenericPlatform()
    return GenericPlatform()
