from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

_WRITE_LOCK = Lock()


def _hermes_home() -> Path:
    configured = os.environ.get("HERMES_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".hermes"


def default_events_path() -> Path:
    return _hermes_home() / "capability-lab" / "events.jsonl"


def stable_hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_event(event: dict[str, Any], path: Path | None = None) -> Path:
    """Append one compact JSON event without persisting prompt/args/result content."""
    destination = path or default_events_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"

    # Hermes hooks run in-process. The lock prevents interleaved writes inside a
    # process; O_APPEND keeps writes append-only if multiple Hermes processes exist.
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    encoded = line.encode("utf-8")
    with _WRITE_LOCK:
        fd = os.open(destination, flags, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)

    return destination
