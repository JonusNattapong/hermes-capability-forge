from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .gates import read_eval_profiles
from .storage import _hermes_home, utc_now_iso

_ALLOWED_SUFFIXES = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".ps1",
}
_MAX_FILE_BYTES = 512 * 1024
_MAX_REPLACEMENT_BYTES = 64 * 1024
_MAX_CAPTURE_BYTES = 32 * 1024
_EXPERIMENT_ID_RE = re.compile(r"^[a-f0-9]{12}$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hypothesis_hash(capability_id: str, hypothesis: str) -> str:
    value = f"{capability_id.strip()}\n{hypothesis.strip()}".encode("utf-8", errors="replace")
    return hashlib.sha256(value).hexdigest()[:16]


def _experiment_root() -> Path:
    configured = os.environ.get("CAPABILITY_FORGE_EXPERIMENT_HOME", "").strip()
    return Path(configured).expanduser() if configured else _hermes_home() / "capability-lab" / "experiments"


def _allowed_repo_roots() -> list[Path]:
    raw = os.environ.get("CAPABILITY_FORGE_EXPERIMENT_REPO_ROOTS", "").strip()
    if not raw:
        return []
    roots: list[Path] = []
    for value in raw.split(os.pathsep):
        value = value.strip()
        if not value:
            continue
        try:
            roots.append(Path(value).expanduser().resolve(strict=True))
        except OSError:
            continue
    return roots


def _mutation_enabled() -> bool:
    return os.environ.get("CAPABILITY_FORGE_ALLOW_EXPERIMENT", "").strip() == "1"


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def _run_git(repo: Path, args: list[str], timeout_seconds: int = 30) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(repo), *args], cwd=repo, timeout_seconds=timeout_seconds)


def _validate_repo(raw_path: str) -> tuple[Path | None, str | None]:
    if not raw_path or "\x00" in raw_path:
        return None, "invalid_repo_path"
    roots = _allowed_repo_roots()
    if not roots:
        return None, "CAPABILITY_FORGE_EXPERIMENT_REPO_ROOTS is not configured"
    try:
        candidate = Path(raw_path).expanduser().resolve(strict=True)
    except OSError:
        return None, "repo_not_found"
    if not candidate.is_dir() or Path(raw_path).expanduser().is_symlink():
        return None, "repo_must_be_regular_directory"
    if not any(_is_under(candidate, root) or candidate == root for root in roots):
        return None, "repo_outside_allowed_roots"

    probe = _run_git(candidate, ["rev-parse", "--show-toplevel"])
    if probe.returncode != 0:
        return None, "not_a_git_repository"
    try:
        top = Path(probe.stdout.strip()).resolve(strict=True)
    except OSError:
        return None, "git_toplevel_unresolvable"
    if top != candidate:
        return None, "repo_path_must_be_git_toplevel"
    return candidate, None


def _manifest_path(experiment_id: str) -> Path:
    return _experiment_root() / experiment_id / "manifest.json"


def _read_manifest(experiment_id: str) -> tuple[dict[str, Any] | None, str | None]:
    normalized = experiment_id.strip().lower()
    if not _EXPERIMENT_ID_RE.fullmatch(normalized):
        return None, "invalid_experiment_id"
    path = _manifest_path(normalized)
    if not path.exists():
        return None, "experiment_not_found"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "invalid_experiment_manifest"
    if not isinstance(raw, dict) or raw.get("experiment_id") != normalized:
        return None, "invalid_experiment_manifest"

    expected_branch = f"forge/exp-{normalized}"
    expected_worktree = (_experiment_root() / normalized / "worktree").resolve(strict=False)
    raw_worktree = Path(str(raw.get("worktree") or "")).expanduser().resolve(strict=False)
    if raw.get("branch") != expected_branch or raw_worktree != expected_worktree:
        return None, "experiment_manifest_identity_mismatch"
    return raw, None


def _write_manifest(manifest: dict[str, Any]) -> Path:
    experiment_id = str(manifest["experiment_id"])
    path = _manifest_path(experiment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = utc_now_iso()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _prior_outcomes(capability_id: str, hypothesis_hash: str, limit: int = 5) -> list[dict[str, Any]]:
    root = _experiment_root()
    if not root.exists():
        return []
    found: list[dict[str, Any]] = []
    for path in root.glob("*/manifest.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict):
            continue
        if item.get("capability_id") != capability_id or item.get("hypothesis_hash") != hypothesis_hash:
            continue
        decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
        found.append({
            "experiment_id": item.get("experiment_id"),
            "state": item.get("state"),
            "decision": decision.get("status"),
            "created_at": item.get("created_at"),
        })
    found.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return found[:limit]


def create_experiment(
    *,
    repo_path: str,
    capability_id: str,
    hypothesis: str,
    base_ref: str = "HEAD",
) -> dict[str, Any]:
    if not _mutation_enabled():
        return {"success": False, "error": "experiment_mutation_disabled_set_CAPABILITY_FORGE_ALLOW_EXPERIMENT=1"}
    repo, error = _validate_repo(repo_path)
    if error or repo is None:
        return {"success": False, "error": error}
    capability_id = capability_id.strip()[:160]
    hypothesis = hypothesis.strip()[:2000]
    if not capability_id or not hypothesis:
        return {"success": False, "error": "capability_id_and_hypothesis_are_required"}

    base = _run_git(repo, ["rev-parse", "--verify", f"{base_ref}^{{commit}}"])
    if base.returncode != 0:
        return {"success": False, "error": "invalid_base_ref"}
    base_commit = base.stdout.strip()
    experiment_id = uuid.uuid4().hex[:12]
    branch = f"forge/exp-{experiment_id}"
    experiment_dir = _experiment_root() / experiment_id
    worktree = experiment_dir / "worktree"
    experiment_dir.mkdir(parents=True, exist_ok=False)

    created = _run_git(repo, ["worktree", "add", "-b", branch, str(worktree), base_commit], timeout_seconds=60)
    if created.returncode != 0:
        shutil.rmtree(experiment_dir, ignore_errors=True)
        return {
            "success": False,
            "error": "git_worktree_create_failed",
            "stderr": created.stderr[-2000:],
        }

    h_hash = _hypothesis_hash(capability_id, hypothesis)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "capability_id": capability_id,
        "hypothesis": hypothesis,
        "hypothesis_hash": h_hash,
        "source_repo": str(repo),
        "base_ref": base_ref[:200],
        "base_commit": base_commit,
        "branch": branch,
        "worktree": str(worktree),
        "state": "CREATED",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "patches": [],
        "evaluation": None,
        "dogfood": None,
        "decision": None,
        "snapshot": None,
    }
    _write_manifest(manifest)
    prior = _prior_outcomes(capability_id, h_hash)
    prior = [item for item in prior if item.get("experiment_id") != experiment_id]
    return {
        "success": True,
        "experiment": _public_manifest(manifest),
        "prior_matching_experiments": prior,
    }


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: manifest.get(key)
        for key in (
            "schema_version", "experiment_id", "capability_id", "hypothesis_hash",
            "source_repo", "base_ref", "base_commit", "branch", "worktree",
            "state", "created_at", "updated_at", "patches", "evaluation",
            "dogfood", "decision", "snapshot", "cleanup",
        )
    }


def _resolve_experiment_file(manifest: dict[str, Any], relative_path: str) -> tuple[Path | None, str | None]:
    if not relative_path or "\x00" in relative_path:
        return None, "invalid_path"
    candidate = Path(relative_path)
    if candidate.is_absolute():
        return None, "path_must_be_relative_to_worktree"
    worktree = Path(str(manifest.get("worktree") or ""))
    try:
        root = worktree.resolve(strict=True)
        target = (root / candidate).resolve(strict=True)
    except OSError:
        return None, "target_not_found"
    if not _is_under(target, root):
        return None, "target_outside_worktree"
    if (root / candidate).is_symlink() or not target.is_file():
        return None, "target_must_be_regular_file"
    if target.suffix.lower() not in _ALLOWED_SUFFIXES:
        return None, "unsupported_file_type"
    return target, None


def _replacement_variant(text: str, old_text: str, new_text: str) -> tuple[str, str, int, bool]:
    matches = text.count(old_text)
    if matches == 1:
        return old_text, new_text, matches, False
    if matches == 0 and "\r\n" in text and "\r\n" not in old_text and "\n" in old_text:
        old_crlf = old_text.replace("\n", "\r\n")
        new_crlf = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
        adapted_matches = text.count(old_crlf)
        if adapted_matches == 1:
            return old_crlf, new_crlf, adapted_matches, True
    return old_text, new_text, matches, False


def patch_experiment(
    *,
    experiment_id: str,
    relative_path: str,
    expected_sha256: str,
    old_text: str,
    new_text: str,
    reason: str,
) -> dict[str, Any]:
    if not _mutation_enabled():
        return {"success": False, "error": "experiment_mutation_disabled_set_CAPABILITY_FORGE_ALLOW_EXPERIMENT=1"}
    manifest, error = _read_manifest(experiment_id)
    if error or manifest is None:
        return {"success": False, "error": error}
    if manifest.get("state") in {"DECIDED", "CLEANED"}:
        return {"success": False, "error": "experiment_is_closed"}
    target, error = _resolve_experiment_file(manifest, relative_path)
    if error or target is None:
        return {"success": False, "error": error}

    raw = target.read_bytes()
    if len(raw) > _MAX_FILE_BYTES:
        return {"success": False, "error": "file_too_large"}
    current_hash = _sha256_bytes(raw)
    if current_hash != expected_sha256:
        return {"success": False, "error": "sha256_mismatch", "current_sha256": current_hash}
    if len(new_text.encode("utf-8")) > _MAX_REPLACEMENT_BYTES:
        return {"success": False, "error": "replacement_too_large"}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"success": False, "error": "target_not_utf8"}
    selected_old, selected_new, matches, newline_adapted = _replacement_variant(text, old_text, new_text)
    if matches != 1:
        return {"success": False, "error": "old_text_must_match_exactly_once", "matches": matches}

    updated = text.replace(selected_old, selected_new, 1).encode("utf-8")
    mode = stat.S_IMODE(target.stat().st_mode)
    fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".exp-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, mode)
        # Re-check immediately before replacement to avoid overwriting concurrent edits.
        if _sha256_bytes(target.read_bytes()) != current_hash:
            os.unlink(temporary_name)
            return {"success": False, "error": "target_changed_during_patch"}
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise

    patch_record = {
        "path": relative_path.replace("\\", "/")[:500],
        "reason": reason.strip()[:500],
        "original_sha256": current_hash,
        "updated_sha256": _sha256_bytes(updated),
        "newline_adapted": newline_adapted,
        "applied_at": utc_now_iso(),
    }
    patches = manifest.get("patches") if isinstance(manifest.get("patches"), list) else []
    patches.append(patch_record)
    manifest["patches"] = patches[-100:]
    manifest["state"] = "PATCHED"
    _write_manifest(manifest)
    return {"success": True, "experiment_id": experiment_id, "patch": patch_record, "state": "PATCHED"}


def _eval_checks_for(capability_id: str) -> tuple[list[dict[str, Any]], str | None]:
    profile = read_eval_profiles().get(capability_id)
    if not profile:
        return [], "no_eval_profile"
    checks = profile.get("checks", [])
    if not isinstance(checks, list):
        return [], "invalid_eval_checks"
    normalized: list[dict[str, Any]] = []
    for item in checks:
        if not isinstance(item, dict):
            return [], "invalid_eval_check"
        name = item.get("name")
        argv = item.get("argv")
        if not isinstance(name, str) or not name.strip() or not isinstance(argv, list) or not argv:
            return [], "invalid_eval_check"
        if not all(isinstance(value, str) and value for value in argv):
            return [], "invalid_eval_check_argv"
        try:
            timeout_seconds = int(item.get("timeout_seconds", 120))
        except (TypeError, ValueError):
            return [], "invalid_eval_timeout"
        normalized.append({
            "name": name.strip()[:120],
            "argv": argv[:32],
            "timeout_seconds": max(1, min(timeout_seconds, 900)),
        })
    if not normalized:
        return [], "no_eval_checks"
    return normalized[:32], None


def evaluate_experiment(experiment_id: str) -> dict[str, Any]:
    manifest, error = _read_manifest(experiment_id)
    if error or manifest is None:
        return {"success": False, "error": error}
    if manifest.get("state") == "CLEANED":
        return {"success": False, "error": "experiment_is_cleaned"}
    worktree = Path(str(manifest.get("worktree") or ""))
    if not worktree.exists():
        return {"success": False, "error": "experiment_worktree_missing"}

    checks, error = _eval_checks_for(str(manifest.get("capability_id") or ""))
    if error:
        return {"success": False, "error": error}

    results: list[dict[str, Any]] = []
    all_passed = True
    for check in checks:
        started = time.monotonic()
        try:
            completed = _run(
                list(check["argv"]),
                cwd=worktree,
                timeout_seconds=int(check["timeout_seconds"]),
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            stdout = completed.stdout.encode("utf-8", errors="replace")[:_MAX_CAPTURE_BYTES]
            stderr = completed.stderr.encode("utf-8", errors="replace")[:_MAX_CAPTURE_BYTES]
            passed = completed.returncode == 0
            all_passed = all_passed and passed
            results.append({
                "name": check["name"],
                "passed": passed,
                "exit_code": completed.returncode,
                "duration_ms": duration_ms,
                "stdout_sha256": _sha256_bytes(stdout),
                "stderr_sha256": _sha256_bytes(stderr),
                "stdout_bytes_captured": len(stdout),
                "stderr_bytes_captured": len(stderr),
            })
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            all_passed = False
            results.append({
                "name": check["name"],
                "passed": False,
                "timed_out": True,
                "duration_ms": duration_ms,
            })
        except OSError as exc:
            all_passed = False
            results.append({
                "name": check["name"],
                "passed": False,
                "error": type(exc).__name__,
            })

    diff = _run_git(worktree, ["diff", "--check"])
    diff_check_passed = diff.returncode == 0
    all_passed = all_passed and diff_check_passed
    evaluation = {
        "status": "PASS" if all_passed else "FAIL",
        "evaluated_at": utc_now_iso(),
        "checks": results,
        "diff_check_passed": diff_check_passed,
        "check_count": len(results),
    }
    manifest["evaluation"] = evaluation
    manifest["state"] = "EVALUATED"
    _write_manifest(manifest)
    return {"success": True, "experiment_id": experiment_id, "evaluation": evaluation}


def record_dogfood(experiment_id: str, outcome: str, evidence: str) -> dict[str, Any]:
    manifest, error = _read_manifest(experiment_id)
    if error or manifest is None:
        return {"success": False, "error": error}
    normalized = outcome.strip().lower()
    if normalized not in {"better", "same", "worse", "unclear"}:
        return {"success": False, "error": "outcome_must_be_better_same_worse_or_unclear"}
    if manifest.get("state") == "CLEANED":
        return {"success": False, "error": "experiment_is_cleaned"}
    evidence_bytes = evidence.strip().encode("utf-8", errors="replace")[:8192]
    manifest["dogfood"] = {
        "outcome": normalized,
        "evidence_sha256": _sha256_bytes(evidence_bytes),
        "evidence_bytes": len(evidence_bytes),
        "recorded_at": utc_now_iso(),
    }
    if manifest.get("state") != "DECIDED":
        manifest["state"] = "DOGFOODED"
    _write_manifest(manifest)
    return {"success": True, "experiment_id": experiment_id, "dogfood": manifest["dogfood"]}


def decide_experiment(experiment_id: str) -> dict[str, Any]:
    manifest, error = _read_manifest(experiment_id)
    if error or manifest is None:
        return {"success": False, "error": error}
    evaluation = manifest.get("evaluation") if isinstance(manifest.get("evaluation"), dict) else None
    dogfood = manifest.get("dogfood") if isinstance(manifest.get("dogfood"), dict) else None

    if evaluation is None:
        status = "MORE_EVIDENCE"
        reason = "isolated_eval_missing"
    elif evaluation.get("status") != "PASS":
        status = "ROLLBACK"
        reason = "isolated_eval_failed"
    elif dogfood is None or dogfood.get("outcome") == "unclear":
        status = "MORE_EVIDENCE"
        reason = "dogfood_evidence_missing_or_unclear"
    elif dogfood.get("outcome") == "worse":
        status = "ROLLBACK"
        reason = "dogfood_regression"
    elif dogfood.get("outcome") == "better":
        status = "PROMOTE"
        reason = "eval_passed_and_dogfood_improved"
    else:
        status = "MORE_EVIDENCE"
        reason = "dogfood_not_better_than_baseline"

    decision = {"status": status, "reason": reason, "decided_at": utc_now_iso()}
    manifest["decision"] = decision
    manifest["state"] = "DECIDED"
    _write_manifest(manifest)
    return {"success": True, "experiment_id": experiment_id, "decision": decision}


def snapshot_experiment(experiment_id: str) -> dict[str, Any]:
    if not _mutation_enabled():
        return {"success": False, "error": "experiment_mutation_disabled_set_CAPABILITY_FORGE_ALLOW_EXPERIMENT=1"}
    manifest, error = _read_manifest(experiment_id)
    if error or manifest is None:
        return {"success": False, "error": error}
    decision = manifest.get("decision") if isinstance(manifest.get("decision"), dict) else {}
    evaluation = manifest.get("evaluation") if isinstance(manifest.get("evaluation"), dict) else {}
    dogfood = manifest.get("dogfood") if isinstance(manifest.get("dogfood"), dict) else {}
    if decision.get("status") != "PROMOTE":
        return {"success": False, "error": "snapshot_requires_promote_decision"}
    if evaluation.get("status") != "PASS" or dogfood.get("outcome") != "better":
        return {"success": False, "error": "snapshot_requires_passing_eval_and_better_dogfood"}
    worktree = Path(str(manifest.get("worktree") or ""))
    if not worktree.exists():
        return {"success": False, "error": "experiment_worktree_missing"}

    diff_check = _run_git(worktree, ["diff", "--check"])
    if diff_check.returncode != 0:
        return {"success": False, "error": "git_diff_check_failed", "stderr": diff_check.stderr[-2000:]}
    patches = manifest.get("patches") if isinstance(manifest.get("patches"), list) else []
    latest_by_path: dict[str, dict[str, Any]] = {}
    for patch in patches:
        if isinstance(patch, dict) and isinstance(patch.get("path"), str):
            latest_by_path[patch["path"]] = patch
    if not latest_by_path:
        return {"success": False, "error": "no_forge_patches_to_snapshot"}

    patch_paths = sorted(latest_by_path)
    for relative_path in patch_paths:
        target, target_error = _resolve_experiment_file(manifest, relative_path)
        if target_error or target is None:
            return {"success": False, "error": "patched_file_missing_before_snapshot", "path": relative_path}
        current_hash = _sha256_bytes(target.read_bytes())
        expected_hash = str(latest_by_path[relative_path].get("updated_sha256") or "")
        if current_hash != expected_hash:
            return {
                "success": False,
                "error": "patched_file_changed_after_patch",
                "path": relative_path,
                "current_sha256": current_hash,
                "expected_sha256": expected_hash,
            }

    # Eval commands run inside the experiment worktree and are trusted executable
    # configuration, so they may have touched the Git index. Clear staged state first
    # without discarding working-tree files, then stage only Forge-owned patch paths.
    reset = _run_git(worktree, ["reset", "--mixed", "HEAD", "--"])
    if reset.returncode != 0:
        return {"success": False, "error": "git_index_reset_failed", "stderr": reset.stderr[-2000:]}
    added = _run_git(worktree, ["add", "--", *patch_paths])
    if added.returncode != 0:
        return {"success": False, "error": "git_add_failed", "stderr": added.stderr[-2000:]}
    staged = _run_git(worktree, ["diff", "--cached", "--quiet"])
    if staged.returncode == 0:
        return {"success": False, "error": "no_changes_to_snapshot"}
    if staged.returncode not in {0, 1}:
        return {"success": False, "error": "git_staged_diff_failed", "stderr": staged.stderr[-2000:]}
    message = f"forge(exp): {str(manifest.get('capability_id') or 'capability')[:80]} {experiment_id}"
    committed = _run_git(
        worktree,
        [
            "-c", "user.name=Capability Forge",
            "-c", "user.email=capability-forge@local.invalid",
            "commit", "-m", message,
        ],
        timeout_seconds=60,
    )
    if committed.returncode != 0:
        return {"success": False, "error": "git_commit_failed", "stderr": committed.stderr[-2000:]}
    head = _run_git(worktree, ["rev-parse", "HEAD"])
    if head.returncode != 0:
        return {"success": False, "error": "git_rev_parse_failed"}
    snapshot = {
        "commit": head.stdout.strip(),
        "message": message,
        "changed_paths": len(patch_paths),
        "created_at": utc_now_iso(),
    }
    manifest["snapshot"] = snapshot
    manifest["state"] = "SNAPSHOTTED"
    _write_manifest(manifest)
    return {"success": True, "experiment_id": experiment_id, "snapshot": snapshot}


def status_experiment(experiment_id: str) -> dict[str, Any]:
    manifest, error = _read_manifest(experiment_id)
    if error or manifest is None:
        return {"success": False, "error": error}
    worktree = Path(str(manifest.get("worktree") or ""))
    git_status: dict[str, Any] | None = None
    if worktree.exists():
        status = _run_git(worktree, ["status", "--porcelain=v1"])
        if status.returncode == 0:
            lines = [line for line in status.stdout.splitlines() if line.strip()]
            git_status = {"dirty": bool(lines), "changed_paths": len(lines)}
    return {"success": True, "experiment": _public_manifest(manifest), "git": git_status}


def cleanup_experiment(experiment_id: str, delete_branch: bool = False) -> dict[str, Any]:
    if not _mutation_enabled():
        return {"success": False, "error": "experiment_mutation_disabled_set_CAPABILITY_FORGE_ALLOW_EXPERIMENT=1"}
    manifest, error = _read_manifest(experiment_id)
    if error or manifest is None:
        return {"success": False, "error": error}
    repo, error = _validate_repo(str(manifest.get("source_repo") or ""))
    if error or repo is None:
        return {"success": False, "error": error}

    decision = manifest.get("decision") if isinstance(manifest.get("decision"), dict) else {}
    if decision.get("status") == "PROMOTE" and not isinstance(manifest.get("snapshot"), dict):
        return {"success": False, "error": "promote_requires_snapshot_before_cleanup"}
    if delete_branch and decision.get("status") == "PROMOTE":
        return {"success": False, "error": "refuse_delete_branch_for_promote_decision"}

    branch_name = str(manifest.get("branch") or "")
    if delete_branch:
        branch_tip = _run_git(repo, ["rev-parse", "--verify", f"{branch_name}^{{commit}}"])
        if branch_tip.returncode != 0:
            return {"success": False, "error": "experiment_branch_missing"}
        snapshot = manifest.get("snapshot") if isinstance(manifest.get("snapshot"), dict) else {}
        expected_tip = str(snapshot.get("commit") or manifest.get("base_commit") or "")
        if branch_tip.stdout.strip() != expected_tip:
            return {"success": False, "error": "branch_changed_since_experiment"}

    worktree = Path(str(manifest.get("worktree") or ""))
    if worktree.exists():
        removed = _run_git(repo, ["worktree", "remove", "--force", str(worktree)], timeout_seconds=60)
        if removed.returncode != 0:
            return {"success": False, "error": "git_worktree_remove_failed", "stderr": removed.stderr[-2000:]}
    _run_git(repo, ["worktree", "prune"])

    branch_deleted = False
    if delete_branch:
        deleted = _run_git(repo, ["branch", "-D", branch_name])
        if deleted.returncode != 0:
            return {"success": False, "error": "git_branch_delete_failed", "stderr": deleted.stderr[-2000:]}
        branch_deleted = True

    manifest["state"] = "CLEANED"
    manifest["cleanup"] = {"cleaned_at": utc_now_iso(), "branch_deleted": branch_deleted}
    _write_manifest(manifest)
    return {"success": True, "experiment_id": experiment_id, "state": "CLEANED", "branch_deleted": branch_deleted}


def handle_experiment(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    action = str(params.get("action") or "status").strip().lower()

    if action == "create":
        result = create_experiment(
            repo_path=str(params.get("repo_path") or ""),
            capability_id=str(params.get("capability_id") or ""),
            hypothesis=str(params.get("hypothesis") or ""),
            base_ref=str(params.get("base_ref") or "HEAD"),
        )
    elif action == "patch":
        result = patch_experiment(
            experiment_id=str(params.get("experiment_id") or ""),
            relative_path=str(params.get("relative_path") or ""),
            expected_sha256=str(params.get("expected_sha256") or ""),
            old_text=str(params.get("old_text") or ""),
            new_text=str(params.get("new_text") or ""),
            reason=str(params.get("reason") or ""),
        )
    elif action == "evaluate":
        result = evaluate_experiment(str(params.get("experiment_id") or ""))
    elif action == "dogfood":
        result = record_dogfood(
            str(params.get("experiment_id") or ""),
            str(params.get("outcome") or ""),
            str(params.get("evidence") or ""),
        )
    elif action == "decide":
        result = decide_experiment(str(params.get("experiment_id") or ""))
    elif action == "snapshot":
        result = snapshot_experiment(str(params.get("experiment_id") or ""))
    elif action == "cleanup":
        result = cleanup_experiment(
            str(params.get("experiment_id") or ""),
            bool(params.get("delete_branch", False)),
        )
    elif action == "status":
        result = status_experiment(str(params.get("experiment_id") or ""))
    else:
        result = {"success": False, "error": "action must be create, patch, evaluate, dogfood, decide, snapshot, status, or cleanup"}
    return json.dumps(result, ensure_ascii=False)
