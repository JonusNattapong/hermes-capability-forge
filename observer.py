from __future__ import annotations

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

    # Older Hermes versions may not pass structured status/error_type. Inspect only
    # enough of the return envelope to classify it, and never persist the result.
    if isinstance(result, str):
        probe = result[:256].lower()
        if '"error"' in probe or '"success":false' in probe:
            return "error"
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
    event = {
        "schema_version": 1,
        "timestamp": utc_now_iso(),
        "event": "tool_call",
        "tool": str(tool_name or "unknown")[:128],
        "status": status,
        "error_class": str(error_type)[:128] if error_type else None,
        "duration_ms": duration,
        "task_hash": stable_hash(task_id),
        "session_hash": stable_hash(kwargs.get("session_id")),
        "turn_hash": stable_hash(kwargs.get("turn_id")),
    }

    # Remove absent values to keep telemetry small and easy to diff/process.
    append_event({k: v for k, v in event.items() if v is not None})
