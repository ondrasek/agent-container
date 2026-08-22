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

## 6. `Record` — the one payload both legs carry

**Defined ONCE.** The same field set governs the OTLP export and the local trail `collect` retrieves
(FR-009f). Two definitions would drift the moment one is edited, and **the drift would be invisible**
— each leg still looks correct on its own.

Three classes, one shape: the **attribution records** (FR-009a), Feature 016's **run records**, and
Feature 012's **egress events**.

| Field | Provenance | Notes |
|---|---|---|
| `environment`, `host`, `agent`, `kind`, `run_id`, `started_at`, `ended_at`, `outcome`, `exit_code` | `tool` | |
| `repository` | `git` | SHAs and paths |
| `usage` | `agent` | numbers under identifier-shaped keys only |
| `task` | **`operator`** | exported **by default**; excludable **by name** (§7) |
| `attribution` | `tool` | which control plane performed the action (FR-009a) |
| `egress_decision` | `tool` | Feature 012 events |
| **`export_state`** | `tool` | §7 — `tool` provenance, so it does **not** touch FR-009c's single `operator` row |

**`task` is exported because a task is not a credential channel** (FR-009f0). Credentials arrive by
injection; the only exception is the SSH keys a container generates itself. Withholding it would
design around operator error the tool already provides the correct alternative for — and it is the
single most useful field for *"this run failed, what was it doing"*, on a phone, with no laptop to
correlate against.

**No second free-text field may be added** (FR-009c). `RECORD_FIELD_PROVENANCE` has exactly one
`operator` row and a test asserts the table, because that closure *is* the no-credentials claim: a
second free-text field falsifies it while every other test still passes.

**`run_id` is always exported**, whatever the `task` setting, so a record at the collector can always
be matched to its local counterpart — which is what makes the optional exclusion cheap rather than
lossy.

---

## 7. `Export state`

Four values on every record (FR-009h). Export is fail-open and always on, so **partial export is a
designed-in condition, not an error**.

| Value | Means | Retry? |
|---|---|---|
| `pending` | written; not yet resolved with the endpoint | **yes** |
| `accepted` | the **configured endpoint** returned success **for this record** | no |
| `rejected` | the endpoint explicitly refused it | **no** — it will refuse again unchanged |
| `failed` | unreachable, or an error | **yes** — it may be back later |

**`accepted` means endpoint-accepted and NOTHING MORE.** It must not be read, or named, as arrival at
a backend: establishing that requires querying the backend's own API — the vendor coupling FR-009d
forbids. The state claims only what the client can see.

**A 2xx response is not acceptance.** OTLP's export response carries `partial_success` with a
rejected-record count, so a receiver may return success while refusing records. An implementation
**must subtract those** before marking anything `accepted`, or it marks refused records as delivered.

**`rejected` and `failed` are distinct because they decide whether retrying helps.** Collapsing them
would either retry forever against a refusal or abandon a recoverable record.

**Derived from the response, never from the attempt** (FR-009i). Distinguishing attempt from outcome
is the entire purpose of having the state.

**State transitions**: `pending` → `accepted` | `rejected` | `failed`. `failed` → `pending` on a
`collect` retry. **`accepted` and `rejected` are terminal** — re-exporting an accepted record would
duplicate it at the collector, and re-exporting a rejected one repeats a refusal.

---

## 8. Reconciliation

Not an entity — a comparison, modelled here because its scope is the part that gets wrong.

Over a **defined window** — since the last successful `reconcile`, or an operator-supplied range — the
set of records marked `accepted` locally equals the set the collector holds, **or the difference is
reported** (SC-020).

**`pending` records are OUTSIDE the window.** They have not finished being exported; counting not-yet
as disagreement would make the criterion fail against a healthy system.

This comparison is only expressible because both legs carry identical payloads (§6). *"Do they
agree?"* has no answer when they carry different things.

---

## What is deliberately NOT modelled

- **A passphrase store, cache, or escrow.** FR-017 makes loss unrecoverable by design; a recovery
  path is by definition a way to obtain the key without the passphrase.
- **A control-plane-local inventory.** It enumerates live (FR-003a). A second durable source would
  drift from the operator's, and 014 deliberately has one.
- **Subset-scope inheritance for nested control planes.** Scope is where the key is authorised, so a
  parent cannot constrain a child even in principle (research R8).
- **A redaction filter.** The task text is exported or excluded **by name** (§6). A filter that misses
  one value converts caution into false confidence; omitting a named field either happens or it does
  not.
- **An "ingested" or "confirmed" state.** Not observable without querying a backend (§7).
- **A second puller.** `collect` is `drain` generalised, not a parallel mechanism (research R13).
