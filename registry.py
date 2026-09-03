from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .storage import _hermes_home


def _bundled_registry_path() -> Path:
    return Path(__file__).parent / "data" / "default-capabilities.json"


def default_registry_path() -> Path:
    configured = os.environ.get("CAPABILITY_FORGE_REGISTRY", "").strip()
    return Path(configured).expanduser() if configured else _hermes_home() / "capability-lab" / "capabilities.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_registry(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Merge bundled capability ownership with the user's explicit registry.

    User entries override bundled entries by capability id. Ownership is explicit;
    no model or heuristic guesses which component owns an arbitrary tool.
    """
    merged: dict[str, dict[str, Any]] = {}
    for source in (_bundled_registry_path(), path or default_registry_path()):
        raw = _read_json(source)
        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list):
            continue
        for item in capabilities:
            if not isinstance(item, dict):
                continue
            capability_id = item.get("id")
            if not isinstance(capability_id, str) or not capability_id.strip():
                continue
            normalized = dict(item)
            normalized["id"] = capability_id.strip()[:160]
            normalized["kind"] = str(item.get("kind") or "unknown")[:64]
            normalized["tools"] = [
                str(value)[:160]
                for value in item.get("tools", [])
                if isinstance(value, str) and value.strip()
            ][:128]
            normalized["tool_prefixes"] = [
                str(value)[:160]
                for value in item.get("tool_prefixes", [])
                if isinstance(value, str) and value.strip()
            ][:128]
            normalized["skills"] = [
                str(value)[:160]
                for value in item.get("skills", [])
                if isinstance(value, str) and value.strip()
            ][:128]
            normalized["depends_on"] = [
                str(value)[:160]
                for value in item.get("depends_on", [])
                if isinstance(value, str) and value.strip() and str(value).strip() != normalized["id"]
            ][:128]
            merged[normalized["id"]] = normalized
    return merged


def owner_for_tool(tool_name: str, registry: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    name = str(tool_name or "")
    if not name:
        return None

    exact: list[dict[str, Any]] = []
    prefix: list[tuple[int, dict[str, Any]]] = []
    for capability in registry.values():
        if name in capability.get("tools", []):
            exact.append(capability)
        for candidate in capability.get("tool_prefixes", []):
            if candidate and name.startswith(candidate):
                prefix.append((len(candidate), capability))

    # Ambiguous exact matches are intentionally unresolved instead of guessed.
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    if not prefix:
        return None

    prefix.sort(key=lambda item: item[0], reverse=True)
    longest = prefix[0][0]
    winners = [capability for length, capability in prefix if length == longest]
    return winners[0] if len(winners) == 1 else None


def public_owner(capability: dict[str, Any] | None) -> dict[str, Any] | None:
    if capability is None:
        return None
    payload = {
        "id": capability.get("id"),
        "kind": capability.get("kind"),
        "source": capability.get("source"),
        "depends_on": capability.get("depends_on", []),
    }
    return {key: value for key, value in payload.items() if value is not None}


def dependency_edges(registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for capability_id, capability in registry.items():
        for dependency in capability.get("depends_on", []):
            if not isinstance(dependency, str) or not dependency:
                continue
            edges.append({
                "capability": capability_id,
                "depends_on": dependency,
                "resolved": dependency in registry,
            })
    edges.sort(key=lambda item: (item["capability"], item["depends_on"]))
    return edges
