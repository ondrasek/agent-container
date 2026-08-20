# Contract: the control plane, and the telemetry export

Each clause is testable and names the failure it prevents.

---

## Commands

```
agent-container up <name> --role control-plane [--hosts a,b] [--json]
agent-container ssh-key show <name>              # the public half to authorise (019, reused)
agent-container revoke <name> [--json]           # withdraw its key everywhere (FR-008)
agent-container telemetry collect [--host H]     # always available (FR-009e)
```

`doctor`, `list`, `runs`, `panic` and `inventory` all work **inside** a control plane; that is the
feature.

## C1 — The CLI is present and configured on arrival

SSH in from a device with **nothing installed** and find a working `agent-container` that knows the
operator's hosts (FR-002, SC-001).

> *Fails without this*: the CLI is **not** in any image today (research R1). This is a build, not
> configuration, and forgetting it turns the feature into an empty container with a nice name.

## C2 — Enumeration is LIVE, and an unreachable host is named

The environment list comes from querying permitted hosts on connect (FR-003a). A host that does not
answer MUST be reported as unreachable, never omitted (SC-002).

> *Fails without this*: a short list that looks complete is worse than an error — the operator acts
> on absence.

## C3 — The keypair is minted in-container and the tool never handles the private half

Generated on first deploy, `0600`, **passphrase-encrypted at rest** (FR-007). The tool has no channel
for the private key.

## C4 — The passphrase touches nothing durable

Printed **exactly once**, held only within the printing call. MUST NOT appear in any file, log, run
record, `--json` payload, or telemetry export (FR-007, data-model §3).

> **The narrow Constitution III exception in this feature.** Every alternative route puts it
> somewhere durable: operator-supplied means argv or an env file; printing to the container's log
> means the log driver keeps it. Verified by grepping every artifact after a deploy, not by reading
> the print statement.

## C5 — Locked whenever nobody is attached

Interactive-only; the passphrase is supplied **on connect** (FR-007a). After a host reboot it comes
back locked, which is harmless because it has no unattended work.

## C6 — Public-key authorisation is always an explicit act

Never implicit in deployment (FR-007b). Deploying a control plane grants it **nothing**; capability
begins where its public key is authorised.

> This is what makes nesting safe (FR-014a) and revocation meaningful (FR-008).

## C7 — Revocation is one command, not N hosts

Withdraw the public key across every host and container that trusts it (FR-008, SC-005).

## C8 — It appears in the inventory, with its role and provenance

Identified as a control plane, and showing whether it was deployed from the operator's machine or
from another control plane (FR-009, FR-014a, SC-011).

## C9 — A stop-everything action from inside EXCLUDES ITSELF and says so

Refuse to act on its own container, exclude it from the run, report the exclusion, and name how to
stop it instead (FR-010, SC-010).

> *Fails without this*: it is the one container whose stopping makes the report undeliverable — so
> self-exclusion is what makes "the outcome is never unknown" achievable at all. Reported, not
> silently skipped: those differ, and only the report is checkable.

## C10 — Version mismatch: semver precedence, and a direction

PATCH differences (and post-1.0 minor) are **ignored**. A breaking-channel difference is **advisory**
when the control plane is newer, and **REFUSED** when the environment is newer. Unreadable version ⇒
**unknown**, never assumed compatible (FR-016, SC-012).

> `major_on_zero = false`, so **pre-1.0 a breaking change lands as MINOR** — not obvious from the
> numbers, which is why it is in the contract.

## C11 — Legible at 80 columns

Every management command (FR-011, SC-007). Selected by measured width, not by a flag: the operator is
already on a phone.

## C12 — The image carries NO agent CLIs, verified on the built image

The control-plane image installs the CLI, ssh, tmux and git, and **no agent CLIs or runtimes**
(FR-015a, SC-009).

> **And the source-level census must be parameterised over every Dockerfile, failing on one it has no
> expectation for** (research R2). The existing test hardcodes `image/Dockerfile`, so a second image
> would be *invisible* to it — the suite stays green while the container holding keys to everything
> goes unchecked. The spec predicted a failing test; the real risk is a passing one.

## C13 — Two legs, one payload definition

The local trail and the OTLP export carry **identical payloads from a single field-set definition**
(FR-009f): the attribution trail, Feature 016's run records, Feature 012's egress events.

> *Fails without this*: two lists that agree today drift the moment one is edited, and **the drift is
> invisible** — each leg still looks correct alone. It also makes C17's reconciliation
> unexpressible: "do they agree?" has no answer if they carry different things.

## C14 — `accepted` means endpoint-accepted, and 2xx is not enough

Every record carries an export state: `pending` · `accepted` · `rejected` · `failed` (FR-009h).
**`accepted` means the configured endpoint returned success for that record and nothing more** — it
MUST NOT be read or named as arrival at a backend.

OTLP's export response carries **`partial_success`** with a rejected-record count. An implementation
MUST subtract those before marking anything `accepted`.

> *Fails without this*: a receiver returning 200 while refusing records gets its refusals recorded as
> deliveries — a check that passes while the thing it names is broken. **Verified against a collector
> configured to REFUSE a subset** (SC-021): a compliant collector passes either way, so only a
> refusing one exposes it.

## C15 — `rejected` and `failed` stay distinct

They decide whether retrying helps: a refusal will be refused again unchanged; an unreachable
endpoint may be back later. `collect` retries **`pending` and `failed`** only (FR-009h).

Both are derived from the response, **never from the fact that an export was attempted** (FR-009i) —
distinguishing attempt from outcome is the state's entire purpose. `accepted` and `rejected` are
terminal.

## C16 — Export fires at write time, per record

Not batched at exit, not on a timer (FR-009g). Verified by **`SIGKILL`** on a running container:
every record whose export **completed** before the kill is at the collector (SC-022).

> *Fails without this*: anything held for later is lost exactly when a container is killed, which is
> the case an audit trail exists for. And a **graceful** stop would pass against an exit-time batch —
> the implementation this clause rejects — so the test must kill.

A record POSTed whose response has not arrived stays `pending`. That is correct, not a loss;
`collect`'s retry settles it.

## C17 — The two legs reconcile, over a defined window

Over a window — **since the last successful `collect`, or an operator-supplied range** — the set of
locally-`accepted` records equals the collector's, **or the difference is reported** (SC-020).
**`pending` records are outside the window.**

> *Fails without this*: a dual stack whose halves can silently diverge is two unreliable stacks. And
> counting `pending` as divergence would fail the criterion against a healthy system with exports in
> flight.

## C18 — `collect` is always available, lands in the durable store, and is the only puller

Available **whether or not** an endpoint is declared (FR-009e) — the local record exists
unconditionally, so its retrieval must too. Records land in `$XDG_DATA_HOME/agent-container/`
(`0600`) where `runs`/`egress` already read, with **per-host ingest counts** and **every unreachable
host named**.

It is Feature 016's `drain` **generalised**, not a second mechanism (research R13).

> *Fails without this*: a collection that silently skipped a host reads as a complete trail; and two
> pullers of the same volumes diverge on what they consider pending, diagnosable only by reading both.

## C18a — The task text: exported by default, excluded by name

Exported by default, because a task is **not a credential channel** (FR-009f0) — credentials arrive
by injection, the SSH keys being container-generated. Excludable **by name**, never by a
pattern-matching redactor. `run_id` exports regardless, so correlation always survives.

> *Fails without this*: a redactor that misses one value converts caution into false confidence
> (T12/T15). **SC-017 tests both positions** — a switch verified in one position may not be wired.

## C18b — Export adds no dependency, and none may be added

OTLP/HTTP+JSON is a POST of a JSON document and `curl` already ships (research R5). **Zero** Python
packages; **no backend-specific package, ever** (FR-009d) — the condition the OTel dependency was
accepted under. The endpoint is declared at **either config level, project winning**.

## C18c — Export is fail-open, and the gap is reported

An unreachable or undeclared collector degrades to the local record and **reports the gap**; it never
blocks the work (FR-009d).

> *Fails without this*: under enforced egress an undeclared collector produces an **empty** collector,
> which reads exactly like a quiet system — the most misleading outcome an audit trail can have.

## C18d — Each container exports its own

An agent's records reach the collector with **no control plane deployed** (FR-009g, SC-018).

> *Fails without this*: export gets built as control-plane plumbing, which is what widening 017
> risked and what the spec explicitly warns against.

## C18e — No second operator-free-text field

`RECORD_FIELD_PROVENANCE` keeps exactly one `operator` row, asserted on the table itself (FR-009c).
The export state is `tool`-provenance and does not touch it.

> *Fails without this*: a second free-text field falsifies the no-credentials closure while every
> other test still passes.

## C19 — Consequences stated BEFORE deployment

That a session holds whatever the container holds; that the passphrase has **no recovery**; what the
declared scope is (FR-006, FR-017, SC-004).

---

## Non-goals, as contract

- No web UI, HTTP API, or non-SSH surface.
- No passphrase store, cache or escrow — FR-017 makes loss unrecoverable **by design**.
- No agents in the control plane — structural via C12, not documentary.
- No subset-scope enforcement for nested control planes: scope is where the key is authorised, so a
  parent cannot constrain a child even in principle.
- No backend-specific telemetry package, and no destination the tool chooses.
