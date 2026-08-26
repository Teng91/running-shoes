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


def _native_response(*, content=(), tool_calls=()):
    def generate():
        yield from content
        return {
            "content": "".join(content),
            "finish_reason": "tool_calls" if tool_calls else "stop",
            "tool_calls": list(tool_calls),
            "model": "routed/model:free",
        }

    return generate()


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
    assert "remaining_mileage_km" in messages[0]["content"]
    assert "不要自行重算" in messages[0]["content"]
    assert "本輪必須重新呼叫" in messages[0]["content"]
    assert messages[1:] == [
        {"role": "user", "content": "上一題"},
        {"role": "assistant", "content": "上一答"},
        {"role": "user", "content": "新問題"},
    ]


@pytest.mark.parametrize("message", ["hi", "你好", "謝謝你", "你是誰？"])
def test_simple_conversation_does_not_offer_tools(message):
    assert agent._should_offer_tools(message) is False


@pytest.mark.parametrize("message", ["分析我的跑鞋", "幫我排課表", "比較兩雙鞋"])
def test_running_intents_offer_tools(message):
    assert agent._should_offer_tools(message) is True


def test_lookup_and_contextual_follow_ups_offer_tools_without_forcing_a_call():
    assert agent._should_offer_tools("幫我查 NB 的 SC Rebel v1") is True
    assert agent._should_offer_tools(
        "對",
        [{"role": "assistant", "content": "你要我上網查詢這雙鞋嗎？"}],
    ) is True
    assert agent._should_offer_tools(
        "SC Rebel v1 呢",
        [{"role": "user", "content": "幫我搜尋 NB 最新跑鞋"}],
    ) is True
    assert agent._should_offer_tools(
        "對",
        [{"role": "assistant", "content": "你喜歡藍色嗎？"}],
    ) is False
    assert agent._should_offer_tools(
        "謝謝你",
        [{"role": "user", "content": "幫我搜尋 NB 最新跑鞋"}],
    ) is False


def test_greeting_request_calls_model_without_tools(monkeypatch):
    call = MagicMock(return_value=iter(["你好！"]))
    monkeypatch.setattr(llm, "call_llm_stream", call)

    events = _events(agent.run_agent_stream("hi", model="vendor/free:free"))

    assert events[-2] == {"type": "token", "text": "你好！"}
    assert call.call_args.kwargs["tools"] is None


def test_execute_tool_dispatches_all_argument_shapes(monkeypatch):
    monkeypatch.setattr(agent, "run_web_search", lambda args: f"search:{args['query']}")
    assert agent._execute_tool("web_search", {"query": "跑鞋"}, None, 7) == "search:跑鞋"
    assert "未知工具" in agent._execute_tool("missing", {}, None, 7)
    assert "缺少使用者資料庫上下文" in agent._execute_tool(
        "shoe_summary", {}, None, 7
    )

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


def test_tool_done_event_marks_structured_search_failure():
    event = _events([
        agent._tool_done_event(
            "web_search",
            '{"tool":"web_search","ok":false,"status":"request_failed",'
            '"error":"blocked"}',
        )
    ])[0]

    assert event == {
        "type": "tool_done",
        "name": "web_search",
        "ok": False,
        "status": "request_failed",
        "message": "搜尋服務暫時無法連線",
        "error": "blocked",
    }


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
    assert call.call_args.args[1] == llm._DEFAULT_MODEL
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

    events = _events(
        agent.run_agent_stream("分析", model="openrouter/free", db="db", user_id=7)
    )

    assert [event.get("name") for event in events if event["type"] == "tool"] == ["shoe_summary"]
    tool.assert_called_once()


def test_bare_json_tool_call_stops_repetitive_model_stream_early(monkeypatch):
    emitted_calls = 0

    def repetitive_response():
        nonlocal emitted_calls
        yield "馬上幫你搜尋。"
        for _ in range(100):
            emitted_calls += 1
            yield (
                '{"tool":"web_search","arguments":'
                '{"query":"New Balance Rebel v1"}}'
            )

    model_calls = MagicMock(
        side_effect=[repetitive_response(), iter(["搜尋完成。"])]
    )
    execute = MagicMock(return_value='{"tool":"web_search","ok":true}')
    monkeypatch.setattr(llm, "call_llm_stream", model_calls)
    monkeypatch.setattr(agent, "_execute_tool", execute)

    events = _events(
        agent.run_agent_stream("推薦 Rebel v1 跑鞋", model="vendor/free:free")
    )

    assert emitted_calls == 1
    assert [event["name"] for event in events if event["type"] == "tool"] == [
        "web_search"
    ]
    execute.assert_called_once()
    assert events[-2] == {"type": "token", "text": "搜尋完成。"}


def test_duplicate_native_tool_call_is_returned_but_not_executed_twice(monkeypatch):
    call = {
        "id": "call_summary",
        "name": "shoe_summary",
        "arguments": {},
        "arguments_json": "{}",
    }
    snapshots = []
    responses = iter([
        _native_response(tool_calls=[call]),
        _native_response(tool_calls=[{**call, "id": "call_summary_again"}]),
        _native_response(content=("依現有資料回答。",)),
    ])

    def fake_model(provider, model, messages, **kwargs):
        snapshots.append([dict(message) for message in messages])
        return next(responses)

    execute = MagicMock(return_value="鞋況資料")
    monkeypatch.setattr(llm, "call_llm_stream", fake_model)
    monkeypatch.setattr(agent, "_execute_tool", execute)

    events = _events(
        agent.run_agent_stream("分析跑鞋", model="vendor/free:free", db="db", user_id=7)
    )

    assert sum(event["type"] == "tool" for event in events) == 2
    execute.assert_called_once()
    assert "duplicate_call_blocked" in snapshots[-1][-2]["content"]
    assert "不要**再呼叫" in snapshots[-1][-1]["content"]


def test_web_search_total_call_limit_blocks_fourth_distinct_search(monkeypatch):
    def call(index):
        return {
            "id": f"call_{index}",
            "name": "web_search",
            "arguments": {"query": f"query {index}"},
            "arguments_json": json.dumps({"query": f"query {index}"}),
        }

    responses = iter([
        _native_response(tool_calls=[call(1)]),
        _native_response(tool_calls=[call(2)]),
        _native_response(tool_calls=[call(3)]),
        _native_response(tool_calls=[call(4)]),
        _native_response(content=("停止搜尋並回答。",)),
    ])
    monkeypatch.setattr(
        llm, "call_llm_stream", lambda *args, **kwargs: next(responses)
    )
    execute = MagicMock(return_value='{"tool":"web_search","ok":true}')
    monkeypatch.setattr(agent, "_execute_tool", execute)

    events = _events(
        agent.run_agent_stream("推薦跑鞋", model="vendor/free:free", db="db", user_id=7)
    )

    assert sum(event["type"] == "tool" for event in events) == 4
    assert execute.call_count == 3
    assert events[-2] == {"type": "token", "text": "停止搜尋並回答。"}


def test_llm_can_choose_to_confirm_lookup_without_backend_forcing_search(monkeypatch):
    model = MagicMock(return_value=iter(["你是要我上網查 SC Rebel v1 嗎？"]))
    execute = MagicMock()
    monkeypatch.setattr(llm, "call_llm_stream", model)
    monkeypatch.setattr(agent, "_execute_tool", execute)

    events = _events(
        agent.run_agent_stream("幫我查 NB 的 SC Rebel v1", model="vendor/free:free")
    )

    assert events == [
        {"type": "token", "text": "你是要我上網查 SC Rebel v1 嗎？"},
        {"type": "done"},
    ]
    assert model.call_args.kwargs["tools"] is db_tools.TOOL_DEFINITIONS
    execute.assert_not_called()


def test_llm_receives_tools_after_user_affirms_search_confirmation(monkeypatch):
    call = {
        "id": "call_search",
        "name": "web_search",
        "arguments": {"query": "New Balance SC Rebel v1"},
        "arguments_json": '{"query":"New Balance SC Rebel v1"}',
    }
    responses = iter([
        _native_response(tool_calls=[call]),
        _native_response(content=("這是搜尋結果。",)),
    ])
    model = MagicMock(side_effect=lambda *args, **kwargs: next(responses))
    execute = MagicMock(return_value='{"tool":"web_search","ok":true,"results":[]}')
    monkeypatch.setattr(llm, "call_llm_stream", model)
    monkeypatch.setattr(agent, "_execute_tool", execute)

    events = _events(
        agent.run_agent_stream(
            "對",
            history=[
                {"role": "user", "content": "幫我查 NB 的 SC Rebel v1"},
                {"role": "assistant", "content": "你是要我上網查這雙鞋嗎？"},
            ],
            model="vendor/free:free",
        )
    )

    assert _event_types(events) == ["reasoning_start", "tool", "tool_done", "token", "done"]
    assert model.call_args_list[0].kwargs["tools"] is db_tools.TOOL_DEFINITIONS
    execute.assert_called_once_with(
        "web_search", {"query": "New Balance SC Rebel v1"}, None, None
    )


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

    def fake_model(provider, model, messages, **kwargs):
        snapshots.append([dict(message) for message in messages])
        return iter(next(responses))

    monkeypatch.setattr(llm, "call_llm_stream", fake_model)
    monkeypatch.setattr(agent, "run_web_search", MagicMock(return_value="（搜尋暫時失敗）"))

    events = _events(agent.run_agent_stream("推薦新鞋", model="openrouter/free"))

    assert sum(event["type"] == "tool" for event in events) == 3
    assert any(
        "不要**再呼叫" in message["content"]
        for message in snapshots[-1]
    )
    assert events[-2] == {"type": "token", "text": "依現有資料回答。"}


def test_last_turn_forces_answer_without_another_tool(monkeypatch):
    snapshots = []
    tools_by_turn = []
    call_count = 0

    def fake_model(provider, model, messages, **kwargs):
        nonlocal call_count
        call_count += 1
        snapshots.append([dict(message) for message in messages])
        tools_by_turn.append(kwargs["tools"])
        if call_count < agent.MAX_TURNS:
            return iter(['<tool>shoe_summary {}</tool>'])
        return iter(["最後結論"])

    monkeypatch.setattr(llm, "call_llm_stream", fake_model)
    tool = MagicMock(return_value="鞋況")
    monkeypatch.setattr(agent, "_execute_tool", tool)

    events = _events(
        agent.run_agent_stream("完整分析", model="openrouter/free", db="db", user_id=7)
    )

    assert call_count == agent.MAX_TURNS
    # The first call executes; identical calls in later turns receive a
    # structured duplicate error instead of hitting the database repeatedly.
    assert tool.call_count == 1
    assert any("這是最後一輪" in message["content"] for message in snapshots[-1])
    assert all(tools is db_tools.TOOL_DEFINITIONS for tools in tools_by_turn[:-1])
    assert tools_by_turn[-1] is None
    assert events[-2] == {"type": "token", "text": "最後結論"}


def test_native_tool_calls_use_standard_assistant_and_tool_messages(monkeypatch):
    calls = [
        {
            "id": "call_summary",
            "name": "shoe_summary",
            "arguments": {},
            "arguments_json": "{}",
        },
        {
            "id": "call_mileage",
            "name": "monthly_mileage_stats",
            "arguments": {},
            "arguments_json": "{}",
        },
    ]
    snapshots = []
    responses = iter(
        [
            _native_response(content=("我先讀資料。",), tool_calls=calls),
            _native_response(content=("完整分析",)),
        ]
    )

    def fake_model(provider, model, messages, **kwargs):
        snapshots.append([dict(message) for message in messages])
        assert kwargs["tools"] is db_tools.TOOL_DEFINITIONS
        return next(responses)

    monkeypatch.setattr(llm, "call_llm_stream", fake_model)
    execute = MagicMock(side_effect=["鞋況結果", "跑量結果"])
    monkeypatch.setattr(agent, "_execute_tool", execute)

    events = _events(
        agent.run_agent_stream("分析跑鞋", model="openrouter/free", db="db", user_id=7)
    )

    assert [event["name"] for event in events if event["type"] == "tool"] == [
        "shoe_summary",
        "monthly_mileage_stats",
    ]
    assert execute.call_count == 2
    second_round = snapshots[1]
    assistant_message = second_round[-3]
    assert assistant_message["role"] == "assistant"
    assert [call["id"] for call in assistant_message["tool_calls"]] == [
        "call_summary",
        "call_mileage",
    ]
    assert second_round[-2] == {
        "role": "tool",
        "tool_call_id": "call_summary",
        "name": "shoe_summary",
        "content": "鞋況結果",
    }
    assert second_round[-1]["tool_call_id"] == "call_mileage"
    assert events[-2] == {"type": "token", "text": "完整分析"}


def test_database_tool_without_request_context_reports_stream_error(monkeypatch):
    calls = [
        {
            "id": "call_summary",
            "name": "shoe_summary",
            "arguments": {},
            "arguments_json": "{}",
        }
    ]
    monkeypatch.setattr(
        llm,
        "call_llm_stream",
        MagicMock(return_value=_native_response(tool_calls=calls)),
    )

    events = _events(agent.run_agent_stream("分析跑鞋", model="openrouter/free"))

    assert _event_types(events) == ["reasoning_start", "tool", "error", "done"]
    assert "缺少使用者資料庫上下文" in events[-2]["text"]
