from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import _hermes_home, utc_now_iso

_ALLOWED_SUFFIXES = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".ps1",
}
_MAX_FILE_BYTES = 512 * 1024
_MAX_REPLACEMENT_BYTES = 64 * 1024


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _patch_roots() -> list[Path]:
    raw = os.environ.get("CAPABILITY_FORGE_PATCH_ROOTS", "").strip()
    if not raw:
        return []
    roots: list[Path] = []
    for item in raw.split(os.pathsep):
        item = item.strip()
        if not item:
            continue
        try:
            roots.append(Path(item).expanduser().resolve(strict=True))
        except OSError:
            continue
    return roots


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_target(raw_path: str) -> tuple[Path | None, str | None]:
    if not raw_path or "\x00" in raw_path:
        return None, "invalid_path"
    roots = _patch_roots()
    if not roots:
        return None, "CAPABILITY_FORGE_PATCH_ROOTS is not configured"
    candidate = Path(raw_path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None, "target_not_found"
    if candidate.is_symlink() or not resolved.is_file():
        return None, "target_must_be_regular_file"
    if not any(_is_under(resolved, root) for root in roots):
        return None, "target_outside_allowed_roots"
    if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
        return None, "unsupported_file_type"
    return resolved, None


def _patch_store() -> Path:
    return _hermes_home() / "capability-lab" / "patches"


def _manifest_path(patch_id: str) -> Path:
    return _patch_store() / patch_id / "manifest.json"


def _safe_patch_id(value: str) -> bool:
    return len(value) == 32 and all(char in "0123456789abcdef" for char in value.lower())


def preview_patch(
    *,
    path: str,
    expected_sha256: str,
    old_text: str,
    new_text: str,
    capability_id: str,
    reason: str,
) -> dict[str, Any]:
    target, error = _resolve_target(path)
    if error or target is None:
        return {"success": False, "error": error}

    try:
        raw = target.read_bytes()
    except OSError:
        return {"success": False, "error": "read_failed"}
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

    occurrences = text.count(old_text)
    if occurrences != 1:
        return {"success": False, "error": "old_text_must_match_exactly_once", "matches": occurrences}
    updated = text.replace(old_text, new_text, 1)
    updated_bytes = updated.encode("utf-8")

    return {
        "success": True,
        "mode": "preview",
        "capability_id": capability_id[:160],
        "reason": reason[:500],
        "path": str(target),
        "original_sha256": current_hash,
        "updated_sha256": _sha256_bytes(updated_bytes),
        "original_bytes": len(raw),
        "updated_bytes": len(updated_bytes),
        "matches": occurrences,
    }


def apply_patch(
    *,
    path: str,
    expected_sha256: str,
    old_text: str,
    new_text: str,
    capability_id: str,
    reason: str,
) -> dict[str, Any]:
    preview = preview_patch(
        path=path,
        expected_sha256=expected_sha256,
        old_text=old_text,
        new_text=new_text,
        capability_id=capability_id,
        reason=reason,
    )
    if not preview.get("success"):
        return preview
    if os.environ.get("CAPABILITY_FORGE_ALLOW_PATCH", "").strip() != "1":
        preview["success"] = False
        preview["error"] = "patch_apply_disabled_set_CAPABILITY_FORGE_ALLOW_PATCH=1"
        return preview

    target = Path(preview["path"])
    raw = target.read_bytes()
    if _sha256_bytes(raw) != expected_sha256:
        return {"success": False, "error": "sha256_changed_after_preview"}
    text = raw.decode("utf-8")
    updated = text.replace(old_text, new_text, 1).encode("utf-8")
    patch_id = uuid.uuid4().hex
    patch_dir = _patch_store() / patch_id
    patch_dir.mkdir(parents=True, exist_ok=False)
    backup = patch_dir / "original.bin"
    backup.write_bytes(raw)

    manifest = {
        "schema_version": 1,
        "patch_id": patch_id,
        "created_at": utc_now_iso(),
        "capability_id": capability_id[:160],
        "reason": reason[:500],
        "path": str(target),
        "original_sha256": preview["original_sha256"],
        "updated_sha256": preview["updated_sha256"],
        "backup": str(backup),
        "rolled_back_at": None,
    }
    _manifest_path(patch_id).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    original_mode = stat.S_IMODE(target.stat().st_mode)
    fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".forge-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, original_mode)
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        shutil.rmtree(patch_dir, ignore_errors=True)
        raise

    return {
        "success": True,
        "mode": "applied",
        "patch_id": patch_id,
        "capability_id": capability_id[:160],
        "path": str(target),
        "original_sha256": preview["original_sha256"],
        "updated_sha256": preview["updated_sha256"],
        "rollback_available": True,
    }


def rollback_patch(patch_id: str) -> dict[str, Any]:
    normalized = patch_id.strip().lower()
    if not _safe_patch_id(normalized):
        return {"success": False, "error": "invalid_patch_id"}
    if os.environ.get("CAPABILITY_FORGE_ALLOW_PATCH", "").strip() != "1":
        return {"success": False, "error": "patch_apply_disabled_set_CAPABILITY_FORGE_ALLOW_PATCH=1"}

    manifest_path = _manifest_path(normalized)
    if not manifest_path.exists():
        return {"success": False, "error": "patch_not_found"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"success": False, "error": "invalid_patch_manifest"}
    if manifest.get("rolled_back_at"):
        return {"success": False, "error": "patch_already_rolled_back"}

    target, error = _resolve_target(str(manifest.get("path") or ""))
    if error or target is None:
        return {"success": False, "error": error}
    current = target.read_bytes()
    current_hash = _sha256_bytes(current)
    if current_hash != manifest.get("updated_sha256"):
        return {"success": False, "error": "target_changed_since_patch", "current_sha256": current_hash}

    backup = Path(str(manifest.get("backup") or ""))
    try:
        original = backup.read_bytes()
    except OSError:
        return {"success": False, "error": "backup_missing"}
    if _sha256_bytes(original) != manifest.get("original_sha256"):
        return {"success": False, "error": "backup_hash_mismatch"}

    patched_mode = stat.S_IMODE(target.stat().st_mode)
    fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".forge-rollback-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(original)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, patched_mode)
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise

    manifest["rolled_back_at"] = utc_now_iso()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "success": True,
        "mode": "rolled_back",
        "patch_id": normalized,
        "path": str(target),
        "restored_sha256": manifest.get("original_sha256"),
    }


def handle_patch(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    action = str(params.get("action") or "preview").strip().lower()
    if action == "rollback":
        result = rollback_patch(str(params.get("patch_id") or ""))
        return json.dumps(result, ensure_ascii=False)
    if action not in {"preview", "apply"}:
        return json.dumps({"success": False, "error": "action must be preview, apply, or rollback"})

    required = ("path", "expected_sha256", "old_text", "new_text", "capability_id", "reason")
    missing = [key for key in required if not isinstance(params.get(key), str) or not params.get(key)]
    if missing:
        return json.dumps({"success": False, "error": "missing_required_fields", "fields": missing})

    function = apply_patch if action == "apply" else preview_patch
    result = function(
        path=params["path"],
        expected_sha256=params["expected_sha256"],
        old_text=params["old_text"],
        new_text=params["new_text"],
        capability_id=params["capability_id"],
        reason=params["reason"],
    )
    return json.dumps(result, ensure_ascii=False)
