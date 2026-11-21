"""应用入口：创建 QApplication 并打开主窗口。"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .platform import get_platform
from .ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    """启动 SubBridge。返回退出码。"""
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("SubBridge")
    app.setOrganizationName("SubBridge")
    app.setApplicationVersion("1.0.0")

    # 确保配置与缓存目录存在（平台层负责路径）。
    platform = get_platform()
    platform.config_dir().mkdir(parents=True, exist_ok=True)
    platform.cache_dir().mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
