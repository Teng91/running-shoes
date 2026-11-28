"""Report orchestration emits domain events without HTTP or LLM dependencies."""

import logging
from collections.abc import Callable, Generator, Iterable

from sqlalchemy.orm import Session

from backend.services.report_storage import begin_generation, persist_current_report

# SPEC-140: users see a neutral message; the cause goes to the server log (no report text).
logger = logging.getLogger("running_shoes.reports")


class ReportModelError(Exception):
    """A safe, user-visible error supplied by the model adapter."""


def generate_report(
    db: Session, user_id: int, year: int, month: int, model: str, *,
    build_stats: Callable[[], dict], stream_text: Callable[[dict], Iterable[str]],
) -> Generator[dict]:
    try:
        token = begin_generation(db, user_id, year, month)
        stats = build_stats()
        # Neither a reader snapshot nor a writer reservation spans the LLM wait.
        db.rollback()
    except Exception:
        logger.exception("Report preparation failed for %04d-%02d", year, month)
        db.rollback()
        yield {"type": "error", "text": "報告準備失敗，請稍後再試。"}
        return

    chunks: list[str] = []
    try:
        for chunk in stream_text(stats):
            chunks.append(chunk)
            yield {"type": "token", "text": chunk}
    except ReportModelError as exc:
        yield {"type": "error", "text": str(exc)}
        return
    except Exception:
        logger.exception("Report model stream failed for %04d-%02d", year, month)
        yield {"type": "error", "text": "報告產生失敗，請稍後再試。"}
        return

    content = "".join(chunks)
    if not content.strip():
        yield {"type": "error", "text": "模型未回傳任何內容，請稍後再試。"}
        return
    try:
        updated_at = persist_current_report(db, user_id, year, month, token, content, model, stats)
    except Exception:
        logger.exception("Report save failed for %04d-%02d", year, month)
        db.rollback()
        yield {"type": "error", "text": "報告產生成功，但儲存失敗，請重新產生。"}
        return
    if updated_at is None:
        yield {"type": "error", "text": "已有較新的月報生成請求，本次內容未儲存。"}
        return
    yield {"type": "done", "model": model, "year": year, "month": month, "updated_at": updated_at}
