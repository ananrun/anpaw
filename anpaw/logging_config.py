from __future__ import annotations

"""后端日志配置。

日志同时输出到：
- 控制台：适合前台运行 `python run.py --server`
- logs/anpaw.log：适合隐藏窗口运行时查看
"""

import logging
import sys
from pathlib import Path


def setup_logging(root_dir: Path, level: str = "INFO") -> Path:
    """初始化全局 logging，并返回日志文件路径。"""
    log_dir = root_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "anpaw.log"

    root = logging.getLogger()
    if root.handlers:
        # 避免重复调用 setup_logging 时重复添加 handler。
        return log_file

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return log_file
