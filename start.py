from __future__ import annotations

import importlib.util
import sys


REQUIRED_FOR_UI = ["PySide6"]


def main() -> int:
    missing = [name for name in REQUIRED_FOR_UI if importlib.util.find_spec(name) is None]
    if missing:
        print("缺少界面依赖：" + ", ".join(missing))
        print("请先安装 requirements.txt 里的依赖。")
        return 1

    from app.main import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
