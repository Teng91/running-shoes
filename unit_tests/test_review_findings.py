"""SPEC-130: fixes from the 2026-11-26 code review of the AI coach, invites and admin names."""

from types import SimpleNamespace

from backend import agent, llm
from backend.services import invites
from backend.settings import Settings, account_name_key
from backend.tools import db_tools


def test_a_text_tool_turn_keeps_only_the_call_that_runs():
    two_calls = "先查鞋款。<tool>list_my_shoes{}</tool><tool>monthly_mileage_stats{}</tool>"
    messages: list[dict] = []
    turn = agent._Turn()
    turn.content = two_calls
    agent._record_assistant_turn(messages, turn)
    assert [call["name"] for call in turn.tool_calls] == ["list_my_shoes"]
    assert messages[-1]["content"] == "先查鞋款。<tool>list_my_shoes{}</tool>"

    bare = '{"tool":"list_my_shoes","arguments":{}} 你有 3 雙鞋，總里程 500 km。'
    turn = agent._Turn()
    turn.content = bare
    agent._record_assistant_turn(messages, turn)
    assert messages[-1]["content"] == '{"tool":"list_my_shoes","arguments":{}}', "text invented after the call is dropped"
    assert db_tools.first_tool_call_end("沒有工具") is None


def _delta(name="", arguments="", index=0, call_id=None):
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def test_streamed_tool_names_merge_whether_split_or_repeated():
    repeated: dict = {}
    llm._merge_tool_call_deltas(repeated, [_delta("list_my_shoes", '{"a"', call_id="c1")])
    llm._merge_tool_call_deltas(repeated, [_delta("list_my_shoes", ":1}")])
    assert repeated[0]["name"] == "list_my_shoes"
    assert repeated[0]["arguments"] == '{"a":1}'

    split: dict = {}
    for piece in ("list_", "my_", "shoes"):
        llm._merge_tool_call_deltas(split, [_delta(piece)])
    assert split[0]["name"] == "list_my_shoes"


def test_admin_names_fold_like_account_names():
    settings = Settings.from_env({"ADMIN_USERNAMES": " Strasse , Coach"})
    assert settings.admin_usernames == frozenset({"strasse", "coach"})
    assert settings.is_admin("STRASSE") and settings.is_admin("coach")
    assert not settings.is_admin("Straße"), "a different account never matches an admin name"
    assert account_name_key("  Ärger ") == "Ärger"


def test_a_generated_invite_code_that_collides_is_drawn_again(db, monkeypatch):
    first = invites.create_invite(db, note="first", max_uses=1, days=1)
    taken = first["code"].replace("-", "")
    draws = iter([taken, "ABCD2345"])
    monkeypatch.setattr(invites, "_generated_code", lambda: next(draws))
    second = invites.create_invite(db, note="second", max_uses=1, days=1)
    assert second["code"] == "ABCD-2345"
