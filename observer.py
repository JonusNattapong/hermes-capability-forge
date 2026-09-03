from __future__ import annotations

import json
from typing import Any

from .storage import append_event, stable_hash, utc_now_iso


def _normalize_status(status: Any, error_type: Any, result: Any) -> str:
    raw = str(status or "").strip().lower()
    if raw in {"success", "ok", "completed"}:
        return "success"
    if raw in {"blocked", "denied", "cancelled", "canceled"}:
        return "blocked"
    if raw in {"error", "failed", "failure"}:
        return "error"
    if error_type:
        return "error"

    # Current/older Hermes versions may expose only the JSON result envelope.
    # Parse it only for top-level status classification and never persist payload data.
    if isinstance(result, str):
        try:
            envelope = json.loads(result)
        except json.JSONDecodeError:
            return "unknown"

        if isinstance(envelope, dict):
            envelope_status = str(envelope.get("status") or "").strip().lower()
            if envelope_status in {"blocked", "denied", "cancelled", "canceled"}:
                return "blocked"
            if envelope_status in {"error", "failed", "failure"}:
                return "error"
            if envelope.get("success") is False or envelope.get("error") not in {None, "", False}:
                return "error"
            return "success"
        if isinstance(envelope, list):
            return "success"

    return "unknown"


def observe_tool_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    result: str | None = None,
    task_id: str = "",
    duration_ms: int | float | None = None,
    **kwargs: Any,
) -> None:
    """Record privacy-preserving telemetry from Hermes post_tool_call.

    Intentionally does not persist args, result, prompt text, tool-call payloads,
    file contents, commands, URLs, credentials, or user messages.
    """
    del args

    status = _normalize_status(kwargs.get("status"), kwargs.get("error_type"), result)
    duration = None
    if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
        duration = int(duration_ms)

    error_type = kwargs.get("error_type")
    error_class = str(error_type)[:128] if error_type else None
    if status == "error" and error_class is None:
        error_class = "returned_error"

    event = {
        "schema_version": 1,
        "timestamp": utc_now_iso(),
        "event": "tool_call",
        "tool": str(tool_name or "unknown")[:128],
        "status": status,
        "error_class": error_class,
        "duration_ms": duration,
        "task_hash": stable_hash(task_id),
        "session_hash": stable_hash(kwargs.get("session_id")),
        "turn_hash": stable_hash(kwargs.get("turn_id")),
    }

    # Remove absent values to keep telemetry small and easy to diff/process.
    append_event({k: v for k, v in event.items() if v is not None})
