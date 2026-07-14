# Research: Container Lifecycle Engine (net-new decisions)

Phase 0 for Feature 002. Only decisions **not already settled by Feature 001** are recorded; deploy/build-on-host/identity/compose-run/injection are inherited (see `specs/001-multi-host-deployment/research.md`).

## R1 — pause/reclaim via `compose stop` / `compose start`, not `docker stop <cname>`

**Decision**: `stop`/`start` run `<rt> --context <H> compose -p agent-container-<name> -f <state>/<host>/<name>.compose.yaml stop|start`.

**Rationale**: compose `stop`/`start` operate on **all services in the project**, so a sidecar helper (R5) is paused/reclaimed together with the agent as one unit (FR-004) with no extra bookkeeping. It retains the container and its volumes (pause/reclaim, FR-006) and needs the persisted compose file (already written by `up`). A raw `docker stop agent-container-<name>` would miss sidecars and re-introduce per-container name juggling the compose project already solves.

**Alternatives rejected**: (a) `docker stop/start <cname>` — single-container, ignores sidecars; (b) `compose pause`/`unpause` (freeze process) — that is SIGSTOP-style suspension, not "stop then start", and doesn't survive a host reboot; the spec's pause/reclaim = stop-and-start.

## R2 — redeploy = `compose up -d --build --force-recreate` (volumes preserved)

**Decision**: `redeploy <name>` regenerates the compose file from current parameters and runs `<rt> --context H compose … up -d --build --force-recreate`. Named volumes are declared external-by-name and are **never** recreated, so the 7 persistent volumes survive.

**Rationale**: `--build` rebuilds the image on the host; `--force-recreate` guarantees the container is replaced even when compose's own change-detection would skip it, satisfying FR-008 (apply a changed image). A plain `up` (no `--force-recreate`) stays the **idempotent reconcile** path (FR-010): compose recreates only if the image/config actually changed. Volumes are pinned `{"name": vn}` (already the case from 001), so a recreate re-attaches them rather than making new ones.

**Alternatives rejected**: (a) diff the image digest ourselves then decide — reimplements compose's reconciliation, more code, no benefit; (b) `docker rm` + `docker run` — abandons the compose project (loses sidecars + the declarative artifact).

## R3 — wipe = `compose down --volumes --rmi local` behind confirmation

**Decision**: add a `wipe <name>` verb = `<rt> --context H compose … down --volumes --rmi local` (removes the container(s), the named volumes, AND the image(s) compose built locally), gated by the same TTY/`-y` confirmation idiom as `down`/`host rm --destroy`. `down` (dispose) and `down --purge` (dispose + volumes) are unchanged.

**Rationale**: FR-009 defines wipe as container + volumes + **locally-built image**. `--rmi local` removes only images built by this project (never a referenced public sidecar image that other deployments might share). Keeping `wipe` a distinct verb makes the three persistence levels explicit (stop → dispose → wipe) rather than overloading `down` with another flag.

**Alternatives rejected**: (a) `--rmi all` — would delete shared/public sidecar base images; (b) a manual `docker image rm <tag>` after `down --purge` — races and needs us to recompute the exact tag compose used; `--rmi local` is compose's own, correct answer.

## R4 — live reconciliation in `list` (the deferred 001 T030), opt-out via `--local`

**Decision**: `list`/`status` reconciles against **live host state**. For the local host it already runs `ps` (0.5.0). Extend `gather_rows` to also iterate every **registered** host in `hosts.json`, call `host_ps_rows(h)` (which `ensure_tunnel`s a provisioned host first) wrapped in a narrow `try/except (Fatal, OSError, subprocess.SubprocessError)` so one unreachable host is skipped (shown as `unreachable`) without breaking the listing, and reconcile each live row against the per-host `*.port` state files — enriching a placeholder row in place, keyed by `(host, cname)` to avoid duplicates. A `--local` flag restores the fast, local-only view.

**Rationale**: FR-011/SC-004 require truth read from the host, not a stale local record — the exact hole the 001 US3 review left open (T030 deferred). Bounding each host behind its own `ps` timeout + `try/except` keeps a dead host from hanging or masking the rest; `--local` gives the operator an escape hatch when they only care about the default host. This makes status truthful after a reboot/crash/out-of-band `docker` action (recomputing identity from the name, FR-012).

**Alternatives rejected**: (a) keep `list` local-only (status stays stale — violates FR-011); (b) always hit every host with no opt-out (every `list` pays N round-trips — the latency concern that got T030 deferred). Default-live + `--local` opt-out balances truth and speed.

## R5 — sidecars via an operator-supplied compose **override** file, merged

**Decision**: a deployment may declare helper services in an **override compose file** discovered next to the `.env` (resolution order mirroring env: `./agent-container.<name>.services.yaml` → `~/.config/agent-container/<name>.services.yaml`). When present, every compose invocation for that deployment passes it as a second `-f`: `compose -f <generated>.compose.yaml -f <override> …`, so helpers join the same project and share its lifecycle (up/stop/start/down/wipe act on the unit — FR-004). Helper services reference public images (built-on-host applies only to the agent). The tool validates the override is a compose `services:`-only fragment and never lets it redefine the agent service's identity-bearing fields (name/ports/volumes).

**Rationale**: compose's native multi-`-f` merge is the zero-dependency, well-understood way to add services to a project without the tool modeling a sidecar schema of its own. Discovery-by-convention matches the existing `.env` UX. Keeping it operator-supplied (not tool-generated) avoids inventing a config language here.

**Forward link**: this is a deliberately thin, file-based seam. The richer declarative model — a whole directory as the deployment spec — is **Feature 006 (agent-as-code)**; 002's override file is the primitive 006 will build on, not a competing design. Flagged so the two stay aligned.

**Alternatives rejected**: (a) a bespoke sidecar schema in `hosts.json`/env — reinvents compose; (b) separate deployments per helper — violates "one unit" lifecycle (FR-004); (c) baking helpers into the agent image — couples unrelated services, breaks Least Privilege/immutable-runtime intent.

## R6 — per-`(host, name)` lifecycle lock for serialization (FR-017)

**Decision**: guard each mutating lifecycle op (`up`/`stop`/`start`/`redeploy`/`down`/`wipe`) with a non-blocking advisory lock on a per-deployment lock file under the host state dir (`<state>/<host>/<name>.lock`, stdlib `fcntl.flock` on POSIX; the CLI targets POSIX operators). A second concurrent op on the same container **fails fast** with "another lifecycle operation is in progress for <name> on <host>" rather than interleaving.

**Rationale**: FR-017 requires concurrent ops on one container to be serialized or safely rejected, never corrupting state. A per-(host,name) advisory lock is the minimal, stdlib, deterministic mechanism; non-blocking + clear refusal beats silent queueing for a single-operator CLI. Read-only `list`/`logs` do not take the lock.

**Alternatives rejected**: (a) no locking (spec-violating race on double-invoke); (b) a global lock (needlessly serializes independent containers); (c) blocking lock with wait (hides the concurrency from the operator; a fast refusal is clearer).

## Summary of net-new surface

| Concern | Mechanism | New deps |
|---|---|---|
| pause/reclaim | `compose stop`/`start` | none |
| redeploy | `compose up -d --build --force-recreate` | none |
| wipe (+image) | `compose down --volumes --rmi local` + confirm | none |
| live reconcile | `gather_rows` over registered hosts (`host_ps_rows`) | none |
| sidecars | operator override file, merged via `-f` | none |
| serialization | stdlib `fcntl` per-(host,name) lock | none |
