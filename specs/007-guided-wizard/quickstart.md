# Quickstart: Guided Setup Wizard

Validation journeys that prove the state-aware guide works end-to-end. Run the wizard with
no arguments (`agent-container`) at an interactive terminal. Each scenario maps to success
criteria in [spec.md](./spec.md); the engine assertions are covered hermetically in
`bin/tests/test_guided_wizard.py` and referenced here as the observable behavior.

## Prerequisites

- A working local container runtime (docker or podman) for the live journeys.
- The unit tier needs neither a runtime nor a TTY (the engine is pure).

## Scenario A — Zero to attached, guided the whole way (US1 / SC-001, SC-002)

```bash
# On a machine with no host registered, no image built, no container:
agent-container            # launches the guided wizard
```

**Expected**: each turn shows a compact state summary and **one** clearly-marked
recommendation with a reason; following only the recommendations walks
`choose/confirm local host → build image → (supply credentials, optional) → name + start
container → attach` and lands in a running session. At no step must the operator guess
which of several options applies.

## Scenario B — Credentials are a soft step, not a gate (FR-018)

```bash
# host + image ready, no credentials present:
agent-container
```

**Expected**: the wizard recommends supplying credentials **and** still offers `start`
(the recommendation is marked, but `start` remains a valid choice); starting a local
interactive agent succeeds and the agent can authenticate inside the session.

## Scenario C — First-container naming (FR-019)

**Expected**: when no container exists, the wizard offers a **default name** to accept or
edit before starting; when exactly one container already exists on the active host, the
wizard targets it instead of prompting for a new name.

## Scenario D — Adapts to a healthy environment (US2 / SC-002)

```bash
# with at least one running container:
agent-container
```

**Expected**: the recommended next step is a day-to-day action (attach), not a setup step;
with multiple running containers the wizard prompts which one (FR-014).

## Scenario E — Detects and guides out of broken states (US3 / SC-004)

For each: runtime unreachable, container exited/crash-looping, missing credential, orphaned
volumes — **Expected**: the wizard **names the specific problem** and recommends the
corrective step (fix connectivity / view logs → recreate|remove / supply credential / clean
volumes) with a reason, instead of offering unrelated actions as if normal.

## Scenario F — Always explains, never traps (US4 / SC-006, SC-007)

**Expected**: every turn shows the state summary + the marked recommendation; the operator
can still pick any currently-valid action (destructive ones confirm first); and the
**equivalent non-interactive command** is shown for whatever action is taken — and never
contains a secret value.

## Scenario G — No interactive terminal (FR-013)

```bash
echo | agent-container      # or run under a non-TTY
```

**Expected**: the wizard declines cleanly with a message pointing to the non-interactive
subcommands (`agent-container --help`) and a non-zero status — it never hangs or crashes.

## Success signal

All scenarios pass: a first-time operator reaches an attached session by following
recommendations alone; the wizard leads with exactly one reasoned recommendation scoped to
a single active target; it never presents an unmet-prerequisite action as ready; it names
broken states and guides out of them; it always shows a secret-free equivalent command and
never hides a valid choice — matching SC-001…SC-007.
