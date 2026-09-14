# Contract: CLI surface

Additions only. Every existing command keeps its behaviour; the shared-namespace, inventory, kill
switch and version-skew rules apply to an interpreter exactly as they do to any other container this
tool creates.

---

## `up NAME --role interpreter`

The existing `up`, with a third role. `--role` grows from `agent|control-plane` to
`agent|control-plane|interpreter`.

| Option | Required | Notes |
|---|---|---|
| `--role interpreter` | yes | selects the role |
| `--agent` | no | any of `AGENTS`; the existing default applies (FR-003) |
| `--stack NAME` | yes | the tool-managed telemetry stack to read and write. **Refusal if absent or unreachable, naming the stack** — not a degraded mode (R3) |
| `--watch HOST[/ENV]` | repeatable | the watched scope. Snapshot at deploy, as 017's registry is |
| `--channel slack` | yes | named choice; only channels that authenticate senders are admissible (FR-024b) |
| `--slack-conversation ID` | yes | the conversation to speak in |
| `--declared-sender ID` | yes | the workspace member it will answer. **No default** (FR-023) |
| `--stall-window`, `--poll-interval`, `--digest`, `--notify` | no | named defaults, reported when applied (research R6) |

### It states what it holds, before it creates anything

Printed, not prompted — 017's rule, because `up` is a path an agent may drive and a prompt would be
auto-answered, which reads as consent.

```text
=== NAME: interpreter — what this container will hold and what it can do ===
  READS     the telemetry stack 'obs' on vps1, and run records for: vps1/*, vps2/api
  HOLDS     a Slack bot token — whoever holds it can speak to you AS this interpreter
  CANNOT    stop, start, redeploy, destroy, task or reconfigure anything.
            No container runtime client is installed and no host key is held.
            This is structural, not a setting.
  SENDS     task text and agent output to Slack conversation C0123456789.
            Everyone who can read that conversation, and your workspace
            administrators, will see them. Workspace retention applies.
=== this statement is recorded in the inventory; compare it there afterwards ===
```

The `SENDS` paragraph is FR-024a and is not abbreviated: it is the trust-domain crossing, and 023's
`--exposure network` warning is the precedent for stating a consequence in full before it applies.

---

## `interpret` command group

Read-only by composition. Every command in this group is covered by the FR-020a reachability guard,
which asserts that no mutating helper is reachable from any of them.

| Command | Does |
|---|---|
| `interpret ls` | interpreters, their scope, channel, watched-fleet health, and when each last read the trail |
| `interpret show NAME` | one interpreter: policy, watermarks, delivery state, what it currently cannot see |
| `interpret history NAME` | interpretations it produced, newest first; `--run RUN_ID` for one run. This is FR-012a — "what did you tell me about run X, and why" |
| `interpret serve` | **in-container only.** The bridge loop. Refuses to run outside an interpreter container, because on an operator's machine it would be a long-lived process holding a channel token with no container boundary around it |
| `interpret test-channel NAME` | proves the binding end to end: posts, reads back, reports the sender identity it would admit. Run before trusting it overnight |

`--json` on every read command, as the CLI's existing rule requires.

**Naming.** `ls` reads and the destructive verbs are spelled out — the group verb convention. There
is no `interpret stop`, `interpret act` or `interpret run`: FR-020a forbids a command surface that
would act if a credential were supplied later, so the absence is part of the contract.

---

## Changes to existing commands

| Command | Change |
|---|---|
| `list` / `inventory ls` | an interpreter shows `role=interpreter` with its scope and channel (FR-002) |
| `runs show` | when a run's log was exported, names the stack as where it went instead of saying only that logs are gone with the container (FR-009). When it was not exported, says so |
| `panic` / kill switch | stops interpreters with everything else (FR-030). Invoked *through* an interpreter's channel it cannot act at all under this feature's authority, so 017's self-exclusion case does not arise yet — stated so the future authority feature inherits the question rather than rediscovering it |
| `doctor` | reports whether an interpreter's stack, channel binding and declared sender resolve. Read-only, and stays inside 013's guarantee — it checks that the token is *declared*, never that it works, because resolving it would be the credential access 013 refuses |

---

## Settings

```yaml
# ~/.config/agent-container/settings.yaml  (or .agent-container/settings.yaml)
otlp_endpoint: http://172.17.0.1:4438/v1/logs   # existing (017)
export_task_text: true                           # existing (017)
export_agent_logs: true                          # NEW — FR-007b, named, its own switch
agent_log_cap_mb: 10                             # NEW — FR-008, named default
```

`export_agent_logs` is deliberately **separate** from `export_task_text`. They are different
exposures: the task is one operator-authored string, the log is everything the agent printed. One
switch governing both would make an operator who excluded the task believe they had excluded the
wider thing.

---

## Refusals this feature adds

| Situation | Behaviour |
|---|---|
| `--role interpreter` without a reachable tool-managed stack | refuse, name the stack, name `telemetry stack up` |
| `--declared-sender` omitted | refuse. There is no default that admits anyone (FR-023) |
| a message from an undeclared sender | no reply; record the refusal with the sender's channel identity (FR-023, SC-007) |
| a channel that cannot authenticate senders | refuse to bind (FR-024b, SC-014) |
| any channel message asking it to act on the fleet | decline, name the path that can, record the request (FR-022) |
| a run record whose schema it does not understand | refuse to interpret it, report as a finding (FR-029) |
| `interpret serve` outside an interpreter container | refuse |
