from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .maintainer import build_report
from .storage import _hermes_home, utc_now_iso


def default_eval_registry_path() -> Path:
    configured = os.environ.get("CAPABILITY_FORGE_EVALS", "").strip()
    return Path(configured).expanduser() if configured else _hermes_home() / "capability-lab" / "evals.json"


def default_baselines_path() -> Path:
    configured = os.environ.get("CAPABILITY_FORGE_BASELINES", "").strip()
    return Path(configured).expanduser() if configured else _hermes_home() / "capability-lab" / "baselines.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def read_eval_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    raw = _read_json(path or default_eval_registry_path())
    profiles = raw.get("capabilities", raw)
    if not isinstance(profiles, dict):
        return {}
    return {
        str(name): dict(profile)
        for name, profile in profiles.items()
        if isinstance(name, str) and isinstance(profile, dict)
    }


def read_baselines(path: Path | None = None) -> dict[str, dict[str, Any]]:
    raw = _read_json(path or default_baselines_path())
    baselines = raw.get("capabilities", raw)
    if not isinstance(baselines, dict):
        return {}
    return {
        str(name): dict(value)
        for name, value in baselines.items()
        if isinstance(name, str) and isinstance(value, dict)
    }


def _metric_checks(metrics: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    rules = [
        ("max_error_rate", "error_rate", "max"),
        ("max_retry_rate", "retry_rate", "max"),
        ("max_unknown_rate", "unknown_rate", "max"),
        ("max_p95_duration_ms", "p95_duration_ms", "max"),
        ("min_success_rate", "success_rate", "min"),
    ]
    checks: list[dict[str, Any]] = []
    for rule_name, metric_name, direction in rules:
        if rule_name not in profile:
            continue
        threshold = profile.get(rule_name)
        actual = metrics.get(metric_name)
        if not isinstance(threshold, (int, float)) or not isinstance(actual, (int, float)):
            checks.append({
                "rule": rule_name,
                "metric": metric_name,
                "actual": actual,
                "threshold": threshold,
                "passed": False,
                "reason": "metric_unavailable",
            })
            continue
        passed = actual <= threshold if direction == "max" else actual >= threshold
        checks.append({
            "rule": rule_name,
            "metric": metric_name,
            "actual": actual,
            "threshold": threshold,
            "passed": passed,
        })
    return checks


def evaluate_capability(
    capability_id: str,
    report: dict[str, Any],
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    capability = next(
        (item for item in report.get("capabilities", []) if item.get("id") == capability_id),
        None,
    )
    if capability is None:
        return {
            "capability_id": capability_id,
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": "capability_not_observed",
            "checks": [],
        }
    if not profile:
        return {
            "capability_id": capability_id,
            "status": "NO_PROFILE",
            "reason": "no_eval_profile",
            "metrics": capability,
            "checks": [],
        }

    try:
        min_calls = int(profile.get("min_calls") or 1)
    except (TypeError, ValueError):
        return {
            "capability_id": capability_id,
            "status": "FAIL",
            "reason": "invalid_profile_min_calls",
            "metrics": capability,
            "checks": [],
        }
    if min_calls < 1:
        return {
            "capability_id": capability_id,
            "status": "FAIL",
            "reason": "invalid_profile_min_calls",
            "metrics": capability,
            "checks": [],
        }
    calls = int(capability.get("calls") or 0)
    if calls < min_calls:
        return {
            "capability_id": capability_id,
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": "min_calls_not_met",
            "required_calls": min_calls,
            "observed_calls": calls,
            "metrics": capability,
            "checks": [],
        }

    checks = _metric_checks(capability, profile)
    passed = bool(checks) and all(check.get("passed") is True for check in checks)
    return {
        "capability_id": capability_id,
        "status": "PASS" if passed else "FAIL",
        "metrics": capability,
        "checks": checks,
    }


def compare_to_baseline(
    capability_id: str,
    metrics: dict[str, Any],
    baseline: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if not baseline:
        return {"status": "NO_BASELINE", "capability_id": capability_id}

    previous = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else baseline
    drift_cfg = profile.get("drift", {}) if isinstance(profile, dict) else {}
    if not isinstance(drift_cfg, dict):
        drift_cfg = {}
    has_drift_rules = any(
        key.startswith("max_") and isinstance(value, (int, float))
        for key, value in drift_cfg.items()
    )

    deltas: dict[str, Any] = {}
    regressions: list[str] = []
    for metric in ("error_rate", "retry_rate", "unknown_rate", "p95_duration_ms", "success_rate"):
        current_value = metrics.get(metric)
        old_value = previous.get(metric) if isinstance(previous, dict) else None
        if not isinstance(current_value, (int, float)) or not isinstance(old_value, (int, float)):
            continue
        delta = current_value - old_value
        relative = None if old_value == 0 else delta / abs(old_value)
        deltas[metric] = {
            "baseline": old_value,
            "current": current_value,
            "delta": round(delta, 6),
            "relative": None if relative is None else round(relative, 6),
        }

        absolute_limit = drift_cfg.get(f"max_{metric}_increase")
        relative_limit = drift_cfg.get(f"max_{metric}_relative_increase")
        if metric == "success_rate":
            absolute_limit = drift_cfg.get("max_success_rate_drop")
            relative_limit = drift_cfg.get("max_success_rate_relative_drop")
            worsening = old_value - current_value
            relative_worsening = None if old_value == 0 else worsening / abs(old_value)
        else:
            worsening = delta
            relative_worsening = relative

        if isinstance(absolute_limit, (int, float)) and worsening > absolute_limit:
            regressions.append(f"{metric}:absolute")
        if (
            isinstance(relative_limit, (int, float))
            and isinstance(relative_worsening, (int, float))
            and relative_worsening > relative_limit
        ):
            regressions.append(f"{metric}:relative")

    return {
        "status": "NO_DRIFT_PROFILE" if not has_drift_rules else ("REGRESSION" if regressions else "STABLE"),
        "capability_id": capability_id,
        "baseline_recorded_at": baseline.get("recorded_at"),
        "deltas": deltas,
        "regressions": regressions,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def record_baseline(
    capability_id: str,
    evaluation: dict[str, Any],
    path: Path | None = None,
) -> dict[str, Any]:
    if evaluation.get("status") != "PASS":
        return {"success": False, "error": "baseline_requires_passing_gate"}
    target = path or default_baselines_path()
    raw = _read_json(target)
    capabilities = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
    capabilities = dict(capabilities)
    capabilities[capability_id] = {
        "recorded_at": utc_now_iso(),
        "metrics": evaluation.get("metrics", {}),
    }
    payload = {"schema_version": 1, "capabilities": capabilities}
    _atomic_write_json(target, payload)
    return {"success": True, "baseline_path": str(target), "capability_id": capability_id}


def handle_gate(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    action = str(params.get("action") or "evaluate").strip().lower()
    capability_id = str(params.get("capability_id") or "").strip()
    if not capability_id:
        return json.dumps({"success": False, "error": "capability_id is required"})

    try:
        days = max(1, min(int(params.get("days", 7)), 90))
    except (TypeError, ValueError):
        return json.dumps({"success": False, "error": "days must be an integer between 1 and 90"})

    report = build_report(days=days)
    profiles = read_eval_profiles()
    profile = profiles.get(capability_id)
    evaluation = evaluate_capability(capability_id, report, profile)
    payload: dict[str, Any] = {"success": True, "evaluation": evaluation}

    baselines = read_baselines()
    metrics = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), dict) else {}
    if action in {"evaluate", "compare"} and metrics:
        payload["drift"] = compare_to_baseline(capability_id, metrics, baselines.get(capability_id), profile)
    elif action == "record_baseline":
        payload["baseline"] = record_baseline(capability_id, evaluation)
    else:
        if action not in {"evaluate", "compare", "record_baseline"}:
            return json.dumps({"success": False, "error": "action must be evaluate, compare, or record_baseline"})

    return json.dumps(payload, ensure_ascii=False)
