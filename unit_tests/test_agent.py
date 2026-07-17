"""驗證 agent loop：tool 呼叫 → 觀察 → 最終回覆，以及 SSE 事件格式。"""

import json
from unittest.mock import MagicMock, patch

from backend.agent import run_agent
from backend.models import User


def _collect(generator):
    events = []
    for chunk in generator:
        # chunk 形如 "data: {...}\n\n"
        line = chunk.strip()
        assert line.startswith("data:")
        events.append(json.loads(line[len("data:"):].strip()))
    return events


def test_agent_runs_tool_then_answers(seeded_db):
    db, uid = seeded_db
    calls = {"n": 0}

    def fake_llm(provider, model, messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": "我來查一下。\n<tool>nearing_end_of_life {\"threshold\": 0.5}</tool>",
                "finish_reason": "stop",
            }
        return {
            "content": "Wave Sky 7 快要到壽命了，建議準備替換。",
            "finish_reason": "stop",
        }

    with patch("backend.agent.llm.call_llm", side_effect=fake_llm):
        events = _collect(run_agent(
            user_message="我哪些鞋快該換了？",
            provider="openrouter",
            model="meta-llama/llama-3.3-70b-instruct:free",
            db=db,
            user_id=uid,
        ))

    types = [e["type"] for e in events]
    assert "tool" in types
    assert "token" in types
    assert types[-1] == "done"
    tool_event = next(e for e in events if e["type"] == "tool")
    assert tool_event["name"] == "nearing_end_of_life"
    # 最終文字應被切成多個 token 事件
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "Wave Sky 7" in answer


def test_agent_handles_unknown_provider(seeded_db):
    db, uid = seeded_db
    events = _collect(run_agent(
        user_message="hi",
        provider="not-a-provider",
        db=db,
        user_id=uid,
    ))
    assert events[0]["type"] == "error"
    assert events[-1]["type"] == "done"


def test_agent_handles_llm_error(seeded_db):
    db, uid = seeded_db
    with patch("backend.agent.llm.call_llm", side_effect=Exception("boom")):
        events = _collect(run_agent(
            user_message="hi",
            provider="openrouter",
            db=db,
            user_id=uid,
        ))
    assert any(e["type"] == "error" for e in events)


def test_agent_respects_user_isolation(seeded_db):
    """agent 只用傳入的 user_id 查資料，看不到別人。"""
    db, uid = seeded_db
    other = User(username="ghost", hashed_password="x")
    db.add(other)
    db.commit()
    db.refresh(other)

    calls = {"n": 0}

    def fake_llm(provider, model, messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": "<tool>shoe_summary {}</tool>",
                "finish_reason": "stop",
            }
        return {"content": "你目前沒有任何跑鞋紀錄。", "finish_reason": "stop"}

    with patch("backend.agent.llm.call_llm", side_effect=fake_llm):
        events = _collect(run_agent(
            user_message="我的鞋呢？",
            provider="openrouter",
            db=db,
            user_id=other.id,  # 用 ghost 的 id
        ))
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "沒有任何跑鞋" in answer


def test_agent_forces_answer_on_last_turn(seeded_db):
    """就算模型每輪都硬要呼叫工具，最後一輪也會被強制收斂成最終答案，
    而不是丟出「多次呼叫仍未給結論」的錯誤。"""
    db, uid = seeded_db

    def stubborn_llm(provider, model, messages):
        # 收到「最後一輪」的系統提示才勉強給結論
        if any("這是最後一輪" in m["content"] for m in messages if m["role"] == "user"):
            return {"content": "根據你的資料，暫時不需要買鞋。", "finish_reason": "stop"}
        return {
            "content": "我再查一下。\n<tool>web_search {\"query\": \"跑鞋\"}</tool>",
            "finish_reason": "stop",
        }

    with patch("backend.agent.llm.call_llm", side_effect=stubborn_llm), \
         patch("backend.agent._execute_tool", return_value="（沒有找到結果）"):
        events = _collect(run_agent(
            user_message="我要買鞋嗎？",
            provider="openrouter",
            db=db,
            user_id=uid,
        ))

    types = [e["type"] for e in events]
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "error" not in types           # 不再報「未給結論」的錯
    assert "不需要買鞋" in answer          # 最後一輪被逼出真正的答案
    assert types[-1] == "done"
