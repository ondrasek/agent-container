# Contract: Guided Setup Wizard

The wizard is an interactive CLI surface, so its "contract" is (1) the pure
recommendation-engine interface, (2) the stage → existing-probe mapping the snapshot
assembler honors, (3) the equivalent-command mapping, and (4) the interaction guarantees.
All symbols live in `bin/agent-container`.

## 1. Recommendation engine (pure — the tested core)

```
assess_stages(snapshot: EnvSnapshot) -> list[SetupStage]      # ordered, tri-state statuses
recommend_next_step(snapshot: EnvSnapshot) -> RecommendedAction # EXACTLY ONE
valid_actions(snapshot: EnvSnapshot) -> list[RecommendedAction] # the escape-hatch menu (FR-008)
```

**Guarantees** (unit-tested, no I/O):

- `recommend_next_step` returns **exactly one** action (SC-002).
- It never returns an action whose **hard** prerequisites are unmet — it returns the
  prerequisite's action instead (SC-003).
- When `snapshot.problems` is non-empty, the returned action is the **corrective** step for
  the highest-priority problem, ahead of forward progress (SC-004).
- `credentials` is soft: an unsatisfied `credentials` stage yields a
  `supply_credentials` recommendation **only when nothing hard is pending**, and never
  blocks a subsequent `start` (FR-018) — the `start` action stays in `valid_actions`.
- Every returned/listed action's `equivalent_cmd` is **secret-free** (Constitution III).
- `valid_actions` contains **only actions valid right now** — any action whose **hard**
  prerequisites are unmet is **withheld**, not shown-marked (FR-004) — and **always
  includes `quit`** (FR-015).
- Determinism: the same snapshot always yields the same recommendation (testable).

## 2. Stage → probe mapping (snapshot assembler, thin/impure)

| Stage `key` | Assessed from | `unusable` when |
|-------------|---------------|-----------------|
| `runtime` | `detect_runtime()`, `probe_host_runtime(host_rec)` | daemon reachable but erroring |
| `host` | `load_registry`/`registry_hosts`, `resolve_deploy_host` | host registered but `probe_host_runtime` ≠ None |
| `image` | `image_exists(rt, IMAGE_NAME)` | (n/a — present or absent) |
| `credentials` | `resolve_env_file(name)` + declared-key presence | (n/a) |
| `container` | `host_container_names(include_stopped=True)` | present but `Exited`/`Restarting` (from `host_ps_rows`) |
| `running` | running set + `probe_session(user, host, port)` | container up but session dead |

The assembler is bounded to the **active target's host** (FR-017); it additionally lists
the host's container inventory + orphan volumes for target-choice and broken-state detection.

## 3. Equivalent-command mapping (FR-010)

| Action `kind` | `equivalent_cmd` (example) |
|---------------|----------------------------|
| `setup_host` | `agent-container host add <name> --docker-context <ctx>` |
| `build_image` | `agent-container build` |
| `supply_credentials` | `agent-container up <name> --env-file <path>` *(references a path, never a value)* |
| `start` | `agent-container up <name> [--host <H>]` |
| `attach` | `agent-container attach <name> [--host <H>]` |
| `view_logs` | `agent-container logs <name>` |
| `recreate` | `agent-container redeploy <name>` |
| `remove` | `agent-container down <name> --purge` |
| `clean_volumes` | `agent-container purge <name>` |

No entry ever interpolates a secret (Constitution III) — credentials ride the Feature 003
injection channels, so the command names a flag/path at most.

## 4. Interaction guarantees (shell)

- **One recommendation, distinctly marked**, shown with a compact current-state summary
  every turn (FR-002/009, SC-002).
- **Escape hatch**: the operator can choose any action in `valid_actions(snapshot)` instead
  of the recommendation (FR-008, SC-007); a destructive choice confirms first (FR-011).
- **Equivalent command shown** for whatever action is taken (FR-010, SC-006).
- **Re-evaluate after every action** on a fresh snapshot (FR-005); a failed action reports
  and re-evaluates, never advances blindly (FR-012).
- **Which-one prompt** when an action could apply to several containers/hosts (FR-014).
- **No-TTY**: decline cleanly, pointing to the non-interactive commands (FR-013) — never
  hang.
- **Quit** always available; cancelling an in-progress action returns to the re-evaluated
  guided state (FR-015).
