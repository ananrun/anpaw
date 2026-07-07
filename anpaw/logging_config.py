from __future__ import annotations

"""后端日志配置。

logging 只写入 logs/anpaw.log。
控制台流程由 anpaw.console.flow 单独输出，避免同一条信息打印两遍。
"""

import logging
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

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(file_handler)
    return log_file
