# Contract: OTLP payloads and the channel

Two contracts that cross a boundary and must therefore be pinned by tests rather than by
convention: what this feature writes to the telemetry stack, and what it exchanges with Slack.

---

## Part 1 — OTLP payloads

All three signal classes are OTLP/HTTP **JSON** log records, posted with `curl` to the declared
`otlp_endpoint`. The transport, the body shape and the attribute-composition helper already exist —
017 exports this way and 023's ingest probe builds the same `{"resourceLogs":[...]}` envelope by
hand. This contract adds producers, not a protocol.

### Shared resource attributes

Every payload this feature writes carries the attribution 017 already composes, from the **same
definition** — never a second list. Two lists would agree today and drift invisibly, because each
leg still looks correct alone.

```
service.namespace         = agent-container
agent_container.run_id    = <016 run id>
agent_container.environment, .host, .agent, .mode
```

### Signal `log` — agent output

```
agent_container.signal    = log
agent_container.stream    = stdout | stderr
agent_container.seq       = <monotonic per run; a gap is detectable>
body                      = <the agent's output lines for this batch>
```

On reaching the per-run cap, exactly one final record:

```
agent_container.signal    = log
agent_container.truncated = true
agent_container.seq       = <where it stopped>
body                      = "agent log export reached the <N>MB cap for this run and stopped here"
```

**The marker is a record, not a log line**, so a consumer can find it by attribute rather than by
matching text in a body it does not control.

### Signal `interpretation`

```
agent_container.signal            = interpretation
agent_container.interpreter       = <name>            # who claims this
agent_container.interpretation_id = <stable id>
agent_container.state             = <run state as read>
agent_container.confidence        = sourced | inferred
body                              = <the assessment>
```

with structured `evidence[]`, `contradictions[]`, `input_health` and `observed_directives` as
[data-model.md](../data-model.md) defines.

### Signal `notification`

```
agent_container.signal          = notification
agent_container.interpreter     = <name>
agent_container.event_key       = <run_id + event kind + triggering state>
agent_container.delivery_state  = sent | held | delayed | failed
agent_container.held_reason     = channel_unreachable | silence_window
```

### Rules that tests pin

1. **A closed attribute set per signal.** A payload carrying an attribute this build does not
   declare is warned about at read time, as 016 warns for unknown record fields — the same reasoning:
   a consumer that silently ignores what it does not recognise cannot tell a new field from a forged
   one.
2. **`agent_container.interpreter` is mandatory on the two signals the interpreter writes.** The
   ingest is unauthenticated; identity is what keeps two interpreters — or an impostor — from being
   read as one voice.
3. **The probe namespace stays clean.** 023's health probe writes into its own service namespace so
   it never appears in dashboards; these signals write into the tool's namespace and MUST NOT appear
   in the probe's, or 023's ingest health would start measuring this feature's traffic.
4. **`run_id` is present on every payload.** It is the only join between the three classes and the
   run record.

---

## Part 2 — The Slack channel

Mechanism settled in [research R1](../research.md): **HTTPS polling**, not Socket Mode. Socket Mode
requires a WebSocket client and therefore a third-party dependency, which Constitution VI forbids.

### Calls used

| Call | Direction | Purpose |
|---|---|---|
| `chat.postMessage` | out | notifications and replies |
| `conversations.history` | out | poll for operator messages |
| `auth.test` | out | `interpret test-channel`: confirm the token works and report the identity it resolves to |

All are HTTPS with a bot token in the `Authorization` header. **No inbound port is opened or
published** — the container makes every connection.

### Supported app shape, and why it is stated

The app must be a **custom app** installed in the operator's own workspace. `conversations.history`
allows **50+ requests per minute** for custom apps but only **1 request per minute** for
commercially distributed non-Marketplace apps ([Slack: Rate
limits](https://docs.slack.dev/apis/web-api/rate-limits/)). At the 15-second default the interpreter
makes 4 requests per minute — an eighth of the custom-app allowance, and four times over the
distributed one.

This is named in the deploy-time statement because the failure is otherwise undiagnosable: a
distributed app would answer minutes late, and nothing in this tool could tell that apart from a
quiet fleet.

### Scopes

| Scope | For |
|---|---|
| `chat:write` | posting |
| `channels:history` / `groups:history` | reading the bound conversation |
| `users:read` | resolving the declared sender to a readable name in output |

Deliberately **no scope that can act on the workspace** beyond posting in the bound conversation:
the credential's blast radius, if it leaks, is "can speak as the interpreter", which is what FR-006
already requires it be described as.

### Inbound message handling

```text
message arrives on the bound conversation
   │
   ├─ sender ≠ declared_sender ──► no reply; record refusal with the sender's identity (FR-023)
   │
   └─ sender = declared_sender
         ├─ asks for status  ──► answer, grounded, citing run ids (FR-011a)
         ├─ changes policy   ──► apply, confirm back in the conversation (FR-019)
         └─ asks it to act   ──► decline, name the path that can, record it (FR-022)
```

**Every reply names the interpreter that sent it** (FR-016), so an operator running two, or reading
a conversation an impostor can also post to, can tell who is speaking.

### Rate limiting and backoff

`429` responses carry `Retry-After` and MUST be honoured. A channel that is rate-limiting or down
causes notifications to be **held and delivered in order on recovery** (FR-018) — never dropped, and
never allowed to affect any agent in the fleet, which is the property FR-018's second sentence
exists to protect.
