from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_NAME = "capability_observer_testpkg"


def load_plugin_package():
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


class FakeContext:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback


class CapabilityObserverTests(unittest.TestCase):
    def test_registers_post_tool_call_hook(self):
        plugin = load_plugin_package()
        ctx = FakeContext()
        plugin.register(ctx)
        self.assertIn("post_tool_call", ctx.hooks)

    def test_records_metadata_without_sensitive_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_home = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = tmp
            try:
                plugin = load_plugin_package()
                plugin._on_post_tool_call(
                    tool_name="terminal",
                    args={"command": "echo super-secret"},
                    result='{"success":true,"stdout":"super-secret"}',
                    task_id="task-secret-id",
                    duration_ms=42,
                    status="success",
                    session_id="session-secret-id",
                    turn_id="turn-secret-id",
                )

                path = Path(tmp) / "capability-lab" / "events.jsonl"
                event = json.loads(path.read_text(encoding="utf-8").strip())
                serialized = json.dumps(event)

                self.assertEqual(event["tool"], "terminal")
                self.assertEqual(event["status"], "success")
                self.assertEqual(event["duration_ms"], 42)
                self.assertNotIn("args", event)
                self.assertNotIn("result", event)
                self.assertNotIn("super-secret", serialized)
                self.assertNotIn("task-secret-id", serialized)
                self.assertNotIn("session-secret-id", serialized)
            finally:
                if old_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_home

    def test_legacy_error_envelope_is_classified_without_persisting_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_home = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = tmp
            try:
                plugin = load_plugin_package()
                plugin._on_post_tool_call(
                    tool_name="read_file",
                    args={"path": "C:/secret.txt"},
                    result='{"error":"not found"}',
                    task_id="task-1",
                    duration_ms=3,
                )
                path = Path(tmp) / "capability-lab" / "events.jsonl"
                event = json.loads(path.read_text(encoding="utf-8").strip())
                self.assertEqual(event["status"], "error")
                self.assertNotIn("C:/secret.txt", json.dumps(event))
                self.assertNotIn("not found", json.dumps(event))
            finally:
                if old_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
