---
name: capability-forge
description: >
  Continuously improve Hermes capabilities while doing real work. Use when a task
  reveals missing capability, repeated friction, an unreliable workflow, or an
  opportunity to create or improve a Skill, helper script, Hermes plugin/tool, or
  MCP server. Research existing solutions lightly before building, prefer reuse
  and patching over creating new components, verify changes, dogfood them on the
  current real task, and preserve useful lessons for future runs.
version: 0.3.0
metadata:
  hermes:
    tags:
      - self-improvement
      - skills
      - tools
      - mcp
      - research
      - dogfood
      - engineering
    category: autonomous-ai-agents
    related_skills:
      - capability-maintainer
---

# Capability Forge

Build capabilities only when real work demonstrates that they are useful.

The purpose is not to maximize installed tools, skills, plugins, or MCP servers.
The purpose is to reduce repeated friction, improve reliability, and make future
work easier.

## Core loop

**OBSERVE -> RESEARCH -> DECIDE -> BUILD -> VERIFY -> DOGFOOD -> LEARN -> IMPROVE**

Do not interrupt ordinary work merely to invent infrastructure.

When the `capability_forge_report` tool is available, use it before broad maintenance work or before creating a replacement for an unreliable existing capability. It provides sanitized evidence from real tool usage; treat missing telemetry as unknown, not proof of non-use.

## 1. Observe

While completing real work, notice:

- repeated commands, procedures, or research
- missing access to an external system
- recurring errors or workarounds
- repetitive result transformation
- fragile multi-step workflows
- missing validation or verification
- user corrections
- unnecessary tool calls
- incomplete or stale skills

Do not treat every inconvenience as a reason to create a capability. Prefer
evidence from actual usage.

## 2. Inspect existing capabilities first

Before creating anything:

1. inspect relevant installed skills
2. inspect available Hermes tools
3. inspect enabled plugins
4. inspect configured MCP servers
5. inspect project-local skills
6. search the Hermes skills catalog when appropriate

Prefer, in order:

1. use an existing capability unchanged
2. configure an existing capability
3. patch an existing skill
4. add a helper/reference to an existing skill
5. create a focused new skill
6. create a plugin/tool
7. create or integrate an MCP server

Do not create near-duplicate skills.

## 3. Light research

When implementation depends on technology, APIs, standards, current versions, or
community solutions, perform bounded web research before building.

Default research budget:

- official project documentation
- official repository/source
- 1-3 strong external/community sources only when they materially help

Research should answer:

- Does a good implementation already exist?
- What is the current recommended approach?
- What changed recently?
- What are common failure modes?
- Are there security or compatibility concerns?
- Is there a maintained CLI, SDK, Skill, Plugin, or MCP server to reuse?

Stop once there is enough evidence to implement safely. Do not turn small
engineering work into a literature review.

## 4. Choose the extension surface

| Need | Prefer |
| --- | --- |
| Procedure, knowledge, process | Skill |
| Existing CLI works but commands are complex | Skill + script |
| Deterministic logic or native execution | Hermes Plugin / Tool |
| Hermes lifecycle hooks | Hermes Plugin |
| External API/service with multiple operations | MCP |
| Capability shared by multiple agents/clients | MCP |
| Repo-specific workflow | Project-local skill |
| Short preference/path/fact | Memory |
| One-off task | Build nothing |

Keep reasoning and workflow in Skills. Keep deterministic mechanics in scripts or
tools. Do not wrap trivial terminal functionality in MCP.

## 5. Define success before building

Define a small set of observable criteria, for example:

- reduce a seven-step workflow to two steps
- eliminate a known recurring error
- produce structured deterministic output
- handle three representative tasks successfully
- expose only MCP operations required by the workflow
- cause no regression in ordinary Hermes usage

Avoid criteria such as "smarter" or "better".

## 6. Build the minimum useful version

Implement the smallest version that solves the current real problem. Prefer:

- focused interfaces
- narrow permissions
- small schemas
- explicit errors
- idempotent operations where practical
- timeouts for external operations
- structured outputs
- simple dependencies

Never put secrets in skill files or source code.

## 7. Verify

### Skill

Check trigger specificity, self-contained workflow, valid commands/paths,
references, failure cases, and verification instructions. Run representative
prompts when practical.

### Plugin / Tool

Check input validation, error handling, timeout behavior, missing configuration,
safe defaults, and basic tests.

### MCP

Check tool naming/descriptions, minimal schemas, validation, actionable failures,
permissions, destructive-operation separation, and representative multi-tool
workflows.

## 8. Dogfood on real work

After isolated verification, resume the original task and use the capability
normally. Observe:

- correct selection timing
- unnecessary calls
- argument quality
- output usefulness
- work reduction
- latency
- new failure modes
- user corrections

If it is worse than the previous approach, revert or disable it.

## 9. Learn during use

When real usage reveals a reusable lesson:

- patch Skills for procedural improvements
- update references when external behavior changes
- improve scripts for deterministic failures
- improve tool schemas/descriptions when selection is poor
- improve MCP boundaries when workflows require unnecessary calls

Prefer targeted patches. Do not encode one-off accidents as permanent rules.

## 10. Register ownership and evals

When a capability becomes reusable, add it to the explicit capability registry at
`~/.hermes/capability-lab/capabilities.json` (or `CAPABILITY_FORGE_REGISTRY`).
Record its stable id, kind, source, exact tool names or narrow tool prefixes, and
related skills. Never guess ownership from a vague name when multiple components
could match.

Create a capability-specific eval profile in
`~/.hermes/capability-lab/evals.json` (or `CAPABILITY_FORGE_EVALS`) before treating
telemetry as a promotion gate. Define observable thresholds such as minimum calls,
maximum error/retry/unknown rates, latency, success rate, and drift tolerances.

## 11. Promotion gate and baseline

Before promoting a changed capability:

1. dogfood it on representative real work
2. call `capability_forge_gate(action="evaluate", capability_id=...)`
3. require `PASS`; `NO_PROFILE` and `INSUFFICIENT_EVIDENCE` are not passes
4. compare against the prior baseline when one exists
5. investigate any `REGRESSION`
6. after a trusted passing window, record the baseline with
   `capability_forge_gate(action="record_baseline", capability_id=...)`

Do not lower eval thresholds merely to make a failing change pass.

## 12. Guarded repair

`capability_forge_patch` is optional and must remain disabled unless the user has
explicitly configured `CAPABILITY_FORGE_PATCH_ROOTS` and set
`CAPABILITY_FORGE_ALLOW_PATCH=1`.

Use it only for a narrow exact-text repair after evidence and an eval plan exist:

1. obtain the current SHA-256
2. `preview` the exact one-match replacement
3. verify the target capability and expected effect
4. `apply` only in an interactive/foreground workflow with explicit patch policy
5. run tests and dogfood
6. run the promotion gate
7. `rollback` by patch id if validation regresses or the target changed unexpectedly

Scheduled maintainer runs must stay proposal-first and must not apply patches.

## 13. Maintenance and retirement

Periodically review active capabilities for upstream changes, recurring failures,
broken references, usage, overlap, and baseline drift. Research maintenance changes
only when active evidence justifies it. Avoid churn simply because a newer version
exists.

Archive or consolidate capabilities that are superseded, unused, duplicated,
dependent on abandoned software, or consistently more complex than valuable.
Preserve reusable lessons first.

## Operating principle

**Real work is the benchmark.**

Research informs implementation. Tests establish a baseline. Dogfooding discovers
reality. Usage evidence decides what survives.
