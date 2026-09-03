---
name: capability-maintainer
description: >
  Weekly evidence-based maintenance for Hermes capabilities. Analyze sanitized
  capability telemetry and Hermes skill usage, identify repeated failures or high-use
  friction, perform bounded research only for justified candidates, and produce
  conservative patch/retire/keep proposals. Do not mutate capabilities automatically.
version: 0.4.0
author: JonusNattapong
license: MIT
metadata:
  hermes:
    tags:
      - maintenance
      - telemetry
      - reliability
      - skills
      - plugins
      - mcp
      - research
      - blueprint
    category: autonomous-ai-agents
    related_skills:
      - capability-forge
    requires_tools:
      - capability_forge_report
      - capability_forge_gate
    blueprint:
      schedule: "every 7d"
      prompt: >
        Review the last 7 days of capability evidence. Research only candidates that
        have recurring failures, meaningful active use, or likely upstream drift.
        Return a concise maintenance report with keep, patch, investigate, or retire
        proposals. Do not modify capabilities automatically.
      no_agent: false
---

# Capability Maintainer

Maintain capabilities from evidence, not instinct.

This skill is the periodic counterpart to `capability-forge`. The forge improves
capabilities while real work is happening. The maintainer looks across recent usage
and decides what deserves attention next.

## Safety policy

Default mode is **proposal-first**.

- Scheduled runs do not patch, delete, archive, replace, install, publish, or record new baselines automatically.
- Do not change Hermes core.
- Treat unresolved tool ownership as a request to improve the registry, not permission to guess.
- Inspect explicit dependency edges before attributing a failure to the top-level capability.
- Require a passing capability eval gate before recommending promotion of a change.
- If a baseline exists, flag regressions before proposing KEEP or promotion.
- Do not treat missing telemetry as proof that a capability is unused.
- Do not research every installed capability on every run.
- Do not persist prompts, tool arguments, tool results, secrets, URLs, commands, or file contents.
- Prefer reversible changes and existing Hermes lifecycle mechanisms.

## Weekly loop

**REPORT -> MAP OWNER -> TRIAGE -> INSPECT -> RESEARCH IF JUSTIFIED -> GATE -> PROPOSE -> VERIFY PLAN**

### 1. Generate evidence

Call `capability_forge_report` with:

```json
{"days": 7, "write_report": true}
```

Start from `report.candidates`. Prefer capability-level candidates whose `owner.id` is explicit. For unresolved tool-level candidates, improve or request the ownership registry before attributing a root cause.

If `candidate_count` is zero, do not invent maintenance work. Summarize that no
candidate crossed the current evidence thresholds and stop unless another concrete
signal exists.

### 2. Triage candidates

Interpret candidate reasons conservatively:

- `repeated_failures`: inspect first; likely worth fixing.
- `retry_loop`: the same tool was called again after an error within the same hashed task/session; inspect repeated workaround behavior.
- `elevated_failure_rate`: inspect failure pattern and recent environment changes.
- `high_latency`: confirm latency is actually harmful before redesigning anything.
- `high_usage_review`: high usage alone is not a defect; look for repeated friction or simplification opportunities.

Use the report as a shortlist, not as an autonomous verdict.

### 3. Inspect existing capability surfaces

For each serious candidate, determine which surface owns the behavior:

1. existing Skill or Skill + script
2. Hermes Plugin / Tool
3. MCP server
4. external CLI, SDK, API, or service
5. Hermes built-in behavior

Inspect the current implementation and configuration before suggesting replacement.
Check `report.dependency_edges` for explicit upstream capability dependencies. A failure
in a dependency may explain a healthy owner's symptoms; do not patch the owner until
that possibility is ruled out. Prefer a targeted patch over creating a near-duplicate
capability.

### 4. Use Hermes skill usage carefully

The report may include counters from `~/.hermes/skills/.usage.json`.

Use these counters as supporting evidence only:

- high `use_count` means breakage has higher impact
- repeated `patch_count` can indicate drift or unstable instructions
- recent use can justify maintenance research
- stale state can justify inspection, but not automatic deletion

Some skill provenance is not tracked or curated the same way. Missing usage must be
reported as `unknown`, not `unused`.

### 5. Research only when justified

Research is allowed when at least one is true:

- recurring failure may be caused by upstream API/CLI/SDK changes
- an active capability depends on a changing external service
- documentation or references appear stale
- a maintained replacement may now exist
- a security or compatibility concern needs current verification

Research budget:

1. official documentation
2. official repository/source
3. one to three strong external sources only when materially useful

Stop once there is enough evidence to decide.

Do not research healthy low-change capabilities merely because seven days passed.

### 6. Run the capability gate when possible

For a candidate with explicit ownership and an eval profile, call:

```json
{"action":"evaluate","capability_id":"<owner.id>","days":7}
```

Interpret results conservatively:

- `PASS`: current observed window meets the configured thresholds.
- `FAIL`: do not recommend promotion; identify the failed checks.
- `INSUFFICIENT_EVIDENCE`: collect more representative use before deciding.
- `NO_PROFILE`: propose an eval profile before calling the capability verified.
- `drift.status = REGRESSION`: flag the regression even if absolute thresholds still pass.

Do not record a new baseline from a scheduled maintenance run.

### 7. Choose a proposal

Every candidate should end in one of these states:

#### KEEP

Use when the capability is healthy or the signal is noise.

#### PATCH

Use when a focused change can fix the observed friction.

A patch proposal must include:

- evidence
- suspected root cause
- exact surface to change
- smallest change
- verification steps
- rollback path

#### INVESTIGATE

Use when evidence is insufficient or the root cause crosses system boundaries.

State what additional evidence is needed. Do not guess.

#### RETIRE / CONSOLIDATE

Use only when there is evidence of duplication, supersession, abandonment, or negative value.

Prefer Hermes Curator/archive mechanisms where they apply. Do not auto-delete.

### 8. Prevent capability churn

Reject proposals that only:

- rename things without reducing friction
- wrap a trivial shell command in MCP
- add a new tool when an existing Skill solves it
- replace a working dependency only because a newer version exists
- create another scheduler instead of using Hermes cron/blueprints
- add broad permissions for convenience

### 9. Produce the maintenance report

Return a compact report with:

```text
Capability Maintenance
Window: 7 days
Evidence: <event count> events / <tool count> tools / <capability count> mapped capabilities

KEEP
- ...

PATCH
- capability: ...
  evidence: ...
  change: ...
  verification: ...
  gate: PASS | FAIL | INSUFFICIENT_EVIDENCE | NO_PROFILE
  drift: STABLE | REGRESSION | NO_BASELINE | NO_DRIFT_PROFILE

INVESTIGATE
- ...

RETIRE / CONSOLIDATE
- ...

Research performed
- candidate -> sources / finding

No automatic mutations performed.
```

If a persisted JSON report was created, include its path.

## After approval

When a user explicitly approves a PATCH proposal, hand the work back to
`capability-forge`. For repo-backed changes, prefer an isolated
`capability_forge_experiment` so the normal loop becomes:

**CREATE EXPERIMENT -> PATCH -> ISOLATED EVAL -> DOGFOOD -> DECIDE -> SNAPSHOT / ROLLBACK**

Scheduled Maintainer runs must never create, patch, snapshot, clean up, or otherwise
mutate experiments themselves. A weekly report is not success. A verified improvement
during real work is success.

## Interaction with Hermes Curator

Do not replace Curator.

Curator remains responsible for the Hermes lifecycle behavior it supports, including
stale/archive/recovery policies. This maintainer focuses on cross-surface engineering
signals that Curator cannot infer from skill usage alone, especially tool/plugin/MCP
failures seen during normal work.
