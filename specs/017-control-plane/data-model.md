# Phase 1 Data Model: Control-Plane Container

Five entities from the spec, plus the telemetry record the widened export needs. Two of them hold
material nothing else in this tool holds.

---

## 1. `Control plane`

An environment whose role is management. It **is** an ordinary environment — same naming, ports and
volumes (Constitution IV) — distinguished by a role and the material it carries.

| Field | Notes |
|---|---|
| `name` | the environment name; the usual identity contract |
| `role` | `control-plane` vs `agent`. **Persisted on the inventory entry** so FR-009 can identify it without inspecting the container, which a stopped one would defeat |
| `provenance` | `operator` \| `control-plane:<name>` — where it was deployed *from* (FR-014a) |
| `permitted_hosts` | the declared scope, visible **before** deploy (FR-004, SC-004) |
| `image` | the narrower control-plane image (FR-015a), version-stamped like the agent image |

**`provenance` exists because nesting is supported.** A standing key can now be minted from inside a
session, so the count and origin of standing keys must be readable — a count nobody can see is a
count nobody audits (SC-011).

**`permitted_hosts` is a DECLARATION, not an enforcement point.** Actual reach is wherever the public
key is authorised (FR-004), which lives outside the container on purpose. The field exists so the
operator can see intent before deploying and compare it against reality afterwards; treating it as
the boundary would be a control that does not control.

---

## 2. `Control-plane keypair`

| Field | Notes |
|---|---|
| private half | generated **in-container**, `0600`, **passphrase-encrypted at rest** on the control plane's own volume. The tool has no channel for it and never sees it |
| public half | read out by the existing capture; authorised wherever the control plane must reach (FR-007b) |
| lock state | **locked** whenever no operator is attached (FR-007a) |

**Persisting deliberately** (against Constitution I's grain, and correctly): this is *identity*, not
work. Regenerating per boot would invalidate every authorisation the operator made, so the volume is
the right home and `--purge` is the revocation boundary.

---

## 3. `Passphrase`

**Not a field. Not stored anywhere by the tool.** Modelled here only to state what must never
happen to it.

| Property | Rule |
|---|---|
| origin | generated **in-container** at first deploy |
| transit | crosses to the tool **once**, within the scope of the printing call |
| destination | the operator's password manager. Nowhere else |
| forbidden | any file, any log, any run record, any `--json` payload, any variable outliving the print, any telemetry export |
| recovery | **none** (FR-017). Redeploy mints a fresh keypair; the old public half is withdrawn via FR-008 |

**This is the narrow exception to Constitution III in this feature**, and it is the one thing in the
data model with no durable representation on purpose. Anything that gives it one is a defect, not an
enhancement — including a well-meant "save it for me" flag.

---

## 4. `Session`

An operator's SSH connection. The key is unlocked for its duration and locked when it ends.

**Two sessions are not modelled as sharing an unlocked key.** Each supplies the passphrase; nothing
caches it between sessions, because a cache is a place the passphrase lives (§3).

---

## 5. `Permission scope`

Which hosts the control plane may reach, and what it may do there. Declared (§1) and **enforced
outside the container** by where the public key is authorised — which is what makes revocation
concrete: withdraw the key (FR-008).

---

## 6. `Telemetry record`

What leaves a container for the operator-declared OTLP endpoint (FR-009d–g). A **closed** set.

| Exported | Source |
|---|---|
| `environment`, `host`, `agent`, `kind`, `run_id`, `started_at`, `ended_at`, `outcome`, `exit_code` | tool |
| `repository` | git (SHAs and paths) |
| `usage` | agent — numbers under identifier-shaped keys only |
| `task` | **operator** — exported **by default** (FR-009f), excludable **by name** |
| `attribution` | which control plane performed the action (FR-009a) |
| `egress_decision` | Feature 012 events |

**`task` is exported because a task is not a credential channel** (FR-009f0). Credentials arrive by
injection; the only exception is the SSH keys a container generates itself. Withholding the field
would design around operator error the tool already provides the correct alternative for — and it is
the single most useful field for *"this run failed, what was it doing"*, on a phone, without a laptop
to correlate against.

**The exclusion is by NAME, never by pattern.** A redactor that misses one value converts caution into
false confidence (T12/T15); omitting a named field either happens or it does not. The switch exists
because the tool cannot know whether the collector is the operator's own VPS or a shared corporate
backend — trust domains the operator can distinguish and the tool cannot.

**`run_id` is always exported**, so a record at the collector can always be matched to its local
counterpart — which is what makes the optional exclusion cheap rather than lossy.

**No second free-text field may be added** (FR-009c). `RECORD_FIELD_PROVENANCE` has exactly one
`operator` row across fourteen fields and a test asserts the table, because that closure *is* the
no-credentials claim: a second free-text field falsifies it while every other test still passes.

---

## What is deliberately NOT modelled

- **A passphrase store, cache, or escrow.** FR-017 makes loss unrecoverable by design; a recovery
  path is by definition a way to obtain the key without the passphrase.
- **A control-plane-local inventory.** It enumerates live (FR-003a). A second durable source would
  drift from the operator's, and 014 deliberately has one.
- **Subset-scope inheritance for nested control planes.** Scope is where the key is authorised, so a
  parent cannot constrain a child even in principle (research R8).
- **A redaction filter.** See §6.
