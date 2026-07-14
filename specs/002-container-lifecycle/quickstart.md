# Quickstart: Container Lifecycle Engine (validation scenarios)

Runnable scenarios that prove Feature 002's net-new verbs. Assume Feature 001 is in place: a configured, reachable, compose-capable host (local `lima-docker` context is fine) is registered as the default. See [contracts/cli-commands.md](./contracts/cli-commands.md) and [data-model.md](./data-model.md) for details.

## Prerequisites

- `agent-container` installed (0.5.0+); a registered default host (`agent-container host ls` shows one).
- A `.env` for the test container (as for `up`).

## Scenario A — pause / reclaim (FR-006, SC-002)

```bash
agent-container up alpha                 # running
agent-container stop alpha               # -> stopped (retained; volumes intact)
agent-container list                     # alpha shows Exited/stopped, live from the host
agent-container start alpha              # -> running again, NO recreation
agent-container attach alpha             # interactive session (fresh, per Ephemerality)
```

**Expected**: `stop` halts without removing; `start` resumes the same container (no rebuild, same volumes); `list` reflects the real host state at each step.

## Scenario B — dispose then recreate is a non-event (FR-007, SC-003)

```bash
agent-container down alpha               # dispose: container gone, volumes KEPT (inherited from 001)
agent-container up alpha                 # recreate by same name -> prior config restored from volumes
```

**Expected**: after `down`+`up`, alpha comes back with its persisted configuration and zero manual reconfiguration.

## Scenario C — image-aware redeploy preserves volumes (FR-008, SC-006)

```bash
# (rebuild the image on the host with a change, e.g. bump the Dockerfile)
agent-container redeploy alpha           # rebuild on host + recreate, volumes preserved
agent-container list                     # new image id; same published port; volumes unchanged
```

**Expected**: the new image is running; the 7 volumes are the same ones (not recreated); an immediate re-`up` of the same name does not hit a stale-port error (SC-008, inherited `wait_port_released`).

## Scenario D — wipe requires confirmation and removes everything (FR-009, SC-005)

```bash
agent-container wipe alpha               # prompts (default No) on a TTY; -y to skip
# confirm -> container + its volumes + the locally-built image removed
agent-container list                     # alpha absent; its volumes gone
```

**Expected**: nothing is destroyed without confirmation; a referenced public sidecar image is NOT removed (`--rmi local`).

## Scenario E — live reconciliation stays truthful (FR-011/FR-012, SC-004)

```bash
agent-container up beta
# out-of-band change directly on the host daemon:
docker --context <H> stop agent-container-beta      # or reboot the host
agent-container list                     # beta shows Exited/stopped — the REAL host state
agent-container list --local             # fast local-only view (no remote round-trips)
```

**Expected**: after an out-of-band stop/reboot/crash, the next `list` reflects the host's actual state, not a stale local record; a dead host appears as `unreachable`, never as running and never hanging the listing.

## Scenario F — sidecar shares the lifecycle (FR-004)

```bash
# declare a helper next to the container:
cat > agent-container.gamma.services.yaml <<'YAML'
services:
  cache:
    image: redis:7-alpine
YAML
agent-container up gamma                 # agent + cache start together (one project)
agent-container stop gamma               # both stop as one unit
agent-container start gamma              # both start; agent can reach cache
agent-container wipe gamma -y            # both removed together; no orphaned helper
```

**Expected**: every lifecycle verb acts on the agent and its helper together; the agent can reach the helper by service name on the compose network.

## Scenario G — concurrent ops are serialized (FR-017)

```bash
agent-container redeploy delta &         # holds the (host,delta) lock
agent-container stop delta               # second op -> fails fast: "another lifecycle operation is in progress"
```

**Expected**: a concurrent second mutating op on the same container is refused with a clear message, never interleaved; read-only `list`/`logs` are never blocked.

## Success signal

All scenarios pass with state read live from the host, volumes preserved except on an explicitly-confirmed `wipe`, sidecars moving as one unit, and no stale-local-record surprises — matching SC-001…SC-009.
