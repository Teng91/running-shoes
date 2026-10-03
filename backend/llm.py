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

# There is deliberately no hard-coded model allowlist.  OpenRouter's free
# catalog changes during the day, so stale IDs must never be presented as if
# they were still usable.
MODELS: dict[str, list[dict[str, str]]] = {"openrouter": []}

# 動態模型快取
_MODELS_CACHE: dict[str, list[dict[str, str]]] = {}
_MODELS_CACHE_META: dict[str, float] = {}  # provider -> cached_at
_MODELS_CACHE_TTL = 900  # 15 分鐘；讓「今日免費」清單保持新鮮

_DEFAULT_MODEL: str | None = None
_REMOVED_MODELS = {"openrouter/free"}

_MODELS_URL = "https://openrouter.ai/api/v1/models?supported_parameters=tools"
_RANKINGS_URL = "https://openrouter.ai/api/v1/datasets/rankings-daily"
_DAILY_USAGE_POOL_LIMIT = 50


def _fetch_free_models() -> list[dict[str, str]]:
    """抓取今日使用量前 50 名中的免費工具模型。

    Pricing and tool support come from the live catalog. Popularity comes from
    ``rankings-daily``: rank every model first, keep the top 50, then intersect
    that pool with the free, tool-capable catalog. This avoids presenting
    obscure catalog entries as today's usable models.
    """
    cfg = _PROVIDER_CONFIG[LLMProvider.openrouter]
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        raise LLMError(f"未設定 {cfg['key_label']}，無法抓取模型列表。")

    try:
        resp = httpx.get(
            _MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise LLMError(f"抓取 OpenRouter 模型列表失敗：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise LLMError("抓取 OpenRouter 模型列表失敗：回傳格式無效。")

    models_by_id: dict[str, dict[str, str]] = {}
    model_keys: dict[str, str] = {}
    for item in data.get("data", []):
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        pricing = item.get("pricing")
        pricing = pricing if isinstance(pricing, dict) else {}
        supported = item.get("supported_parameters")
        supported = supported if isinstance(supported, list) else []
        try:
            prompt_price = pricing.get("prompt")
            completion_price = pricing.get("completion")
            is_free = float(str(prompt_price)) == 0 and float(str(completion_price)) == 0
        except (TypeError, ValueError):
            is_free = False
        supports_tools = "tools" in supported
        if is_free and supports_tools and model_id not in _REMOVED_MODELS:
            models_by_id[model_id] = {
                "id": model_id,
                "display": str(item.get("name") or model_id),
            }
            model_keys[model_id] = model_id
            canonical = item.get("canonical_slug")
            if isinstance(canonical, str) and canonical:
                tail = model_id.rsplit("/", 1)[-1]
                if ":" in tail:
                    variant = tail.split(":", 1)[1]
                    model_keys.setdefault(f"{canonical}:{variant}", model_id)
                else:
                    model_keys.setdefault(canonical, model_id)

    try:
        rankings = httpx.get(
            _RANKINGS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        rankings.raise_for_status()
        ranking_body = rankings.json()
        ranking_data = ranking_body.get("data", []) if isinstance(ranking_body, dict) else []
        ranking_rows: list[dict[str, Any]] = [
            row for row in ranking_data if isinstance(row, dict)
        ] if isinstance(ranking_data, list) else []
        meta = ranking_body.get("meta", {}) if isinstance(ranking_body, dict) else {}
        end_date = meta.get("end_date") if isinstance(meta, dict) else None
        if not end_date:
            dates = [str(row["date"]) for row in ranking_rows if row.get("date")]
            end_date = max(dates) if dates else None
        totals: dict[str, int] = {}
        for row in ranking_rows:
            if end_date and row.get("date") != end_date:
                continue
            ranked_slug = row.get("model_permaslug")
            if not isinstance(ranked_slug, str) or ranked_slug == "other":
                continue
            try:
                total_tokens = int(row.get("total_tokens") or 0)
            except (TypeError, ValueError):
                continue
            totals[ranked_slug] = totals.get(ranked_slug, 0) + total_tokens
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        raise LLMError(f"抓取 OpenRouter 本日模型排行榜失敗：{exc}") from exc

    ranked_slugs = sorted(totals, key=lambda slug: (-totals[slug], slug))[
        :_DAILY_USAGE_POOL_LIMIT
    ]
    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for ranked_slug in ranked_slugs:
        model_id = model_keys.get(ranked_slug)
        if model_id and model_id not in seen:
            models.append(models_by_id[model_id])
            seen.add(model_id)
    return models

# Optional local preference; it is honored only when the model is present in
# today's live free catalog, so it can never opt into a paid or stale model.
_OR_DEFAULT = os.environ.get("OR_MODEL")


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
        if not models:
            raise LLMError("OpenRouter 沒有回傳可用的免費工具模型。")
        # A local preference may move a model to the front only when it is
        # present in today's live free list; it can never add a stale/paid ID.
        if _OR_DEFAULT in {model["id"] for model in models}:
            models = sorted(models, key=lambda m: 0 if m["id"] == _OR_DEFAULT else 1)
        _MODELS_CACHE[provider.value] = models
        _MODELS_CACHE_META[provider.value] = now
        return models
    except LLMError:
        cached = _MODELS_CACHE.get(provider.value)
        return cached if cached is not None else MODELS.get(provider.value, [])


def resolve_allowed_model(provider: LLMProvider, requested_model: str | None) -> str:
    """Resolve a request to a server-approved free, tool-capable model.

    Client input must never be forwarded directly to OpenRouter because every
    request uses the server-owned API key. The dynamic list is already filtered
    to zero-price tool models; there is no stale static fallback allowlist.
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
