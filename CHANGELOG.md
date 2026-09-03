# Changelog

## 0.3.0 - 2026-09-03

- Add explicit capability ownership registry with exact tool and narrow-prefix mapping.
- Promote owned tool failures to capability-level maintenance candidates without LLM guessing.
- Add `capability_forge_gate` with capability-specific eval profiles and promotion statuses.
- Add passing-only baseline recording and deterministic baseline drift/regression comparison.
- Add opt-in `capability_forge_patch` preview/apply/rollback with allowlisted roots, SHA-256 concurrency checks, exact one-match replacement, atomic writes, and backups.
- Keep scheduled Maintainer runs proposal-only even when foreground guarded patching is enabled.
- Add bundled registry metadata plus capability/eval examples.
- Expand integration/security tests for ownership, gates, drift, allowlists, stale hashes, apply, rollback, and tool registration.

## 0.2.0 - 2026-09-03

- Add deterministic `capability_forge_report` plugin tool.
- Add 7-day evidence aggregation across Observer events and Hermes skill usage.
- Detect repeated failures, retry loops, elevated failure rates, high latency, and high-usage review candidates.
- Add persisted sanitized reports under `~/.hermes/capability-lab/reports/`.
- Add `capability-maintainer` weekly Hermes Blueprint with proposal-first maintenance policy.
- Improve Observer JSON envelope classification without persisting tool payloads.
- Prevent the report tool from nominating itself as a maintenance candidate.
- Expand tests for privacy, retries, candidate ranking, report persistence, and plugin registration.

## 0.1.0 - 2026-09-03

- Add `capability-forge` Skill.
- Add privacy-preserving `capability-observer` plugin.
- Add Git-tracked skill layout, safe example config, CI, and MCP builder reuse guidance.
