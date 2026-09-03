from __future__ import annotations

import logging

from .maintainer import handle_report
from .observer import observe_tool_call
from .schemas import CAPABILITY_FORGE_REPORT

logger = logging.getLogger(__name__)


def _on_post_tool_call(
    tool_name: str,
    args: dict,
    result: str,
    task_id: str = "",
    duration_ms: int = 0,
    **kwargs,
) -> None:
    try:
        observe_tool_call(
            tool_name=tool_name,
            args=args,
            result=result,
            task_id=task_id,
            duration_ms=duration_ms,
            **kwargs,
        )
    except Exception:
        # Telemetry must never break normal Hermes work.
        logger.exception("capability-observer failed to persist telemetry")


def register(ctx) -> None:
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_tool(
        name="capability_forge_report",
        toolset="capability_forge",
        schema=CAPABILITY_FORGE_REPORT,
        handler=handle_report,
    )
