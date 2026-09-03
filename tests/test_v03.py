from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_NAME = "capability_forge_v03_testpkg"


def load_package():
    for name in list(sys.modules):
        if name == PKG_NAME or name.startswith(PKG_NAME + "."):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        PKG_NAME,
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def import_submodule(name: str):
    load_package()
    return sys.modules[f"{PKG_NAME}.{name}"]


class CapabilityForgeV03Tests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_explicit_registry_maps_exact_and_prefix_without_guessing_ambiguity(self):
        registry = import_submodule("registry")
        data = {
            "alpha": {"id": "alpha", "kind": "mcp", "tools": ["alpha_read"], "tool_prefixes": ["alpha_"]},
            "beta": {"id": "beta", "kind": "plugin", "tools": ["beta_run"]},
        }
        self.assertEqual(registry.owner_for_tool("alpha_read", data)["id"], "alpha")
        self.assertEqual(registry.owner_for_tool("alpha_write", data)["id"], "alpha")
        self.assertIsNone(registry.owner_for_tool("unknown_tool", data))

        ambiguous = {
            "a": {"id": "a", "tools": ["same"], "tool_prefixes": []},
            "b": {"id": "b", "tools": ["same"], "tool_prefixes": []},
        }
        self.assertIsNone(registry.owner_for_tool("same", ambiguous))

    def test_report_promotes_owned_tool_failure_to_capability_candidate(self):
        maintainer = import_submodule("maintainer")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            registry_path = root / "capabilities.json"
            now = datetime.now(timezone.utc)
            lines = []
            for index in range(5):
                lines.append(json.dumps({
                    "schema_version": 1,
                    "timestamp": (now - timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
                    "event": "tool_call",
                    "tool": "repo_scan",
                    "status": "error" if index < 3 else "success",
                    "duration_ms": 100,
                    "task_hash": f"task-{index}",
                }))
            events.write_text("\n".join(lines) + "\n", encoding="utf-8")
            registry_path.write_text(json.dumps({
                "capabilities": [{
                    "id": "repo-inspector",
                    "kind": "skill+plugin",
                    "source": "local",
                    "tools": ["repo_scan"],
                }]
            }), encoding="utf-8")

            report = maintainer.build_report(
                days=7,
                now=now,
                events_path=events,
                usage_path=root / "missing-usage.json",
                registry_path=registry_path,
            )
            self.assertEqual(report["schema_version"], 3)
            self.assertEqual(report["capabilities"][0]["id"], "repo-inspector")
            self.assertEqual(report["capabilities"][0]["calls"], 5)
            self.assertEqual(report["candidates"][0]["kind"], "capability")
            self.assertEqual(report["candidates"][0]["name"], "repo-inspector")
            self.assertEqual(report["tools"][0]["owner"]["id"], "repo-inspector")

    def test_capability_p95_uses_combined_event_distribution(self):
        maintainer = import_submodule("maintainer")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            registry_path = root / "capabilities.json"
            now = datetime.now(timezone.utc)
            rows = []
            durations = [("tool_a", value) for value in [1, 1, 1, 1, 1000]]
            durations += [("tool_b", 1) for _ in range(95)]
            for index, (tool, duration) in enumerate(durations):
                rows.append(json.dumps({
                    "schema_version": 1,
                    "timestamp": (now - timedelta(seconds=index)).isoformat().replace("+00:00", "Z"),
                    "event": "tool_call",
                    "tool": tool,
                    "status": "success",
                    "duration_ms": duration,
                    "task_hash": f"task-{index}",
                }))
            events.write_text("\n".join(rows) + "\n", encoding="utf-8")
            registry_path.write_text(json.dumps({
                "capabilities": [{"id": "combo", "kind": "plugin", "tools": ["tool_a", "tool_b"]}]
            }), encoding="utf-8")
            report = maintainer.build_report(
                days=7,
                now=now,
                events_path=events,
                usage_path=root / "missing.json",
                registry_path=registry_path,
            )
            capability = next(item for item in report["capabilities"] if item["id"] == "combo")
            self.assertEqual(capability["p95_duration_ms"], 1)

    def test_eval_gate_passes_records_baseline_and_detects_regression(self):
        gates = import_submodule("gates")
        report = {
            "capabilities": [{
                "id": "repo-inspector",
                "calls": 30,
                "successes": 28,
                "errors": 1,
                "blocked": 0,
                "unknown": 1,
                "retries": 1,
                "success_rate": 0.9333,
                "error_rate": 0.0333,
                "retry_rate": 0.0333,
                "unknown_rate": 0.0333,
                "p95_duration_ms": 1200,
                "tools": ["repo_scan"],
            }]
        }
        profile = {
            "min_calls": 20,
            "max_error_rate": 0.10,
            "max_retry_rate": 0.05,
            "max_unknown_rate": 0.10,
            "max_p95_duration_ms": 5000,
            "min_success_rate": 0.85,
            "drift": {
                "max_error_rate_increase": 0.05,
                "max_p95_duration_ms_relative_increase": 0.50,
            },
        }
        evaluation = gates.evaluate_capability("repo-inspector", report, profile)
        self.assertEqual(evaluation["status"], "PASS")

        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baselines.json"
            recorded = gates.record_baseline("repo-inspector", evaluation, baseline_path)
            self.assertTrue(recorded["success"])
            baseline = gates.read_baselines(baseline_path)["repo-inspector"]
            stable = gates.compare_to_baseline("repo-inspector", evaluation["metrics"], baseline, profile)
            self.assertEqual(stable["status"], "STABLE")

            regressed_metrics = dict(evaluation["metrics"])
            regressed_metrics["error_rate"] = 0.20
            regressed_metrics["p95_duration_ms"] = 3000
            drift = gates.compare_to_baseline("repo-inspector", regressed_metrics, baseline, profile)
            self.assertEqual(drift["status"], "REGRESSION")
            self.assertIn("error_rate:absolute", drift["regressions"])
            self.assertIn("p95_duration_ms:relative", drift["regressions"])

    def test_invalid_eval_profile_fails_closed(self):
        gates = import_submodule("gates")
        report = {"capabilities": [{"id": "demo", "calls": 10}]}
        result = gates.evaluate_capability("demo", report, {"min_calls": "banana"})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], "invalid_profile_min_calls")

    def test_drift_without_thresholds_is_not_reported_stable(self):
        gates = import_submodule("gates")
        metrics = {
            "error_rate": 0.05,
            "retry_rate": 0.0,
            "unknown_rate": 0.0,
            "p95_duration_ms": 100,
            "success_rate": 0.95,
        }
        baseline = {"recorded_at": "2026-09-01T00:00:00Z", "metrics": dict(metrics)}
        result = gates.compare_to_baseline("demo", metrics, baseline, {"min_calls": 1})
        self.assertEqual(result["status"], "NO_DRIFT_PROFILE")

    def test_gate_refuses_baseline_without_pass(self):
        gates = import_submodule("gates")
        with tempfile.TemporaryDirectory() as tmp:
            result = gates.record_baseline(
                "broken",
                {"status": "FAIL", "metrics": {"calls": 100}},
                Path(tmp) / "baselines.json",
            )
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "baseline_requires_passing_gate")

    def test_guarded_patch_preview_apply_and_rollback(self):
        patcher = import_submodule("patcher")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / "hermes-home"
            workspace = root / "workspace"
            workspace.mkdir()
            target = workspace / "SKILL.md"
            target.write_text("alpha\nbeta\n", encoding="utf-8")
            os.chmod(target, 0o744)
            original_mode = stat.S_IMODE(target.stat().st_mode)
            original = target.read_bytes()
            expected = hashlib.sha256(original).hexdigest()

            os.environ["HERMES_HOME"] = str(hermes_home)
            os.environ["CAPABILITY_FORGE_PATCH_ROOTS"] = str(workspace)

            preview = patcher.preview_patch(
                path=str(target),
                expected_sha256=expected,
                old_text="beta",
                new_text="gamma",
                capability_id="demo",
                reason="eval-backed repair",
            )
            self.assertTrue(preview["success"])
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nbeta\n")

            disabled = patcher.apply_patch(
                path=str(target),
                expected_sha256=expected,
                old_text="beta",
                new_text="gamma",
                capability_id="demo",
                reason="eval-backed repair",
            )
            self.assertFalse(disabled["success"])
            self.assertIn("disabled", disabled["error"])

            os.environ["CAPABILITY_FORGE_ALLOW_PATCH"] = "1"
            applied = patcher.apply_patch(
                path=str(target),
                expected_sha256=expected,
                old_text="beta",
                new_text="gamma",
                capability_id="demo",
                reason="eval-backed repair",
            )
            self.assertTrue(applied["success"])
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\ngamma\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), original_mode)

            rolled_back = patcher.rollback_patch(applied["patch_id"])
            self.assertTrue(rolled_back["success"])
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), original_mode)

    def test_guarded_patch_rejects_outside_root_and_stale_hash(self):
        patcher = import_submodule("patcher")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed = root / "allowed"
            allowed.mkdir()
            outside = root / "outside.md"
            outside.write_text("secret\n", encoding="utf-8")
            inside = allowed / "inside.md"
            inside.write_text("hello\n", encoding="utf-8")
            os.environ["CAPABILITY_FORGE_PATCH_ROOTS"] = str(allowed)

            rejected = patcher.preview_patch(
                path=str(outside),
                expected_sha256=hashlib.sha256(outside.read_bytes()).hexdigest(),
                old_text="secret",
                new_text="changed",
                capability_id="demo",
                reason="should fail",
            )
            self.assertFalse(rejected["success"])
            self.assertEqual(rejected["error"], "target_outside_allowed_roots")

            stale = patcher.preview_patch(
                path=str(inside),
                expected_sha256="0" * 64,
                old_text="hello",
                new_text="hi",
                capability_id="demo",
                reason="stale",
            )
            self.assertFalse(stale["success"])
            self.assertEqual(stale["error"], "sha256_mismatch")


if __name__ == "__main__":
    unittest.main()
