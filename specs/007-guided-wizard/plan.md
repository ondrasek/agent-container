# Implementation Plan: Guided Setup Wizard (state-aware next-step guidance)

**Branch**: `007-guided-wizard` | **Date**: 2026-07-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/007-guided-wizard/spec.md`

## Summary

Replace the wizard's flat menu of every action with a **state-aware guide**: on each
turn it assembles a snapshot of the setup journey **for a single active target** (one
host + one container identity), computes the **single most useful next step**, and leads
with that recommendation plus a plain-language reason — while still letting the operator
pick any action valid right now and always showing the equivalent non-interactive
command.

The technical approach is a **pure recommendation engine** (a snapshot → recommendation
function with no I/O) driving a **thin interactive shell**. The engine is where every
load-bearing rule lives (exactly one recommendation; never an unmet-prerequisite action;
broken-state detection; soft-vs-hard stages), so it is unit-testable without a TTY
(Constitution V). The shell only gathers the snapshot by calling the tool's **existing
probes** and performs the chosen action through the tool's **existing operations** — this
feature introduces no new underlying capability and no new dependency.

## Technical Context

**Language/Version**: Python ≥ 3.14 — the single-file PEP 723 script `bin/agent-container`.

**Primary Dependencies**: Typer, questionary, rich (all already present). **No new
dependency** (Constitution VI) — managers/probes are existing internal functions.

**Storage**: None new. Reads the existing host registry (`hosts.json`) and per-host
`*.port` state; assembles an in-memory snapshot only.

**Testing**: pytest hermetic unit tests for the recommendation engine and stage assessors
(new `bin/tests/test_guided_wizard.py`); the interactive shell's non-interactive guard and
rendering via a scripted-stdin / captured-output test; real-container acceptance for the
zero-to-attached journey where practical.

**Target Platform**: the operator's host (macOS + Linux) at an **interactive terminal**;
guided mode is TTY-only (FR-013).

**Project Type**: single CLI tool (interactive wizard + subcommands in one script).

**Performance Goals**: the state assessment for the active target is **bounded** —
scoped to one host, reusing the fail-closed, time-bounded probes (`host_ps_rows` already
caps at 20 s); the wizard does **not** probe every registered host each run (FR-017), so a
turn is responsive even with many hosts registered.

**Constraints**: TTY-only guided mode (FR-013); **no secret value in any shown equivalent
command** (Constitution III); reuse existing operations only — no new underlying op
(Assumption); the recommendation is advisory, never a forced path (FR-008).

**Scale/Scope**: single operator; a handful of hosts and containers; a fixed, ordered set
of ~6 setup stages.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|-----------|-----------|
| **I — Ephemerality & Commit-Push** | Unaffected. The wizard orchestrates existing ops (which already commit/push inside the container); it stores no new durable state. ✅ |
| **II — Least Privilege / Immutable Runtime** | Host-side CLI only; touches neither the image nor the container's runtime privileges; no runtime apt. ✅ |
| **III — Least Exposure** | **Gate**: FR-010 shows the equivalent command for each action — it MUST NEVER contain a secret value (credentials ride the 003 injection channels, never argv). The engine emits only secret-free command strings. ✅ (enforced by design + a test) |
| **IV — Deterministic Identity** | The wizard's container naming (FR-019) uses the same `container_name`/identity the rest of the tool computes — one source of truth, no parallel scheme. ✅ |
| **V — Hermetic, Contract-Pinned Testing** | The pure engine makes the load-bearing logic (SC-002/003/004) unit-testable with an injected snapshot — no TTY, no daemon. The interactive shell gets a thin guard/render test + acceptance. ✅ (this split is the plan's central decision) |
| **VI — Least Dependencies** | No new third-party dependency; reuses Typer/questionary/rich and existing probes. ✅ |
| **VII — Continuous Deployment** | A `feat` merge auto-releases via Conventional Commits; the quality gate blocks a broken merge. ✅ |

**Result**: PASS — no violations, no Complexity Tracking entries required. The single
design gate (III — no secret in a shown command) is a design constraint, not a deviation.

## Project Structure

### Documentation (this feature)

```text
specs/007-guided-wizard/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions (engine/shell split, stage→probe map, testing)
├── data-model.md        # Phase 1 — SetupStage, StageStatus, EnvSnapshot, RecommendedAction, …
├── quickstart.md        # Phase 1 — validation scenarios (zero-to-attached, healthy, broken, no-TTY)
├── contracts/
│   └── guided-wizard.md  # Phase 1 — the recommendation-engine contract + stage→probe + equiv-command map
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

All implementation lands in the existing single-file CLI and its test suite — matching the
project's architecture (one PEP 723 script; no new module layout):

```text
bin/agent-container            # the recommendation engine (new pure functions) + rewritten
                               #   wizard_loop shell; reuses existing action handlers
                               #   (wizard_start/attach/logs/stop/purge) and probes
                               #   (probe_host_runtime, image_exists, resolve_env_file,
                               #    host_ps_rows, probe_session, resolve_deploy_host)
bin/tests/test_guided_wizard.py   # NEW — hermetic unit tests for the engine + stage assessors
bin/tests/test_acceptance.py      # additions — zero-to-attached / no-TTY guard (where practical)
```

**Structure Decision**: Single-file CLI (no `src/` tree — the tool is one script by
decision, see CLAUDE.md). The feature adds a cohesive **pure block** (snapshot dataclasses +
`assess_stages` + `recommend_next_step`) and **rewrites `wizard_loop`** to gather → render →
act → re-evaluate. Existing per-action handlers (`wizard_start`, `wizard_attach`, …) are
reused as the "perform" step, so the diff is additive over proven code.

## Complexity Tracking

> No Constitution Check violations — this section is intentionally empty.

## Phase notes

- **Phase 0 (research.md)** — resolve the plan-level unknowns: the engine/shell split; the
  exact **stage → existing-probe** mapping; the ordered stage list and hard-vs-soft
  classification (credentials soft, FR-018); the broken-state taxonomy → probe mapping;
  active-target resolution (FR-017) and first-container naming (FR-019); and **how to test
  an interactive wizard** hermetically.
- **Phase 1 (data-model, contracts, quickstart)** — the snapshot/recommendation data model;
  the recommendation-engine contract (inputs, the single-recommendation guarantee, the
  equivalent-command mapping, the escape-hatch listing of currently-valid actions); and the
  quickstart validation journeys mapped to SC-001…SC-007.
- **Agent context update** — no `update-agent-context` script exists in this repo; skipped.
