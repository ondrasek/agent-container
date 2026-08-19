# Implementation Plan: Control-Plane Container

**Branch**: `017-control-plane` | **Date**: 2026-08-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/017-control-plane/`

## Summary

An SSH-reachable container holding a **configured** `agent-container` CLI, so the management surface
is something you attach to from a phone rather than something that lives only on your laptop. It
mints its own passphrase-protected keypair, enumerates hosts live, refuses to stop itself, and — as
of this feature — carries the tool's **telemetry export** for every container, not just for itself.

**This is the highest-risk feature in the roadmap and the risk is located, not vague**: one key spans
a sandbox shell and machine-level daemon access, and whoever holds the volume *and* the passphrase
holds both. The spec accepts that deliberately. What the plan adds is that **three of the pieces
this feature needs do not exist yet** — the CLI is not in any image, no second image exists, and no
generator produces a passphrase-protected key.

## The decisions this plan settles first

### 1. The CLI has to be installed into an image. It is not there today.

`image/Dockerfile` bakes the *agent* CLIs and **not `agent-container`** (verified — research R1). So
FR-002 is not configuration work; it is a new build. Installed from **PyPI at a pinned version**, and
stamped with Feature 013's `org.opencontainers.image.version` label so `doctor` and FR-016 read one
source rather than two.

Installing from the checkout is not available: the build context **is** `image/` by construction
(Feature 011), and widening it would undo a narrowness that exists because the context crosses the
network.

### 2. The agent-census test will NOT fail on a second image — it will silently not cover it

The spec predicts this test *"would otherwise fail, correctly"*. It would not:
`test_dockerfile_installs_exactly_the_canonical_agents` reads a **hardcoded** `image/Dockerfile`
(R2). A second Dockerfile is invisible to it, so the image holding keys to everything goes unchecked
while the suite stays green.

So the test is **parameterised over every Dockerfile in the repo**, each with a declared expectation,
and **fails when it finds one it has no expectation for**. That last clause is the point: it makes a
third image impossible to add unnoticed. SC-009's built-image check stays alongside it — source
census catches an added install line at review, image inspection catches one that arrives another
way.

### 3. The passphrase is the one place the tool touches a secret, and that must be said

FR-007 has the tool print a passphrase once. Feature 019's generator uses `-N ''`, and the existing
capture reads the **public** half — so this is a new direction: a secret crossing to the tool's side.
The clarification's "the tool never handles the private key" is true and does not cover it.

Chosen route (R3): generated **in-container**, read out **once** through the runtime, held only
within the printing call's own scope. Never assigned to anything that outlives it, never in a record,
never in `--json`, never in a container log. It is the only route where the durable copy exists
**nowhere** but the operator's password manager.

The operator-supplied alternative is worse (argv or env file, both forbidden for exactly this), and
printing to the container's own log makes the secret durable where nothing rotates it.

**The threat model row must state this narrow exception** rather than repeating a claim that is true
about the key and silent about the passphrase.

### 4. Telemetry export needs no dependency, because `curl` is already in the image

OTLP/HTTP+JSON is a POST of a JSON document, and `curl` is installed (R5). Export is therefore
**shell-level in the entrypoint**, works in both images, and adds **zero** Python packages —
satisfying the condition FR-009d set when the OTel dependency was accepted.

### 5. Nesting needs visibility, not enforcement

A nested control plane inherits no reach, because authorising a key is an explicit act outside the
container (FR-007b). There is nothing to gate. The work is FR-014a's provenance field on the
inventory entry (R8). Any "subset scope" enforcement would be a control that cannot control, since
scope lives where the key is authorised.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI, POSIX shell entrypoint.

**New dependencies**: **none**. OTLP rides `curl` (R5); `opentelemetry-sdk` is permitted by FR-009d
but not reached for, because the dependency-free encoding suffices.

**New build artifacts**: a **second image** (`image-control-plane/`), narrower than the agent image —
CLI, ssh, tmux, git, **no agent CLIs** (FR-015a).

**Storage**: the control plane's own volume holds its encrypted keypair. No new store on the
operator's machine; telemetry goes to an operator-declared OTLP endpoint, and the local records are
Feature 016's existing ones.

**Testing**: hermetic for the semver rule, the exit/severity mapping, the export field set and the
provenance closure; acceptance for what only real containers show — a second image with no agents, a
key that survives reboot locked, self-exclusion under `panic`, and export arriving at a collector.

**Constraints**:
- **The passphrase reaches no disk, log, record or `--json`** (FR-007, R3).
- **`task` is not a credential channel** (FR-009f0) — which is why its text *is* exported.
- **No backend-specific package, ever** (FR-009d) — the condition the OTel dependency was accepted
  under.
- **Self-exclusion is reported, not silent** (FR-010, SC-010).
- **Legible at ≤ 80 columns** (SC-007).

**Scale/Scope**: one operator, single-digit hosts, tens of environments, one or two control planes.

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS, with the wrinkle named.** The keypair deliberately survives recreate; it is identity, not work. `--purge` rotating it is correct rather than lossy, and FR-017 makes redeploy the recovery. |
| **II. Least Privilege, Immutable Runtime** | **PASS, and strengthened.** The narrower image (FR-015a) makes "no agents here" structural. No new capability; still rootless. |
| **III. Least Exposure** | **PASS with a stated, narrow exception.** The private key is container-generated and never handled. The **passphrase** transits the tool for the duration of one print (R3) — a real amendment, recorded rather than glossed. Against that: a standing key is the largest grant the tool has ever made, which is why FR-004/FR-006/FR-008 exist. |
| **IV. Deterministic Identity** | **PASS** — a control plane is an environment; naming, ports and volumes are unchanged. |
| **V. Durable Spec, Disposable Code** | **PASS** — four clarification sessions; every decision above is in the spec, not only here. |
| **VI. Least Dependencies** | **PASS.** OTel accepted at the protocol level only; **zero** packages added, because `curl` already ships. |
| **VII. Continuous Deployment** | **`feat`, MINOR.** Additive: a new command, a second image, an export path. Nothing removed; no flag changes meaning. |

**Threat model (Development Workflow, MUST)**: 017 **introduces a new trust boundary** — the row must
record the standing key spanning two privilege levels, the passphrase's transit through the tool
(R3), the export path as a new outbound channel governed by a Feature 012 declaration, and the
residual that a compromised control plane can act until its key is withdrawn. Reconciled in the same
change, not after.

## Project Structure

```text
bin/agent-container            control-plane deploy + the `--role`/kind distinction; passphrase
                              generation and one-shot print; live host enumeration; FR-016's semver
                              rule; self-exclusion in `panic`; narrow rendering; OTLP export config;
                              the FR-009e collect command; revocation across hosts (FR-008)
image-control-plane/          the SECOND image: CLI from PyPI, ssh, tmux, git, NO agent CLIs
image/entrypoint.sh           passphrase-protected keygen; shell-level OTLP export via curl
bin/tests/test_control_plane.py   semver rule, export field set, provenance closure, self-exclusion,
                              scope resolution, narrow rendering
bin/tests/test_pure_logic.py  PARAMETERISE the agent census over every Dockerfile, and fail on one
                              with no declared expectation (R2)
bin/tests/test_acceptance.py  second image has no agents (built image, SC-009); key survives reboot
                              locked; panic self-exclusion; export reaches a collector; task text
                              present by default and absent when excluded (SC-017 both positions)
docs/control-plane.md         the surface, the passphrase contract, revocation, the export
docs/observability.md         the export: what leaves, what never does, the declared endpoint
docs/threat-model.md          the 017 row — new trust boundary (Constitution MUST)
CLAUDE.md                     one line; the file has ~7 tokens of headroom, so it DISPLACES
```

**Structure Decision**: a second image directory rather than a build arg on the existing one. FR-015a
wants "no agents installed" to be a property, and a shared Dockerfile with a conditional install is a
property you have to read the build args to know.

## Phasing

**P1 — a CLI you can reach.** US1. The second image with the tool installed, the registry injected,
live enumeration, narrow output. Ends with: SSH in from an unconfigured device and list across hosts.

**P2 — bounded and revocable.** US2. The passphrase-protected keypair, the one-shot print, declared
scope, revocation across hosts, and the pre-deploy statement of consequences. **This is the phase
that makes P1 safe to have shipped.**

**P3 — coherent with itself.** US3. Inventory identity and provenance, `panic` self-exclusion, restart
without reconfiguration, the semver rule.

**P4 — telemetry.** FR-009a–g. Attribution, per-container export, the collect command. Last because
it is the widest-reaching and the least coupled to the control plane itself — and because the spec
warns it must not be built as control-plane plumbing.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A second image | FR-015a wants no-agents to be structural; this is the one container worth stealing | a build arg on the shared image — a property you must read build args to know |
| The passphrase transits the tool | FR-007 requires printing it once, and every other route puts it somewhere durable | operator-supplied (argv/env, forbidden); container log (durable, unrotated) |
| A standing key across hosts | a control plane that can inspect but not stop is a viewer | per-deployment keys — cannot reach containers created later, which is the point |
| 017 owning general telemetry export | operator chose widening over a separate feature | splitting it; rejected explicitly, and the spec warns the plan not to treat export as control-plane plumbing |
