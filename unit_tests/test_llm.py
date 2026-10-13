"""Tests for the OpenRouter LLM integration and model selection."""

import time
from concurrent.futures import ThreadPoolExecutor
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


def test_model_catalog_has_no_stale_static_default():
    assert llm._DEFAULT_MODEL is None
    assert llm.MODELS["openrouter"] == []


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
    ranking_response = MagicMock()
    ranking_response.json.return_value = {
        "data": [{"date": "2026-10-03", "model_permaslug": "vendor/free-with-tools", "total_tokens": "100"}],
        "meta": {"end_date": "2026-10-03"},
    }
    get = MagicMock(side_effect=[response, ranking_response])
    monkeypatch.setattr(llm.httpx, "get", get)

    assert llm._fetch_free_models() == [
        {"id": "vendor/free-with-tools", "display": "Free With Tools"},
    ]
    response.raise_for_status.assert_called_once_with()
    assert get.call_args_list[0].kwargs["headers"] == {"Authorization": "Bearer test-key"}
    assert get.call_args_list[0].args == (
        "https://openrouter.ai/api/v1/models?supported_parameters=tools",
    )
    assert get.call_args_list[1].args == (llm._RANKINGS_URL,)


def test_fetch_free_models_sorts_by_today_usage(monkeypatch):
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
    ranking_response = MagicMock()
    ranking_response.json.return_value = {
        "data": [
            {"date": "2026-10-03", "model_permaslug": "vendor/popular:free", "total_tokens": "200"},
            {"date": "2026-10-03", "model_permaslug": "vendor/less-used:free", "total_tokens": "10"},
        ],
        "meta": {"end_date": "2026-10-03"},
    }
    monkeypatch.setattr(
        llm.httpx,
        "get",
        MagicMock(side_effect=[models_response, ranking_response]),
    )

    assert [model["id"] for model in llm._fetch_free_models()] == [
        "vendor/popular:free",
        "vendor/less-used:free",
    ]


def test_fetch_free_models_rejects_catalog_only_fallback_when_ranking_fails(monkeypatch):
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

    with pytest.raises(llm.LLMError, match="本日模型排行榜失敗"):
        llm._fetch_free_models()


def test_fetch_free_models_only_keeps_free_tool_models_in_overall_top_50(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    models_response = MagicMock()
    models_response.json.return_value = {
        "data": [
            {
                "id": "vendor/in-top-50:free",
                "name": "In Top 50",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools"],
            },
            {
                "id": "vendor/outside-top-50:free",
                "name": "Outside Top 50",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools"],
            },
        ]
    }
    paid_rows = [
        {
            "date": "2026-10-03",
            "model_permaslug": f"vendor/paid-{index}",
            "total_tokens": str(1_000 - index),
        }
        for index in range(49)
    ]
    ranking_response = MagicMock()
    ranking_response.json.return_value = {
        "data": [
            *paid_rows,
            {
                "date": "2026-10-03",
                "model_permaslug": "vendor/in-top-50:free",
                "total_tokens": "100",
            },
            {
                "date": "2026-10-03",
                "model_permaslug": "vendor/outside-top-50:free",
                "total_tokens": "99",
            },
        ],
        "meta": {"end_date": "2026-10-03"},
    }
    monkeypatch.setattr(
        llm.httpx,
        "get",
        MagicMock(side_effect=[models_response, ranking_response]),
    )

    assert llm._fetch_free_models() == [
        {"id": "vendor/in-top-50:free", "display": "In Top 50"},
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


@pytest.mark.parametrize("payload", [{"data": {}}, {"data": [None, "bad"]}, []])
def test_fetch_free_models_rejects_or_skips_malformed_catalog(monkeypatch, payload):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    response = MagicMock()
    response.json.return_value = payload
    monkeypatch.setattr(llm.httpx, "get", MagicMock(return_value=response))

    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        # A malformed item is ignored, then the empty ranking response produces
        # an empty usable list rather than a server error.
        assert llm._fetch_free_models() == []
    else:
        with pytest.raises(llm.LLMError, match="回傳格式無效"):
            llm._fetch_free_models()


def test_get_models_preserves_today_usage_order(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    monkeypatch.setattr(llm, "_OR_DEFAULT", None)
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(
            return_value=[
                {"id": "vendor/other:free", "display": "Other"},
                {"id": "vendor/today:free", "display": "Today"},
            ]
        ),
    )

    models = llm._get_models(llm.LLMProvider.openrouter, force=True)

    assert models[0]["id"] == "vendor/other:free"


def test_get_models_honors_current_day_preference_only(monkeypatch):
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


def test_get_models_fails_closed_after_stale_cache_grace(monkeypatch):
    now = 10_000.0
    cached = [{"id": "formerly/free", "display": "Formerly Free"}]
    llm._MODELS_CACHE["openrouter"] = cached
    llm._MODELS_CACHE_META["openrouter"] = now - llm._MODELS_CACHE_MAX_STALE - 1
    monkeypatch.setattr(llm.time, "time", MagicMock(return_value=now))
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(side_effect=llm.LLMError("offline")),
    )

    assert llm._get_models(llm.LLMProvider.openrouter, force=True) == []


def test_get_models_allows_brief_stale_cache_grace(monkeypatch):
    now = 10_000.0
    cached = [{"id": "verified/free", "display": "Verified Free"}]
    llm._MODELS_CACHE["openrouter"] = cached
    llm._MODELS_CACHE_META["openrouter"] = now - llm._MODELS_CACHE_TTL - 1
    monkeypatch.setattr(llm.time, "time", MagicMock(return_value=now))
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(side_effect=llm.LLMError("offline")),
    )

    assert llm._get_models(llm.LLMProvider.openrouter, force=True) is cached


def test_get_models_falls_back_to_empty_catalog_without_live_data(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(side_effect=llm.LLMError("offline")),
    )

    models = llm._get_models(llm.LLMProvider.openrouter, force=True)

    assert models is llm.MODELS["openrouter"]
    assert models == []


def test_get_models_falls_back_when_successful_response_is_empty(monkeypatch):
    monkeypatch.setattr(llm, "_fetch_free_models", MagicMock(return_value=[]))

    models = llm._get_models(llm.LLMProvider.openrouter, force=True)

    assert models is llm.MODELS["openrouter"]


def test_resolve_allowed_model_accepts_allowlist_and_rejects_client_override(monkeypatch):
    allowed = [
        {"id": "vendor/free-tools:free", "display": "Free Tools"},
        {"id": "vendor/other:free", "display": "Other"},
    ]
    monkeypatch.setattr(llm, "_get_models", MagicMock(return_value=allowed))

    assert (
        llm.resolve_allowed_model(llm.LLMProvider.openrouter, None)
        == "vendor/free-tools:free"
    )
    assert (
        llm.resolve_allowed_model(
            llm.LLMProvider.openrouter, "vendor/other:free"
        )
        == "vendor/other:free"
    )
    with pytest.raises(llm.LLMError, match="不允許使用此模型"):
        llm.resolve_allowed_model(
            llm.LLMProvider.openrouter, "openai/expensive-paid-model"
        )


def test_resolve_allowed_model_rejects_empty_allowlist(monkeypatch):
    monkeypatch.setattr(llm, "_get_models", MagicMock(return_value=[]))

    with pytest.raises(llm.LLMError, match="沒有可用"):
        llm.resolve_allowed_model(llm.LLMProvider.openrouter, None)


def test_list_providers_reports_configuration(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_models = MagicMock(return_value=[{"id": "vendor/today:free", "display": "Today"}])
    monkeypatch.setattr(llm, "_get_models", get_models)

    providers = llm.list_providers(force=True)

    assert providers[0]["configured"] is True
    assert providers[0]["models"][0]["id"] == "vendor/today:free"
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
        timeout=llm._LLM_TIMEOUT_SECONDS,
    )


def test_cold_model_cache_is_fetched_once_across_threads(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    models = [{"id": "vendor/free:free", "display": "Free"}]

    def fetch():
        time.sleep(0.05)
        return models

    fetch_mock = MagicMock(side_effect=fetch)
    monkeypatch.setattr(llm, "_fetch_free_models", fetch_mock)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _index: llm._get_models(llm.LLMProvider.openrouter),
            range(4),
        ))

    assert results == [models] * 4
    fetch_mock.assert_called_once_with()


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
    assert create.call_args.kwargs["max_tokens"] == llm._LLM_MAX_OUTPUT_TOKENS


def test_call_llm_stream_closes_provider_stream_when_consumer_stops_early(monkeypatch):
    class ClosableStream:
        def __init__(self):
            self.closed = False

        def __iter__(self):
            return iter([_chunk("first"), _chunk("unused")])

        def close(self):
            self.closed = True

    provider_stream = ClosableStream()
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=MagicMock(return_value=provider_stream),
            )
        )
    )
    monkeypatch.setattr(llm, "_build_client", MagicMock(return_value=client))

    stream = llm.call_llm_stream(
        llm.LLMProvider.openrouter,
        "openrouter/free",
        [{"role": "user", "content": "搜尋跑鞋"}],
    )
    assert next(stream) == "first"

    stream.close()

    assert provider_stream.closed is True


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
