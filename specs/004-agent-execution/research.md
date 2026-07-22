# Research: Agent Execution & Session Management (Feature 004)

Decisions resolving the plan's unknowns. This feature **inherits** from Features
001/002 the host/compose run mechanism, the `workspace` volume identity, and
restart-on-crash; from Feature 003 the git credentials (SSH push key +
`GH_TOKEN`) and injected-material seam (`build_compose_model`'s `injected_configs`).
It does not redefine those.

**Ground truth (verified):** today the container runs sshd + a detached tmux
session `main` whose windows are **bare shells** — no agent is auto-launched, no
clone-on-start exists, the workspace is a single **persistent** named volume,
`restart: unless-stopped` is hardcoded, and attach only *heuristically* infers a
dead session (the wizard, via exit code) with no explicit `tmux has-session`
probe. So execution mode, agent launch, headless, workspace modes, and
clone-on-start are all **net-new**.

---

## R1 — Execution mode: one entrypoint, branch on an env flag; restart policy per mode

**Decision**: A deploy-time `--mode interactive|headless` (default **interactive**)
sets `AGENT_CONTAINER_MODE`, which the entrypoint branches on:
- **interactive** (today's shape + the agent): sshd + tmux `main`, and the chosen
  agent is launched in a dedicated tmux window (US1), optionally seeded with an
  initial task; PID 1 stays alive; `restart: unless-stopped` (kept alive/restarted,
  FR-001/005).
- **headless**: the chosen agent runs as PID 1's **workload** (non-interactive),
  the container **exits with the agent's exit code** (FR-002), and
  `restart: on-failure` — a success terminates and is **not** resurrected, a
  failure follows the deployment's restart policy (FR-002/005, edge cases).

`build_compose_model` gains a `restart` parameter (today a hardcoded literal).

**Rationale**: one image, one entrypoint, branch by env — reuses the existing
`exec "$@"` override seam without a second headless image. `restart: on-failure`
is compose's exact match for "success exits, failure retries."

**Alternatives rejected**: (a) a separate headless entrypoint/image — more moving
parts, duplicate boot logic; (b) a compose `command:` override per mode — works,
but keeping the flow in the single entrypoint (env-branched) preserves one source
of truth for startup.

**Validation**: unit (the compose model carries the mode env + the per-mode
`restart`); entrypoint shell test (the mode branch runs the agent-as-workload vs
sshd+tmux); acceptance (headless exits with the agent's code and is not
auto-restarted; interactive keeps running).

---

## R2 — Agent selection + per-agent invocation map

**Decision**: `--agent claude|codex|pi` (default **claude**, the flagship) names
the single primary agent for the deployment. The entrypoint holds a small
per-agent invocation map:
- **interactive**: launch the agent in the tmux window (e.g. `claude`), optionally
  passing the seeded initial task.
- **headless**: run the agent's non-interactive form with the task (e.g.
  `claude -p "<task>"`, `codex exec "<task>"`, pi's non-interactive form).

`--task <text|@file>` (US1 initial task / US3 headless task) is delivered as an
**injected file** (003's `injected_configs` channel) so it never rides argv/env
and has no size limit; the entrypoint reads it.

**Rationale**: the tool must know *which* agent to run and *how* to invoke it
interactively vs headlessly — a per-agent map in the entrypoint is the minimal
mechanism. One primary agent per deployment matches the spec assumption (the
operator may still launch more processes manually in an interactive session).

**Alternatives rejected**: (a) auto-detect the agent — ambiguous; (b) run all
three — nonsensical; (c) task on argv — leaks into the process table / size caps.

**Validation**: unit (the invocation map resolves per agent/mode); entrypoint
shell test (the right agent command is built with the task); acceptance for the
real agent *responding* is opt-in/tokened (needs a model key — SC-001/US3).

---

## R3 — Workspace modes: what is mounted at `/workspace`

**Decision**: `--workspace persistent|bind|ephemeral` (default **persistent**)
selects what is mounted at `/workspace`:
- **persistent**: the named `agent-container-<name>-workspace` volume (today's
  behavior; survives recreation — FR-012).
- **bind**: `<local-abs-dir>:/workspace`, **local hosts only** — refused with a
  clear message on a non-local host (FR-011), reusing `resolve_bind_mount`'s
  local-path validation.
- **ephemeral**: **nothing** mounted at `/workspace` → the container's own
  writable layer, freshly populated on start and **gone on teardown** (FR-013).

**Identity nuance (Constitution IV)**: the workspace named volume exists **only**
in persistent mode; the other six per-container volumes (claude/codex/pi/shellenv/
tmux/ssh) are unchanged. `--purge`/`wipe` tolerate the workspace volume's absence.
Existing (pre-004) deployments are persistent by default, so their identity is
unchanged — no migration needed.

**Rationale**: the mode is purely *what mounts at `/workspace`*; the container's
own layer is the simplest **true**-ephemeral (disk-backed, no RAM cap, vanishes
with the container) and needs no new volume machinery.

**Alternatives rejected**: (a) `tmpfs` for ephemeral — RAM-bound, a large clone
could exhaust memory; (b) an anonymous volume — only removed with the right
`down` flags, less predictable than the container layer.

**Validation**: unit (the compose model mounts the right thing per mode; bind on a
non-local host is refused); acceptance (persistent survives recreate; bind edits
appear on the local FS and remote-bind is refused; ephemeral is gone after
teardown).

---

## R4 — Clone-on-start: layered credential chosen by URL scheme (operator-confirmed)

**Decision**: `--repo <url>` configures clone-on-start for **persistent/ephemeral**
workspaces (a **bind** workspace is already present and is never cloned). On start,
if `/workspace` has no working copy yet and a repo is configured, the entrypoint
clones it, choosing the credential by **URL scheme** (both wired by Feature 003):
- `git@github.com:…` (SSH) → the injected **SSH push key** via `core.sshCommand`;
  if an SSH URL is configured but **no push key is injected**, the deploy **fails
  fast** before starting an empty-workspace agent (FR-014).
- `https://github.com/…` → **`GH_TOKEN`** (a required env, always present).

Idempotent: skip the clone if `/workspace` already holds a working copy (a
persistent recreate does not re-clone over local state).

**Rationale**: `GH_TOKEN` is always required/present and Feature 003 kept HTTPS a
first-class layered channel — so clone-by-URL-scheme is the natural fit and never
forces an SSH key when HTTPS works. Confirmed with the operator.

**Alternatives rejected**: (a) push-key-only (spec-literal) — forces an SSH key
even for HTTPS repos; (b) HTTPS-only — ignores the SSH-first design and the SSH
repos operators use.

**Validation**: acceptance — an SSH-URL clone with no push key fails fast (SC-008);
an HTTPS-URL clone populates `/workspace` on start (SC-008); a persistent recreate
does not clobber local state.

---

## R5 — Headless foreground vs detached; result = exit code + logs

**Decision**: headless launches **detached by default** (`up` returns immediately;
the container runs the agent and exits with its code — FR-004 detached). The
result is the **container exit code** (FR-002 — success/failure distinguishable)
plus `logs` output, both retrievable afterward; `list` surfaces the exited
status/code. A **foreground** launch (`up --foreground`) streams the compose run
and returns control on completion (FR-004 foreground).

**Rationale**: the container's exit code *is* the agent result; compose `logs` are
always available regardless of sshd; foreground is just compose up run attached.

**Alternatives rejected**: a separate result file — redundant with the exit code +
logs, and another thing to clean up.

**Validation**: acceptance — a foreground headless run streams and returns on
completion; a detached one returns immediately and its output/result are
retrievable; success is not auto-restarted, failure is distinguishable (SC-004/005).

---

## R6 — Detach/reattach + an explicit dead-session report (FR-008)

**Decision**: detach/reattach is **inherited** — detach = disconnect (tmux `main`
survives), reattach = SSH back to the canonical session from any machine
(FR-006/007). Add an explicit **dead-session probe**: attach checks
`tmux has-session -t main` (or interprets its result) and either presents a freshly
(re)started session or **clearly reports "nothing running"** — never a silent empty
attach (FR-008). A crash-restart lands on a **fresh** session (FR-009), consistent
with the entrypoint's existing `has-session` guard.

**Rationale**: the tmux + attach machinery already exists; FR-008 only needs the
explicit `has-session` check the current `execvp` attach path lacks (today only
the wizard *heuristically* infers a dead session from the ssh exit code).

**Alternatives rejected**: rely on the exit-code heuristic — reactive and
unclear, not the proactive report FR-008 requires.

**Validation**: acceptance — reattach lands on the same running session (incl. from
a second client); attach to a deployment whose session ended reports "nothing
running" (or a fresh session), never a blank attach (SC-003).

---

## R7 — CLI surface + delivery of mode/agent/task/repo/workspace

**Decision**: `up`/`redeploy` gain `--mode interactive|headless`,
`--agent claude|codex|pi`, `--task <text|@file>`, `--workspace persistent|bind|
ephemeral` (+ the bind dir), `--repo <url>`, and a headless `--foreground`.
Non-secret settings (mode/agent/repo/workspace) ride as compose **environment**;
the initial task rides as an **injected file** (003's `injected_configs`). Every
new failure mode (bind on remote, missing clone credential, dead-session reattach)
produces a clear diagnostic (FR-017). Zero new Python dependencies.

**Rationale**: consistent with the existing flag surface and the injected-material
channel; the task-as-file reuses 003's mechanism and keeps it off argv.

**Alternatives rejected**: a `run`/`exec` subcommand family — heavier than the
deploy-time flags the modes actually need; the deployment *is* the run.

**Validation**: unit (the flags thread mode/restart/workspace/agent/task/repo into
the compose model + env; bind-on-remote refused); the entrypoint shell + acceptance
tiers cover the runtime behavior.
