"""LLM 抽象層 — 目前僅使用 OpenRouter（串流版）。

OpenRouter 提供 OpenAI-compatible 端點，用同一個 `openai` SDK 設定
`base_url` + api_key 即可。本模組只負責「呼叫模型並回傳標準化結果」，
不處理 tool loop（那是 agent.py 的責任）。
"""

import json
import os
import time
from collections.abc import Generator
from enum import StrEnum
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class LLMError(Exception):
    """LLM 呼叫失敗（缺 key、網路錯、模型不存在等）。"""


class LLMProvider(StrEnum):
    openrouter = "openrouter"

    @classmethod
    def from_str(cls, value: str) -> "LLMProvider":
        try:
            return cls(value)
        except ValueError:
            raise LLMError(f"未知的 provider：{value!r}（可用：openrouter）") from None


# 各家 endpoint + 從哪個 env 取 key
_PROVIDER_CONFIG = {
    LLMProvider.openrouter: {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "key_label": "OPENROUTER_API_KEY",
    },
}

# 各家免費/低成本的建議模型清單。display 是給前端顯示的名稱。
MODELS: dict[str, list[dict[str, str]]] = {
    "openrouter": [
        {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "display": "Nemotron 3 Ultra 550B (free)"},
        {"id": "poolside/laguna-s-2.1:free", "display": "Laguna S 2.1 (free)"},
        {"id": "nvidia/nemotron-3.5-lightning:free", "display": "Nemotron 3.5 Lightning (free)"},
        {"id": "nvidia/nemotron-3-super-120b-a12b:free", "display": "Nemotron 3 Super 120B (free)"},
    ],
}

# 動態模型快取
_MODELS_CACHE: dict[str, list[dict[str, str]]] = {}
_MODELS_CACHE_META: dict[str, float] = {}  # provider -> cached_at
_MODELS_CACHE_TTL = 3600  # 1 小時

_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
_REMOVED_MODELS = {"openrouter/free"}
_POPULARITY_URL = (
    "https://openrouter.ai/api/frontend/v1/models/find"
    "?supported_parameters=tools&max_price=0&max_output_price=0"
    "&order=top-weekly&active=true"
)


def _fetch_popularity_ranks() -> dict[str, int]:
    """取得 OpenRouter Models 頁的近 7 天 token 使用量排序。

    這是顯示順序的輔助資料；若端點暫時不可用，模型清單仍應正常回傳。
    """
    try:
        resp = httpx.get(_POPULARITY_URL, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        raw_models = data.get("models") if isinstance(data, dict) else None
        payload: list[Any] = raw_models if isinstance(raw_models, list) else []
    except (httpx.HTTPError, TypeError, ValueError):
        return {}

    ranks: dict[str, int] = {}
    for rank, item in enumerate(payload):
        endpoint = item.get("endpoint") or {}
        model_id = endpoint.get("model_variant_slug") or item.get("slug")
        if model_id:
            ranks[model_id] = rank
    return ranks


def _fetch_free_models() -> list[dict[str, str]]:
    """抓取免費 Agent 模型，並依近 7 天 token 使用量由高到低排列。"""
    cfg = _PROVIDER_CONFIG[LLMProvider.openrouter]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        raise LLMError(f"未設定 {cfg['key_label']}，無法抓取模型列表。")

    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/models?supported_parameters=tools",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise LLMError(f"抓取 OpenRouter 模型列表失敗：{exc}") from exc

    popularity_ranks = _fetch_popularity_ranks()
    models = []
    for item in data.get("data", []):
        pricing = item.get("pricing") or {}
        supported = item.get("supported_parameters") or []
        is_free = pricing.get("prompt") == "0" and pricing.get("completion") == "0"
        supports_tools = "tools" in supported
        if is_free and supports_tools and item.get("id") not in _REMOVED_MODELS:
            models.append({"id": item["id"], "display": item.get("name", item["id"])})

    # OpenRouter 的 Models 頁以最近 7 天處理的 token 數排序。新模型若尚未
    # 出現在排名資料中，放在已排名模型之後，再以名稱確保順序穩定。
    models.sort(key=lambda model: (
        popularity_ranks.get(model["id"], len(popularity_ranks)),
        model["display"].casefold(),
    ))

    return models

# 各 provider 的預設模型可被環境變數覆寫（使用者可在 .env 指定，
# 例如轉用付費模型時不必改程式碼）。
_OR_DEFAULT = os.environ.get("OR_MODEL")
if _OR_DEFAULT in _REMOVED_MODELS or (
    _OR_DEFAULT is not None and not _OR_DEFAULT.endswith(":free")
):
    _OR_DEFAULT = None
if _OR_DEFAULT:
    _existing = [m["id"] for m in MODELS["openrouter"]]
    if _OR_DEFAULT not in _existing:
        MODELS["openrouter"] = [{"id": _OR_DEFAULT, "display": _OR_DEFAULT + " (env)"}] + MODELS["openrouter"]
    else:
        MODELS["openrouter"] = (
            [next(m for m in MODELS["openrouter"] if m["id"] == _OR_DEFAULT)]
            + [m for m in MODELS["openrouter"] if m["id"] != _OR_DEFAULT]
        )


def _get_models(provider: LLMProvider, force: bool = False) -> list[dict[str, str]]:
    """取得模型列表，優先使用快取，快取失效時從 OpenRouter API 抓取。
    預設模型會排到最前面。
    """
    now = time.time()
    cached = _MODELS_CACHE.get(provider.value)
    cached_at = _MODELS_CACHE_META.get(provider.value, 0)
    if not force and cached is not None and (now - cached_at) < _MODELS_CACHE_TTL:
        return cached

    try:
        models = _fetch_free_models()
        # Without an explicit override, preserve the weekly-usage ordering.
        if _OR_DEFAULT:
            models = sorted(models, key=lambda m: 0 if m["id"] == _OR_DEFAULT else 1)
        _MODELS_CACHE[provider.value] = models
        _MODELS_CACHE_META[provider.value] = now
        return models
    except LLMError:
        return MODELS.get(provider.value, [])


def resolve_allowed_model(provider: LLMProvider, requested_model: str | None) -> str:
    """Resolve a request to a server-approved free, tool-capable model.

    Client input must never be forwarded directly to OpenRouter because every
    request uses the server-owned API key. The dynamic list is already filtered
    to zero-price tool models; the static list is the outage fallback allowlist.
    """
    models = _get_models(provider)
    if not models:
        raise LLMError("目前沒有可用的免費工具模型，請稍後再試。")

    allowed_ids = {model["id"] for model in models}
    selected = requested_model or models[0]["id"]
    if selected not in allowed_ids:
        raise LLMError("不允許使用此模型；請重新整理並選擇清單中的免費工具模型。")
    return selected


def list_providers(force: bool = False) -> list[dict[str, Any]]:
    """回傳前端下拉要用的 provider/model 清單，並標註 key 是否已設定。

    force=True 時強制重新抓取 OpenRouter API（忽略快取）。
    """
    out = []
    for provider, cfg in _PROVIDER_CONFIG.items():
        has_key = bool(os.environ.get(cfg["key_env"]))
        models = _get_models(provider, force=force) if has_key else MODELS.get(provider.value, [])
        out.append({
            "id": provider.value,
            "label": provider.value,
            "key_env": cfg["key_label"],
            "configured": has_key,
            "models": models,
        })
    return out


def _build_client(provider: LLMProvider) -> OpenAI:
    cfg = _PROVIDER_CONFIG[provider]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        raise LLMError(f"未設定 {cfg['key_label']}，無法使用 {provider.value}。")
    return OpenAI(base_url=cfg["base_url"], api_key=api_key)


def call_llm_stream(
    provider: LLMProvider,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> Generator[str, None, dict[str, Any]]:
    """串流呼叫模型，逐 token 產出文字並收集原生 tool calls。

    Yields:
        每個 token 的文字片段（可能為空字串，由呼叫方自行過濾）。

    Returns:
        {"content": str, "finish_reason": str | None, "tool_calls": list,
         "model": str | None}
        在 generator 結束時回傳（透過 StopIteration value）。
    """
    client = _build_client(provider)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "stream": True,
        "stream_options": {"include_usage": False},
    }
    if tools:
        kwargs["tools"] = tools

    full_content = ""
    finish_reason = None
    actual_model = None
    tool_call_parts: dict[int, dict[str, str]] = {}

    stream = None
    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            actual_model = getattr(chunk, "model", None) or actual_model
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                full_content += delta.content
                yield delta.content
            for position, tool_call in enumerate(getattr(delta, "tool_calls", None) or []):
                index = getattr(tool_call, "index", None)
                index = position if index is None else index
                part = tool_call_parts.setdefault(
                    index,
                    {"id": "", "name": "", "arguments": ""},
                )
                if getattr(tool_call, "id", None):
                    part["id"] = tool_call.id
                function = getattr(tool_call, "function", None)
                if function:
                    part["name"] += getattr(function, "name", None) or ""
                    part["arguments"] += getattr(function, "arguments", None) or ""
            if choice.finish_reason:
                finish_reason = choice.finish_reason
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"LLM 串流呼叫失敗（{provider.value} / {model}）：{exc}") from exc
    finally:
        close_stream = getattr(stream, "close", None)
        if close_stream is not None:
            close_stream()

    if not full_content and finish_reason is None:
        raise LLMError(f"LLM 回傳空串流（{provider.value} / {model}）")

    tool_calls = []
    for index, part in sorted(tool_call_parts.items()):
        if not part["name"]:
            continue
        raw_arguments = part["arguments"] or "{}"
        normalized_arguments = raw_arguments
        try:
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                arguments = {}
                normalized_arguments = "{}"
        except (TypeError, json.JSONDecodeError):
            arguments = {}
            normalized_arguments = "{}"
        tool_calls.append({
            "id": part["id"] or f"call_{index}",
            "name": part["name"],
            "arguments": arguments,
            "arguments_json": normalized_arguments,
        })

    return {
        "content": full_content,
        "finish_reason": finish_reason,
        "tool_calls": tool_calls,
        "model": actual_model,
    }
