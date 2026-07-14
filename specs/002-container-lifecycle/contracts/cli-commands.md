# Contract: CLI commands (Feature 002, net-new verbs)

Net-new user-facing commands. Grammar follows 001's docker-idiomatic style: a container is a bare top-level verb addressed by name, with `--host NAME` selecting the target (default: the registry default). Inherited verbs (`up`, `down`, `logs`, `attach`) are unchanged and only referenced.

## Commands

| Command | Contract |
|---------|----------|
| `stop <name> [--host H]` | **Pause/reclaim** (FR-006). Runs `<rt> --context H compose -p agent-container-<name> -f <state>/<H>/<name>.compose.yaml stop`. Halts all services in the project (agent + sidecars) but retains them and their volumes. Takes the deployment lock. No-op-safe if already stopped. |
| `start <name> [--host H]` | Resume a stopped deployment: `compose … start`. No recreation, no rebuild — volumes and container identity unchanged. Takes the lock. Errors clearly if the deployment was disposed (nothing to start → suggests `up`). |
| `redeploy <name> [--host H] [--env-file F] [--mount …]` | **Image-aware redeploy** (FR-008/FR-010). Regenerates the compose file from current inputs and runs `compose … up -d --build --force-recreate`. Rebuilds the image on the host and recreates the container **preserving the 7 volumes** (declared external-by-name). Reports the reattach address/port. Takes the lock. |
| `wipe <name> [--host H] [-y/--yes]` | **Wipe** (FR-009): `compose … down --volumes --rmi local` — removes the container(s), the named volumes, AND the locally-built image. **Requires confirmation**: on a TTY prompts (default No); non-TTY without `-y` refuses with exit 2 (mirrors `down`/`host rm --destroy`). Clears the per-(host,name) state. Never removes a referenced public sidecar image (`--rmi local`, not `all`). Takes the lock. |
| `list [--host H] [--local] [--json]` | **Live-reconciled state** (FR-011/FR-012, SC-004). Default: reconcile against every **registered** host's live daemon (`host_ps_rows`, `ensure_tunnel` for provisioned hosts) plus per-host state files, keyed by `(host, cname)`; an unreachable host is shown `unreachable`, never dropped, and never hangs the listing. `--local` restores the fast local-daemon-only view. `--host H` scopes to one host. Read-only — no lock. |

### Sidecars (behavioral contract, not a new command)

A deployment with an operator-supplied override file (`./agent-container.<name>.services.yaml` or `~/.config/agent-container/<name>.services.yaml`) has that file merged as a second `-f` into **every** compose invocation for it (`up`/`stop`/`start`/`redeploy`/`down`/`wipe`). The agent and its helpers thus start, stop, and are torn down as one unit (FR-004). The override is parse-validated (services-only; must not redefine the agent's identity fields) before any compose call.

## Invariants

- **Identity recomputed, never stored-and-trusted** (FR-012, Constitution IV): every verb derives container name / port / volumes / project key from `<name>` (+ host); `list` reconciles live and lets the host win.
- **Volume preservation ladder** (FR-006/007/008/009): `stop` keeps everything; `down` keeps volumes; `wipe` (and only `wipe`) removes volumes + built image, and only with confirmation.
- **One unit** (FR-004): sidecars share the project, so every lifecycle verb acts on the agent + helpers together — no orphaned helper.
- **Serialized** (FR-017): a mutating verb takes the per-(host,name) lock; a concurrent second op fails fast, never interleaves.
- **Fail-fast** (FR-015/FR-018): unreachable/incapable host, an invalid override, or a lock contention all produce a clear diagnostic and leave no partial deployment.
- **Inherited** (unchanged): build-on-host, no registry, port-release-before-return (`wait_port_released`), attach flow, injected identity as compose configs, per-host state contract — all from Feature 001.

## Non-goals (grammar)

- No `restart` verb — `stop` then `start` (or `redeploy` for an image change) covers it; a convenience alias may be added later if wanted.
- No cross-host batch verbs ("stop everything everywhere") — out of scope (per-container on a single host + host-scoped `list`).
- No pools of identical instances — would extend the identity contract; deferred.
