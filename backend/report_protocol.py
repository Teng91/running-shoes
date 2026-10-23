"""Serialize report domain events for the HTTP SSE adapter."""

import json
from collections.abc import Iterable, Iterator

from backend.schemas import serialize_utc_timestamp


def report_sse(events: Iterable[dict]) -> Iterator[str]:
    for event in events:
        yield f"data: {json.dumps(event, ensure_ascii=False, default=serialize_utc_timestamp)}\n\n"
