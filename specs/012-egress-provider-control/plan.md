# Implementation Plan: Egress and Provider Control

**Branch**: `012-egress-provider-control` | **Date**: 2026-07-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-egress-provider-control/spec.md`

## Summary

Let an operator declare which model providers an environment may reach, enforce that with an
**egress proxy sidecar**, and disclose the built-in default provider that motivated the feature.

Phase 0 answered the question the clarification said would decide whether enforcement is real:
**all four supported agents honour proxy environment variables** — verified by running each one
against a black-holed proxy, not read from documentation. So FR-008's honest-strength statement is
*"enforced for all four"*, which is materially stronger than the spec dared assume.

Two findings shape the design beyond what the spec anticipated:

- **The proxy must not terminate TLS** (research R2). Allowlisting works on the `CONNECT` target,
  before TLS is established, so decryption is unnecessary — and a decrypting proxy would see every
  `Authorization` header, creating a new plaintext credential location inside the very component
  meant to improve least-exposure.
- **`NO_PROXY` is the bypass** (research R3). An operator env-file setting it wide would silently
  disable the feature while the declaration still reads as enforced. That is the most likely
  silent failure and needs a test, not a doc line. The tool therefore refuses **any** operator
  `NO_PROXY` under an enforced declaration and **attempts no subset comparison** — deciding
  "is this wider?" across `*`, `.suffix`, IP, CIDR and port forms would err permissively and
  reproduce the bypass it exists to prevent.

## Technical Context

**Language/Version**: Python ≥ 3.14 (single-file CLI) · POSIX shell (entrypoint) · Compose v2
model generation · a proxy image (sidecar)

**Primary Dependencies**: one new **runtime** dependency — a forward-proxy image capable of host
allowlisting without TLS interception. No new Python dependency.

**Storage**: egress records reuse Feature 016's container-writes / tool-ingests pattern (R5).

**Testing**: hermetic `pytest` for the declaration, mapping, compose model and `NO_PROXY`
precedence; acceptance for the real refusal path against a live sidecar.

**Target Platform**: rootless container, local or remote host, unchanged.

**Performance Goals**: none. The proxy sits in the request path, so it must not be pathologically
slow, but no target is set.

**Constraints**:

- **No added privileges** — the proxy is a separate container; the agent container is untouched
  except for environment variables.
- **No TLS interception** (R2) — a Constitution III requirement, not a preference.
- **The proxy must refuse, never drop** (R1a) — a refusal produces a clean client error; a drop
  produces the hangs observed for `claude` and `opencode`.
- **`NO_PROXY` precedence belongs to the tool** (R3).

**Scale/Scope**: `bin/agent-container` (declaration parsing, provider→host mapping, compose model,
sidecar generation, `NO_PROXY` control), the declarative spec schema, docs, and tests.

## Constitution Check

| Principle | Gate | Verdict |
|---|---|---|
| **I. Ephemerality** | No dependence on uncommitted container state | **PASS** — the proxy is stateless; its records follow 016's durable path |
| **II. Least Privilege, Immutable Runtime** | Rootless, nothing added at runtime | **PASS** — enforcement lives in a *sidecar*, so the agent container gains no privileges, no packages, and (because of R2) no CA certificate |
| **III. Least Exposure** | No secret exposed | **PASS, and improves — conditional on R2.** No TLS termination means the proxy never sees an `Authorization` header. A decrypting proxy would have *inverted* this principle while claiming to serve it |
| **IV. Deterministic Identity** | Names derived, never stored | **PASS *if* FR-010 defers (R9)** — the proxy joins the existing compose project and changes no name. But an egress-record volume would be a **tenth** per-container volume, which the identity lock treats as a migration. Deferring FR-010 to Feature 016's store keeps this a PASS |
| **V. Durable Spec, Disposable Code** | Spec is the durable artifact | **PASS** — spec clarified before planning; R1 strengthened a claim rather than contradicting one |
| **VI. Least Dependencies** | Justify every new dependency | **PASS with a named cost** — a proxy image is added. It is the only way to enforce egress without privileges, and it is **optional**: absent a declaration, no sidecar is deployed |
| **VII. Continuous Deployment** | Gate green; Conventional Commits | **PASS** — `feat`, additive, no breaking change |

**No unjustified violations.** R2 is what keeps Principle III on the right side of the ledger; if
TLS interception were ever introduced, this gate would flip.

## Project Structure

### Documentation (this feature)

```text
specs/012-egress-provider-control/
├── spec.md            # clarified 2026-07-29
├── plan.md            # this file
├── research.md        # R1 (verified, all four honour) · R2 (no TLS) · R3 (NO_PROXY)
├── data-model.md
├── contracts/
│   └── egress-contract.md
├── quickstart.md
└── checklists/requirements.md
```

### Source Code (repository root)

```text
bin/agent-container      # provider declaration parsing + validation
                         #   provider→host mapping table (R6)
                         #   sidecar generation into the compose model
                         #   NO_PROXY precedence and refusal (R3)
                         #   `--json` exposure of the permitted set (FR-013)
bin/tests/               # declaration, mapping, NO_PROXY precedence, agent-honours fixture,
                         #   compose model, acceptance refusal path
image/                   # unchanged — the agent image gains nothing
docs/                    # credentials.md (providers vs credentials), a new egress section
```

**Structure decision**: no new module. The sidecar is generated data, not code; the proxy itself
is an off-the-shelf image, not something this project builds.

## Design decisions carried into tasks

1. **The proxy allowlists on `CONNECT`, never decrypts** (R2) — the Constitution III linchpin.
2. **The proxy refuses rather than drops** (R1a) — refusal yields a clean client error; dropping
   yields the observed hangs.
3. **The tool owns `NO_PROXY`** (R3) and refuses **any** operator value under an enforced
   declaration, comparing nothing. This is the most likely silent failure in the feature, and a
   subset check would fail permissively while passing its own tests.
4. **The known-honours-proxy list is a test fixture, not a comment** (R7) — a newly added agent
   must fail that test rather than silently inherit "honours".
5. **The proxy is a second service in the model the tool already generates** (R4 revised, after
   reading the code) — *not* in the operator's `<name>.services.yaml`. That file is validated as
   services-only and forbidden from redefining `agent`; it is operator-owned by design. The
   generated file is the tool's, so a service added there inherits the project, the lifecycle and
   teardown for free, and the operator override still layers on top.
6. **Egress records reuse Feature 016's store** (R5, R9) — see phasing below.

## Two consequences not visible in the spec

**FR-010 needs a volume, and a tenth volume is a migration (R9).** The identity contract pins nine
per-container volume names; `--purge`, `wipe` and both completions read that list, and the identity
lock test fails on a tenth *by design*. That volume should be paid for **once**, by whichever
feature ships it first — expected to be 016, since the storage-and-ingestion machinery is its
subject. 012's egress events then reuse **that store**, keeping **their own schema**: a different
producer (the proxy, not the agent) and a different lifetime (continuous, not at-run-end), and
016's FR-011a already establishes that a distinct concern gets a distinct schema.

**Recommended phasing**: ship US1 (declaration + enforcement) and US2 (disclosure) — both P1,
neither needs FR-010 — and deliver US3/FR-010 after 016 lands. US3 is already P2 for exactly this
reason. The alternative, a throwaway ingestion path plus an announced identity migration, costs
more and is discarded later.

**Headless foreground changes shape (R4).** `--abort-on-container-exit --exit-code-from agent`
stops every service when any one exits, so a crashing proxy now aborts the agent run. Fail-closed
and correct, but a behaviour change for headless users that must be stated, not discovered.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| A proxy image is added to deployments | The only way to enforce egress without adding privileges (Constitution II forbids packet filtering) | Configuring agents' own provider lists is advisory only, and R1 shows a proxy makes enforcement real for all four agents. **This justification is generic and must be re-run against the concrete image (T002a)** — size, provenance and maintenance cadence are properties of the choice, not of the category |
| A second service appears in the generated compose model | Inherits the project, lifecycle and teardown the model already guarantees | The operator override channel is validated services-only and forbidden from redefining `agent` — tool material there would clobber an operator file or need a third `-f` |
