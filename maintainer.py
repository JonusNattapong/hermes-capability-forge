from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .registry import dependency_edges, load_registry, owner_for_tool, public_owner
from .storage import _hermes_home, default_events_path, utc_now_iso


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def read_events(path: Path | None = None) -> Iterable[dict[str, Any]]:
    source = path or default_events_path()
    if not source.exists():
        return []

    events: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
    return events


def _usage_path() -> Path:
    return _hermes_home() / "skills" / ".usage.json"


def read_skill_usage(path: Path | None = None) -> dict[str, dict[str, Any]]:
    source = path or _usage_path()
    if not source.exists():
        return {}
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("skills"), dict):
        raw = raw["skills"]

    result: dict[str, dict[str, Any]] = {}
    for name, stats in raw.items():
        if isinstance(name, str) and isinstance(stats, dict):
            result[name] = stats
    return result


def _candidate_reason(tool: dict[str, Any]) -> tuple[str | None, int]:
    calls = int(tool["calls"])
    errors = int(tool["errors"])
    error_rate = float(tool["error_rate"])
    p95 = tool.get("p95_duration_ms")

    retries = int(tool.get("retries") or 0)

    if errors >= 3 and error_rate >= 0.30:
        return "repeated_failures", 100 + errors
    if retries >= 2 and calls >= 3:
        return "retry_loop", 90 + retries
    if errors >= 2 and calls >= 4 and error_rate >= 0.20:
        return "elevated_failure_rate", 80 + errors
    if isinstance(p95, int) and calls >= 5 and p95 >= 10_000:
        return "high_latency", 50 + min(p95 // 1000, 30)
    if calls >= 20:
        return "high_usage_review", 30 + min(calls // 5, 20)
    return None, 0


def build_report(
    *,
    days: int = 7,
    now: datetime | None = None,
    events_path: Path | None = None,
    usage_path: Path | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    days = max(1, min(int(days), 90))
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since = reference - timedelta(days=days)
    registry = load_registry(registry_path)

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "errors": 0,
            "blocked": 0,
            "unknown": 0,
            "retries": 0,
            "durations": [],
            "error_classes": defaultdict(int),
        }
    )
    total_events = 0
    previous_status: dict[tuple[str, str], tuple[str, datetime]] = {}

    for event in read_events(events_path):
        if event.get("event") != "tool_call":
            continue
        timestamp = _parse_timestamp(event.get("timestamp"))
        if timestamp is None or timestamp < since or timestamp > reference + timedelta(minutes=5):
            continue

        total_events += 1
        tool_name = str(event.get("tool") or "unknown")[:128]
        bucket = grouped[tool_name]
        bucket["calls"] += 1

        status = str(event.get("status") or "unknown").lower()
        correlation = event.get("task_hash") or event.get("session_hash")
        if isinstance(correlation, str) and correlation:
            retry_key = (correlation, tool_name)
            previous = previous_status.get(retry_key)
            if previous is not None:
                previous_state, previous_at = previous
                if previous_state == "error" and timestamp - previous_at <= timedelta(minutes=30):
                    bucket["retries"] += 1
            previous_status[retry_key] = (status, timestamp)

        if status == "success":
            bucket["successes"] += 1
        elif status == "error":
            bucket["errors"] += 1
        elif status == "blocked":
            bucket["blocked"] += 1
        else:
            bucket["unknown"] += 1

        duration = event.get("duration_ms")
        if isinstance(duration, (int, float)) and duration >= 0:
            bucket["durations"].append(int(duration))

        error_class = event.get("error_class")
        if status == "error" and isinstance(error_class, str) and error_class:
            bucket["error_classes"][error_class[:128]] += 1

    tools: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for tool_name, bucket in grouped.items():
        calls = bucket["calls"]
        errors = bucket["errors"]
        owner = owner_for_tool(tool_name, registry)
        summary = {
            "tool": tool_name,
            "owner": public_owner(owner),
            "calls": calls,
            "successes": bucket["successes"],
            "errors": errors,
            "blocked": bucket["blocked"],
            "unknown": bucket["unknown"],
            "retries": bucket["retries"],
            "error_rate": round(errors / calls, 4) if calls else 0.0,
            "p50_duration_ms": _percentile(bucket["durations"], 0.50),
            "p95_duration_ms": _percentile(bucket["durations"], 0.95),
            "error_classes": dict(sorted(bucket["error_classes"].items(), key=lambda item: (-item[1], item[0]))[:5]),
        }
        tools.append(summary)
        reason, priority = (None, 0) if tool_name.startswith("capability_forge_") else _candidate_reason(summary)
        if reason and owner is None:
            candidates.append(
                {
                    "kind": "tool",
                    "name": tool_name,
                    "owner": None,
                    "reason": reason,
                    "priority": priority,
                    "calls": calls,
                    "errors": errors,
                    "retries": summary["retries"],
                    "error_rate": summary["error_rate"],
                    "p95_duration_ms": summary["p95_duration_ms"],
                }
            )

    tools.sort(key=lambda item: (-item["calls"], item["tool"]))

    capability_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "successes": 0,
            "errors": 0,
            "blocked": 0,
            "unknown": 0,
            "retries": 0,
            "durations": [],
            "tools": [],
            "error_classes": defaultdict(int),
        }
    )
    capability_meta: dict[str, dict[str, Any]] = {}
    for tool in tools:
        owner = tool.get("owner")
        if not isinstance(owner, dict) or not isinstance(owner.get("id"), str):
            continue
        capability_id = owner["id"]
        capability_meta[capability_id] = owner
        bucket = capability_buckets[capability_id]
        for key in ("calls", "successes", "errors", "blocked", "unknown", "retries"):
            bucket[key] += int(tool.get(key) or 0)
        bucket["durations"].extend(grouped[tool["tool"]]["durations"])
        bucket["tools"].append(tool["tool"])
        for error_class, count in tool.get("error_classes", {}).items():
            bucket["error_classes"][error_class] += int(count)

    capabilities: list[dict[str, Any]] = []
    for capability_id, bucket in capability_buckets.items():
        calls = bucket["calls"]
        summary = {
            "id": capability_id,
            "kind": capability_meta[capability_id].get("kind"),
            "source": capability_meta[capability_id].get("source"),
            "depends_on": capability_meta[capability_id].get("depends_on", []),
            "calls": calls,
            "successes": bucket["successes"],
            "errors": bucket["errors"],
            "blocked": bucket["blocked"],
            "unknown": bucket["unknown"],
            "retries": bucket["retries"],
            "success_rate": round(bucket["successes"] / calls, 4) if calls else 0.0,
            "error_rate": round(bucket["errors"] / calls, 4) if calls else 0.0,
            "retry_rate": round(bucket["retries"] / calls, 4) if calls else 0.0,
            "unknown_rate": round(bucket["unknown"] / calls, 4) if calls else 0.0,
            "p50_duration_ms": _percentile(bucket["durations"], 0.50),
            "p95_duration_ms": _percentile(bucket["durations"], 0.95),
            "tools": sorted(bucket["tools"]),
            "error_classes": dict(sorted(bucket["error_classes"].items(), key=lambda item: (-item[1], item[0]))[:5]),
        }
        capabilities.append(summary)
        reason, priority = (None, 0) if capability_id == "hermes-capability-forge" else _candidate_reason(summary)
        if reason:
            candidates.append(
                {
                    "kind": "capability",
                    "name": capability_id,
                    "owner": {
                        "id": capability_id,
                        "kind": summary.get("kind"),
                        "source": summary.get("source"),
                    },
                    "reason": reason,
                    "priority": priority,
                    "calls": calls,
                    "errors": summary["errors"],
                    "retries": summary["retries"],
                    "error_rate": summary["error_rate"],
                    "p95_duration_ms": summary["p95_duration_ms"],
                }
            )

    capabilities.sort(key=lambda item: (-item["calls"], item["id"]))
    candidates.sort(key=lambda item: (-item["priority"], item["name"]))

    usage = read_skill_usage(usage_path)
    skill_usage: list[dict[str, Any]] = []
    for name, stats in usage.items():
        uses = _safe_int(stats.get("use_count") or 0)
        views = _safe_int(stats.get("view_count") or 0)
        patches = _safe_int(stats.get("patch_count") or 0)
        skill_usage.append(
            {
                "skill": name,
                "use_count": uses,
                "view_count": views,
                "patch_count": patches,
                "state": stats.get("state"),
                "pinned": bool(stats.get("pinned", False)),
                "last_used_at": stats.get("last_used_at"),
                "last_patched_at": stats.get("last_patched_at"),
            }
        )
    skill_usage.sort(key=lambda item: (-(item["use_count"] + item["view_count"]), item["skill"]))

    return {
        "schema_version": 3,
        "generated_at": utc_now_iso(),
        "window": {
            "days": days,
            "since": since.isoformat().replace("+00:00", "Z"),
            "until": reference.isoformat().replace("+00:00", "Z"),
        },
        "summary": {
            "events": total_events,
            "tools_observed": len(tools),
            "candidate_count": len(candidates),
            "capabilities_observed": len(capabilities),
            "skills_with_usage": len(skill_usage),
        },
        "candidates": candidates,
        "capabilities": capabilities,
        "dependency_edges": dependency_edges(registry),
        "tools": tools,
        "skill_usage": skill_usage[:50],
        "policy": {
            "maintenance_mode": "proposal_first",
            "research_only_candidates": True,
            "auto_mutation": False,
            "ownership": "explicit_registry_only",
            "promotion_requires_eval_gate": True,
        },
    }


def write_report(report: dict[str, Any], directory: Path | None = None) -> Path:
    target_dir = directory or (_hermes_home() / "capability-lab" / "reports")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"capability-report-{stamp}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def handle_report(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    try:
        days = int(params.get("days", 7))
    except (TypeError, ValueError):
        return json.dumps({"error": "days must be an integer between 1 and 90"})

    report = build_report(days=days)
    report_path = None
    if bool(params.get("write_report", True)):
        report_path = str(write_report(report))

    payload = {"success": True, "report": report}
    if report_path:
        payload["report_path"] = report_path
    return json.dumps(payload, ensure_ascii=False)
