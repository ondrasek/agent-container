# Data Model: Guided Setup Wizard (Phase 1)

In-memory only — assembled each turn, never persisted (Constitution IV: the registry and
the running containers remain the single source of truth). All types are plain dataclasses
in `bin/agent-container`.

## StageStatus (enum)

The tri-state a stage can be in — **"present-but-unusable" is distinct from "absent"**
(Edge Case: a host exists but is unreachable; an image exists but is stale):

| Value | Meaning |
|-------|---------|
| `satisfied` | the stage's prerequisite is met and usable |
| `unsatisfied` | absent — the prerequisite does not exist yet |
| `unusable` | present but not usable (e.g. host registered but unreachable; container present but exited) |

## SetupStage

A milestone on the path to a working environment. Fixed, ordered set (R2):

| Field | Type | Notes |
|-------|------|-------|
| `key` | str | one of `runtime`, `host`, `image`, `credentials`, `container`, `running` |
| `status` | StageStatus | assessed from the active target's probes |
| `hard` | bool | `credentials` is **soft** (FR-018); all others hard |
| `detail` | str | plain-language note (e.g. "host 'vps' is unreachable") |

**Ordering / validation**: the stage list order **is** the tool's prerequisite chain
(FR-016). The engine walks it in order; a later stage is only reachable once the earlier
**hard** stages are `satisfied`.

## ActiveTarget

The single (host, container) the wizard guides toward (FR-017):

| Field | Type | Notes |
|-------|------|-------|
| `host_name` | str | resolved via `resolve_deploy_host` (implicit local default) |
| `host_rec` | dict | the registry record for the host |
| `container_name` | str \| None | the short name; None until chosen/defaulted (FR-019) |
| `ambiguous_host` | bool | >1 registered host and none selected → the shell must prompt |

## EnvSnapshot

The wizard's assessment at a moment — the **sole input** to the recommendation engine
(so the engine is pure and testable):

| Field | Type | Notes |
|-------|------|-------|
| `target` | ActiveTarget | what is being guided |
| `stages` | list[SetupStage] | the ordered, assessed stage list |
| `containers` | list[tuple] | (name, status) inventory on the active host — for "which one" + broken detection |
| `orphan_volumes` | list[str] | volumes with no owning container |
| `problems` | list[str] | detected broken states (R4), each a named fault |

**Scope**: bounded to the active target's host (FR-017) plus the light inventory needed to
choose a target and to detect broken states — never a probe of every registered host.

## RecommendedAction

The single best next step for a snapshot (SC-002 — exactly one):

| Field | Type | Notes |
|-------|------|-------|
| `kind` | str | `choose_host`, `setup_host`, `build_image`, `supply_credentials`, `name_container`, `start`, `attach`, `view_logs`, `recreate`, `remove`, `clean_volumes`, `fix_runtime`, `quit` |
| `reason` | str | plain-language "why this step, now" (FR-003) |
| `target` | ActiveTarget | host/container it applies to |
| `destructive` | bool | triggers a confirm (FR-011) |
| `soft` | bool | a recommendation the operator may skip without being blocked (e.g. supply_credentials, FR-018) |
| `equivalent_cmd` | str | the secret-free non-interactive command (FR-010, Constitution III) |

**Validation rules**:
- Exactly one `RecommendedAction` is returned per snapshot (SC-002).
- Its `kind` never corresponds to an action whose **hard** prerequisites are unmet
  (SC-003) — the engine recommends the *prerequisite's* action instead.
- A `problem` present ⇒ the recommendation is the corrective action for it (SC-004),
  taking precedence over forward progress.
- `equivalent_cmd` MUST NOT contain a resolved secret value (Constitution III).

## ActionOutcome

The result of performing an action — triggers re-evaluation:

| Field | Type | Notes |
|-------|------|-------|
| `ok` | bool | success/failure |
| `message` | str | shown to the operator; a failure never advances blindly (FR-012) |

## State transitions (engine)

```
assess_stages(snapshot)
      │
      ▼
 first HARD stage not `satisfied`?  ──yes──▶ recommend that stage's action
      │ no                                     (choose_host / setup_host / build_image /
      ▼                                          name_container / start …)
 any `problem` (broken state)?     ──yes──▶ recommend its corrective (fix_runtime /
      │ no                                     view_logs / recreate / clean_volumes …)
      ▼
 container running?                ──yes──▶ recommend `attach` (day-to-day, US2)
      │ no
      ▼
 recommend `start`  (soft: note missing credentials but do not gate)
```

The shell renders the state summary + this single recommendation, lets the operator pick
any currently-valid action instead (FR-008), performs it, then re-runs `assess_stages` on a
fresh snapshot (FR-005) — never on stale state (Edge Case).
