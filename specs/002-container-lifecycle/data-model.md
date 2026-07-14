# Data Model: Container Lifecycle Engine (net-new)

Entities and state machines **added or refined** by Feature 002. The **Host**, the **Deployment (container instance)** identity, the **generated compose model**, and the **7 volumes** are defined in `specs/001-multi-host-deployment/data-model.md` and referenced here, not restated.

## Lifecycle state (authoritative source = the host)

A deployment's lifecycle state is **read live from the host**, never from a stored value (FR-011/FR-012, Constitution I).

| State | Meaning | Host observation (`ps`) | Reached by |
|-------|---------|-------------------------|------------|
| `running` | container(s) up | present + Up | `up`, `start`, `redeploy` |
| `stopped` | retained, halted (volumes intact) | present + Exited | `stop` (pause/reclaim) |
| `disposed` | container gone, **volumes kept** | absent; volumes present; compose file present | `down` (inherited) |
| `wiped` | container + volumes + built image gone | absent; volumes absent | `wipe` |
| `absent` | never deployed / fully removed | absent | initial / after `wipe` |

**Transitions** (each recomputes identity from the name):

```text
absent ──up──▶ running ──stop──▶ stopped ──start──▶ running
                 │                    │
                 ├──down────▶ disposed ◀── (recreate by same name = up, volumes restored)
                 ├──redeploy▶ running (new image, volumes preserved)
                 └──wipe────▶ wiped/absent   (confirmation required)
```

- **Recreation is a non-event**: `disposed → up` re-attaches the same named volumes → prior configuration restored (SC-003).
- **Reconciliation**: the tool's expected state (from state files + compose artifact) is compared to the live `ps`; on mismatch (out-of-band stop/rm, reboot, crash) the **live state wins** (SC-004).

## Service (within a deployment)

A deployment's compose project contains one or more services sharing its lifecycle (FR-004).

| Field | Notes |
|-------|-------|
| `role` | `agent` (exactly one, image built on the host) or `helper`/sidecar (0..n) |
| `image source` | agent: `build.context` on the host; helper: a referenced (public) image |
| `lifecycle` | bound to the deployment — every verb acts on all services as one unit |

The **agent** service's identity-bearing fields (container name, published port, the 7 volumes, project key) are owned by the tool and derived from the deployment name; a sidecar override MUST NOT redefine them.

## Sidecar override (operator-supplied)

A compose `services:`-only fragment that adds helper services to a deployment. Optional; discovered by convention.

| Attribute | Value |
|-----------|-------|
| discovery | `./agent-container.<name>.services.yaml` → `~/.config/agent-container/<name>.services.yaml` (mirrors `.env` resolution) |
| application | passed as a second `-f` after the generated compose file on every compose invocation for that deployment |
| validation | must be a mapping with only a `services:` key; MUST NOT declare a service named like the agent or touch its identity fields; parse-checked before any compose call (fail-fast, FR-015/FR-018) |
| authority | a **regenerable input**, not stored running state — the merged result is what compose runs |

## Deployment lock (serialization)

Guards concurrent mutating operations on one deployment (FR-017).

| Attribute | Value |
|-----------|-------|
| path | `$XDG_STATE_HOME/agent-container/<host>/<name>.lock` |
| mechanism | stdlib `fcntl.flock`, **non-blocking** (`LOCK_EX \| LOCK_NB`) |
| scope | per `(host, name)` — independent containers never contend |
| held by | mutating verbs: `up`, `stop`, `start`, `redeploy`, `down`, `wipe` |
| NOT held by | read-only `list`/`status`, `logs` |
| on contention | fail fast: "another lifecycle operation is in progress for `<name>` on `<host>`" |

## Reconciled list row (extends 001's `gather_rows`)

Each `list`/`status` row is keyed by `(host, container-name)` and carries the **live** status when reachable:

| Field | Source |
|-------|--------|
| `name`, `host`, `port` | recomputed from name + per-host state |
| `image`, `status`, `uptime` | **live** from the host daemon (`host_ps_rows`) when reachable; `unreachable` (host down) or `stale`/`on remote host` (local placeholder) otherwise |
| `reconciled` | true when a live `ps` succeeded for that host |

Keying by `(host, cname)` de-duplicates a state-file placeholder against its live row; a host whose `ps` failed is marked `unreachable`, never silently dropped or shown as running.
