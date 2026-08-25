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


def test_openrouter_free_is_static_default():
    assert llm._DEFAULT_MODEL == "openrouter/free"
    assert llm.MODELS["openrouter"][0]["id"] == "openrouter/free"


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
                "id": "openrouter/free",
                "name": "Free Models Router",
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "vendor/paid",
                "name": "Paid",
                "pricing": {"prompt": "0.1", "completion": "0.2"},
            },
        ]
    }
    get = MagicMock(return_value=response)
    monkeypatch.setattr(llm.httpx, "get", get)

    assert llm._fetch_free_models() == [
        {"id": "openrouter/free", "display": "Free Models Router"}
    ]
    response.raise_for_status.assert_called_once_with()
    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer test-key"}


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


def test_fetch_free_models_rejects_empty_free_list(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    response = MagicMock()
    response.json.return_value = {"data": []}
    monkeypatch.setattr(llm.httpx, "get", MagicMock(return_value=response))

    with pytest.raises(llm.LLMError, match="沒有回傳任何免費模型"):
        llm._fetch_free_models()


def test_get_models_places_openrouter_free_first(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    monkeypatch.setattr(llm, "_OR_DEFAULT", None)
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(
            return_value=[
                {"id": "vendor/other:free", "display": "Other"},
                {"id": "openrouter/free", "display": "Auto"},
            ]
        ),
    )

    models = llm._get_models(llm.LLMProvider.openrouter, force=True)

    assert models[0]["id"] == "openrouter/free"


def test_get_models_honors_or_model_override(monkeypatch):
    llm._MODELS_CACHE.clear()
    llm._MODELS_CACHE_META.clear()
    monkeypatch.setattr(llm, "_OR_DEFAULT", "vendor/preferred:free")
    monkeypatch.setattr(
        llm,
        "_fetch_free_models",
        MagicMock(
            return_value=[
                {"id": "openrouter/free", "display": "Auto"},
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
    assert models[0]["id"] == "openrouter/free"


def test_list_providers_reports_configuration(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_models = MagicMock(return_value=[{"id": "openrouter/free", "display": "Auto"}])
    monkeypatch.setattr(llm, "_get_models", get_models)

    providers = llm.list_providers(force=True)

    assert providers[0]["configured"] is True
    assert providers[0]["models"][0]["id"] == "openrouter/free"
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
