# Phase 0 research: Interpreting control plane

Every decision below was forced by a constraint the project already holds, not chosen on taste. The
two that changed the design are R1 (the channel mechanism) and R4 (where the interpreter's state
lives); the two that bound the feature's honesty are R3 (what the tool may query) and R5 (how an
absence is proven).

---

## R1 — How the interpreter talks to Slack without a dependency

**Decision: HTTPS polling of the Web API — `conversations.history` to read, `chat.postMessage` to
write — with a bot token. Not Socket Mode.**

**Rationale.** The requirement is outbound-only (FR-024: no port opened, no port published), and
Socket Mode advertises exactly that property — so it was the obvious candidate. It fails on a
constraint one layer down. Socket Mode obtains a WebSocket URL at runtime from
`apps.connections.open` using an **app-level token** (`xapp-`), then speaks **WebSocket**, "a
bidirectional stateful protocol" ([Slack: Using Socket
Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/), [apps.connections.open](https://api.slack.com/methods/apps.connections.open)).
Python's standard library has no WebSocket client. So Socket Mode does not cost "a Slack SDK if we
feel like it" — it makes a third-party dependency **unavoidable**, in a project whose stated
position is that PyYAML is the one third-party dependency (Constitution VI, CLAUDE.md).

Polling the Web API has the identical inbound-surface property — the container opens the connection,
nothing listens — and needs only HTTPS, which the image already speaks with `curl` and which the
tool already uses for OTLP export (017) and for 023's ingest probe.

**The rate limits make it comfortable, and the distinction matters.** As of 29 May 2025,
`conversations.history` is **1 request per minute with `limit` capped at 15** for commercially
distributed non-Marketplace apps, but **50+ requests per minute with `limit` up to 1000 for custom
apps** ([Slack: Rate limits](https://docs.slack.dev/apis/web-api/rate-limits/), [rate-limit
changelog](https://api.slack.com/changelog/2025-05-terms-rate-limit-update-and-faq)). An
interpreter's app is a **custom app** installed in the operator's own workspace — it is not
distributed — so the 50+/min tier applies. A 15-second poll is 4 requests per minute, an eighth of
the allowance, and meets SC-010's one-minute answer budget with the interval to spare.

**This must be written into the docs, not just the plan**: an operator who distributes their app
outside the Marketplace silently drops to 1 request per minute, and the interpreter would then
answer minutes late for a reason nothing in this tool could detect. The deploy-time statement names
"custom app" as the supported shape.

**Alternatives considered.**

| Option | Why not |
|---|---|
| Socket Mode | Needs a WebSocket client → an unavoidable new dependency. The reason this research exists. |
| Events API over HTTP | Requires a **public inbound Request URL**. Contradicts FR-024 outright and would put a listening port on a host whose exposure 023 works hard to bound. |
| Shelling out to an SDK in a sidecar | A dependency with extra steps, plus a second container to keep alive. |
| Email | Cannot authenticate a sender; FR-023 makes it inadmissible, and FR-024b names it as the example. |

**Consequence for the spec.** The Clarifications entry recorded the operator's channel choice with
"over socket mode" as the mechanism, which was the author's paraphrase in the option preview rather
than the operator's decision. The decision was *Slack, no inbound path*; the mechanism is settled
here. The spec entry is corrected to say "connected outbound", with the mechanism referred to this
document.

---

## R2 — How the agent's output becomes an OTLP signal

**Decision: tee the agent's output stream in `image/entrypoint.sh` into a small batching exporter
that POSTs OTLP/HTTP JSON logs with `curl`, beside the existing attribute composition.**

**Rationale.** 017 already exports by speaking the protocol directly with `curl` and zero backend
packages, and `image/entrypoint.sh` already composes OTLP resource attributes (`_otel_attrs`, around
line 1442) including `agent_container.mode`. 023's health probe already builds a
`{"resourceLogs":[...]}` body by hand and posts it. So the payload shape, the transport and the
attribute set all exist in-tree; this is an additional producer of a shape the repo already writes,
not a new integration.

Batching is required because a log line is not a run record: a per-line POST would turn a chatty
agent into a request storm against the operator's own stack. Lines accumulate and flush on whichever
comes first — a line count, a byte budget, or a short interval — each a named default (Constitution
VIII).

**Fail-open is not a nicety here, it is the gate.** FR-007a forbids log export from slowing, blocking
or failing a run. The exporter therefore runs **off the agent's critical path**: the tee writes to a
buffer the exporter drains, and an exporter that is slow, wedged or dead loses log lines rather than
applying back-pressure to the agent. A blocked write that stalled an agent would make observability
the thing that broke the work, which inverts the entire point of the dual stack.

**The cap and its marker.** FR-008's per-run ceiling exists because an agent in a loop can print
without bound, and an unbounded stream would evict the rest of the stack's retention window — the
run that printed most would erase the runs that mattered. On reaching the cap, export stops and
writes one explicit truncation marker naming where it stopped. 016's rule applies exactly: the trail
may be incomplete, never misleadingly complete.

**Alternatives considered.** A runtime log driver (`--log-driver`) shifts the work to the daemon but
is configured per runtime, differs between docker and podman, and would put the correlation
identifier — which is generated *inside* the container by 016 — out of reach. A sidecar collector
adds a container and a dependency to do what `curl` already does.

---

## R3 — Reading back out of the stack, and the vendor-coupling line

**Decision: the interpreter queries the telemetry stack's Loki API with `curl`, and this is
permitted **only** because the stack is one the tool created. Querying an operator's own collector
remains forbidden.**

**Rationale.** There is a real tension to resolve rather than skate over. 017 refuses to query the
operator's collector during `reconcile` — that is "the vendor coupling this feature refuses" — and
makes the operator supply collector ids instead. This feature must read telemetry back, so the line
has to be drawn explicitly or it will be crossed by accident later.

The line 023 already drew is the right one: 023's ingest probe queries Loki directly
(`/loki/api/v1/query_range`) because it is probing **a stack this tool created, running an image the
tool names by default**. The coupling is to the tool's own artifact, not to the operator's
infrastructure. 024 sits on that same side of the line, which is why the spec makes a tool-managed
stack a prerequisite rather than an option: an interpreter pointed at an arbitrary `otlp_endpoint`
would have to learn that backend's query API, and that is the coupling 017 refuses.

**Consequence.** Deploying an interpreter without a reachable tool-managed stack is a **refusal with
the stack named**, not a degraded mode — the project's standing rule that absence must never look
like a decision.

**Alternatives considered.** Reading the run-record volumes directly would avoid the query API but
gives no logs (they are only in the stack), needs a runtime client to reach remote volumes — the
very thing FR-020 keeps out of the container — and would reintroduce drain-on-contact timing.

---

## R4 — Where the interpreter's own state lives

**Decision: interpretations and notification bookkeeping are OTLP signals written to the stack as
they are produced.**

**Rationale.** This resolved a contradiction latent in the spec. FR-017 requires the
"already reported" set to survive the interpreter's container (Constitution I), and the obvious
mechanism — a runs volume drained by the tool, as 016 does — cannot satisfy it. **016 drains on
contact**, when an operator runs a command. An interpreter's whole purpose is to work while the
operator is asleep; eight unattended hours would leave eight hours of bookkeeping inside the one
container whose loss the requirement exists to survive.

Writing to the stack makes the state durable at the moment it is produced, queryable beside the
records it refers to, correlated by the same run identifier, and pruned by the same retention — so
it needs no second lifecycle, no second store and no new drain path.

**The cost is named, not hidden.** The stack's ingest is unauthenticated by design (023), so anything
that can reach it can forge an interpretation — and a forged interpretation is worth more to an
attacker than a forged record, because the operator reads it as an assessment. Exposure is the only
control, as 023 already states; the default keeps it off the network; and every interpretation
carries the identity of the interpreter claiming it, so an impostor is distinguishable rather than
silently merged. Authenticating the ingest would be a change to 023, and belongs there.

**Alternatives considered.** The interpreter's own runs volume — fails the timing argument above.
The operator's machine — unreachable from a remote host by a container that holds no host identity,
and the laptop is closed at 2am, which is the scenario.

---

## R5 — Proving the interpreter cannot act

**Decision: two independent guarantees — a structural one from the image, and a
call-graph reachability test in the style of Feature 013's `doctor` guard.**

**Rationale.** FR-020 asks for an absence, and FR-020a forbids leaving a dormant path toward the
future feature that will add authority. A negative security property is precisely the kind that
quietly stops being true, so it needs a test that fails when it does.

**The structural half is already true and was verified, not assumed:** `image/Dockerfile` installs
**no container runtime client** — neither `docker` nor `podman` — which is the arrangement 017
documents from the other side when it explains that the control-plane image needs both clients
because "without one, `detect_runtime()` dies and every management command refuses". An interpreter
is that sentence applied deliberately: no client, no daemon, no management, regardless of what any
log tells it to do. It is additionally never given the control plane's standing key, so it has no
host identity either.

**The test half** walks the transitive closure of `__code__.co_names` from the `interpret` command
group and asserts that no mutating helper is reachable — the same technique that proves `doctor` is
read-only by composition rather than read-only on the paths a test happened to exercise. That
distinction is the whole value: it catches the future edit that adds a call, not merely the calls
that exist today.

**And the guard must be shown to fail.** `bin/tests/test_guards_can_fail.py` exists because a guard
nobody has seen fail is a guard nobody knows works. The reachability assertion gets an entry there.

---

## R6 — Named defaults this feature introduces

Constitution VIII requires each to be named at the surface and reported, with absence distinguishable
from default. Values are starting points for `/speckit-tasks` to pin, not yet contractual.

| Setting | Proposed default | Why this value |
|---|---|---|
| channel poll interval | 15s | 4 req/min against a 50+/min custom-app allowance (R1); meets SC-010 with margin. |
| trail poll interval | 30s | SC-001 allows 5 minutes; 30s keeps the notification prompt without polling the stack hard. |
| stall window | 20 min | Long enough that a slow build is not called stalled; short enough to matter overnight. FR-015b reports duration and last output rather than a judgement. |
| per-run log cap | 10 MB | Bounded against 023's 10 GB stack ceiling so one chatty run cannot evict the fleet's history. |
| export batch flush | 100 lines / 64 KB / 2s | Whichever first; keeps a chatty agent from becoming a request storm. |
| notifiable events | the FR-015 set | Quiet by default: success that pushed does not interrupt (FR-015a). |
| digest | off | Opt-in; an unasked-for daily message is noise until the operator wants it. |

---

## Open questions deferred to `/speckit-tasks`

- Exact OTLP attribute names for the interpretation and bookkeeping signals — contract-level detail,
  settled in `contracts/otlp-payloads.md` and pinned by a test, not a research question.
- Whether the bridge invokes the agent per event or keeps a session — an implementation tradeoff
  with no bearing on any FR; both satisfy the evidence-binding requirement.
- Slack message formatting (blocks versus plain text) — presentation, constrained only by FR-016's
  required fields.
