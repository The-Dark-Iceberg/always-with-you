"""PyInstaller 的入口脚本。"""
import sys

from awy.__main__ import guarded_main

if __name__ == "__main__":
    sys.exit(guarded_main())
