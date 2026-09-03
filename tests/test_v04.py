from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_NAME = "capability_forge_v04_testpkg"


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


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class CapabilityForgeV04Tests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hermes_home = self.root / "hermes-home"
        self.repos_root = self.root / "repos"
        self.repo = self.repos_root / "sample"
        self.repo.mkdir(parents=True)
        self.hermes_home.mkdir(parents=True)

        self.assertEqual(git(self.repo, "init", "-b", "main").returncode, 0)
        (self.repo / "app.txt").write_text("old\n", encoding="utf-8")
        self.assertEqual(git(self.repo, "add", "app.txt").returncode, 0)
        commit = git(
            self.repo,
            "-c", "user.name=Forge Test",
            "-c", "user.email=forge@example.invalid",
            "commit", "-m", "init",
        )
        self.assertEqual(commit.returncode, 0, commit.stderr)

        os.environ["HERMES_HOME"] = str(self.hermes_home)
        os.environ["CAPABILITY_FORGE_EXPERIMENT_REPO_ROOTS"] = str(self.repos_root)
        os.environ["CAPABILITY_FORGE_ALLOW_EXPERIMENT"] = "1"
        self.evals = self.root / "evals.json"
        os.environ["CAPABILITY_FORGE_EVALS"] = str(self.evals)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def _write_eval(self, expected: str = "new\n", print_secret: bool = False):
        code = (
            "import pathlib; "
            + ("print('super-secret-output'); " if print_secret else "")
            + f"assert pathlib.Path('app.txt').read_text(encoding='utf-8') == {expected!r}"
        )
        self.evals.write_text(
            json.dumps({
                "capabilities": {
                    "demo-capability": {
                        "min_calls": 1,
                        "max_error_rate": 1.0,
                        "checks": [
                            {
                                "name": "content-check",
                                "argv": [sys.executable, "-c", code],
                                "timeout_seconds": 30,
                            }
                        ],
                    }
                }
            }),
            encoding="utf-8",
        )

    def _create(self, hypothesis: str = "changing old to new improves behavior"):
        experiments = import_submodule("experiments")
        result = experiments.create_experiment(
            repo_path=str(self.repo),
            capability_id="demo-capability",
            hypothesis=hypothesis,
            base_ref="HEAD",
        )
        self.assertTrue(result["success"], result)
        return experiments, result["experiment"]

    def _patch(self, experiments, exp):
        worktree = Path(exp["worktree"])
        target = worktree / "app.txt"
        current = target.read_bytes()
        result = experiments.patch_experiment(
            experiment_id=exp["experiment_id"],
            relative_path="app.txt",
            expected_sha256=hashlib.sha256(current).hexdigest(),
            old_text="old\n",
            new_text="new\n",
            reason="test isolated change",
        )
        self.assertTrue(result["success"], result)
        return worktree

    def test_create_patch_evaluate_dogfood_promote_and_cleanup(self):
        self._write_eval()
        experiments, exp = self._create()
        worktree = self._patch(experiments, exp)

        self.assertEqual((self.repo / "app.txt").read_text(encoding="utf-8"), "old\n")
        self.assertEqual((worktree / "app.txt").read_text(encoding="utf-8"), "new\n")

        evaluated = experiments.evaluate_experiment(exp["experiment_id"])
        self.assertTrue(evaluated["success"], evaluated)
        self.assertEqual(evaluated["evaluation"]["status"], "PASS")

        dogfood = experiments.record_dogfood(
            exp["experiment_id"],
            "better",
            "real workflow completed with fewer manual steps",
        )
        self.assertTrue(dogfood["success"])
        decision = experiments.decide_experiment(exp["experiment_id"])
        self.assertEqual(decision["decision"]["status"], "PROMOTE")

        blocked_cleanup = experiments.cleanup_experiment(exp["experiment_id"], delete_branch=False)
        self.assertFalse(blocked_cleanup["success"])
        self.assertEqual(blocked_cleanup["error"], "promote_requires_snapshot_before_cleanup")

        (worktree / "eval-artifact.tmp").write_text("must-not-be-committed", encoding="utf-8")
        snapshot = experiments.snapshot_experiment(exp["experiment_id"])
        self.assertTrue(snapshot["success"], snapshot)
        snapshot_commit = snapshot["snapshot"]["commit"]

        cleanup = experiments.cleanup_experiment(exp["experiment_id"], delete_branch=False)
        self.assertTrue(cleanup["success"], cleanup)
        self.assertFalse(worktree.exists())
        self.assertEqual(git(self.repo, "show-ref", "--verify", f"refs/heads/{exp['branch']}").returncode, 0)
        self.assertEqual(git(self.repo, "rev-parse", exp["branch"]).stdout.strip(), snapshot_commit)
        branch_file = git(self.repo, "show", f"{exp['branch']}:app.txt")
        self.assertEqual(branch_file.returncode, 0)
        self.assertEqual(branch_file.stdout.replace("\r\n", "\n"), "new\n")
        tree = git(self.repo, "ls-tree", "-r", "--name-only", exp["branch"])
        self.assertNotIn("eval-artifact.tmp", tree.stdout)

    def test_failed_eval_decides_rollback_and_can_delete_branch(self):
        self._write_eval(expected="something-else\n")
        experiments, exp = self._create("bad experiment should fail")
        worktree = self._patch(experiments, exp)
        evaluated = experiments.evaluate_experiment(exp["experiment_id"])
        self.assertEqual(evaluated["evaluation"]["status"], "FAIL")
        decision = experiments.decide_experiment(exp["experiment_id"])
        self.assertEqual(decision["decision"]["status"], "ROLLBACK")

        cleanup = experiments.cleanup_experiment(exp["experiment_id"], delete_branch=True)
        self.assertTrue(cleanup["success"], cleanup)
        self.assertFalse(worktree.exists())
        self.assertNotEqual(git(self.repo, "show-ref", "--verify", f"refs/heads/{exp['branch']}").returncode, 0)

    def test_eval_output_is_hashed_not_persisted(self):
        self._write_eval(print_secret=True)
        experiments, exp = self._create("output privacy")
        self._patch(experiments, exp)
        evaluated = experiments.evaluate_experiment(exp["experiment_id"])
        self.assertEqual(evaluated["evaluation"]["status"], "PASS")

        experiments.record_dogfood(exp["experiment_id"], "better", "super-secret-dogfood-evidence")
        manifest_path = self.hermes_home / "capability-lab" / "experiments" / exp["experiment_id"] / "manifest.json"
        serialized = manifest_path.read_text(encoding="utf-8")
        self.assertNotIn("super-secret-output", serialized)
        self.assertNotIn("super-secret-dogfood-evidence", serialized)
        self.assertIn("stdout_sha256", serialized)
        self.assertIn("evidence_sha256", serialized)

    def test_duplicate_hypothesis_surfaces_prior_outcome(self):
        self._write_eval()
        experiments, first = self._create("repeatable hypothesis")
        self._patch(experiments, first)
        experiments.evaluate_experiment(first["experiment_id"])
        experiments.record_dogfood(first["experiment_id"], "worse", "regressed")
        experiments.decide_experiment(first["experiment_id"])
        experiments.cleanup_experiment(first["experiment_id"], delete_branch=True)

        second = experiments.create_experiment(
            repo_path=str(self.repo),
            capability_id="demo-capability",
            hypothesis="repeatable hypothesis",
        )
        self.assertTrue(second["success"], second)
        prior = second["prior_matching_experiments"]
        self.assertEqual(len(prior), 1)
        self.assertEqual(prior[0]["decision"], "ROLLBACK")
        experiments.cleanup_experiment(second["experiment"]["experiment_id"], delete_branch=True)

    def test_safety_requires_opt_in_and_allowed_repo_root(self):
        experiments = import_submodule("experiments")
        os.environ.pop("CAPABILITY_FORGE_ALLOW_EXPERIMENT", None)
        disabled = experiments.create_experiment(
            repo_path=str(self.repo),
            capability_id="demo-capability",
            hypothesis="should not run",
        )
        self.assertFalse(disabled["success"])
        self.assertIn("disabled", disabled["error"])

        os.environ["CAPABILITY_FORGE_ALLOW_EXPERIMENT"] = "1"
        os.environ["CAPABILITY_FORGE_EXPERIMENT_REPO_ROOTS"] = str(self.root / "elsewhere")
        blocked = experiments.create_experiment(
            repo_path=str(self.repo),
            capability_id="demo-capability",
            hypothesis="outside root",
        )
        self.assertFalse(blocked["success"])
        self.assertEqual(blocked["error"], "CAPABILITY_FORGE_EXPERIMENT_REPO_ROOTS is not configured")

    def test_snapshot_refuses_file_changed_after_forge_patch(self):
        self._write_eval()
        experiments, exp = self._create("snapshot drift guard")
        worktree = self._patch(experiments, exp)
        experiments.evaluate_experiment(exp["experiment_id"])
        experiments.record_dogfood(exp["experiment_id"], "better", "looks better")
        experiments.decide_experiment(exp["experiment_id"])
        (worktree / "app.txt").write_text("changed-after-patch\n", encoding="utf-8")
        snapshot = experiments.snapshot_experiment(exp["experiment_id"])
        self.assertFalse(snapshot["success"])
        self.assertEqual(snapshot["error"], "patched_file_changed_after_patch")

    def test_cleanup_validates_branch_tip_before_removing_worktree(self):
        self._write_eval(expected="something-else\n")
        experiments, exp = self._create("branch race guard")
        worktree = self._patch(experiments, exp)
        experiments.evaluate_experiment(exp["experiment_id"])
        experiments.decide_experiment(exp["experiment_id"])
        (worktree / "extra.txt").write_text("external change", encoding="utf-8")
        self.assertEqual(git(worktree, "add", "extra.txt").returncode, 0)
        external_commit = git(
            worktree,
            "-c", "user.name=External",
            "-c", "user.email=external@example.invalid",
            "commit", "-m", "external branch movement",
        )
        self.assertEqual(external_commit.returncode, 0, external_commit.stderr)
        cleanup = experiments.cleanup_experiment(exp["experiment_id"], delete_branch=True)
        self.assertFalse(cleanup["success"])
        self.assertEqual(cleanup["error"], "branch_changed_since_experiment")
        self.assertTrue(worktree.exists())

    def test_dependency_graph_is_explicit_and_reported(self):
        registry = import_submodule("registry")
        data = {
            "a": {"id": "a", "depends_on": ["b", "external"]},
            "b": {"id": "b", "depends_on": []},
        }
        edges = registry.dependency_edges(data)
        self.assertEqual(
            edges,
            [
                {"capability": "a", "depends_on": "b", "resolved": True},
                {"capability": "a", "depends_on": "external", "resolved": False},
            ],
        )

    def test_decision_requires_real_dogfood_for_promotion(self):
        self._write_eval()
        experiments, exp = self._create("eval alone should not promote")
        self._patch(experiments, exp)
        experiments.evaluate_experiment(exp["experiment_id"])
        decision = experiments.decide_experiment(exp["experiment_id"])
        self.assertEqual(decision["decision"]["status"], "MORE_EVIDENCE")
        experiments.cleanup_experiment(exp["experiment_id"], delete_branch=True)


    def test_manifest_identity_tampering_is_rejected_before_cleanup(self):
        self._write_eval()
        experiments, created = self._create()
        experiment_id = created["experiment_id"]
        manifest_path = self.hermes_home / "capability-lab" / "experiments" / experiment_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["worktree"] = str(self.root / "not-the-experiment-worktree")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        status = experiments.status_experiment(experiment_id)
        self.assertFalse(status["success"])
        self.assertEqual(status["error"], "experiment_manifest_identity_mismatch")

        cleanup = experiments.cleanup_experiment(experiment_id, delete_branch=True)
        self.assertFalse(cleanup["success"])
        self.assertEqual(cleanup["error"], "experiment_manifest_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
