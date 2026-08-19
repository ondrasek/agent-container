# Contract: the control plane, and the telemetry export

Each clause is testable and names the failure it prevents.

---

## Commands

```
agent-container up <name> --role control-plane [--hosts a,b] [--json]
agent-container ssh-key show <name>              # the public half to authorise (019, reused)
agent-container revoke <name> [--json]           # withdraw its key everywhere (FR-008)
agent-container telemetry collect [--host H]     # the no-endpoint path (FR-009e)
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

## C13 — Telemetry export: closed set, `task` included by default, excludable by name

Exports attribution, run records and egress events over **OTLP** to an operator-declared endpoint
(FR-009d–g). `task` is exported by default because a task is **not** a credential channel (FR-009f0),
and may be excluded **by name** — never by a pattern-matching redactor.

> *Fails without this*: a redactor that misses one value converts caution into false confidence
> (T12/T15). Omitting a named field either happens or it does not, and SC-017 tests **both**
> positions — a switch verified in one position may not be wired.

## C14 — Export adds no dependency and no privilege

OTLP/HTTP+JSON is a POST of a JSON document and `curl` already ships in the image (research R5).
**Zero** Python packages added; **no** backend-specific package, ever (FR-009d).

## C15 — Export is fail-open, and the gap is reported

An unreachable or undeclared collector degrades to the local record and **reports the gap**; it never
blocks the work (FR-009d).

> *Fails without this*: under enforced egress an undeclared collector produces an **empty** collector,
> which reads exactly like a quiet system — the most misleading outcome an audit trail can have.

## C16 — Each container exports its own

An agent's records reach the collector with **no control plane deployed** (FR-009g, SC-018).

> *Fails without this*: export gets built as control-plane plumbing, which is what widening 017
> risks and what the spec explicitly warns against.

## C17 — Correlation always survives

`run_id` is exported regardless of the `task` setting, so a collector record can always be matched to
its local counterpart (FR-009f, SC-019).

## C18 — No second operator-free-text field

`RECORD_FIELD_PROVENANCE` keeps exactly one `operator` row across fourteen fields, asserted by a test
on the table itself (FR-009c).

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
