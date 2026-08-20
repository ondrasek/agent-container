# Implementation Plan: Control-Plane Container

**Branch**: `017-control-plane` | **Date**: 2026-08-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/017-control-plane/` — 32 FR, 22 SC, four clarification
sessions.

**Regenerated** after two clarification sessions added the dual-stack observability. The previous
plan predated `FR-009h`/`FR-009i` and `SC-020`/`021`/`022` entirely; an analyze pass found it, the
data model, the contract and the quickstart all describing an older feature.

## Summary

An SSH-reachable container holding a **configured** `agent-container` CLI, so the management surface
is something you attach to from a phone rather than something that lives only on your laptop. It
mints its own passphrase-protected keypair, enumerates hosts live, and refuses to stop itself.

And — as of this feature — it carries the tool's **dual-stack observability** for *every* container,
not only for itself.

**This is the highest-risk feature in the roadmap and the risk is located, not vague**: one key spans
a sandbox shell and machine-level daemon access, and whoever holds the volume *and* the passphrase
holds both. Three of the pieces it needs **do not exist yet**: the CLI is in no image, no second
image exists, and no generator produces a passphrase-protected key.

## The decisions this plan settles first

### 1. The CLI has to be installed into an image. It is not there today.

`image/Dockerfile` bakes the *agent* CLIs and **not `agent-container`** (research R1). FR-002 is a
build, not configuration. Installed from **PyPI at a pinned version** and stamped with Feature 013's
`org.opencontainers.image.version` so `doctor` and FR-016 read one source.

### 2. The agent-census test will NOT fail on a second image — it will silently not cover it

`test_dockerfile_installs_exactly_the_canonical_agents` reads a **hardcoded** `image/Dockerfile`
(R2). A second Dockerfile is invisible to it: the suite stays green while the image holding keys to
everything goes unchecked. The spec predicted the safe failure mode; the real one is worse.

The test is **parameterised over every Dockerfile**, each with a declared expectation, and **fails on
one it has no expectation for** — the clause that makes a third image impossible to add unnoticed.

### 3. The passphrase is the one place the tool touches a secret, and that must be said

Generated **in-container**, read out **once** through the runtime, held only within the printing
call's scope (R3). Never a file, a log, a record, a `--json` payload, or a variable outliving the
print. The alternatives are worse: operator-supplied means argv or an env file, and printing to the
container's log makes it durable where nothing rotates it.

**The threat model row must state this narrow exception** rather than repeating a claim that is true
about the key and silent about the passphrase.

### 4. Two observability legs, one payload definition

The local trail is the **durable baseline** — written where the action lands regardless of any
endpoint. OTLP export is an **additional active path**. They are **independent, not alternatives**,
and they read **one** field-set definition (R11), because two lists that agree today drift the moment
one is edited and the drift is invisible: each leg still looks correct alone.

That single definition is also the precondition for SC-020 existing at all — *"do the legs agree?"*
has no answer if they carry different things.

### 5. `accepted` claims only what the client can observe, and a 2xx is not it

End-to-end ingestion is **not observable** to an exporting container; establishing it means querying
a backend's API, the coupling FR-009d forbids. So `accepted` means *the configured endpoint returned
success for this record* — and OTLP's **`partial_success`** means a receiver can return **200 while
refusing records** (R9). An implementation must subtract the rejected count before marking anything
accepted, or it marks refused records as delivered.

Consequence for testing: only a collector **configured to refuse** exposes the naive version. A
compliant one passes either way, which is why SC-021 specifies a refusing collector.

`rejected` and `failed` stay distinct because they decide whether retrying helps (R10).

### 6. Export fires at write time, because a killed container is the case that matters

Not batched at exit, not on a timer (FR-009g). Anything held for later is lost exactly when a
container is `kill -9`'d — the circumstance under which someone later asks what happened. It also
needs no resident exporter, which this project avoids on the same grounds Feature 012's boundary
runs no refresher. And it is natural rather than imposed: a `curl` POST has nothing to flush (R5).

### 7. `collect` is `drain` generalised — one puller, not two

Feature 016's `drain_host_records` already pulls pending records from host volumes into the
operator's store. `telemetry collect` is that, widened to three record classes and made an explicit
operator-invoked command (R13). Two pullers of the same volumes would diverge on what they consider
pending, and the divergence would be diagnosable only by reading both implementations.

### 8. Nesting needs visibility, not enforcement

A nested control plane inherits no reach, because authorising a key is an explicit act outside the
container (FR-007b). There is nothing to gate; the work is FR-014a's provenance field (R8). Any
"subset scope" enforcement would be a control that cannot control.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI, POSIX shell entrypoint.

**New dependencies**: **none**. OTLP rides `curl`, already in the image (R5). `opentelemetry-sdk` is
permitted by FR-009d but not reached for; **no backend-specific package, ever** — the condition the
OTel dependency was accepted under.

**New build artifacts**: a **second image** (`image-control-plane/`) — CLI, ssh, tmux, git, **no
agent CLIs** (FR-015a).

**Storage**: the control plane's own volume holds its encrypted keypair. Collected records land in
the operator's existing durable store (`$XDG_DATA_HOME/agent-container/`, `0600`) where `runs` and
`egress` already read (FR-009e) — no new store.

**Testing**: hermetic for the semver rule, the export-state transitions, the single payload
definition and the provenance closure; acceptance for what only real containers show — a second image
with no agents, a passphrase that exists nowhere, self-exclusion under `panic`, a **refusing**
collector, a `SIGKILL`, and reconciliation between the legs.

**Constraints**:
- **The passphrase reaches no disk, log, record or `--json`** (FR-007, R3).
- **`task` is not a credential channel** (FR-009f0) — which is why its text *is* exported.
- **`accepted` never means ingested** (FR-009h, R9); `partial_success` subtracted first.
- **Export is fail-open** and the gap is reported (FR-009d).
- **One payload definition** for both legs (FR-009f, R11).
- **Self-exclusion is reported, not silent** (FR-010, SC-010).
- **Legible at ≤ 80 columns** (SC-007).

**Scale/Scope**: one operator, single-digit hosts, tens of environments, one or two control planes.

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS, with the wrinkle named.** The keypair deliberately survives recreate; it is identity, not work. `--purge` rotating it is correct, and FR-017 makes redeploy the recovery. |
| **II. Least Privilege, Immutable Runtime** | **PASS, and strengthened.** The narrower image (FR-015a) makes "no agents here" structural. No new capability; still rootless. |
| **III. Least Exposure** | **PASS with a stated, narrow exception.** The private key is container-generated and never handled; the **passphrase** transits the tool for one print (R3) — recorded, not glossed. Second consideration, also recorded: the export carries the **task text by default** (FR-009f0), so a shared collector inherits it — which is why the exclusion-by-name exists and why the threat model must say so. |
| **IV. Deterministic Identity** | **PASS** — a control plane is an environment; naming, ports and volumes unchanged. |
| **V. Durable Spec, Disposable Code** | **PASS** — four clarification sessions; every decision is in the spec, not only here. This plan being regenerated *from* the spec is the principle working. |
| **VI. Least Dependencies** | **PASS.** OTel at the protocol level only; **zero** packages added, because `curl` already ships. |
| **VII. Continuous Deployment** | **`feat`, MINOR.** Additive: a command, a second image, an export path. Nothing removed; no flag changes meaning. |

**Threat model (Development Workflow, MUST)**: 017 **introduces a new trust boundary**. The row must
record the standing key spanning two privilege levels; the passphrase's transit through the tool
(R3); the export as a new outbound channel a Feature 012 declaration governs; that the exported
payload **carries the task text by default** and what that means for a collector outside the
operator's trust domain; and the residual that a compromised control plane acts until its key is
withdrawn. Reconciled in the same change, not after.

## Project Structure

```text
bin/agent-container            control-plane deploy + role/provenance; passphrase generation and
                              one-shot print; live host enumeration; FR-016's semver rule;
                              self-exclusion in `panic`; narrow rendering; revocation (FR-008);
                              ONE payload definition; the export state and its transitions;
                              `telemetry collect` as generalised drain; reconciliation
image-control-plane/          the SECOND image: CLI from PyPI, ssh, tmux, git, NO agent CLIs
image/entrypoint.sh           passphrase-protected keygen; write-time OTLP export via curl
bin/tests/test_control_plane.py   semver rule, export-state transitions, partial_success handling,
                              single-definition assertion, provenance closure, scope resolution
bin/tests/test_pure_logic.py  PARAMETERISE the agent census over every Dockerfile, failing on one
                              with no declared expectation (R2)
bin/tests/test_acceptance.py  second image has no agents (built image); passphrase exists nowhere;
                              panic self-exclusion; a REFUSING collector; SIGKILL; reconciliation;
                              task text present by default and absent when excluded
docs/control-plane.md         the surface, the passphrase contract, revocation
docs/observability.md         the dual stack: both legs, the export state, what `accepted` does NOT
                              mean, the task include/exclude
docs/threat-model.md          the 017 row — new trust boundary (Constitution MUST)
CLAUDE.md                     one line; the file has ~7 tokens of headroom, so it DISPLACES
```

**Structure Decision**: a second image directory rather than a build arg on the existing one. FR-015a
wants "no agents installed" to be a property, and a shared Dockerfile with a conditional install is a
property you have to read the build args to know.

## Phasing

**P1 — a CLI you can reach.** US1. The second image with the tool installed, the registry injected,
live enumeration, narrow output.

**P2 — bounded and revocable.** US2. The passphrase-protected keypair, the one-shot print, declared
scope, revocation, consequences stated up front. **This is the phase that makes P1 safe to have
shipped** — the spec says shipping US1 without US2 trades a security property for convenience.

**P3 — coherent with itself.** US3. Inventory identity and provenance, `panic` self-exclusion,
restart without reconfiguration, the semver rule.

**P4 — the dual stack.** FR-009a–i. **Depends only on P1's build, not on US1–US3**: an agent must
export with no control plane deployed (SC-018), and building it downstream of the control plane is
exactly what widening this feature risked.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A second image | FR-015a wants no-agents to be structural; this is the one container worth stealing | a build arg on the shared image — a property you must read build args to know |
| The passphrase transits the tool | FR-007 requires printing it once, and every other route puts it somewhere durable | operator-supplied (argv/env, forbidden); container log (durable, unrotated) |
| A standing key across hosts | a control plane that can inspect but not stop is a viewer | per-deployment keys — cannot reach containers created later, which is the point |
| 017 owning general observability | operator chose widening over a separate feature | splitting it; rejected explicitly, and the spec warns the plan not to treat export as control-plane plumbing |
| An export **state** on every record | fail-open plus always-on export makes partial export a designed-in condition; without state, "lost" and "never sent" are indistinguishable | inferring by querying the collector — makes the local leg depend on the remote one it exists to be independent of |
