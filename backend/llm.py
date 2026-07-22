"""LLM 抽象層 — 目前僅使用 OpenRouter（串流版）。

OpenRouter 提供 OpenAI-compatible 端點，用同一個 `openai` SDK 設定
`base_url` + api_key 即可。本模組只負責「呼叫模型並回傳標準化結果」，
不處理 tool loop（那是 agent.py 的責任）。
"""

import os
from enum import Enum
from typing import Any, Generator

from openai import OpenAI


class LLMError(Exception):
    """LLM 呼叫失敗（缺 key、網路錯、模型不存在等）。"""


class LLMProvider(str, Enum):
    openrouter = "openrouter"

    @classmethod
    def from_str(cls, value: str) -> "LLMProvider":
        try:
            return cls(value)
        except ValueError:
            raise LLMError(f"未知的 provider：{value!r}（可用：openrouter）")


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
        {"id": "nvidia/nemotron-3-super-120b-a12b:free", "display": "Nemotron 3 Super 120B (free)"},
    ],
}

# 各 provider 的預設模型可被環境變數覆寫（使用者可在 .env 指定，
# 例如轉用付費模型時不必改程式碼）。
_OR_DEFAULT = os.environ.get("OR_MODEL")
if _OR_DEFAULT:
    _existing = [m["id"] for m in MODELS["openrouter"]]
    if _OR_DEFAULT not in _existing:
        MODELS["openrouter"] = [{"id": _OR_DEFAULT, "display": _OR_DEFAULT + " (env)"}] + MODELS["openrouter"]
    else:
        MODELS["openrouter"] = (
            [next(m for m in MODELS["openrouter"] if m["id"] == _OR_DEFAULT)]
            + [m for m in MODELS["openrouter"] if m["id"] != _OR_DEFAULT]
        )


def list_providers() -> list[dict[str, Any]]:
    """回傳前端下拉要用的 provider / model 清單，並標註 key 是否已設定。"""
    out = []
    for provider, cfg in _PROVIDER_CONFIG.items():
        has_key = bool(os.environ.get(cfg["key_env"]))
        out.append({
            "id": provider.value,
            "label": provider.value,
            "key_env": cfg["key_label"],
            "configured": has_key,
            "models": MODELS[provider.value],
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
) -> Generator[str, None, dict[str, Any]]:
    """串流呼叫模型，逐 token 產出文字片段。

    Yields:
        每個 token 的文字片段（可能為空字串，由呼叫方自行過濾）。

    Returns:
        {"content": str, "finish_reason": str | None}
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

    full_content = ""
    finish_reason = None

    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                full_content += delta.content
                yield delta.content
            if choice.finish_reason:
                finish_reason = choice.finish_reason
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"LLM 串流呼叫失敗（{provider.value} / {model}）：{exc}") from exc

    if not full_content and finish_reason is None:
        raise LLMError(f"LLM 回傳空串流（{provider.value} / {model}）")

    return {"content": full_content, "finish_reason": finish_reason}