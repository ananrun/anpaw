from __future__ import annotations

"""模型配置合成。

配置来源按优先级合并：
1. 页面请求传入的 provider/model/api_key
2. `.env` 或系统环境变量
3. ProviderSpec 中的默认值

这样可以模拟 QwenPaw 的 Provider 配置层，但保持足够简单。
"""

import os
from dataclasses import dataclass
from pathlib import Path

from .providers import get_provider


@dataclass
class ModelConfig:
    """一次模型调用最终使用的配置。"""

    provider: str = "kilo"
    base_url: str = "https://api.kilo.ai/api/gateway"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    api_key: str = ""


def load_model_config(
    api_key: str = "",
    provider_id: str = "",
    model: str = "",
) -> ModelConfig:
    """加载本轮请求的模型配置。"""
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    provider_name = provider_id or os.getenv("ANPAW_PROVIDER", "kilo")
    provider = get_provider(provider_name)
    base_url_env = (
        os.getenv(f"{provider.id.upper()}_BASE_URL")
        or (
            os.getenv("KILO_BASE_URL")
            if provider.id == "kilo"
            else ""
        )
    )
    model_env = (
        os.getenv(f"{provider.id.upper()}_MODEL")
        or (
            os.getenv("KILO_MODEL")
            if provider.id == "kilo"
            else ""
        )
        or os.getenv("ANPAW_MODEL")
    )
    return ModelConfig(
        provider=provider.id,
        base_url=(base_url_env or provider.base_url).rstrip("/"),
        model=model or model_env or provider.default_model,
        api_key=api_key or os.getenv(provider.api_key_env, ""),
    )


def _load_dotenv(path: Path) -> None:
    """加载项目根目录下的 `.env`。

    为了避免额外依赖，这里没有使用 python-dotenv。
    已存在于系统环境变量中的值不会被覆盖。
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
