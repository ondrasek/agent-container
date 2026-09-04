# Phase 1 data model: telemetry stack container

## Entity: Telemetry stack

A container this tool created whose purpose is receiving and displaying telemetry.

| Field | Type | Rules |
|---|---|---|
| `name` | string | Matches the tool's existing name grammar. **Unique per host across ALL kinds** (FR-009a) — not merely unique among stacks. |
| `host` | host reference | Any host the tool can deploy to; resolved by the existing resolver. |
| `kind` | enum | `telemetry-stack`. Distinguishes it in listings and inventory **without inspecting the image** (FR-003). |
| `image` | string | Named default, overridable (FR-008). |
| `exposure` | enum | `loopback` \| `host` \| `network`. Default `host` (FR-018/018a). |
| `ui_port` | int | Allocated per host; no two stacks collide (FR-009). |
| `otlp_http_port` | int | Allocated per host. |
| `otlp_grpc_port` | int | Allocated per host. |
| `retention_days` | int | Named default (FR-025). |
| `retention_size` | size | Named default (FR-025). |
| `state` | enum | `running` \| `stopped` \| `absent` \| `undetermined`. |

### `state` — why `undetermined` is a value, not an error

The inventory work (014) established that an unreachable host yields `undetermined`, never
`stopped`: reporting a definite state we could not observe is how absence of evidence becomes
evidence of absence. FR-024 carries the same rule into `panic` for this kind. `ls` therefore has four
possible answers, not three.

### State transitions

```
absent ──up──> running
running ──(host reboot / runtime stop)──> stopped
stopped ──up──> running          # FR-007: starts it, KEEPS data
running ──remove──> absent       # data retained unless discard requested
stopped ──remove──> absent
any ──(host unreachable)──> undetermined   # observation, not a transition
```

`stopped ──up──> running` is the transition the clarification session added. It is not cosmetic: a
host reboot is the ordinary way a stack becomes stopped, and treating that as "already exists,
nothing to do" leaves the operator with a dead endpoint that fails open.

---

## Entity: Stack endpoint (derived, never stored)

The address telemetry is sent to. **Two forms, and conflating them is the feature's principal
failure mode** (research R1).

| Form | Consumer | Derivation |
|---|---|---|
| `operator_url` | a human's browser / CLI on the operator's machine | host address + `ui_port`; may require a tunnel when not directly reachable |
| `container_endpoint` | an agent container exporting via `otlp_endpoint` | **runtime-specific host address** + `otlp_http_port` + `/v1/logs` |

Derived on demand rather than stored, because it depends on the runtime and on where the asking
process sits — storing it would freeze one viewpoint and hand the other a wrong answer.

**Validation**: `container_endpoint` MUST carry a scheme (the tool already refuses a schemeless
`otlp_endpoint`) and MUST end in the signal path the tool's own exporter POSTs to. It MUST NOT be a
loopback address on a runtime where a container's loopback is its own.

---

## Entity: Exposure level (resolved, reported)

| Level | Intent | Reachable from |
|---|---|---|
| `loopback` | the host only | processes on the host |
| `host` *(default)* | the host and its containers | host + containers on it — **not** other machines |
| `network` | anything that can route to the host | any machine |

A level is an **intent**; the concrete bind addresses are resolved per runtime and MUST be reported
(FR-018b). On some runtimes `host` requires binding more than loopback, because a container cannot
reach a service bound only to the host's loopback — which is why the default level is `host` and not
`loopback`, and why the resolved addresses are stated rather than assumed.

---

## Entity: Dashboard set

Views the tool installs into a stack.

| Field | Type | Rules |
|---|---|---|
| `uid` | string | Stable across re-provisioning, so `dashboards` overwrites rather than duplicates (FR-015). |
| `title` | string | — |
| `queries` | list | MUST filter correlation attributes AFTER a stream selector (research R5). |

**Versioned with the tool, not with the stack.** Re-provisioning brings an older stack up to the
current tool's expectations, which is why the set is not stored on the stack's volume.

**Constraint from R5**: the run selector MUST be a free-text variable seeded from a "recent runs"
panel. A query variable over the correlation attribute renders empty — the attribute is structured
metadata, not an indexed label — and every panel then filters on the empty string and shows "No
Data" while the data is present.

**Constraint from R6**: metric panels may filter only on attributes carried on the DATA POINT.
Resource attributes other than `service.*` do not survive into Prometheus.

---

## Entity: Inventory record (existing, extended)

The durable note that this tool created this container. Extended with `kind`, so a stack is
distinguishable from an agent environment after the container, host and registry entry are all gone.

`panic` reads the same record: a kind absent from it is a kind the kill switch does not stop, which
is a hole in a safety property rather than a missing feature.
