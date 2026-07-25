# Research: Guided Setup Wizard (Phase 0)

Decisions that resolve the plan's unknowns. Every stage detection and every action reuses
an **existing** internal — this feature adds a decision layer, not new capability.

## R1 — Pure recommendation engine vs interactive shell (the central split)

- **Decision**: Separate a **pure** `recommend_next_step(snapshot) -> RecommendedAction`
  (plus `assess_stages(snapshot)`) that does **no I/O**, from the interactive
  `wizard_loop` shell that (1) assembles the snapshot by calling existing probes, (2)
  renders the state summary + recommendation, (3) performs the chosen action via existing
  handlers, (4) re-evaluates.
- **Rationale**: The load-bearing rules — exactly one recommendation (SC-002), never an
  unmet-prerequisite action (SC-003), broken-state detection (SC-004), the zero-state
  journey order (SC-001), soft-vs-hard stages (FR-018) — become unit-testable with an
  injected snapshot dataclass, no TTY and no daemon (Constitution V). The shell shrinks to
  glue over proven code.
- **Alternatives rejected**: Keep the logic inline in `wizard_loop` (today's shape) — then
  every rule is only reachable through an interactive `questionary` prompt, which is
  painful to test and exactly why the current menu is hard to reason about.

## R2 — Setup stages, order, and hard-vs-soft classification

- **Decision**: A fixed ordered stage list, each assessed to *satisfied /
  unsatisfied / present-but-unusable*:

  | # | Stage | Existing probe | Hard? |
  |---|-------|----------------|-------|
  | 1 | runtime reachable | `detect_runtime()` + `probe_host_runtime(host)` (None ⇒ usable) | hard |
  | 2 | host available (active target chosen) | `load_registry`/`registry_hosts` + `resolve_deploy_host` (implicit local default) | hard |
  | 3 | image available | `image_exists(rt, IMAGE_NAME)` on the active host | hard |
  | 4 | credentials/config present | `resolve_env_file(name)` + declared key presence | **soft** (FR-018) |
  | 5 | container created | `container_name(name) ∈ host_container_names(include_stopped=True)` | hard |
  | 6 | container running / attachable | running set + `probe_session` | hard (goal) |

- **Rationale**: The order is the tool's real prerequisite chain (FR-016). Stage 4 is
  **soft** (FR-018): missing credentials produce a *recommendation* to supply them but do
  **not** block advancing to "start" — a local interactive agent can authenticate inside
  the session. All others are hard gates.
- **Note on stage 3**: `up` can build on demand via compose `--build`, but a silent
  multi-minute build on first start is confusing, so an absent image yields an explicit
  **build** recommendation (matches US1 scenario 2). Documented as a deliberate choice.
- **Alternatives rejected**: Treating credentials as a hard gate (blocks the common local
  first-run that needs no key — rejected in clarification); a dynamic/derived stage set
  (unnecessary — the chain is fixed).

## R3 — Active-target resolution (FR-017) and first-container naming (FR-019)

- **Decision**: The active target = **(host, container-name)**. Host resolves via
  `resolve_deploy_host(selected or default)` — registry default, else the implicit local
  host; if **more than one** registered host and none selected, the shell prompts to pick
  (never guesses). Container name: if **exactly one** container exists on the active host,
  target it; otherwise offer a **default name** the operator accepts or edits.
- **Rationale**: A single active target gives one clear journey and **bounds probing to
  one host** (FR-017 perf). Naming reuses the tool's deterministic identity (`container_name`,
  Constitution IV). Prompting only on genuine ambiguity keeps the fast path fast.
- **Alternatives rejected**: Global assessment across all hosts each run (fuzzy "best step
  anywhere"; N remote probes per turn); a silent fixed container name (hides the
  identity everything keys off).

## R4 — Broken/partial-state taxonomy → probe mapping (FR-007, US3)

- **Decision**: Detect each broken state from an existing signal and map to a corrective
  recommendation:

  | Broken state | Signal | Corrective recommendation |
  |--------------|--------|---------------------------|
  | runtime unreachable | `probe_host_runtime` error / `ensure_tunnel` fails | fix connectivity (before any container action) |
  | container exited / crash-looping | `host_ps_rows` status contains `Exited` / `Restarting` | view logs → recreate or remove |
  | missing credential (regressed) | stage-4 absent for an agent that needs it | supply the credential |
  | orphaned volumes | `per_container_volumes` present with no container (the wizard's existing orphan scan) | clean up (with an explanation of what they are) |

- **Rationale**: "present-but-unusable" is distinct from "absent" (Edge Case), so the
  engine must carry a tri-state per stage, not a boolean. Every signal already exists;
  the engine only classifies.
- **Alternatives rejected**: A generic "something's wrong" catch-all (the whole point is to
  **name** the specific fault, SC-004).

## R5 — Equivalent non-interactive command, secret-free (FR-010, Constitution III)

- **Decision**: Each `RecommendedAction` carries an `equivalent_cmd` string built from the
  same argv the tool would run, **with no secret ever interpolated** — credentials travel
  the Feature 003 injection channels, never argv, so the shown command references a
  file/flag, never a value. Reuse the existing `hint(...)` rendering.
- **Rationale**: Least Exposure is a hard gate; the command is a teaching aid, not a
  transport. A unit test asserts no shown command contains a resolved secret.
- **Alternatives rejected**: Echoing the literal executed command (could embed a value on a
  future code path) — instead the engine composes the command from safe, known parts.

## R6 — Testing an interactive wizard (Constitution V)

- **Decision**: Three tiers.
  1. **Hermetic unit** (`test_guided_wizard.py`): construct `EnvSnapshot` fixtures and
     assert `recommend_next_step` — exactly one recommendation (SC-002), never an
     unmet-prereq action (SC-003), each broken state → its corrective (SC-004), the full
     zero→attached ordering (SC-001), soft-credentials-does-not-gate-start (FR-018),
     naming reuse (FR-019), and secret-free `equivalent_cmd` (III).
  2. **Shell guard/render**: assert the no-TTY path declines cleanly pointing to
     subcommands (FR-013), and that a turn renders the state summary + a single marked
     recommendation (captured output).
  3. **Acceptance** (where practical): drive the zero-to-attached journey against a real
     local runtime via scripted input; otherwise rely on tier 1 + the existing per-action
     acceptance tests for the underlying ops.
- **Rationale**: Pushing the logic into a pure function is what makes the wizard testable
  at all; the interactive surface is intentionally thin.
- **Alternatives rejected**: Only acceptance-testing the whole TUI (brittle, slow, and
  leaves the rule logic unverified in isolation).

## R7 — Reuse of existing action handlers

- **Decision**: The "perform" step calls the existing wizard handlers (`wizard_start`,
  `wizard_attach`, `wizard_logs`, `wizard_stop`, the orphan-purge path) rather than new
  code; the engine only decides *which* to recommend and supplies the target.
- **Rationale**: Additive over proven, already-acceptance-tested operations; keeps the
  feature to a decision layer (Assumption: reuse existing capabilities).
- **Alternatives rejected**: Reimplementing the actions inside the guided flow (needless
  duplication and risk).
