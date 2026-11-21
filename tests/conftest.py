"""pytest 配置：把 src 加入 sys.path，保证可导入 subbridge 包。"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
