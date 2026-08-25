"""Tests for the OpenRouter LLM integration and model selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from backend import llm


@pytest.fixture(autouse=True)
def restore_model_cache():
    """Keep global model-cache state isolated between tests."""
    cached_models = dict(llm._MODELS_CACHE)
    cache_meta = dict(llm._MODELS_CACHE_META)
    yield
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE.update(cached_models)
    llm._MODELS_CACHE_META.clear()
    llm._MODELS_CACHE_META.update(cache_meta)


def _chunk(content=None, finish_reason=None, model="openrouter/free"):
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model=model)


def _tool_chunk(tool_calls, finish_reason=None, model="routed/model:free"):
    delta = SimpleNamespace(content=None, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model=model)


def _consume(generator):
    chunks = []
    while True:
        try:
            chunks.append(next(generator))
        except StopIteration as stop:
            return chunks, stop.value


def test_ultra_is_static_fallback_default():
    assert llm._DEFAULT_MODEL == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert llm.MODELS["openrouter"][0]["id"] == llm._DEFAULT_MODEL


def test_provider_from_str_accepts_openrouter_and_rejects_unknown():
    assert llm.LLMProvider.from_str("openrouter") is llm.LLMProvider.openrouter

    with pytest.raises(llm.LLMError, match="未知的 provider"):
        llm.LLMProvider.from_str("unknown")


def test_fetch_free_models_filters_out_paid_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    response = MagicMock()
    response.json.return_value = {
        "data": [
            {
                "id": "vendor/free-without-tools",
                "name": "Free Without Tools",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["temperature"],
            },
            {
                "id": "vendor/free-with-tools",
                "name": "Free With Tools",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools", "temperature"],
            },
            {
                "id": "vendor/paid",
                "name": "Paid",
                "pricing": {"prompt": "0.1", "completion": "0.2"},
                "supported_parameters": ["tools"],
            },
        ]
    }
    popularity_response = MagicMock()
    popularity_response.json.return_value = {
        "data": {
            "models": [
                {"endpoint": {"model_variant_slug": "vendor/free-with-tools"}},
            ]
        }
    }
    get = MagicMock(side_effect=[response, popularity_response])
    monkeypatch.setattr(llm.httpx, "get", get)

    assert llm._fetch_free_models() == [
        {"id": "vendor/free-with-tools", "display": "Free With Tools"},
    ]
    response.raise_for_status.assert_called_once_with()
    assert get.call_args_list[0].kwargs["headers"] == {"Authorization": "Bearer test-key"}
    assert get.call_args_list[0].args == (
        "https://openrouter.ai/api/v1/models?supported_parameters=tools",
    )
    assert get.call_args_list[1].args == (llm._POPULARITY_URL,)


def test_fetch_free_models_sorts_by_weekly_usage(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    models_response = MagicMock()
    models_response.json.return_value = {
        "data": [
            {
                "id": "vendor/less-used:free",
                "name": "Less Used",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools"],
            },
            {
                "id": "vendor/popular:free",
                "name": "Popular",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools"],
            },
        ]
    }
    popularity_response = MagicMock()
    popularity_response.json.return_value = {
        "data": {
            "models": [
                {"endpoint": {"model_variant_slug": "vendor/popular:free"}},
                {"endpoint": {"model_variant_slug": "vendor/less-used:free"}},
            ]
        }
    }
    monkeypatch.setattr(
        llm.httpx,
        "get",
        MagicMock(side_effect=[models_response, popularity_response]),
    )

    assert [model["id"] for model in llm._fetch_free_models()] == [
        "vendor/popular:free",
        "vendor/less-used:free",
    ]


def test_fetch_free_models_keeps_models_when_popularity_lookup_fails(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    models_response = MagicMock()
    models_response.json.return_value = {
        "data": [
            {
                "id": "vendor/model:free",
                "name": "Model",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools"],
            }
        ]
    }
    monkeypatch.setattr(
        llm.httpx,
        "get",
        MagicMock(side_effect=[models_response, httpx.ConnectError("offline")]),
    )

    assert llm._fetch_free_models() == [
        {"id": "vendor/model:free", "display": "Model"},
    ]


def test_fetch_free_models_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(llm.LLMError, match="未設定 OPENROUTER_API_KEY"):
        llm._fetch_free_models()


def test_fetch_free_models_wraps_http_errors(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        llm.httpx,
        "get",
        MagicMock(side_effect=httpx.ConnectError("offline")),
    )

    with pytest.raises(llm.LLMError, match="抓取 OpenRouter 模型列表失敗"):
        llm._fetch_free_models()


def test_fetch_free_models_returns_empty_when_api_has_no_compatible_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    response = MagicMock()
    response.json.return_value = {"data": []}
    monkeypatch.setattr(llm.httpx, "get", MagicMock(return_value=response))

    assert llm._fetch_free_models() == []


def test_get_models_preserves_weekly_usage_order(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    monkeypatch.setattr(llm, "_OR_DEFAULT", None)
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(
            return_value=[
                {"id": "vendor/other:free", "display": "Other"},
                {"id": llm._DEFAULT_MODEL, "display": "Ultra"},
            ]
        ),
    )

    models = llm._get_models(llm.LLMProvider.openrouter, force=True)

    assert models[0]["id"] == "vendor/other:free"


def test_get_models_honors_or_model_override(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    monkeypatch.setattr(llm, "_OR_DEFAULT", "vendor/preferred:free")
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(
            return_value=[
                {"id": "vendor/other:free", "display": "Other"},
                {"id": "vendor/preferred:free", "display": "Preferred"},
            ]
        ),
    )

    models = llm._get_models(llm.LLMProvider.openrouter, force=True)

    assert models[0]["id"] == "vendor/preferred:free"


def test_get_models_uses_valid_cache(monkeypatch):
    cached = [{"id": "cached/model", "display": "Cached"}]
    llm._MODELS_CACHE["openrouter"] = cached
    llm._MODELS_CACHE_META["openrouter"] = llm.time.time()
    fetch = MagicMock()
    monkeypatch.setattr(llm, "_fetch_free_models", fetch)

    assert llm._get_models(llm.LLMProvider.openrouter) is cached
    fetch.assert_not_called()


def test_get_models_falls_back_to_static_list(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(side_effect=llm.LLMError("offline")),
    )

    models = llm._get_models(llm.LLMProvider.openrouter, force=True)

    assert models is llm.MODELS["openrouter"]
    assert models[0]["id"] == llm._DEFAULT_MODEL


def test_list_providers_reports_configuration(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_models = MagicMock(return_value=[{"id": llm._DEFAULT_MODEL, "display": "Ultra"}])
    monkeypatch.setattr(llm, "_get_models", get_models)

    providers = llm.list_providers(force=True)

    assert providers[0]["configured"] is True
    assert providers[0]["models"][0]["id"] == llm._DEFAULT_MODEL
    get_models.assert_called_once_with(llm.LLMProvider.openrouter, force=True)


def test_build_client_requires_key_and_uses_openrouter_endpoint(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="未設定 OPENROUTER_API_KEY"):
        llm._build_client(llm.LLMProvider.openrouter)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = object()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(llm, "OpenAI", constructor)

    assert llm._build_client(llm.LLMProvider.openrouter) is client
    constructor.assert_called_once_with(
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
    )


def test_call_llm_stream_yields_content(monkeypatch):
    create = MagicMock(
        return_value=[
            _chunk("跑鞋"),
            _chunk("建議"),
            _chunk(finish_reason="stop"),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))

    chunks = list(
        llm.call_llm_stream(
            llm.LLMProvider.openrouter,
            "openrouter/free",
            [{"role": "user", "content": "推薦跑鞋"}],
        )
    )

    assert chunks == ["跑鞋", "建議"]
    assert create.call_args.kwargs["model"] == "openrouter/free"
    assert create.call_args.kwargs["stream"] is True


def test_call_llm_stream_reassembles_native_tool_call_fragments(monkeypatch):
    first_call = SimpleNamespace(
        index=0,
        id="call_abc",
        function=SimpleNamespace(name="nearing_end_", arguments='{"threshold":'),
    )
    second_call = SimpleNamespace(
        index=0,
        id=None,
        function=SimpleNamespace(name="of_life", arguments="0.8}"),
    )
    create = MagicMock(
        return_value=[
            _tool_chunk([first_call]),
            _tool_chunk([second_call], finish_reason="tool_calls"),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))
    tools = [{"type": "function", "function": {"name": "nearing_end_of_life"}}]

    chunks, result = _consume(
        llm.call_llm_stream(
            llm.LLMProvider.openrouter,
            "openrouter/free",
            [],
            tools=tools,
        )
    )

    assert chunks == []
    assert result["model"] == "routed/model:free"
    assert result["finish_reason"] == "tool_calls"
    assert result["tool_calls"] == [
        {
            "id": "call_abc",
            "name": "nearing_end_of_life",
            "arguments": {"threshold": 0.8},
            "arguments_json": '{"threshold":0.8}',
        }
    ]
    assert create.call_args.kwargs["tools"] is tools


def test_call_llm_stream_handles_incomplete_and_invalid_tool_arguments(monkeypatch):
    calls = [
        SimpleNamespace(index=None, id=None, function=None),
        SimpleNamespace(
            index=1,
            id=None,
            function=SimpleNamespace(name="shoe_summary", arguments="[]"),
        ),
        SimpleNamespace(
            index=2,
            id="call_bad_json",
            function=SimpleNamespace(name="monthly_mileage_stats", arguments="{bad"),
        ),
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=MagicMock(
                    return_value=[_tool_chunk(calls, finish_reason="tool_calls")]
                )
            )
        )
    )
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))

    _, result = _consume(
        llm.call_llm_stream(llm.LLMProvider.openrouter, "openrouter/free", [])
    )

    assert result["tool_calls"][0] == {
        "id": "call_1",
        "name": "shoe_summary",
        "arguments": {},
        "arguments_json": "{}",
    }
    assert result["tool_calls"][1]["arguments"] == {}
    assert result["tool_calls"][1]["arguments_json"] == "{}"


def test_call_llm_stream_wraps_sdk_errors(monkeypatch):
    create = MagicMock(side_effect=RuntimeError("provider unavailable"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))

    with pytest.raises(llm.LLMError, match="LLM 串流呼叫失敗"):
        list(llm.call_llm_stream(llm.LLMProvider.openrouter, "openrouter/free", []))


def test_call_llm_stream_rejects_empty_stream(monkeypatch):
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=MagicMock(return_value=[])))
    )
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))

    with pytest.raises(llm.LLMError, match="LLM 回傳空串流"):
        list(llm.call_llm_stream(llm.LLMProvider.openrouter, "openrouter/free", []))


def test_call_llm_stream_skips_chunks_without_choices(monkeypatch):
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=MagicMock(
                    return_value=[
                        SimpleNamespace(choices=[]),
                        _chunk(finish_reason="stop"),
                    ]
                )
            )
        )
    )
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))

    assert list(llm.call_llm_stream(llm.LLMProvider.openrouter, "openrouter/free", [])) == []


def test_call_llm_stream_preserves_llm_errors_from_iterator(monkeypatch):
    def failing_stream():
        raise llm.LLMError("upstream detail")
        yield  # pragma: no cover - makes this a generator

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=MagicMock(return_value=failing_stream()))
        )
    )
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))

    with pytest.raises(llm.LLMError, match="upstream detail"):
        list(llm.call_llm_stream(llm.LLMProvider.openrouter, "openrouter/free", []))
