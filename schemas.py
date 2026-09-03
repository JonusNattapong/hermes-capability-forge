CAPABILITY_FORGE_REPORT = {
    "name": "capability_forge_report",
    "description": (
        "Analyze recent privacy-preserving Hermes capability telemetry, explicit ownership, "
        "and skill usage, then return an evidence-backed maintenance shortlist."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "default": 7,
                "description": "Lookback window in days.",
            },
            "write_report": {
                "type": "boolean",
                "default": True,
                "description": "Persist the sanitized JSON report under ~/.hermes/capability-lab/reports/.",
            },
        },
        "additionalProperties": False,
    },
}

CAPABILITY_FORGE_GATE = {
    "name": "capability_forge_gate",
    "description": (
        "Evaluate an explicitly registered capability against deterministic promotion thresholds, "
        "compare it with a recorded baseline, or record a new baseline after a passing gate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["evaluate", "compare", "record_baseline"],
                "default": "evaluate",
            },
            "capability_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
            },
            "days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "default": 7,
            },
        },
        "required": ["capability_id"],
        "additionalProperties": False,
    },
}

CAPABILITY_FORGE_PATCH = {
    "name": "capability_forge_patch",
    "description": (
        "Preview, apply, or roll back one exact-text patch inside explicit allowlisted roots. "
        "Apply/rollback are disabled unless CAPABILITY_FORGE_ALLOW_PATCH=1."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["preview", "apply", "rollback"],
                "default": "preview",
            },
            "path": {"type": "string"},
            "expected_sha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "capability_id": {"type": "string", "maxLength": 160},
            "reason": {"type": "string", "maxLength": 500},
            "patch_id": {"type": "string", "pattern": "^[a-fA-F0-9]{32}$"},
        },
        "additionalProperties": False,
    },
}
