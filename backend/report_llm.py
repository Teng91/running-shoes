"""One-shot model adapter: prompts and safe model failures, no persistence."""

from collections.abc import Iterator

from backend import llm
from backend.reports import build_report_messages
from backend.services.reports import ReportModelError


def stream_report_text(model: str, stats: dict) -> Iterator[str]:
    try:
        yield from llm.call_llm_stream(
            llm.LLMProvider.openrouter, model, build_report_messages(stats), tools=None
        )
    except llm.LLMError as exc:
        raise ReportModelError(str(exc)) from exc
