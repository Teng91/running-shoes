"""Pure compatibility parsing for legacy model tool-call text."""

import json
import re
from collections.abc import Iterator

_XML_CALL = re.compile(r"<tool>\s*([A-Za-z_]+)\s*(\{.*?\})\s*</tool>", re.DOTALL)
_XML_MARKER = re.compile(r"<tool>.*?</tool>", re.DOTALL)


def _bare_json_calls(text: str, allowed_names: set[str]) -> Iterator[tuple[int, int, str, object]]:
    """Yield ``(start, end, name, arguments)`` for each ``{"tool": <allowed name>, ...}`` object."""
    decoder = json.JSONDecoder()
    cursor = 0
    while True:
        start = text.find("{", cursor)
        if start == -1:
            return
        try:
            payload, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        end = start + consumed
        cursor = end
        if not isinstance(payload, dict):
            continue
        name = payload.get("tool")
        if name in allowed_names:
            yield start, end, name, payload.get("arguments", {})


def _positioned_calls(text: str, allowed_names: set[str]) -> list[tuple[int, int, dict]]:
    """Every recognized call as ``(start, end, call)``, in text order."""
    allowed_names = set(allowed_names)
    positioned: list[tuple[int, int, dict]] = []
    for match in _XML_CALL.finditer(text):
        name = match.group(1)
        if name not in allowed_names:
            continue
        try:
            args = json.loads(match.group(2) or "{}")
        except (TypeError, json.JSONDecodeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        positioned.append((match.start(), match.end(), {"name": name, "arguments": args}))
    for start, end, name, arguments in _bare_json_calls(text, allowed_names):
        if isinstance(arguments, dict):
            positioned.append((start, end, {"name": name, "arguments": arguments}))
    return sorted(positioned, key=lambda item: item[0])


def parse_tool_calls(text: str, allowed_names: set[str]) -> list[dict]:
    """Parse legacy XML markers and bare JSON tool-call fallbacks.

    Some free models ignore native function calling and emit
    ``{"tool":"web_search","arguments":{...}}`` as content. Only registered
    tool names are accepted, and identical calls are deduplicated.
    """
    out = []
    seen = set()
    for _start, _end, call in _positioned_calls(text, allowed_names):
        key = (call["name"], json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            out.append(call)
    return out


def first_call_end(text: str, allowed_names: set[str]) -> int | None:
    """Where the first recognized call ends, so a history can stop at the call that ran."""
    calls = _positioned_calls(text, allowed_names)
    return calls[0][1] if calls else None


def strip_tool_markers(text: str, allowed_names: set[str]) -> str:
    """Remove recognized XML and bare-JSON calls from user-visible reasoning."""
    cleaned = _XML_MARKER.sub("", text)
    spans = [(start, end) for start, end, _name, _args in _bare_json_calls(cleaned, set(allowed_names))]
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    return cleaned.strip()
