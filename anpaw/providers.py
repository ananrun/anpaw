from __future__ import annotations

"""学习版 Provider 注册表。

真实 QwenPaw 的 Provider 系统会动态管理很多模型供应商。
AnPaw 只保留两个云端 Provider，并使用固定 11 个学习模型，
避免把聚合网关里的数百个模型都暴露出来干扰理解。
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    """一个云端 Provider 的基础信息。"""

    id: str
    name: str
    base_url: str
    models_url: str
    api_key_env: str
    default_model: str
    docs_url: str
    api_key_required: bool = False


@dataclass
class ModelInfo:
    """页面模型下拉框需要的模型信息。"""

    id: str
    name: str
    description: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    "kilo": ProviderSpec(
        id="kilo",
        name="Kilo Code",
        base_url="https://api.kilo.ai/api/gateway",
        models_url="https://api.kilo.ai/api/gateway/models",
        api_key_env="KILO_API_KEY",
        default_model="nvidia/nemotron-3-ultra-550b-a55b:free",
        docs_url="https://kilocode.ai/docs/features/providers/kilo-code/",
    ),
    "opencode": ProviderSpec(
        id="opencode",
        name="OpenCode",
        base_url="https://opencode.ai/zen/v1",
        models_url="https://opencode.ai/zen/v1/models",
        api_key_env="OPENCODE_API_KEY",
        default_model="deepseek-v4-flash-free",
        docs_url="https://models.dev/providers/opencode-go",
    ),
}

# 早期版本预留过动态模型缓存。
# 当前学习版使用 LEARNING_MODELS 固定清单，缓存保留只是为了说明真实系统常见结构。
_MODELS_CACHE: dict[str, list[ModelInfo]] = {}

# 这是页面实际展示的 11 个模型。
LEARNING_MODELS: dict[str, list[ModelInfo]] = {
    "opencode": [
        ModelInfo(id="deepseek-v4-flash-free", name="DeepSeek V4 Flash"),
        ModelInfo(id="mimo-v2.5-free", name="Mimo V2.5"),
        ModelInfo(id="nemotron-3-ultra-free", name="Nemotron 3 Ultra"),
        ModelInfo(id="nemotron-3-super-free", name="Nemotron 3 Super"),
    ],
    "kilo": [
        ModelInfo(id="kilo-auto/free", name="Kilo Auto (Free Router)"),
        ModelInfo(
            id="nvidia/nemotron-3-ultra-550b-a55b:free",
            name="Nemotron 3 Ultra 550B",
        ),
        ModelInfo(
            id="nvidia/nemotron-3-super-120b-a12b:free",
            name="Nemotron 3 Super 120B",
        ),
        ModelInfo(id="poolside/laguna-m.1:free", name="Poolside Laguna M.1"),
        ModelInfo(id="poolside/laguna-xs.2:free", name="Poolside Laguna XS.2"),
        ModelInfo(id="stepfun/step-3.7-flash:free", name="Step 3.7 Flash"),
        ModelInfo(id="nex-agi/nex-n2-pro:free", name="Nex N2 Pro"),
    ],
}


def get_provider(provider_id: str) -> ProviderSpec:
    """根据 provider_id 获取 ProviderSpec，找不到时回退到 kilo。"""
    return PROVIDERS.get(provider_id) or PROVIDERS["kilo"]


def list_providers() -> list[dict]:
    """返回页面需要的 Provider 列表。"""
    return [
        {
            "id": provider.id,
            "name": provider.name,
            "base_url": _base_url_from_env(provider),
            "api_key_env": provider.api_key_env,
            "default_model": _default_model_from_env(provider),
            "docs_url": provider.docs_url,
            "has_env_key": bool(os.getenv(provider.api_key_env, "")),
            "api_key_required": provider.api_key_required,
        }
        for provider in PROVIDERS.values()
    ]


def list_models(provider_id: str, refresh: bool = False) -> list[ModelInfo]:
    """返回某个 Provider 的学习版模型清单。"""
    provider = get_provider(provider_id)
    return LEARNING_MODELS.get(provider.id, _fallback_models(provider))


def _fetch_models(provider: ProviderSpec) -> list[ModelInfo]:
    """动态拉取模型列表的示例函数。

    当前页面不使用它，因为学习项目只展示固定 11 个模型。
    留着是为了说明真实 ProviderManager 通常会有这一层。
    """
    request = urllib.request.Request(
        provider.models_url,
        headers={"accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc

    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise RuntimeError("models endpoint returned an unsupported shape")

    models: list[ModelInfo] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        models.append(
            ModelInfo(
                id=str(item["id"]),
                name=str(item.get("name") or item["id"]),
                description=str(item.get("description") or ""),
            ),
        )
    if not models:
        raise RuntimeError("models endpoint returned no models")
    return models


def _fallback_models(provider: ProviderSpec) -> list[ModelInfo]:
    """当 Provider 没有学习清单时的兜底。"""
    if provider.id == "opencode":
        ids = [
            "deepseek-v4-flash-free",
            "mimo-v2.5-free",
            "nemotron-3-ultra-free",
            "nemotron-3-super-free",
        ]
    else:
        ids = [
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "kilo-auto/frontier",
            "kilo-auto/fast",
        ]
    return [ModelInfo(id=item, name=item) for item in ids]


def _base_url_from_env(provider: ProviderSpec) -> str:
    """读取 Provider 的 base_url 环境变量覆盖。"""
    specific_key = f"{provider.id.upper()}_BASE_URL"
    legacy_key = "KILO_BASE_URL" if provider.id == "kilo" else ""
    return (
        os.getenv(specific_key)
        or (os.getenv(legacy_key) if legacy_key else "")
        or provider.base_url
    ).rstrip("/")


def _default_model_from_env(provider: ProviderSpec) -> str:
    """读取 Provider 的默认模型环境变量覆盖。"""
    specific_key = f"{provider.id.upper()}_MODEL"
    legacy_key = "KILO_MODEL" if provider.id == "kilo" else ""
    return (
        os.getenv(specific_key)
        or (os.getenv(legacy_key) if legacy_key else "")
        or provider.default_model
    )
