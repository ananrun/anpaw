from __future__ import annotations

"""控制台流程输出。

这些输出专门给学习/调试时看请求链路用，和 logs/anpaw.log 里的正式日志分开。
"""

import os
import sys
import threading
from datetime import datetime
from typing import Any


_LOCK = threading.Lock()


def flow(stage: str, message: str, **data: Any) -> None:
    """把关键运行流程直接打印到启动服务的控制台。"""
    suffix = ""
    if data:
        pairs = " ".join(f"{key}={value!r}" for key, value in data.items())
        suffix = f" | {pairs}"
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp} pid={os.getpid()}] [{stage}] {message}{suffix}"
    with _LOCK:
        sys.__stdout__.write(line + "\n")
        sys.__stdout__.flush()
