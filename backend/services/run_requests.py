"""Transactional run-creation receipts, independent of HTTP frameworks."""

import hashlib
import json

from sqlalchemy.orm import Session

from backend.models import RunCreationRequest


class RequestConflictError(Exception):
    """The same operation key was reused with different input."""


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def replay(db: Session, user_id: int, key: str, fingerprint: str) -> dict | None:
    receipt = db.query(RunCreationRequest).filter(
        RunCreationRequest.user_id == user_id,
        RunCreationRequest.request_key == key,
    ).first()
    if receipt is None:
        return None
    if receipt.payload_hash != fingerprint:
        raise RequestConflictError
    return receipt.response_json
