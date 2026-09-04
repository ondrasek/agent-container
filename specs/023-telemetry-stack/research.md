# Phase 0 research: telemetry stack container

Every finding below was **measured** in this repository's environment (macOS host, Lima VM,
rootless podman 6.1.0 + netavark; and docker 29.7.2 on a Hetzner Debian 12 host) while
Feature 017's fan-out was being built. None of it is quoted from vendor documentation without
a check, because three of the five findings contradict what the documentation implies.

---

## R1: How a container reaches a collector on its own host

**Decision**: The endpoint an AGENT CONTAINER exports to is resolved PER RUNTIME, and is not
the address the operator uses.

| Runtime | Operator uses | Container uses |
|---|---|---|
| docker (Linux host) | `127.0.0.1:4318` | `172.17.0.1:4318` (bridge gateway) |
| podman rootless (Lima) | `127.0.0.1:4318` (Lima forwards) | `host.containers.internal` → `192.168.5.15:4318` |

**Rationale**: Measured. From a container under rootless podman, `host.containers.internal:4318`
answered `200`; the container's default gateway `10.0.2.2` did **not** — that address routes to the
macOS host, not the Lima VM where the collector runs. Under docker, `127.0.0.1` inside a container
is the container itself, so an operator-facing address there is useless.

**Consequence for the spec**: this is exactly FR-013 and FR-018b. A single "endpoint" field would be
wrong on at least one runtime, and wrong in the silent direction — export fails open, so the stack
looks up and receives nothing.

**Alternatives considered**: publishing on `0.0.0.0` and using the host's LAN address for both. Works
uniformly, and is rejected because it publishes an unauthenticated UI to the network as a side
effect of wanting containers to reach it — precisely what FR-020 forbids.

---

## R2: Readiness is not liveness

**Decision**: Probe readiness by POSTing an EMPTY OTLP payload (`{"resourceLogs":[]}`) to
`/v1/logs` and requiring HTTP 200.

**Rationale**: Measured. `grafana/otel-lgtm` reports the container as `Up ... (starting)` for tens of
seconds after the OTLP port is already listening, and conversely accepts TCP connections before the
receiver is wired. An empty payload is accepted by a ready receiver, creates no data, and is
therefore safe to repeat every second. Warm start reached 200 in ~10s; a cold pull of the image took
60–90s end to end, which is what sets the 180s budget in FR-006a.

**Alternatives considered**: the container runtime's own healthcheck. Rejected — under **rootless
podman** healthchecks are systemd transient timers that never fire when the podman socket runs as a
user service, a failure this project has already been bitten by (compose waited 20+ minutes with the
container stuck in `Created`). Depending on it here would reintroduce a known defect.

---

## R3: Retention controls in the chosen image

**Decision**: Configure retention through the environment variables the image exposes, and treat the
window and the ceiling as two separate named settings (FR-025).

**Rationale**: `grafana/otel-lgtm` bundles Prometheus, Loki and Tempo, each with its own retention
mechanism; the image accepts per-component configuration through mounted config and environment.
Because the spec requires BOTH a window and a ceiling, and the components express these differently,
the plan treats "apply retention" as one task with per-component sub-steps rather than assuming a
single knob exists.

**Open for implementation**: exact variable names must be read off the image at build time rather
than assumed. This is the one place where guessing would produce a stack that silently retains
forever — so the task that applies retention MUST assert the effective value back (FR-025b) rather
than trusting that setting it worked.

**Alternatives considered**: leaving retention to the operator. Rejected by FR-025; an unbounded
store on a developer laptop is a disk-full incident waiting to happen, and it fails silently.

---

## R4: Dashboard provisioning

**Decision**: Provision over the Grafana HTTP API (`POST /api/dashboards/db`, `overwrite: true`)
after readiness, not by mounting provisioning files.

**Rationale**: Measured, and it follows a rule this repository already holds: `configs: {file:}` in
compose is a **daemon-side bind** and does not cross a remote context (the 001/003 lesson, recorded
in CLAUDE.md). Dashboards must work on a remote host, so a file mount is disqualified. The API path
was exercised repeatedly today against both a remote docker host and local podman, including
`overwrite` semantics for re-provisioning (FR-015).

**Rationale for API over `{content:}` compose configs**: `{content:}` does cross, and would work —
but re-provisioning would then require redeploying the container, which FR-015 explicitly forbids.

**Alternatives considered**: shipping dashboards as files in a volume. Same remote-context problem,
plus it puts tool-versioned artifacts on a stack-lifetime volume, contradicting the "dashboards are
versioned with the tool" entity note in the spec.

---

## R5: Loki structured metadata is not a stream label

**Decision**: Dashboard queries MUST filter correlation attributes AFTER a stream selector, never
inside the selector.

```
{agent_container_run_id="X"}                                     # matches NOTHING
{service_namespace="agent-container"} | agent_container_run_id=`X`  # correct
```

**Rationale**: Measured, and it cost a broken dashboard today. Resource attributes arrive as Loki
*structured metadata*; the label-values API does not enumerate them, so a Grafana **query variable**
over `agent_container_run_id` renders an empty picker, `$run_id` interpolates to `""`, and every
panel silently filters on the empty string — the dashboard reads "No Data" while the data is present.

**Consequence**: the run selector must be a **textbox** seeded from a "recent runs" panel, not a query
variable. This is a hard requirement on the dashboard set, not a preference.

---

## R6: The OTLP→Prometheus conversion drops most resource attributes

**Decision**: Any attribute a dashboard filters metrics by MUST be attached to the DATA POINT, not
only to the resource.

**Rationale**: Measured. The conversion promotes `service.*` and drops the rest, so
`agent_container.agent` recorded only as a resource attribute vanished from the series and no
dashboard could ask "every container running claude". Confirmed by reading labels back off the
series, not by inspecting the payload.

**Consequence**: Feature 017's host-metrics sampler already carries `environment`, `agent` and
`run_id` as data-point attributes. The stack's dashboards may rely on those; they may NOT rely on
arbitrary resource attributes surviving into Prometheus.

---

## R7: Name and port allocation for a third kind

**Decision**: Reuse the existing per-host state and naming machinery; allocate the published ports
the same way agent environments allocate their SSH port, and record the choice in per-host state.

**Rationale**: FR-009 and FR-009a require that several stacks coexist and that a name identify
exactly one container of any kind. The tool already solves both problems for agent environments
(`CONTAINER_PREFIX`, per-host state directory, `.port` files). Inventing a second mechanism would
give `panic` and the inventory two things to know about instead of one — and `panic` acting on an
incomplete set is a safety property, not a feature.

**Alternatives considered**: fixed ports (3000/4317/4318). Rejected outright by FR-009: the second
stack on a host would fail to bind, and today's measurement shows the failure mode is a container
that starts and then dies, which reads as "the image is broken".

---

## R8: The image is third-party and must not be assumed present

**Decision**: Pull explicitly, report that a pull is happening, and treat pull failure as a named
cause (spec Edge Cases).

**Rationale**: `grafana/otel-lgtm` is ~1GB and is not in any local cache on a fresh host. Today a
first pull on Hetzner took ~45s on a fast link; on a slow one it dominates the 180s budget, which is
why FR-006b requires the timeout message to say which stage it expired in.

**Constitution note**: this introduces no dependency *of the tool* (Principle VI) — nothing links
into `agent-container`, which continues to export by speaking the protocol with curl. It does add a
container to the fleet whose contents this project does not build, which the threat-model row for
023 records explicitly rather than leaving implied.
