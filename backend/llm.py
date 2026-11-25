"""LLM 抽象層 — 目前僅使用 OpenRouter（串流版）。

OpenRouter 提供 OpenAI-compatible 端點，用同一個 `openai` SDK 設定
`base_url` + api_key 即可。本模組只負責「呼叫模型並回傳標準化結果」，
不處理 tool loop（那是 agent.py 的責任）。
"""

import json
import logging
import time
from collections.abc import Generator
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from openai import OpenAI

from backend.settings import Settings


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


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Provider credentials and limits, injected by the composition root (SPEC-093)."""

    api_key: str | None = None
    default_model: str | None = None
    max_output_tokens: int = 4096

    def __repr__(self) -> str:
        return f"LLMConfig(api_key={'set' if self.api_key else None}, default_model={self.default_model!r}, "                f"max_output_tokens={self.max_output_tokens})"

    @classmethod
    def from_settings(cls, config: Settings) -> "LLMConfig":
        return cls(api_key=config.openrouter_api_key, default_model=config.openrouter_default_model,
                   max_output_tokens=config.llm_max_output_tokens)


# One process serves one application, so create_app configures this adapter once. Scripts
# and tests that call it directly without an app read the environment at call time.
_config: LLMConfig | None = None


def configure(config: LLMConfig | None) -> None:
    """Install the application's LLM configuration; ``None`` returns to the environment."""
    global _config
    _config = config


def current_config() -> LLMConfig:
    return _config if _config is not None else LLMConfig.from_settings(Settings.from_env())


# 各家 endpoint 與缺 key 時顯示的設定名稱
_PROVIDER_CONFIG = {
    LLMProvider.openrouter: {
        "base_url": "https://openrouter.ai/api/v1",
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
_MODELS_CACHE_LOCK = Lock()
_MODELS_CACHE_TTL = 900  # 15 分鐘；讓「今日免費」清單保持新鮮
# A failed refresh may briefly reuse the last verified free catalog so a
# transient OpenRouter outage does not immediately disable the UI.  After this
# grace period we fail closed: an old model may no longer be free.
_MODELS_CACHE_MAX_STALE = 3600

_DEFAULT_MODEL: str | None = None
_REMOVED_MODELS = {"openrouter/free"}

_MODELS_URL = "https://openrouter.ai/api/v1/models?supported_parameters=tools"
_RANKINGS_URL = "https://openrouter.ai/api/v1/datasets/rankings-daily"
_DAILY_USAGE_POOL_LIMIT = 50
# SPEC-118: when no free tool model is in the top 50, fall back to the most-used
# free tool models anywhere in today's ranking, at most this many.
_FALLBACK_MODEL_LIMIT = 5

# OpenAI SDK 2.47+ uses httpx2 internally while older supported releases use
# httpx. A plain number is accepted by both clients and keeps the application
# independent of either transport's private Timeout type.
_LLM_TIMEOUT_SECONDS = 90.0


def _fetch_free_models() -> list[dict[str, str]]:
    """抓取今日使用量前 50 名中的免費工具模型；前 50 名沒有時，改取整份排行榜的前 5 個。

    Pricing and tool support come from the live catalog. Popularity comes from
    ``rankings-daily``: rank every model first, keep the top 50, then intersect
    that pool with the free, tool-capable catalog. This avoids presenting
    obscure catalog entries as today's usable models. When that intersection is
    empty (SPEC-118), the whole ranking is intersected instead and the most-used
    free tool models are kept; models absent from today's ranking never appear.
    """
    cfg = _PROVIDER_CONFIG[LLMProvider.openrouter]
    api_key = current_config().api_key
    if not api_key:
        raise LLMError(f"未設定 {cfg['key_label']}，無法抓取模型列表。")

    try:
        data = _get_json(_MODELS_URL, api_key)
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise LLMError(f"抓取 OpenRouter 模型列表失敗：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise LLMError("抓取 OpenRouter 模型列表失敗：回傳格式無效。")
    models_by_id, model_keys = _free_tool_models(data["data"])

    try:
        totals = _daily_token_totals(_get_json(_RANKINGS_URL, api_key))
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        raise LLMError(f"抓取 OpenRouter 本日模型排行榜失敗：{exc}") from exc

    ranked_slugs = sorted(totals, key=lambda slug: (-totals[slug], slug))
    models = _ranked_free_models(ranked_slugs[:_DAILY_USAGE_POOL_LIMIT], models_by_id, model_keys)
    if models:
        return models
    return _ranked_free_models(ranked_slugs, models_by_id, model_keys)[:_FALLBACK_MODEL_LIMIT]


def _ranked_free_models(
    ranked_slugs: list[str], models_by_id: dict[str, dict[str, str]], model_keys: dict[str, str],
) -> list[dict[str, str]]:
    """Free tool models in ranking order, each once."""
    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for ranked_slug in ranked_slugs:
        model_id = model_keys.get(ranked_slug)
        if model_id and model_id not in seen:
            models.append(models_by_id[model_id])
            seen.add(model_id)
    return models


def _get_json(url: str, api_key: str) -> Any:
    response = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
    response.raise_for_status()
    return response.json()


def _is_free(pricing: dict) -> bool:
    try:
        return float(str(pricing.get("prompt"))) == 0 and float(str(pricing.get("completion"))) == 0
    except (TypeError, ValueError):
        return False


def _free_tool_models(items: list) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Free, tool-capable catalog models by ID, and every ranking key that names one of them."""
    models_by_id: dict[str, dict[str, str]] = {}
    model_keys: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        pricing = item.get("pricing")
        supported = item.get("supported_parameters")
        supports_tools = "tools" in (supported if isinstance(supported, list) else [])
        if not (_is_free(pricing if isinstance(pricing, dict) else {}) and supports_tools
                and model_id not in _REMOVED_MODELS):
            continue
        models_by_id[model_id] = {"id": model_id, "display": str(item.get("name") or model_id)}
        model_keys[model_id] = model_id
        _add_canonical_key(model_keys, model_id, item.get("canonical_slug"))
    return models_by_id, model_keys


def _add_canonical_key(model_keys: dict[str, str], model_id: str, canonical: Any) -> None:
    """Rankings name models by canonical slug, keeping a variant suffix such as ``:free``."""
    if not isinstance(canonical, str) or not canonical:
        return
    tail = model_id.rsplit("/", 1)[-1]
    if ":" in tail:
        variant = tail.split(":", 1)[1]
        model_keys.setdefault(f"{canonical}:{variant}", model_id)
    else:
        model_keys.setdefault(canonical, model_id)


def _daily_token_totals(ranking_body: Any) -> dict[str, int]:
    """Total tokens per model slug on the ranking's latest day."""
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
        ranked_slug = row.get("model_permaslug")
        if (end_date and row.get("date") != end_date) or not isinstance(ranked_slug, str) or ranked_slug == "other":
            continue
        try:
            total_tokens = int(row.get("total_tokens") or 0)
        except (TypeError, ValueError):
            continue
        totals[ranked_slug] = totals.get(ranked_slug, 0) + total_tokens
    return totals

def _get_models(provider: LLMProvider, force: bool = False) -> list[dict[str, str]]:
    """取得模型列表，優先使用快取，快取失效時從 OpenRouter API 抓取。
    預設模型會排到最前面。
    """
    now = time.time()
    cached = _MODELS_CACHE.get(provider.value)
    cached_at = _MODELS_CACHE_META.get(provider.value, 0)
    if not force and cached is not None and (now - cached_at) < _MODELS_CACHE_TTL:
        return cached

    with _MODELS_CACHE_LOCK:
        # Another request may have filled the cold cache while this request
        # waited for the lock. Avoid duplicate outbound catalog/ranking calls.
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
            # The optional OR_MODEL preference can only reorder today's live free list.
            preferred = current_config().default_model
            if preferred in {model["id"] for model in models}:
                models = sorted(models, key=lambda m: 0 if m["id"] == preferred else 1)
            _MODELS_CACHE[provider.value] = models
            _MODELS_CACHE_META[provider.value] = now
            return models
        except LLMError:
            cached = _MODELS_CACHE.get(provider.value)
            cached_at = _MODELS_CACHE_META.get(provider.value, 0)
            if cached is not None and (time.time() - cached_at) <= _MODELS_CACHE_MAX_STALE:
                return cached
            return MODELS.get(provider.value, [])


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
        has_key = bool(current_config().api_key)
        models = _get_models(provider, force=force) if has_key else MODELS.get(provider.value, [])
        out.append({
            "id": provider.value,
            "label": provider.value,
            "key_env": cfg["key_label"],
            "configured": has_key,
            "models": models,
        })
    return out


def _build_client(provider: LLMProvider) -> "OpenAI":
    cfg = _PROVIDER_CONFIG[provider]
    api_key = current_config().api_key
    if not api_key:
        raise LLMError(f"未設定 {cfg['key_label']}，無法使用 {provider.value}。")
    # The SDK takes about a third of the backend import time; only AI requests need it,
    # so a cold start skips it and the first AI call pays the one-time import.
    from openai import OpenAI

    return OpenAI(
        base_url=cfg["base_url"],
        api_key=api_key,
        timeout=_LLM_TIMEOUT_SECONDS,
    )


logger = logging.getLogger("running_shoes.llm")


def user_facing_error(exc: Exception) -> str:
    """Actionable text for the browser; never the provider's raw response.

    The OpenAI SDK embeds the provider's whole error body in its message, which
    can include upstream provider details and account identifiers. That detail
    goes to the server log only. The SDK is matched by class name so this module
    still does not import it at startup.
    """
    names = {cls.__name__ for cls in type(exc).__mro__}
    status = getattr(exc, "status_code", None)
    if "APITimeoutError" in names or isinstance(exc, TimeoutError):
        return "模型回應逾時，請稍後再試或更換模型。"
    if "APIConnectionError" in names:
        return "無法連線到模型服務，請稍後再試。"
    if status == 429:
        return "這個免費模型目前請求過多或今日額度已滿，請稍後再試或更換模型。"
    if status == 402:
        return "模型服務額度不足，請更換模型或稍後再試。"
    if status in (401, 403):
        return "模型服務驗證失敗，請聯絡網站管理員。"
    if status in (400, 404, 422):
        return "這個模型目前無法處理請求，請更換模型。"
    if isinstance(status, int) and status >= 500:
        return "模型服務暫時無法使用，請稍後再試或更換模型。"
    return "模型呼叫發生錯誤，請稍後再試或更換模型。"


class ReasoningText(str):
    """A streamed fragment of the model's reasoning, never part of the answer.

    Only yielded when ``call_llm_stream(include_reasoning=True)``; callers tell it
    apart from answer text with ``isinstance`` (SPEC-086).
    """


def _reasoning_text(delta: Any) -> str:
    """Readable reasoning carried by one streamed delta, or ``""``.

    OpenRouter streams reasoning as ``delta.reasoning`` (``reasoning_content`` is
    its alias) together with structured ``reasoning_details``. Only one source is
    read per delta so the same text is never shown twice; encrypted details are
    opaque and skipped.
    """
    for name in ("reasoning", "reasoning_content"):
        value = getattr(delta, name, None)
        if isinstance(value, str) and value:
            return value
    details = getattr(delta, "reasoning_details", None)
    parts: list[str] = []
    for detail in details if isinstance(details, list) else []:
        key = _READABLE_REASONING_FIELDS.get(_detail_field(detail, "type"))
        value = _detail_field(detail, key) if key else None
        if isinstance(value, str):
            parts.append(value)
    return "".join(parts)


_READABLE_REASONING_FIELDS = {"reasoning.text": "text", "reasoning.summary": "summary"}


def _detail_field(detail: Any, key: str) -> Any:
    return detail.get(key) if isinstance(detail, dict) else getattr(detail, key, None)


def call_llm_stream(
    provider: LLMProvider,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    include_reasoning: bool = False,
) -> Generator[str, None, dict[str, Any]]:
    """串流呼叫模型，逐 token 產出文字並收集原生 tool calls。

    Yields:
        每個 token 的文字片段（可能為空字串，由呼叫方自行過濾）。
        include_reasoning=True 時，模型的思考片段以 ``ReasoningText`` 產出；
        它不會併入回傳的 content。

    Returns:
        {"content": str, "finish_reason": str | None, "tool_calls": list,
         "model": str | None}
        在 generator 結束時回傳（透過 StopIteration value）。
    """
    client = _build_client(provider)

    kwargs = _stream_request(model, messages, tools)
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
            if include_reasoning and delta:
                reasoning = _reasoning_text(delta)
                if reasoning:
                    yield ReasoningText(reasoning)
            if delta and delta.content:
                full_content += delta.content
                yield delta.content
            _merge_tool_call_deltas(tool_call_parts, getattr(delta, "tool_calls", None) or [])
            if choice.finish_reason:
                finish_reason = choice.finish_reason
    except LLMError:
        raise
    except Exception as exc:
        logger.warning("LLM stream failed (%s / %s): %r", provider.value, model, exc)
        raise LLMError(user_facing_error(exc)) from exc
    finally:
        _close_quietly(stream)

    if not full_content and finish_reason is None:
        raise LLMError(f"LLM 回傳空串流（{provider.value} / {model}）")

    return {
        "content": full_content,
        "finish_reason": finish_reason,
        "tool_calls": _finished_tool_calls(tool_call_parts),
        "model": actual_model,
    }


def _stream_request(model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": current_config().max_output_tokens,
        "stream": True,
        "stream_options": {"include_usage": False},
    }
    if tools:
        kwargs["tools"] = tools
    return kwargs


def _close_quietly(stream: Any) -> None:
    """Close the provider stream if it was opened and can be closed."""
    close_stream = getattr(stream, "close", None)
    if close_stream is not None:
        close_stream()


def _merge_tool_call_deltas(parts: dict[int, dict[str, str]], tool_calls: list) -> None:
    """Native tool calls arrive in fragments; join each call's ID, name and arguments by index."""
    for position, tool_call in enumerate(tool_calls):
        index = getattr(tool_call, "index", None)
        index = position if index is None else index
        part = parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if getattr(tool_call, "id", None):
            part["id"] = tool_call.id
        function = getattr(tool_call, "function", None)
        if function:
            part["name"] += getattr(function, "name", None) or ""
            part["arguments"] += getattr(function, "arguments", None) or ""


def _finished_tool_calls(parts: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
    """Named calls in index order; arguments that are not a JSON object become ``{}``."""
    tool_calls = []
    for index, part in sorted(parts.items()):
        if not part["name"]:
            continue
        raw_arguments = part["arguments"] or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except (TypeError, json.JSONDecodeError):
            arguments = None
        normalized_arguments = raw_arguments if isinstance(arguments, dict) else "{}"
        tool_calls.append({
            "id": part["id"] or f"call_{index}",
            "name": part["name"],
            "arguments": arguments if isinstance(arguments, dict) else {},
            "arguments_json": normalized_arguments,
        })
    return tool_calls
