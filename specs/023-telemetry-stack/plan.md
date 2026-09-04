# Implementation Plan: Telemetry stack container

**Branch**: `023-telemetry-stack` | **Date**: 2026-09-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/023-telemetry-stack/spec.md`

## Summary

Add a third kind of container the tool manages — a telemetry stack — behind a
`telemetry stack` subgroup (`up`, `ls`, `url`, `dashboards`, `remove`). It runs one all-in-one
observability image, waits until the OTLP ingest actually **accepts a record** before reporting
success, provisions the tool's dashboards over the Grafana API, and reports the endpoint an *agent
container* must use — which is not the address the operator uses.

The approach is deliberately additive: reuse the existing host resolution, compose generation,
per-host state, inventory and `panic` machinery, and add a kind to them rather than a parallel
mechanism. The one genuinely new thing is an exposure decision, because this is the first container
the tool would publish as a listening service.

## Technical Context

**Language/Version**: Python 3.14 (the single-file PEP 723 CLI, `bin/agent-container`)

**Primary Dependencies**: none new. `typer`/`questionary`/`rich`/`pyyaml` already present; the stack
image is *run*, not linked (Principle VI). HTTP calls use `curl` via subprocess, as Feature 017 does.

**Storage**: per-host state directory (compose file, allocated ports) as for agent environments; the
stack's own data on a named volume it owns; inventory records in the existing durable store.

**Testing**: `pytest` — unit/contract tests in `bin/tests/` (no containers), acceptance tests behind
`-m acceptance` (real containers), plus the completions parity test.

**Target Platform**: docker and podman, local and remote hosts, via compose generated and run on the
target host.

**Project Type**: CLI tool + container orchestration.

**Performance Goals**: `up` reaches "ingest accepting" within 180s including a cold image pull
(FR-006a); measured warm start ~10s, cold pull 60–90s.

**Constraints**: no new third-party Python dependency; `configs: {file:}` must not be used (does not
cross a remote context); default exposure must not be routable; dashboards must be re-provisionable
without redeploying.

**Scale/Scope**: several stacks per host; a handful of hosts. Not a production observability system —
a bounded developer/operations aid (spec Assumptions).

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design.*

| Principle | Verdict | Reasoning |
|---|---|---|
| **I. Ephemerality** | ✅ | The stack is disposable and explicitly *not* a system of record (Assumptions). Its data is bounded by retention (FR-025) and its loss costs nothing authoritative — the local trail written by 017 remains the durable baseline, and export never replaced it. |
| **II. Least Privilege, Immutable Runtime** | ✅ | Runs a fixed upstream image with no build-time mutation and no runtime reshaping. Needs no `NET_ADMIN`, no privileged mode, no host mounts. It is *less* privileged than the egress sidecar the tool already runs. |
| **III. Least Exposure** | ⚠️ **Load-bearing** | The stack holds no credentials and is given none (FR-004). But it **displays verbatim task text** exported by 017, in a UI with no login — so exposure *is* this feature's least-exposure question. Answered by `host` default (FR-018a), explicit `network` opt-in with a stated consequence (FR-019), and no widening as a side effect (FR-020). |
| **IV. Deterministic Identity** | ✅ | FR-009a puts stacks in the single per-host name namespace; ports allocated by the existing mechanism (R7), so N stacks coexist without collision. |
| **V. Durable Spec, Disposable Code** | ✅ | This spec plus `docs/telemetry-stack.md` carry the intent; the implementation is regenerable from them. |
| **VI. Least Dependencies** | ✅ **with a recorded caveat** | No package enters the tool. The tool continues to export by speaking OTLP with `curl` — it does not link a backend SDK. What *is* added is a container image the project does not build, recorded in the 023 threat-model row as T9's shape applied to infrastructure. |
| **VII. Continuous Deployment** | ✅ | Conventional Commits; `feat(telemetry-stack)` → minor. No manual release step. |
| **VIII. Defaults Belong at the Surface** | ✅ | Every default is named and overridable: image, exposure level, readiness budget (180s), retention window and ceiling, ports. FR-018b additionally requires the *resolved* addresses to be reported, so a named level cannot hide what bound. |
| **IX. Secrets Travel to the Container, Not Through Its Description** | ✅ | Nothing secret is staged, inlined or delivered. The stack has no credential channel at all (FR-004) — which is why exposure replaces it as the security question rather than adding to it. |

**Gate result: PASS.** One principle (III) is load-bearing rather than satisfied-by-absence, and the
design answers it explicitly. No violation requires justification in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```
specs/023-telemetry-stack/
├── spec.md              # what and why (32 FRs, 8 SCs)
├── plan.md              # this file
├── research.md          # Phase 0 — eight measured findings
├── data-model.md        # Phase 1 — entities and state
├── contracts/
│   └── cli.md           # Phase 1 — the command surface contract
├── quickstart.md        # Phase 1 — runnable validation
└── checklists/
    └── requirements.md  # spec quality checklist (16/16)
```

### Source Code (repository root)

```
bin/agent-container            # + STACK_* constants, telemetry_stack_app group,
                               #   stack compose model, endpoint resolution,
                               #   readiness probe, dashboard provisioning
bin/tests/
├── test_pure_logic.py         # + endpoint resolution, level→address mapping,
                               #   name-namespace collision (pure, no containers)
├── test_compose.py            # + stack compose model shape
├── test_cli.py                # + group surface, flags, -v injection
├── test_acceptance.py         # + real stack: up/ls/url/dashboards/remove,
                               #   readiness, two-on-one-host, panic, inventory
└── test_completions.sh        # + parity for the new verbs
completions/
├── agent-container.bash       # + telemetry stack verbs and flags
└── agent-container.zsh        # + same, mirrored
docs/
├── telemetry-stack.md         # new: the third kind, exposure, endpoints
├── observability.md           # + pointer: where to send it, not just how
└── threat-model.md            # 023 row exists; reconcile ⬜ → ✅ at implementation
CLAUDE.md                      # + one line under Decisions (budget: prune first)
```

**Structure decision**: everything lands in the existing single-file CLI and its existing test tiers.
No new module, no new package, no second mechanism for hosts, state, inventory or `panic` — a third
kind those subsystems already know about is the whole point, and a parallel path would give the kill
switch something it does not know to stop.

## Phase 2 approach (what `/speckit-tasks` will decompose)

Ordered so each step is independently verifiable, and so the riskiest thing is proved earliest:

1. **Endpoint and exposure resolution, pure.** `level → published addresses` and
   `stack → endpoint an agent container uses`, per runtime. Pure functions, unit-tested with no
   containers. This is R1/R6 territory and the single most likely thing to be silently wrong, so it
   is first and it is testable without deploying anything.
2. **The kind exists.** Constants, name-namespace collision (FR-009a), per-host state, compose model
   for the stack, inventory record with its kind.
3. **`up`.** Pull with a report, deploy, readiness probe by accepted record (R2), stage-aware timeout
   (FR-006b), restart-if-stopped (FR-007), retention applied and asserted back (R3/FR-025b).
4. **`url` and `ls`.** Both addresses, tunnel hint, ingest-answering status.
5. **Dashboards.** Provision over the API (R4), textbox run selector (R5), `dashboards` re-provision,
   failure reported without failing the deploy (FR-016).
6. **`remove`.** Stop, delete, retain data unless asked, state the consequence for exporters.
7. **Fleet integration.** `panic` stops stacks; unreachable ⇒ `undetermined`. Inventory outcome.
8. **Surface parity and docs.** Both completions, `docs/telemetry-stack.md`, threat-model
   reconciliation ⬜ → ✅.
9. **Real-agent validation.** An agent environment configured against a tool-created stack, its
   telemetry read back through the stack's own API — the end-to-end claim SC-003 makes.

## Constitution re-check (post-design)

Re-evaluated after Phase 1. **Still PASS**, with two things the design surfaced that the pre-Phase-0
check could not have seen:

**Principle III got harder, and the design got more specific in response.** Writing the data model
made explicit that the stack displays verbatim task text (017 exports it by default) in a UI with no
login. That is not new information, but it moves exposure from "a setting" to "the security question
of the feature": the default level is `host` rather than `loopback` *because* containers must reach
it, which means the default already binds more than loopback on some runtimes. FR-018b — report the
resolved addresses — is what keeps that from being a silent widening, and it exists because the
design forced the question.

**Principle VIII gained a requirement.** Naming exposure levels (a clarification decision) hides the
address behind a word. Constitution VIII says a reader must be able to tell absent from defaulted
from declared; a level satisfies that for the *intent* and defeats it for the *effect*. Reporting the
resolved addresses restores it. This is why the clarification was integrated as two requirements
rather than one.

Nothing else changed. No new dependency entered the tool (VI), no secret channel was created (IX),
and the kind reuses the identity, inventory and kill-switch machinery rather than paralleling it
(IV).

## Complexity Tracking

No constitutional violation requires justification.

One deliberate complexity is recorded because it is a cost rather than a violation: **the endpoint
has two forms** (operator-facing and container-facing) and the tool must compute both. A simpler
design with one address exists and is wrong on at least one supported runtime — and wrong in the
silent direction, since export fails open. The two-form design is carried because collapsing it
produces exactly the failure this feature exists to prevent.
