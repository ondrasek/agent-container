# Phase 1 contract: the `telemetry stack` command surface

The tool's external interface is its CLI, so this is the contract. It follows the group-verb rule
already enforced by tests: **`ls` reads, destructive verbs are spelled out**, every short flag has a
long form, and `-v`/`--verbose` works on every command (injected, not declared per command).

---

## `agent-container telemetry stack up NAME`

Create or start a telemetry stack.

| Flag | Default | Meaning |
|---|---|---|
| `--host` | resolved default host | Where to deploy. |
| `--image` | named default | Stack image (FR-008). |
| `--exposure` | `host` | `loopback` \| `host` \| `network` (FR-018). |
| `--ui-port` | allocated | Override the UI port. |
| `--otlp-port` | allocated | Override the OTLP/HTTP port. |
| `-y`, `--yes` | off | Required to proceed with `--exposure network` on a non-TTY. |
| `--json` | off | Machine-readable envelope. |

**Exit codes**: `0` running and ingest accepting · `1` failure (cause named) · `2` refusal
(name conflict, port conflict, `network` without `-y` on a non-TTY).

**Guarantees**
- Reports success ONLY after the ingest accepted a record (FR-006).
- On timeout, names which stage expired: pull, start, or ingest (FR-006b).
- Existing + running ⇒ reports it, creates nothing (FR-007).
- Existing + stopped ⇒ starts it, keeps data, says "restarted" not "created" (FR-007).
- Name taken by another kind ⇒ refuses, naming the kind (FR-009a).
- Prints the resolved bind addresses for the chosen level (FR-018b).
- Prints the `otlp_endpoint` value an AGENT CONTAINER uses (FR-011, FR-013).
- Provisions dashboards; failure is reported but does not fail the deploy (FR-016).

---

## `agent-container telemetry stack ls`

List stacks. Read verb, so `ls` (FR-021).

| Column | Notes |
|---|---|
| NAME | |
| HOST | |
| STATE | `running` \| `stopped` \| `undetermined` — never a guess |
| UI | operator-facing address |
| INGEST | whether it is answering right now |

`--host` narrows; `--json` for machines.

---

## `agent-container telemetry stack url NAME`

Report how to reach it (FR-011, FR-012, FR-013).

Prints, in this order: the UI address; the `otlp_endpoint` line to paste into `settings.yaml`; and,
when the UI is not reachable from the operator's machine, the exact command that makes it reachable.

Not running ⇒ says so rather than printing an address that answers nothing (Edge Cases).

---

## `agent-container telemetry stack dashboards NAME`

Re-provision the tool's dashboards (FR-015). Does not redeploy, does not restart, does not discard
data. Reports per-dashboard outcome; a failure names the dashboard.

---

## `agent-container telemetry stack remove NAME`

Stop and delete. Spelled out because it is destructive.

| Flag | Default | Meaning |
|---|---|---|
| `--purge` | off | Also discard collected telemetry (FR-022). |
| `-y`, `--yes` | off | Skip confirmation; required on a non-TTY. |

Retains collected data unless `--purge`. States that environments still exporting to it will now
fail open — silently, which is why it is said out loud (Edge Cases).

---

## Interactions with existing commands

| Command | Behaviour |
|---|---|
| `panic` | Stops telemetry stacks with everything else; unreachable host ⇒ `undetermined` (FR-024). |
| `inventory ls` | Shows stacks with `kind`, distinguishable from agent environments (FR-023). |
| `up` (agent) | Refuses a name already held by a stack, and vice versa (FR-009a). |
| `doctor` | Unchanged; a stack is not a precondition for anything. |

## Machine-readable envelope

`--json` uses the tool's existing envelope (`schema`, `ok`, `data`) — no new shape.
