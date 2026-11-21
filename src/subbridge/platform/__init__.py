"""平台层：操作系统差异收敛于此。"""

from .base import GenericPlatform, Platform, get_platform

__all__ = ["Platform", "GenericPlatform", "get_platform"]
