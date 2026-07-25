# Implementation Plan: Agent-Operable CLI

**Branch**: `009-agent-operable-cli` | **Date**: 2026-07-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/009-agent-operable-cli/spec.md`

## Summary

Make the CLI drivable by an AI agent: a **`--json` flag on every command** emitting a
**versioned** structured payload, **failures carrying a stable code + entity + remediation**,
a **`context`** command that serializes the tool's view of the world in one call, and a
**`skill`** command that installs/updates/removes an **Agent Skills**-conformant definition
into any of four agents' configurations.

Three facts about the existing code make this far smaller than it sounds:

1. **Errors already funnel through one chokepoint.** Every failure is `die()` → `Fatal` →
   caught in `cli()`. Adding a code and a JSON rendering is a **single-site** change, not a
   sweep of ~100 `die()` call sites — those gain codes incrementally.
2. **`context` is mostly already written.** Feature 007's recommendation engine
   (`build_snapshot` → `assess_stages` → `recommend_next_step`/`valid_actions`) is **pure**
   and already computes exactly what FR-009 asks for: hosts, environment state, and the
   suggested next step. `context` is a **serializer over existing pure functions**, not new
   assessment logic.
3. **`--json` has a precedent** on 3 of 23 commands. The work is extending a convention, and
   centralizing *emission* so 23 commands don't hand-roll 23 payloads.

The two genuinely new artifacts are the **failure descriptor** and the **skill installer**.

## Technical Context

**Language/Version**: Python ≥ 3.14 — the single-file PEP 723 script `bin/agent-container`.

**Primary Dependencies**: Typer, questionary, rich, PyYAML (all present). **No new
dependency** — the skill format is plain Markdown + YAML frontmatter, and PyYAML is already
in use for Feature 006.

**Storage**: None new for the tool. The `skill` command **writes outside the tool's own
state** — into a project's or the user's agent configuration — which is this feature's only
external side effect and the reason FR-014/FR-015 (no clobber, no residue) exist.

**Testing**: pytest hermetic units for the payload envelope, the failure descriptor, the
context serializer (feed it a constructed snapshot — the 007 engine is pure, so no daemon),
and the skill installer (install/idempotent-reinstall/drift-refusal/remove against a scratch
config tree); plus a real-invocation test that `--json` output parses and that a failing
command emits a parseable failure.

**Target Platform**: the operator's host (macOS + Linux). Host-side CLI only — the container
image and entrypoint are untouched.

**Project Type**: single CLI tool.

**Performance Goals**: `context` must stay responsive — it inherits Feature 007's
**bounded, single-active-target probing**, so it does not enumerate every registered host's
daemon on each call.

**Constraints**:
- **No secret value in any machine-readable output** (Constitution III) — `context` emits
  **locators only**. This is the load-bearing gate.
- **Never block on a prompt** when non-interactive (FR-007) — generalize the existing
  `-y`-or-refuse behavior already used by `down`/`wipe`/`host rm --destroy`.
- **Additive**: interactive human behavior, the wizard, and existing prose are unchanged
  (FR-019); `--json` is opt-in per invocation (FR-001).
- The **Feature 005 eval contract** must not be broken — see the scoping decision in R3.

**Scale/Scope**: 23 commands gain a flag; 2 new commands; 4 agent targets sharing **one**
skill definition.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|-----------|-----------|
| **I — Ephemerality & Commit-Push** | Unaffected; no durable tool state added. ✅ |
| **II — Least Privilege / Immutable Runtime** | Host-side only; image and entrypoint untouched. The `skill` command writes to agent config — scoped, reported, removable. ✅ |
| **III — Least Exposure** | **The gate.** `context` describes credential state as **locators only**; no machine-readable payload may carry a secret value. Enforced by design + an explicit test. ✅ |
| **IV — Deterministic Identity** | `context` reports the same identities the tool computes; no parallel naming scheme. ✅ |
| **V — Hermetic, Contract-Pinned Testing** | The payload envelope, failure descriptor and context serializer are pure/serializable; the 007 engine is already pure, so `context` is testable from a constructed snapshot with no daemon. ✅ |
| **VI — Least Dependencies** | **No new dependency** — Markdown + YAML frontmatter, PyYAML already present. ✅ |
| **VII — Continuous Deployment** | A `feat` merge auto-releases. The versioned payload (FR-006) is what keeps that safe for agent consumers. ✅ |

**Result**: PASS — no violations, no Complexity Tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/009-agent-operable-cli/
├── plan.md              # This file
├── research.md          # Phase 0 — 7 decisions
├── data-model.md        # Phase 1 — envelope, failure descriptor, context payload, skill artifact
├── quickstart.md        # Phase 1 — validation scenarios per user story
├── contracts/
│   └── agent-interface.md   # Phase 1 — the JSON envelope, failure contract, context schema, skill CLI
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
bin/agent-container            # the JSON envelope + emit helper; die() gains an optional
                               #   code; cli() renders a failure descriptor in --json mode;
                               #   --json added to the remaining commands; `context` (a
                               #   serializer over the 007 engine); `skill` install/update/
                               #   remove; machine-readable help
bin/tests/test_agent_interface.py   # NEW — envelope, failure descriptor, context serializer,
                                    #   skill installer (hermetic; scratch config tree)
docs/agent-interface.md        # NEW — how an agent drives the tool; the skill; the taxonomy
README.md / CLAUDE.md          # the new surface, in budget
```

**Structure Decision**: Single-file CLI (the tool is one PEP 723 script by decision). The
skill's `SKILL.md` body is an **embedded template constant**, not a data file — that keeps
`uv run --script bin/agent-container` working standalone, which a `force-include` package
asset would not (see R6).

## Complexity Tracking

> No Constitution Check violations — intentionally empty.

## Phase notes

- **Phase 0 (research.md)** — the versioned envelope shape; how `--json` reaches 23 commands
  without 23 hand-rolled payloads; **scoping the Feature 005 eval contract vs structured
  errors** (the one real tension); the failure-code taxonomy and how `die()` gains codes
  incrementally; `context` as a serializer over the 007 engine; where the skill template
  lives; and drift detection that cannot clobber operator edits.
- **Phase 1 (data-model, contracts, quickstart)** — the envelope, failure descriptor, context
  payload and skill artifact; the agent-facing contract; validation journeys per story.
- **Agent context update** — no `update-agent-context` script exists in this repo; skipped.
