CAPABILITY_FORGE_REPORT = {
    "name": "capability_forge_report",
    "description": (
        "Analyze recent privacy-preserving Hermes capability telemetry and skill usage, "
        "then return an evidence-backed maintenance shortlist. Use before researching, "
        "patching, replacing, or retiring capabilities."
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
