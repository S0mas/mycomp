from datetime import datetime, timezone
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg_id() -> str:
    return uuid.uuid4().hex[:12]
