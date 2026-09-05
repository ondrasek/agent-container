# The telemetry stack — somewhere to send it (Feature 023)

Feature 017 gave every environment somewhere to *send* telemetry. It never gave you somewhere to
send it **to**, and the gap is silent by design: export is **fail-open**, so an endpoint that does
not exist produces runs that pass with no telemetry — which reads as *"the agent emitted nothing"*
rather than *"nobody is listening"*.

```sh
agent-container telemetry stack up obs
```

That is the whole setup. It prints the endpoint to paste into `settings.yaml`, and the egress
declaration you need if the environment enforces a boundary.

## The third kind of container

| Kind | Reached by | Holds credentials | Security question |
|---|---|---|---|
| agent environment | sshd, declared admit set | yes, injected | what may it reach |
| control plane | sshd, standing key | yes, a standing one | who holds the volume |
| **telemetry stack** | **published ports** | **none** | **what did you publish** |

It runs a third-party image, no agent and no sshd. Because it has no credential channel, **exposure
is the security question that replaces one** — see below.

## TWO ADDRESSES, and this is the thing to understand

The address **you** open and the address an **agent container** exports to are different, on every
runtime where a container does not share your loopback.

```
UI:                     not reachable from here — it is bound on the host
  tunnel:               ssh -N -L 3338:127.0.0.1:3338 root@203.0.113.7
  then open:            http://localhost:3338
otlp_endpoint (agents): http://172.17.0.1:4438/v1/logs   # OBSERVED per host, not fixed
```

Inside a container, `127.0.0.1` is the container. The address that *does* work is a property of the
host, not of the runtime's name, so the tool **measures it** and prints where it came from:

| Host | Containers reach it at | Learned by |
|---|---|---|
| docker, rootful | the `bridge` network gateway (`172.17.0.1` by default) | asking the daemon |
| docker, rootless | the host's own routable address | reading the host network namespace |
| podman, rootless | `host.containers.internal` | the runtime provides it |

Deriving this from the driver name instead was a real defect: under **rootless docker** the bridge
gateway can neither be bound (published ports live in the host namespace, where that address does
not exist) nor reached from a container. **Paste the `otlp_endpoint` line, not the UI line.**

## Exposure

Chosen from named levels; the tool reports the addresses each one **resolved to**, because a level
is an intent and an address is an effect.

| Level | Reachable from |
|---|---|
| `loopback` | the host only |
| `host` *(default)* | the host and containers on it |
| `network` | any machine that can route to the host |

`host` is the default rather than `loopback` because a stack no agent container can reach is
useless — so the default already binds more than its name suggests, and under **rootless podman**
it binds every interface, because there is no stable per-host bridge address to bind instead. That
is why the resolved addresses are printed rather than implied.

`--exposure network` is refused without `-y` on a non-TTY, and states first that it publishes an
**unauthenticated UI showing verbatim agent task text** and an ingest that accepts records from
anyone who can reach it.

## Commands

| Command | Notes |
|---|---|
| `telemetry stack up NAME` | Creates, or starts a stopped one keeping its data. Reports success only once the ingest **accepted a record** — container liveness is not readiness. |
| `telemetry stack ls` | `running` / `stopped` / `undetermined`. An unreachable host is never reported as stopped. |
| `telemetry stack url NAME` | Both addresses, plus the tunnel command when the UI is not reachable from here. |
| `telemetry stack dashboards NAME` | Re-installs the tool's dashboards without redeploying or discarding data. |
| `telemetry stack remove NAME` | Retains collected telemetry unless `--purge`. Says that anything still exporting now fails open. |

`up --set-endpoint` writes `otlp_endpoint` into `settings.yaml` inside a managed region, preserving
everything outside it. Opt-in only: creating a container should not edit your configuration.

## Named defaults

| Setting | Default | Override |
|---|---|---|
| image | `grafana/otel-lgtm` | `--image` |
| exposure | `host` | `--exposure` |
| readiness budget | 180s (pull + start + ingest) | `AGENT_CONTAINER_STACK_READY_TIMEOUT` |
| retention | 7 days / 10GB | `--retention-days`, `--retention-size` |

Retention is **read back** after it is applied. A variable an image does not recognise sets nothing,
and the stack would then retain forever while looking configured — so an unconfirmed value is
reported as `unconfirmed`, never as the number that was requested.

## Dashboards

Three ship with the tool and install themselves: **Fleet**, **Run Trace (correlated)**, **Host**.
They are versioned with the tool, so re-running `dashboards` brings an older stack up to date.

The run picker is a **text box**, not a dropdown, and that is not a style choice: the correlation id
arrives as Loki *structured metadata* rather than an indexed label, so a query variable over it
renders empty and every panel then filters on the empty string. Paste a `run_id` from the *Recent
runs* panel.

## Behind an egress boundary

Export is outbound traffic a Feature 012 declaration governs, and it **fails open**. An environment
that enforces egress and does not declare the collector produces a green run with no telemetry and
no error anywhere. `up` prints the stanza you need:

```yaml
egress:
  allow:
    - host: host.containers.internal
      port: 4318
```

## What it is not

Not a system of record. Bounded local storage, no authentication, no backup, no HA. It is a
development and operations aid — the durable trail remains the local one 017 writes, which export
never replaced. For anything long-lived, run a real backend and point `otlp_endpoint` at it;
`--image` exists so the tool's choice never blocks you.

Host-level signals (the container host's own metrics and systemd journal) are **not** part of a
stack — see [`contrib/telemetry`](../contrib/telemetry/README.md).
