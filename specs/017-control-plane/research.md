# Phase 0 Research: Control-Plane Container

Every finding below was checked against the code as it exists. **Two contradict the spec**, and one
of those inverts a stated consequence — the spec predicts a test will fail, and it will silently
pass instead, which is worse.

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

## R4 — The registry is configuration, not a credential, so it rides an existing channel

**Finding**: the control plane must know *which* hosts to query (R6/Q1's live enumeration needs
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
control-plane image alike without either carrying Python telemetry code.

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

**Finding**: Q2 settled that nesting is supported and that a nested control plane inherits **no**
reach, because FR-007b makes authorising a key an explicit act. So there is nothing to prevent.

**Decision**: no gate. The work is FR-014a's **visibility** — the listing must show provenance
(operator machine vs which control plane), which is a field on the inventory entry, not a check.

**What this rules out**: any "subset scope" enforcement. Scope is where the key is authorised, which
lives outside the container by design (FR-004), so a parent cannot constrain a child even in
principle — and pretending otherwise in code would be a control that does not control.

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
