"""Pure compatibility parsing for legacy model tool-call text."""

import json


def parse_tool_calls(text: str, allowed_names: set[str]) -> list[dict]:
    """Parse legacy XML markers and bare JSON tool-call fallbacks.

    Some free models ignore native function calling and emit
    ``{"tool":"web_search","arguments":{...}}`` as content. Only registered
    tool names are accepted, and identical calls are deduplicated.
    """
    import json as _json
    import re

    allowed_names = set(allowed_names)
    positioned_calls: list[tuple[int, int, dict]] = []

    for m in re.finditer(r"<tool>\s*([A-Za-z_]+)\s*(\{.*?\})\s*</tool>", text, re.DOTALL):
        name = m.group(1)
        if name not in allowed_names:
            continue
        raw = m.group(2) or "{}"
        try:
            args = _json.loads(raw)
        except (TypeError, _json.JSONDecodeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        positioned_calls.append((m.start(), m.end(), {"name": name, "arguments": args}))

    decoder = _json.JSONDecoder()
    cursor = 0
    while True:
        start = text.find("{", cursor)
        if start == -1:
            break
        try:
            payload, consumed = decoder.raw_decode(text[start:])
        except _json.JSONDecodeError:
            cursor = start + 1
            continue
        end = start + consumed
        cursor = end
        if not isinstance(payload, dict):
            continue
        name = payload.get("tool")
        arguments = payload.get("arguments", {})
        if name in allowed_names and isinstance(arguments, dict):
            positioned_calls.append((start, end, {"name": name, "arguments": arguments}))

    out = []
    seen = set()
    for _start, _end, call in sorted(positioned_calls, key=lambda item: item[0]):
        key = (call["name"], _json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            out.append(call)
    return out


def strip_tool_markers(text: str, allowed_names: set[str]) -> str:
    """Remove recognized XML and bare-JSON calls from user-visible reasoning."""
    import re

    cleaned = re.sub(r"<tool>.*?</tool>", "", text, flags=re.DOTALL)
    decoder = json.JSONDecoder()
    spans = []
    cursor = 0
    allowed_names = set(allowed_names)
    while True:
        start = cleaned.find("{", cursor)
        if start == -1:
            break
        try:
            payload, consumed = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        end = start + consumed
        cursor = end
        if isinstance(payload, dict) and payload.get("tool") in allowed_names:
            spans.append((start, end))
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    return cleaned.strip()
