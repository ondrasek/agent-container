# Contract: Agent Execution & Session Management (Feature 004)

Extends the `up`/`redeploy` surface (001/002) and the injected-material seam (003).
Only the **net-new** surface is specified; the compose run mechanism, the six
non-workspace volumes, attach transport, and the 003 credentials are inherited.

## CLI flags (on `up`, and where noted `redeploy`)

| Flag | Meaning |
|------|---------|
| `--mode interactive\|headless` | Execution mode (default `interactive`). Sets `AGENT_CONTAINER_MODE` and the compose `restart:` (`unless-stopped` vs `on-failure`). |
| `--agent claude\|codex\|pi` | The primary agent to run (default `claude`). |
| `--task <text\|@file>` | Optional initial task (interactive) / headless task. Delivered as an **injected file** (never argv/env). `@file` reads a local file. |
| `--workspace persistent\|bind\|ephemeral` | Workspace mode (default `persistent`). `bind` requires `--workspace-dir` (or reuses `--mount` semantics) and a **local** host. |
| `--workspace-dir <local-abs-dir>` | The host directory for a `bind` workspace (local hosts only). |
| `--repo <url>` | Clone-on-start source for persistent/ephemeral workspaces. |
| `--foreground` | Headless only: stream the run attached and return control on completion (default headless is detached). |

Non-secret settings (`mode`/`agent`/`repo`/`workspace`) are delivered as compose
**environment**; the task rides an injected **config** file. `redeploy` accepts the
same flags (a redeploy may change mode/agent/workspace/repo).

## Delivered env + injected paths (in-container)

| Name | Path/var | Read by |
|------|----------|---------|
| `AGENT_CONTAINER_MODE` | env (`interactive`\|`headless`) | entrypoint mode branch |
| `AGENT_CONTAINER_AGENT` | env (`claude`\|`codex`\|`pi`) | entrypoint invocation map |
| `AGENT_CONTAINER_REPO` | env (clone-on-start URL) | entrypoint clone step |
| initial task | injected file at `/run/agent-container/task` (ephemeral, 003 channel) | entrypoint (seeds the agent) |

## Entrypoint mode contract (`entrypoint.sh`)

1. **Branch on `AGENT_CONTAINER_MODE`** (default `interactive`):
   - **interactive** — the existing sshd + tmux `main` flow, PLUS: launch
     `AGENT_CONTAINER_AGENT` in a dedicated tmux window, seeded with the injected
     task if present. PID 1 stays alive (tail + SIGTERM trap, as today).
   - **headless** — run the agent's non-interactive form with the task as PID 1's
     workload; the container **exits with the agent's exit code** (FR-002). sshd/
     tmux are not required for a headless run (output is via compose `logs`).
2. **Clone-on-start** (before the agent runs, for persistent/ephemeral with
   `AGENT_CONTAINER_REPO` set and `/workspace` empty): clone by URL scheme —
   `git@…` uses the injected push key (`core.sshCommand`, 003), `https://…` uses
   `GH_TOKEN` (003). A `git@…` repo with no push key → **die** (FR-014). Idempotent
   (skip if a working copy exists). A **bind** workspace is never cloned.
3. **Per-agent invocation map** — `claude` / `codex` / `pi` each map to an
   interactive launch (in the window) and a headless form (`-p`/`exec`/…) + the task.

## Compose model contract (`build_compose_model`)

| Aspect | Contract |
|--------|----------|
| `restart` | parameter, set per mode (`unless-stopped` interactive / `on-failure` headless) — no longer a hardcoded literal |
| workspace mount | persistent → the named workspace volume; bind → `<local-abs>:/workspace`; ephemeral → **omit** the `/workspace` mount |
| workspace volume | declared in the model's `volumes:` **only** in persistent mode; `per_container_volumes` (purge) tolerates its absence |
| env | `AGENT_CONTAINER_MODE`/`AGENT_CONTAINER_AGENT`/`AGENT_CONTAINER_REPO` added to the service environment (non-secret) |
| task | delivered via the existing `injected_configs` channel (ephemeral `/run` target) |

## Attach contract (`bin/agent-container`)

Attach probes the live session and never presents a silent empty shell (FR-008):
an explicit `tmux has-session -t main` check → attach to the running session, else
present a freshly (re)started session OR report **"nothing running"** clearly.
Reattach works from any machine (FR-007). Inherited local/remote resolution +
published port.

## Failure contract (FR-017)

| Condition | Contract |
|-----------|----------|
| `--workspace bind` on a non-local host | CLI `die`s with a clear message **before** deploy (FR-011) |
| `--repo git@…` with no injected push key | CLI/entrypoint `die`s before starting an empty-workspace agent (FR-014) |
| reattach to a dead session | clear "nothing running" / fresh session — never silent (FR-008) |
| ephemeral durability | surfaced at deploy + documented as non-durable (FR-015) |

## Documentation contract (FR-018)

Any change to execution modes, session behavior, or workspace semantics updates,
in the same change: `README.md`, `CLAUDE.md`, the relevant `docs/`, and this spec.
