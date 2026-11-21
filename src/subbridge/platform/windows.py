"""Windows 平台实现。

目录约定：
- 配置：%APPDATA%\\SubBridge
- 缓存/模型：%LOCALAPPDATA%\\SubBridge\\cache（模型较大，放 Local 不随漫游）
- 默认导出：%USERPROFILE%\\Videos\\SubBridge（没有 Videos 文件夹时用文档）

ffmpeg 查找顺序：环境变量 SUBBRIDGE_FFMPEG → PATH → 程序同目录
→ %LOCALAPPDATA%\\SubBridge\\ffmpeg\\bin → 常见安装路径。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .base import Platform

__all__ = ["WindowsPlatform"]


class WindowsPlatform(Platform):
    """Windows 平台实现。"""

    name = "Windows"

    def _appdata(self) -> Path:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))

    def _local_appdata(self) -> Path:
        return Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )

    def config_dir(self) -> Path:
        return self._appdata() / "SubBridge"

    def cache_dir(self) -> Path:
        return self._local_appdata() / "SubBridge" / "cache"

    def models_dir(self) -> Path:
        return self._local_appdata() / "SubBridge" / "models"

    def default_output_dir(self) -> Path:
        videos = Path.home() / "Videos"
        if videos.is_dir():
            return videos / "SubBridge"
        documents = Path.home() / "Documents"
        return documents / "SubBridge"

    def find_ffmpeg(self) -> str | None:
        # 1. 环境变量（打包版与手动指定优先）
        override = os.environ.get("SUBBRIDGE_FFMPEG")
        if override and Path(override).exists():
            return override
        # 2. 系统 PATH
        found = shutil.which("ffmpeg")
        if found:
            return found
        # 3. 程序同目录（PyInstaller 打包时 ffmpeg 放在 exe 旁边）
        exe_dir = Path(sys.executable).parent
        for candidate in (
            exe_dir / "ffmpeg" / "bin" / "ffmpeg.exe",
            exe_dir / "ffmpeg.exe",
            exe_dir / "bin" / "ffmpeg.exe",
        ):
            if candidate.exists():
                return str(candidate)
        # 4. 应用数据目录（CI 打包与手动放置的常用位置）
        bundled = self._local_appdata() / "SubBridge" / "ffmpeg" / "bin" / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)
        # 5. 常见手动安装路径
        for candidate in (
            Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe",
        ):
            if candidate.exists():
                return str(candidate)
        return None
