"""Tests for the streaming agent loop and its tool dispatcher."""

import json
from unittest.mock import MagicMock

import pytest

from backend import agent, llm
from backend.tools import db_tools


def _events(stream):
    return [json.loads(item.removeprefix("data: ").strip()) for item in stream]


def _event_types(events):
    return [event["type"] for event in events]


def test_build_messages_keeps_only_nonempty_chat_turns():
    messages = agent._build_messages(
        [
            {"role": "user", "content": "上一題"},
            {"role": "assistant", "content": "上一答"},
            {"role": "system", "content": "不應保留"},
            {"role": "user", "content": ""},
        ],
        "新問題",
    )

    assert messages[0]["role"] == "system"
    assert messages[1:] == [
        {"role": "user", "content": "上一題"},
        {"role": "assistant", "content": "上一答"},
        {"role": "user", "content": "新問題"},
    ]


def test_execute_tool_dispatches_all_argument_shapes(monkeypatch):
    monkeypatch.setattr(agent, "run_web_search", lambda args: f"search:{args['query']}")
    assert agent._execute_tool("web_search", {"query": "跑鞋"}, None, 7) == "search:跑鞋"
    assert "未知工具" in agent._execute_tool("missing", {}, None, 7)

    nearing = MagicMock(return_value="near")
    compare = MagicMock(return_value="compare")
    category = MagicMock(return_value="category")
    generic = MagicMock(return_value="generic")
    monkeypatch.setitem(db_tools.REGISTRY, "nearing_end_of_life", nearing)
    monkeypatch.setitem(db_tools.REGISTRY, "compare_shoes", compare)
    monkeypatch.setitem(db_tools.REGISTRY, "shoe_category_status", category)
    monkeypatch.setitem(db_tools.REGISTRY, "generic", generic)

    assert agent._execute_tool("nearing_end_of_life", {"threshold": "invalid"}, "db", 7) == "near"
    nearing.assert_called_once_with("db", 7, threshold=0.8)
    agent._execute_tool("nearing_end_of_life", {"threshold": 9}, "db", 7)
    assert nearing.call_args.kwargs["threshold"] == 1.0

    assert agent._execute_tool(
        "compare_shoes", {"shoe_a": "A", "shoe_b": "B"}, "db", 7
    ) == "compare"
    compare.assert_called_once_with("db", 7, shoe_a="A", shoe_b="B")

    assert agent._execute_tool("shoe_category_status", {"shoe_name": "A"}, "db", 7) == "category"
    category.assert_called_once_with("db", 7, shoe_name="A")
    assert agent._execute_tool("generic", {}, "db", 7) == "generic"
    generic.assert_called_once_with("db", 7)


def test_invalid_provider_emits_error_then_done():
    events = _events(agent.run_agent_stream("hello", provider="invalid"))

    assert _event_types(events) == ["error", "done"]
    assert "未知的 provider" in events[0]["text"]


def test_plain_response_streams_tokens_and_uses_default_model(monkeypatch):
    call = MagicMock(return_value=iter(["跑鞋", "建議"]))
    monkeypatch.setattr(llm, "call_llm_stream", call)

    events = _events(
        agent.run_agent_stream(
            "請推薦",
            history=[{"role": "user", "content": "之前的問題"}],
            model=None,
        )
    )

    assert _event_types(events) == ["token", "token", "done"]
    assert "".join(event.get("text", "") for event in events) == "跑鞋建議"
    assert call.call_args.args[1] == "openrouter/free"
    assert call.call_args.args[2][-1] == {"role": "user", "content": "請推薦"}


def test_empty_response_emits_user_friendly_fallback(monkeypatch):
    monkeypatch.setattr(llm, "call_llm_stream", MagicMock(return_value=iter([])))

    events = _events(agent.run_agent_stream("請推薦", model="openrouter/free"))

    assert _event_types(events) == ["token", "done"]
    assert "模型沒有回應" in events[0]["text"]


def test_falsy_stream_chunks_are_ignored(monkeypatch):
    monkeypatch.setattr(llm, "call_llm_stream", MagicMock(return_value=iter(["", "回答"])))
    events = _events(agent.run_agent_stream("請推薦", model="openrouter/free"))
    assert events == [{"type": "token", "text": "回答"}, {"type": "done"}]


def test_zero_turn_limit_finishes_without_calling_model(monkeypatch):
    monkeypatch.setattr(agent, "MAX_TURNS", 0)
    model = MagicMock()
    monkeypatch.setattr(llm, "call_llm_stream", model)
    assert _events(agent.run_agent_stream("請推薦")) == [{"type": "done"}]
    model.assert_not_called()


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (llm.LLMError("rate limited"), "rate limited"),
        (RuntimeError("broken generator"), "模型呼叫發生錯誤"),
    ],
)
def test_model_errors_are_reported_and_stream_finishes(monkeypatch, exception, expected):
    monkeypatch.setattr(llm, "call_llm_stream", MagicMock(side_effect=exception))

    events = _events(agent.run_agent_stream("請推薦", model="openrouter/free"))

    assert _event_types(events) == ["error", "done"]
    assert expected in events[0]["text"]


def test_tool_round_executes_tool_then_returns_final_answer(monkeypatch):
    model_calls = MagicMock(
        side_effect=[
            iter(["我先查資料。", '<tool>shoe_summary {}</tool>']),
            iter(["你的鞋況目前很健康。"]),
        ]
    )
    tool = MagicMock(return_value="共 5 雙跑鞋")
    monkeypatch.setattr(llm, "call_llm_stream", model_calls)
    monkeypatch.setattr(agent, "_execute_tool", tool)

    events = _events(agent.run_agent_stream("查鞋況", model="openrouter/free", db="db", user_id=7))

    assert _event_types(events) == [
        "token",
        "reasoning_start",
        "tool",
        "tool_done",
        "token",
        "done",
    ]
    assert events[2] == {"type": "tool", "name": "shoe_summary", "args": {}}
    tool.assert_called_once_with("shoe_summary", {}, "db", 7)
    second_messages = model_calls.call_args_list[1].args[2]
    assert second_messages[-1]["content"] == "[工具 shoe_summary 的結果]\n共 5 雙跑鞋"


def test_only_first_tool_is_executed_when_model_emits_multiple(monkeypatch):
    model_calls = MagicMock(
        side_effect=[
            iter(
                [
                    '<tool>shoe_summary {}</tool>',
                    '<tool>monthly_mileage_stats {}</tool>',
                ]
            ),
            iter(["完成"]),
        ]
    )
    tool = MagicMock(return_value="result")
    monkeypatch.setattr(llm, "call_llm_stream", model_calls)
    monkeypatch.setattr(agent, "_execute_tool", tool)

    events = _events(agent.run_agent_stream("分析", model="openrouter/free"))

    assert [event.get("name") for event in events if event["type"] == "tool"] == ["shoe_summary"]
    tool.assert_called_once()


def test_three_failed_web_searches_add_convergence_instruction(monkeypatch):
    snapshots = []
    responses = iter(
        [
            ['<tool>web_search {"query": "A"}</tool>'],
            ['<tool>web_search {"query": "B"}</tool>'],
            ['<tool>web_search {"query": "C"}</tool>'],
            ["依現有資料回答。"],
        ]
    )

    def fake_model(provider, model, messages):
        snapshots.append([dict(message) for message in messages])
        return iter(next(responses))

    monkeypatch.setattr(llm, "call_llm_stream", fake_model)
    monkeypatch.setattr(agent, "run_web_search", MagicMock(return_value="（搜尋暫時失敗）"))

    events = _events(agent.run_agent_stream("推薦新鞋", model="openrouter/free"))

    assert sum(event["type"] == "tool" for event in events) == 3
    assert any(
        "再呼叫 web_search" in message["content"]
        for message in snapshots[-1]
    )
    assert events[-2] == {"type": "token", "text": "依現有資料回答。"}


def test_last_turn_forces_answer_without_another_tool(monkeypatch):
    snapshots = []
    call_count = 0

    def fake_model(provider, model, messages):
        nonlocal call_count
        call_count += 1
        snapshots.append([dict(message) for message in messages])
        if call_count < agent.MAX_TURNS:
            return iter(['<tool>shoe_summary {}</tool>'])
        return iter(["最後結論"])

    monkeypatch.setattr(llm, "call_llm_stream", fake_model)
    tool = MagicMock(return_value="鞋況")
    monkeypatch.setattr(agent, "_execute_tool", tool)

    events = _events(agent.run_agent_stream("完整分析", model="openrouter/free"))

    assert call_count == agent.MAX_TURNS
    assert tool.call_count == agent.MAX_TURNS - 1
    assert any("這是最後一輪" in message["content"] for message in snapshots[-1])
    assert events[-2] == {"type": "token", "text": "最後結論"}
