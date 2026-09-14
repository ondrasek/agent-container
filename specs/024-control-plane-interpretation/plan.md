# Implementation Plan: Interpreting control plane

**Branch**: `024-control-plane-interpretation` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/024-control-plane-interpretation/spec.md`

## Summary

A fourth **role** — `interpreter` — on the existing agent image: an agent that reads the fleet's
trail out of a telemetry stack, decides what warrants the operator's attention, says so on Slack,
and answers when asked. Two supporting changes make that possible: the agent's **output stream**
becomes a third exported payload class beside records and egress events (US2), and the interpreter's
own **interpretations and notification bookkeeping** become a fourth, written back to the same stack
as they are produced (FR-012b).

Everything is built from what is already in the tree. The entrypoint already composes OTLP resource
attributes and exports by speaking the protocol with `curl`; the agent image already bakes `curl`,
`jq` and `python3`; 023 already queries Loki with `curl` for its ingest probe; `ROLES` is already a
tuple the CLI branches on. **No new third-party dependency, no new image, and no new inbound port.**

The feature's security property is an absence, and the absence is structural: the agent image
contains **no container runtime client** (verified — `image/Dockerfile` installs neither `docker` nor
`podman`), and an interpreter is never given the control plane's standing key. A container with no
runtime client and no host identity cannot stop, start or destroy anything, whatever it is told to
do by a log it is reading. That is FR-020 satisfied by construction rather than by conduct.

## Technical Context

**Language/Version**: Python 3.14 (the single-file PEP 723 CLI, `bin/agent-container`); bash for the
entrypoint; Python 3 **stdlib only** (`urllib`, `json`) for the in-container bridge.

**Primary Dependencies**: none new. In the CLI, `typer`/`questionary`/`rich`/`pyyaml` as today. In
the container, `curl`, `jq` and `python3` — all already installed by `image/Dockerfile` (lines 39,
47, 49). **Explicitly rejected**: any Slack SDK, any WebSocket client, any OTLP library.

**Storage**: no new store. Interpretations and notification bookkeeping are OTLP signals written to
the telemetry stack; run records and their volumes are unchanged; per-host state directory as today.

**Testing**: `pytest` for unit/contract tiers in `bin/tests/`, acceptance tests behind
`-m acceptance`, and the shell suites for entrypoint behaviour. A **call-graph reachability test**
in the style of `doctor`'s (Feature 013) carries FR-020a.

**Target Platform**: docker and podman, local and remote hosts, rootless, via compose generated and
run on the target host (ADR 0001).

**Project Type**: CLI tool + container orchestration.

**Performance Goals**: an event reaches the operator's phone within **5 minutes** of its record
landing (SC-001); an answer to a question returns within **1 minute** (SC-010). Both are met with a
wide margin by a 15-second poll.

**Constraints**: no new third-party Python dependency (Constitution VI); no inbound port on the
interpreter; no credential in the deployment description (Constitution IX); log export must not be
able to slow or fail a run (FR-007a); the interpreter must hold nothing that can change the fleet
(FR-020).

**Scale/Scope**: one or two interpreters; tens of environments across a handful of hosts; log volume
bounded per run by a named cap (FR-008).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|---|---|
| **I. Ephemerality** | **Load-bearing, and it drove a design decision.** FR-017 needs the "already reported" set to survive the container; 016's drain-on-contact could not deliver that for a supervisor running unattended overnight. Resolved by writing bookkeeping to the stack as produced (FR-012b). The interpreter holds nothing whose loss matters. |
| **II. Least Privilege, Immutable Runtime** | PASS. No new capability, no root, no runtime client, sshd as `dev` as today. Everything the bridge needs is baked at build. |
| **III. Least Exposure** | **Load-bearing.** Two new exposures: a Slack bot token (an injected credential, delivered per IX, never baked/argv/printed) and — larger — **task text and agent output leaving the operator's trust domain** into a Slack workspace. Not mitigated away; stated before it applies (FR-024a) and recorded in the threat model as 023's T15 crossing a boundary it had not crossed. |
| **IV. Deterministic Identity** | PASS. An interpreter is named, port-allocated and inventoried like any environment; the shared-namespace rule (023 FR-009a) applies unchanged. |
| **V. Durable Spec, Disposable Code** | PASS. Verification targets behaviour — a notification arrives, an action does not — not the bridge's internals. |
| **VI. Least Dependencies** | **THE GATE, and it decided the channel mechanism.** Socket Mode requires an `xapp-` app-level token *and a WebSocket*; Python has no stdlib WebSocket client, so Socket Mode costs a third-party dependency in a project whose one dependency is PyYAML. HTTPS polling of `conversations.history` has the same "no inbound port" property at zero dependency cost. See research R1. |
| **VII. Continuous Deployment** | PASS. Conventional Commits; `feat` → minor. Breaking changes stated in the body, since pre-1.0 they land as MINOR. |
| **VIII. Defaults Belong at the Surface** | **Load-bearing.** Named defaults required for: poll interval, stall window, notifiable-event set, digest schedule, per-run log cap, notification budget. Each named, each reported, absence distinguishable from default (FR-013 makes this a behaviour, not just a convention). |
| **IX. Secrets to the Container, Not Through Its Description** | **Load-bearing.** The Slack bot token and the stack address travel to the running interpreter over its own sshd. Never in the compose model, never on argv, never in a record or `--json` payload. Withdrawable without destroying the interpreter (FR-005). |
| **X. Surgical Change** | **First feature under this principle.** Log export lands beside existing OTLP attribute composition in `image/entrypoint.sh` (~line 1442) — code dense with comments recording measured failures. Those comments are not to be shortened, and adjacent code is not to be tidied. Every changed line traces to an FR. |

**Gate result: PASS.** Three principles (III, VI, IX) are load-bearing rather than satisfied by
absence, and one (I) changed the design. No violations to justify; Complexity Tracking stays empty.

**Reconciliation with 017's image invariant.** 017 forbids an agent CLI in the **control-plane
image** so that "no agents here" is readable off the artifact. An interpreter does not touch that
image: it is the **agent** image with a narrower credential set, which is the opposite arrangement
and leaves the census — parameterised over every Dockerfile, failing on one it has no expectation
for — passing unchanged, because this feature adds no Dockerfile.

## Project Structure

### Documentation (this feature)

```text
specs/024-control-plane-interpretation/
├── spec.md              # /speckit-specify + /speckit-clarify output
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1
│   ├── cli-surface.md
│   ├── otlp-payloads.md
│   └── channel.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks output — not created here
```

### Source Code (repository root)

```text
bin/
├── agent-container            # ROLE_INTERPRETER; `interpret` command group; deploy-time
│                              # statement of what it holds; inventory role + scope + channel
└── tests/
    ├── test_cli.py            # role surface, named defaults, refusals
    ├── test_pure_logic.py     # notification policy, watermark, evidence binding
    ├── test_guards_can_fail.py# the FR-020a reachability guard fails when it should
    ├── test_acceptance.py     # end-to-end: notify, answer, refuse, catch up
    └── test_entrypoint.sh     # log export: correlation, cap + marker, fail-open

image/
├── Dockerfile                 # bake the bridge script; no new package
├── entrypoint.sh              # tee agent output to the log exporter (beside existing OTLP attrs)
└── interpret-bridge.py        # NEW: stdlib-only loop — read stack, run agent, post, write back

docs/
├── interpretation.md          # NEW: the feature's own page
├── observability.md           # logs are now a third payload class
├── control-plane.md           # how an interpreter differs from a 017 control plane
└── threat-model.md            # reconcile: new channel, new credential, trust-domain crossing
```

**Structure decision**: the CLI change is a role plus a command group in the existing single file;
the container change is one new baked script plus a tee in the existing entrypoint. No new image, no
new package, no new directory tier.

## Phase 2 approach (what `/speckit-tasks` will decompose)

Ordered so that each user story is independently demonstrable, per the spec's priorities:

1. **US2 first, despite US1 being the headline.** Log export is the input everything else reads, and
   it has standalone value the moment it lands (logs outlive the container). Entrypoint tee →
   batching exporter → cap and truncation marker → `runs show` naming the stack.
2. **The stack as a read surface.** A guarded query path (023's `curl` idiom) plus the watermark,
   with the vendor-coupling boundary written down: the tool queries **a stack it created**, never an
   arbitrary operator collector (research R3).
3. **US1 — notification.** Policy over the trail, evidence binding, the Slack write path, the
   bookkeeping signal, catch-up after absence.
4. **US3 — conversation.** The poll loop, sender admission, grounded replies, degraded-input
   precedence.
5. **US5 — resistance.** Injected-instruction handling and record-versus-log contradiction, with the
   adversarial acceptance tests that carry SC-005.
6. **US4 — it is a container this tool created.** Inventory role/scope/channel, kill switch, deploy
   time statement, version skew.
7. **US6 — digest and silence.** The quiet-by-default tuning surface.
8. **Docs + threat model reconciliation**, which the constitution makes part of the change, not a
   follow-up.

FR-020a's guard (no partial action path) is written **with** step 3, not after it, because its whole
value is preventing a path from existing in the first place.

## Constitution re-check (post-design)

**Principle VI held, and it chose the mechanism.** The dependency question was not "may we add a
Slack SDK" but the quieter one underneath: Socket Mode's WebSocket requirement makes a dependency
*unavoidable* if Socket Mode is chosen. Discovering that before writing code is why the channel is
HTTPS polling — the same no-inbound-port property, reachable with the `curl` the image already has.

**Principle I changed the design rather than merely passing.** See the Constitution Check table.

**Principle III got more specific, not easier.** Writing the payload contracts made the trust-domain
crossing concrete: the notification body carries the task text and quoted log spans, so "task text
leaves the workspace boundary" is not an abstract risk but a named field in a documented payload.
FR-024a's pre-creation statement is the control, and it is worded against a specific payload rather
than a general worry.

**Principle X is satisfiable but needs naming in the tasks.** The entrypoint edit sits in the
densest commented region of the tree. The tasks must say "add beside, do not restructure", because
the failure mode is an agent tidying what it passed on the way.

## Complexity Tracking

> No Constitution Check violations. Table intentionally empty.
