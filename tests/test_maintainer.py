from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_NAME = "capability_maintainer_testpkg"


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


class CapabilityMaintainerTests(unittest.TestCase):
    def test_build_report_prioritizes_repeated_failures_and_reads_skill_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.jsonl"
            usage_path = root / ".usage.json"
            now = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)

            events = []
            for index in range(6):
                events.append(
                    {
                        "schema_version": 1,
                        "timestamp": (now - timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
                        "event": "tool_call",
                        "tool": "unstable_mcp",
                        "status": "error" if index < 3 else "success",
                        "error_class": "transport_error" if index < 3 else None,
                        "duration_ms": 100 + index,
                    }
                )
            events.append(
                {
                    "schema_version": 1,
                    "timestamp": (now - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                    "event": "tool_call",
                    "tool": "old_failure",
                    "status": "error",
                    "duration_ms": 5,
                }
            )

            with events_path.open("w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event) + "\n")
                handle.write("{broken-json\n")

            usage_path.write_text(
                json.dumps(
                    {
                        "capability-forge": {
                            "use_count": 12,
                            "view_count": 20,
                            "patch_count": 2,
                            "state": "active",
                            "pinned": True,
                            "last_used_at": "2026-09-03T03:00:00Z",
                        }
                    }
                ),
                encoding="utf-8",
            )

            plugin = load_package()
            report = plugin.handle_report.__globals__["build_report"](
                days=7,
                now=now,
                events_path=events_path,
                usage_path=usage_path,
            )

            self.assertEqual(report["summary"]["events"], 6)
            self.assertEqual(report["summary"]["candidate_count"], 1)
            self.assertEqual(report["candidates"][0]["name"], "unstable_mcp")
            self.assertEqual(report["candidates"][0]["reason"], "repeated_failures")
            self.assertEqual(report["tools"][0]["error_rate"], 0.5)
            self.assertEqual(report["skill_usage"][0]["skill"], "capability-forge")
            self.assertTrue(report["skill_usage"][0]["pinned"])
            self.assertFalse(report["policy"]["auto_mutation"])
            self.assertNotIn("old_failure", json.dumps(report))

    def test_high_usage_is_review_candidate_not_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.jsonl"
            now = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
            with events_path.open("w", encoding="utf-8") as handle:
                for index in range(20):
                    handle.write(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "timestamp": (now - timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
                                "event": "tool_call",
                                "tool": "healthy_hot_tool",
                                "status": "success",
                                "duration_ms": 10,
                            }
                        )
                        + "\n"
                    )

            plugin = load_package()
            report = plugin.handle_report.__globals__["build_report"](
                days=7,
                now=now,
                events_path=events_path,
                usage_path=root / "missing.json",
            )
            self.assertEqual(report["candidates"][0]["reason"], "high_usage_review")
            self.assertEqual(report["candidates"][0]["errors"], 0)

    def test_retry_loop_is_detected_without_raw_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.jsonl"
            now = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
            sequence = ["error", "error", "success"]
            with events_path.open("w", encoding="utf-8") as handle:
                for index, status in enumerate(sequence):
                    handle.write(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "timestamp": (now - timedelta(minutes=3 - index)).isoformat().replace("+00:00", "Z"),
                                "event": "tool_call",
                                "tool": "flaky_tool",
                                "status": status,
                                "duration_ms": 12,
                                "task_hash": "safe-hash-only",
                            }
                        )
                        + "\n"
                    )

            plugin = load_package()
            report = plugin.handle_report.__globals__["build_report"](
                days=7,
                now=now,
                events_path=events_path,
                usage_path=root / "missing.json",
            )
            self.assertEqual(report["tools"][0]["retries"], 2)
            self.assertEqual(report["candidates"][0]["reason"], "retry_loop")
            self.assertNotIn("task-raw-id", json.dumps(report))

    def test_report_tool_never_nominates_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.jsonl"
            now = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
            with events_path.open("w", encoding="utf-8") as handle:
                for index in range(25):
                    handle.write(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "timestamp": (now - timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
                                "event": "tool_call",
                                "tool": "capability_forge_report",
                                "status": "success",
                                "duration_ms": 5,
                            }
                        )
                        + "\n"
                    )

            plugin = load_package()
            report = plugin.handle_report.__globals__["build_report"](
                days=7,
                now=now,
                events_path=events_path,
                usage_path=root / "missing.json",
            )
            self.assertEqual(report["summary"]["candidate_count"], 0)
            self.assertEqual(report["tools"][0]["tool"], "capability_forge_report")

    def test_handler_writes_sanitized_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_home = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = tmp
            try:
                plugin = load_package()
                payload = json.loads(plugin.handle_report({"days": 7, "write_report": True}))
                self.assertTrue(payload["success"])
                path = Path(payload["report_path"])
                self.assertTrue(path.exists())
                serialized = path.read_text(encoding="utf-8")
                self.assertNotIn("prompt", serialized.lower())
                self.assertFalse(payload["report"]["policy"]["auto_mutation"])
            finally:
                if old_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_home

    def test_handler_rejects_non_integer_days(self):
        plugin = load_package()
        payload = json.loads(plugin.handle_report({"days": "many"}))
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
