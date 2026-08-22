# Phase 0 Research: Control-Plane Container

Regenerated 2026-08-20, after two clarification sessions moved the spec from 20 FR / 10 SC to
**32 FR / 22 SC** and added the dual-stack observability. **R2 and R3 are carried through verbatim**
— both are discoveries about the codebase rather than inferences re-derivable from the spec, and
re-deriving them would risk losing the finding.

Every other decision below was re-checked against the code as it stands.

---

## R1 — The CLI IS NOT IN THE IMAGE. FR-002 is the largest unbuilt piece.

**Finding**: `image/Dockerfile` installs the *agent* CLIs (claude, codex, pi, opencode) and **not
`agent-container` itself** — verified: no `pip install`, no `uv tool install`, no `agent_container`
anywhere but a comment about `PATH`.

So FR-002's "SSH in and find a working, configured CLI" is not a matter of pointing the existing
container at a registry. **The tool has to be installed into the control-plane image**, which is
new work and carries a consequence the spec already half-anticipates: the image now pins a CLI
version, and FR-016's semver rule is what governs the gap between that and the environments it
manages. The two requirements are the same problem seen twice.

**Decision**: install from **PyPI at a pinned version** (`agent_container==<v>`), stamped into the
image by the same label Feature 013 added (FR-012a's `org.opencontainers.image.version`), so
`doctor` and FR-016 read one source.

**Alternative rejected**: install from the checkout. The build context **is** `image/` by
construction (Feature 011), so the checkout is not reachable from it — and widening the context to
grab it would undo a deliberate narrowness that exists because the context crosses the network to a
possibly-remote daemon.

---

## R2 — The spec's claimed test failure is backwards, and that is the dangerous direction

**The spec says**: *"the existing cross-file test asserting the Dockerfile installs exactly the
supported agents must learn that the control-plane image installs none — it would otherwise fail,
correctly, on a second Dockerfile that omits them."*

**Finding**: it would **not** fail. `test_dockerfile_installs_exactly_the_canonical_agents` reads a
hardcoded path:

```python
body = (_ROOT / "image" / "Dockerfile").read_text()
```

A second Dockerfile is **invisible** to it. The test keeps passing, and the new image — the one
holding keys to everything — is simply never checked.

**This is the project's recurring defect** (a check that passes while the thing it names is
unexamined), and the spec predicted the safe failure mode rather than the real one.

**Decision**: the test must be **parameterised over every Dockerfile in the repo**, each with a
declared expectation — the agent image installs exactly `AGENTS`, the control-plane image installs
**none** — and must **fail when it finds a Dockerfile it has no expectation for**. That last clause
is the load-bearing one: it is what makes a third image impossible to add unnoticed.

**Consequence for SC-009** ("the control-plane image contains zero agent CLIs — verified by
inspecting the built image, not by reading its build definition"): the spec is right to demand the
built image. Keep both — the source-level census catches an added install line at review time, the
image-level check catches one that arrives some other way.

---

---

## R3 — The passphrase is the one place the tool touches a secret, and the spec does not say how

**Finding**: FR-007 requires the tool to print a passphrase "exactly once" and never store it. But
Feature 019's generator uses `-N ''` (no passphrase), and the tool's existing capture reads the
**public** half. Reading a passphrase out means the tool handles a secret — the direction
Constitution III exists to prevent, and the clarification's "the tool never handles the private
key" is true while quietly not covering this.

Three ways, none free:

| Route | Cost |
|---|---|
| Container generates it; tool reads it out once through the runtime | The tool holds a secret in memory transiently. Never written, never logged, but it is on the tool's side of the line. |
| Operator supplies it at deploy | Worse: it arrives on argv or in an env file, both of which the credential rules forbid for exactly this reason. |
| Container prints it to its own stdout at first boot; operator reads it with `logs` | The tool never holds it — but the container log driver **persists** it, so the secret is durable in a place nothing rotates. |

**Decision**: **the first** — generated in-container, read out once through the runtime, held only
in the printing call's own scope, never assigned to anything that outlives it, never in a record,
never in `--json`. It is the only route where the durable copy exists **nowhere**: not on the
operator's disk, not in a log, only in their password manager once they save it.

**And it must be stated as a deliberate narrow exception**, not left implied — the tool touching a
secret for the duration of one print is a real amendment to Constitution III's posture, and the
threat model row must say so rather than repeating "the tool never handles the private key", which
is true and beside the point.

---

---

## R4 — The registry is configuration, not a credential, so it rides an existing channel

**Finding**: the control plane must know *which* hosts to query (FR-003a's live enumeration needs
targets). Host records live in the registry on the operator's machine — names, drivers, contexts,
addresses. None of that is secret; the **capability** is the authorised key, not the list.

**Decision**: inject the registry as **non-secret configuration** through the existing injected
config channel, inline in the compose model (`configs: {content:}`), the same way every other
non-secret injected artifact travels. No new mechanism.

**Consequence worth stating**: the injected registry is a **snapshot**. A host registered after
deployment is invisible until redeploy — which is FR-016's "host registry has drifted" edge case,
and the spec already separates it from a version mismatch.

---

## R5 — `curl` is already in the image, so OTLP export needs no dependency at all

**Finding**: `image/Dockerfile` installs `curl`. OTLP over HTTP with JSON encoding is a POST of a
JSON document (FR-009d).

**Decision**: a container exports with `curl`. **Zero** additions to the four Python packages, and
zero additions to the image. The `opentelemetry-sdk` is permitted by FR-009d but is not reached for,
because the dependency-free path is sufficient — which is the condition FR-009d set.

**Consequence**: export is shell-level in the entrypoint, so it works in the agent image and the
control-plane image alike without either carrying Python telemetry code. It is also what makes
FR-009g's **write-time** trigger natural rather than imposed: a `curl` POST has no long-lived
process to flush, so there is nothing to batch.

---

## R6 — Reuse 015's self-exclusion rather than inventing FR-010

**Finding**: Feature 015's `panic` already enumerates from the inventory, stops by compose project
label, and **verifies by observation**, treating an unverified outcome as `undetermined` rather than
success. FR-010's "refuse to act on itself, exclude it, say so" is one more exclusion in that
machinery, not a new mechanism.

**Decision**: implement FR-010 as an exclusion inside the existing `panic` path, identified by the
control plane's own container name, and **report the exclusion as a first-class outcome** — not as
a silent skip. SC-010 measures the report, not the skip, and those differ.

---

## R7 — Narrow output is a real constraint on an existing habit

**Finding**: the CLI builds `rich` tables (`Table(...)` with six columns for `list`). `rich`
auto-detects terminal width and will wrap or truncate at 80 columns; it does not fail, but a
six-column table at 80 columns is unreadable, which SC-007 measures as "legible".

**Decision**: management commands used from a control plane get a **narrow rendering** — one record
per block rather than a wide row — selected by measured width, not by a flag. A flag would put the
burden on the operator who is already on a phone.

**Alternative rejected**: relying on `--json` plus a phone-side viewer. That makes the human path
the degraded one, on the device the feature exists for.

---

## R8 — Nesting needs no enforcement code, only visibility

**Finding**: nesting is supported and a nested control plane inherits **no** reach, because FR-007b
makes authorising a key an explicit act. So there is nothing to prevent.

**Decision**: no gate. The work is FR-014a's **visibility** — the listing must show provenance
(operator machine vs which control plane), which is a field on the inventory entry, not a check.

**What this rules out**: any "subset scope" enforcement. Scope is where the key is authorised, which
lives outside the container by design (FR-004), so a parent cannot constrain a child even in
principle — and pretending otherwise in code would be a control that does not control.

---

## R9 — `accepted` is the strongest claim the client can make, and 2xx is not it

**Finding, and the reason FR-009h reads as it does**: end-to-end ingestion is **not observable** to
an exporting container. Establishing that a backend indexed a record requires querying that
backend's own API — the vendor coupling FR-009d forbids ("no backend-specific package, ever"). And
"sent" is nearly worthless: a POST that was refused is still sent.

**Decision**: `accepted` means **the configured endpoint returned success for that record**, and the
spec says explicitly it must not be read or named as arrival at a backend.

**The trap, stated because it would otherwise be implemented wrong**: OTLP's export response carries
a **`partial_success`** field with a rejected-record count, so a receiver may return **200 while
refusing records**. Treating 2xx as acceptance marks those `accepted` — a check that passes while the
thing it names is broken. An implementation must subtract the rejected count first.

*Confidence: high that OTLP defines `partial_success` on export responses; the exact field shape is
version-dependent and should be pinned against the OTLP version targeted at implementation time.*

**Consequence for testing**: only a collector **configured to refuse** a subset exposes the naive
implementation. A compliant collector passes either way, which is why SC-021 specifies a refusing
one rather than "a collector".

---

## R10 — `rejected` and `failed` must stay distinct, because they decide whether to retry

**Finding**: the two failure modes call for opposite responses. An explicitly refused record will be
refused again unchanged — retrying is waste. An unreachable endpoint may simply be back later —
retrying is the whole recovery path.

**Decision**: four states, not three. `pending` · `accepted` · `rejected` · `failed`, with
`collect` retrying **`pending` and `failed`** only (FR-009h). Collapsing them into one "not
delivered" state would either retry forever against a refusal or abandon a recoverable record.

**Provenance**: the export state is `tool`-provenance, so it does **not** touch FR-009c's
single-`operator`-row closure. That closure is the whole of the no-credentials claim, and a test
asserts the table itself.

---

## R11 — One payload definition, or the two legs drift invisibly

**Finding**: FR-009e and FR-009d both carry the attribution records, Feature 016's run records and
Feature 012's egress events. Two lists that agree today drift the moment one is edited, **and the
drift is invisible** — each leg still looks correct on its own.

**Decision**: a single field-set definition that both legs read, asserted on the shared constant
rather than by comparing two lists. It is also the precondition for SC-020: "do the legs agree?" has
no answer if they carry different things.

---

## R12 — Reconciliation needs a defined window, and `pending` is outside it

**Finding**: SC-020 compares the locally-`accepted` set against the collector's. Two ways that
fails for the wrong reason: an undefined window makes the comparison unexecutable, and counting
`pending` records as divergence makes it fail against a healthy system that simply has exports in
flight.

**Decision**: the window is **since the last successful `collect`, or an operator-supplied range**,
and `pending` records are **outside** it. Both now stated in SC-020 rather than left to an
implementer.

**SUPERSEDED IN IMPLEMENTATION — and by measurement, not by preference.** "Since the last successful
`collect`" is unusable: `collect` ingests records **written before it ran**, so a watermark set at
collect time puts every record it just gathered *below* the lower bound. The acceptance tier showed
it: `local_accepted: 0` against `collector_holds: 2` on a healthy system, with the collector's own
ids reported as `unknown_locally`.

The boundary that bounds a **comparison** is the previous comparison, so `reconcile` keeps its own
watermark and advances it only on agreement. C17, SC-020 and the data model now say `reconcile`. This
entry is left standing rather than edited, because the decision was genuinely made here and what it
cost is part of the record — R12 identified the right *risk* (an undefined window) and picked a
boundary that could not carry it.

---

## R13 — `drain` and `collect` are the same act, and only one should exist

**Finding**: Feature 016's `drain_host_records` already *"ingests pending records for `<names>` on
`<host>`"* — a pull from host volumes into the operator's store. `telemetry collect` (FR-009e) is
that, generalised to three record classes and made an explicit operator-invoked command.

**Decision**: **`collect` is `drain` generalised.** One mechanism, wider scope, invocable directly.
`drain`'s existing incidental-on-contact behaviour stays as-is for run records; `collect` is the
deliberate, complete, all-classes pull with per-host reporting.

**Why not two**: two pullers of the same volumes will diverge on which records they consider
pending, and the divergence surfaces as records that one path collects and the other does not —
diagnosable only by reading both implementations.

*Open in analyze as finding F6; recorded here as the decision, so the implementation does not have to
rediscover it.*

---

## Summary — what this feature must NOT do

1. Assume the CLI is present in the image (R1).
2. Trust the agent-census test to notice a second Dockerfile (R2).
3. Let the passphrase reach a disk, a log, a record, or `--json` (R3).
4. Treat the injected registry as live (R4).
5. Add a telemetry dependency when `curl` is already there (R5).
6. Reimplement `panic`'s verification to add self-exclusion (R6).
7. Ship a six-column table to a phone (R7).
8. Write scope-enforcement code that cannot enforce (R8).
9. **Treat a 2xx as acceptance** (R9) — `partial_success` must be subtracted first.
10. **Collapse `rejected` and `failed`** (R10) — they decide whether retrying helps.
11. **Define the payload twice** (R11) — the drift would be invisible.
12. **Reconcile without a window, or count `pending` as divergence** (R12).
13. **Build a second puller alongside `drain`** (R13).
