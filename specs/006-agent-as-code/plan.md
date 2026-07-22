# Implementation Plan: Agent-as-Code (declarative project directory)

**Branch**: `006-agent-as-code` | **Date**: 2026-07-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-agent-as-code/spec.md`

## Summary

Add a **declarative** way to drive the whole lifecycle: a **`.agent-container/`
project directory** whose files *are* the desired state for one or more agent
environments (host binding, container(s), agent config, SSH identity, credential
references). Run the tool inside such a directory and it **discovers → validates →
plans → reconciles** reality to the spec (idempotent `apply`, `plan`/`diff`,
scoped `destroy`), reusing today's host/lifecycle/credential/provisioning
capabilities. Additive: with no `.agent-container/` present, the tool behaves
exactly as it does today (FR-004).

Technical approach (see [research.md](./research.md)):
- **Discovery** walks upward to the nearest `.agent-container/` marker and reports
  the root (FR-001).
- **Format**: the declarative files are **YAML** (operator's choice), parsed with
  **PyYAML** — the one new third-party dependency, a deliberate Constitution-VI
  exception recorded in Complexity Tracking (YAML is the expected format for
  human-authored "as-code" config; PyYAML is a single mature, ubiquitous parser).
- **Reconcile** derives a **plan** (declared vs live) and converges by driving the
  existing internals (`do_up`/`compose_up_exec`, host registry/provisioner), so the
  declarative layer is an orchestrator, not a second implementation.
- **Ownership is identity-derived** (Constitution IV) — a declared name maps to the
  tool's deterministic container/volume/host identity; "owned" = exists-with-that-
  identity; `destroy` removes only those; drift = declared-vs-live. **No state file.**
- **Credentials** are references (env / external file / OS keychain / encrypted-at-
  rest + an operator **decrypt command** run in memory) resolved at apply and
  injected via Feature 003's runtime channels — never to disk/log/registry (FR-011..016).
- **Spec integrity (FR-020)** — the governing spec is **immutable from inside the
  container**: the tool reads it only from the operator's host-side `.agent-container/`,
  and bind-mounts that authoritative subtree **read-only** over the container's
  `/workspace/.agent-container` (kernel-enforced, uid-independent), so an untrusted
  agent cannot re-govern itself or smuggle a spec change via `git push`.

## Technical Context

**Language/Version**: Python ≥ 3.14 (single-file CLI `bin/agent-container`, PEP
723). **PyYAML** (`yaml.safe_load`) parses the spec. `entrypoint.sh` gains no new
logic; the read-only `.agent-container/` mount is a compose bind the CLI adds.

**Primary Dependencies**: **one new — PyYAML** (`yaml.safe_load`), the spec parser
(operator chose YAML; the project otherwise has no YAML reader). It is added to the
PEP 723 inline metadata + `pyproject.toml` + the test `--with` pins. Everything else
(reconcile/credential/host machinery) is existing (001–005). This is the recorded
Constitution-VI deviation (Complexity Tracking) — `yaml.safe_load` only (never
`yaml.load`), for eval-safety.

**Storage**: **no new persistent state** — ownership/drift derive from the
deterministic identity (Constitution IV), so there is no Terraform-style state/lock
file. The `.agent-container/` directory itself is the operator's source of truth
(portable, git-trackable). Resolved secrets live only in memory + the existing
ephemeral 003 inject channels.

**Testing**: hermetic unit (`bin/tests/`) — discovery (upward walk, report root,
ambiguity/none → clear result), YAML parse + validation (offending file/field, no
partial change), the plan computation (absent/matching/drifted), ownership→identity
mapping, credential-reference resolution incl. the decrypt-command (in memory,
never to disk) + the missing-source and git-tracked-plaintext refusals, precedence
(spec wins, reported), and the RO-mount wiring in the compose model; YAML parse errors are reported cleanly. Acceptance
(real containers): `apply` reaches the declared environment and a second `apply` is
a no-op (idempotent); `destroy` removes only owned resources; the in-container
`.agent-container/` is **read-only** (a write fails). Real-agent/model calls stay
opt-in/tokened.

**Target Platform**: host CLI (macOS/Linux). OS keychain sources are per-OS
(macOS `security`, Linux `secret-tool`) — see R5.

**Project Type**: single-file CLI + the container image (only a compose bind added).

**Performance Goals**: none — discovery + parse + plan are local file/registry
reads; apply cost is the underlying deploy.

**Constraints**: validate-before-act with no partial change on error (FR-003);
idempotent apply (FR-006); **no secret to disk/log/registry/argv** (FR-013/014,
Constitution III); **spec immutable from the container** (FR-020); ownership never
removes unowned resources (FR-009); every operation reports the root + host chosen
(FR-019). One new dep — PyYAML `safe_load` (Constitution VI deviation, justified).

**Scale/Scope**: single operator; one project dir → one or more declared
environments. **MVP = US1** (declare + validate + idempotent apply against an
existing host). US2 (credential references), US3 (drift/status/scoped destroy), US4
(declarative host provisioning) layer on incrementally.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after design. Constitution v2.1.0.*

| Principle | Assessment |
|-----------|------------|
| **I. Ephemerality** | ✅ Strengthened. The `.agent-container/` directory is durable state *outside* any container (portable, git-trackable, reproducible-from-checkout); the tool stores no new state; environments remain disposable and reconstructable from the spec. |
| **II. Least Privilege, Immutable Runtime** | ✅ **Load-bearing (FR-020).** The governing spec is immutable from inside the container — a read-only, kernel-enforced bind mount; the untrusted agent cannot re-govern itself. The runtime is otherwise unchanged (a bind, not a reshape). |
| **III. Least Exposure** | ✅ **Load-bearing.** Credentials are references, never embedded; the decrypt command runs in memory; no plaintext to disk/log/registry/argv; git-tracked-plaintext is refused. The spec is read only from the trusted host-side copy. |
| **IV. Deterministic Identity** | ✅ Reinforced. Ownership/drift/teardown all derive from the one deterministic identity — no second source of truth, no state file to desync. |
| **V. Durable Spec, Disposable Code** | ✅ The feature *is* this principle at the product level — a directory as the durable, reviewable source of truth reconciled into disposable containers. Verification is acceptance-weighted (apply converges, idempotent, destroy scoped). |
| **VI. Least Dependencies** | ⚠️→✅ **One new dep: PyYAML** (operator chose YAML for the spec format). Justified + recorded in Complexity Tracking — a single mature, ubiquitous parser that earns its place for human-authored declarative config; `yaml.safe_load` only. All other machinery is reused. |
| **VII. Continuous Deployment** | ✅ Ships incrementally as `feat` minors (US1 first); docs updated in-change. |

**Result: PASS** — the one deviation (PyYAML) is justified and recorded in
Complexity Tracking; every other principle is reinforced. FR-020 makes Least
Privilege/Immutable Runtime a first-class, tested gate rather than an afterthought.

## Project Structure

### Documentation (this feature)

```text
specs/006-agent-as-code/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R7 decisions
├── data-model.md        # Phase 1 — the .agent-container schema + reconcile entities
├── quickstart.md        # Phase 1 — validation scenarios A..H
├── contracts/
│   └── agent-as-code.md # Phase 1 — the spec schema, the apply/plan/destroy contract, integrity contract
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
bin/agent-container          # single-file CLI — the primary file edited:
                             #   • discovery: find_project_root() walks upward to .agent-container/, reports it
                             #   • parse+validate: yaml.safe_load + a schema validator (offending file/field; no partial change)
                             #   • reconcile: compute_plan(declared, live) -> per-resource absent|matching|drifted;
                             #     do_apply()/do_plan()/do_destroy()/do_status() driving the EXISTING do_up/host/registry internals
                             #   • ownership: declared name -> deterministic identity (container_name/volumes/host); no state file
                             #   • credentials: resolve_credential_ref() (env|file|keychain|encrypted+decrypt-cmd, in memory)
                             #     -> the Feature 003 inject channels; missing-source + git-tracked-plaintext refusals
                             #   • precedence: spec wins for its scope, reported (FR-018)
                             #   • spec integrity: add the READ-ONLY .agent-container bind to the compose model (FR-020)
docs/…, README.md, CLAUDE.md # the declarative model + the .agent-container schema + the integrity guarantee
bin/tests/
├── test_agent_as_code.py (new)  # discovery, parse/validate, plan, ownership, credential resolution, precedence, RO-mount
├── test_command_construction.py # the compose model carries the read-only .agent-container bind
└── test_acceptance.py           # apply reaches declared state + idempotent; destroy scoped; in-container spec is read-only
```

**Structure Decision**: unchanged single-file CLI. The only container-image touch
is a **read-only bind** the compose model adds for `/workspace/.agent-container`
(FR-020) — no `entrypoint.sh` logic. All CLI edits are single-file-sequential.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|-----------|-----------|--------------------------------------|
| **PyYAML** (one new third-party dependency) — the `.agent-container/` spec files are **YAML** | YAML is the expected, human-authored format for "as-code" declarative config (Compose/k8s/Terraform-adjacent); the operator chose it. PyYAML is a single, mature, ubiquitous parser. Used as `yaml.safe_load` only (never `yaml.load`) for eval-safety. | Stdlib `tomllib` (TOML) is dependency-free and already used in-project, but TOML is awkward for the deeply-nested/list-heavy environment schema and is not the format operators expect here; the operator explicitly chose YAML, so the one dep earns its place against Constitution VI. |

## Phase 0 — Outline & Research

Complete. See [research.md](./research.md): R1 (spec format — YAML via PyYAML,
the recorded Constitution-VI exception), R2 (discovery — upward walk to `.agent-container/`), R3
(reconcile model — plan/apply/status/destroy over existing internals), R4
(ownership via deterministic identity, no state file), R5 (credential resolution +
the decrypt-command + keychain per-OS + git-plaintext refusal), R6 (**spec
integrity** — read-only host-side-only spec, RO bind mount, FR-020), R7 (CLI
surface + precedence). All four clarifications + the FR-020 integrity decision are
folded in; no NEEDS CLARIFICATION remain (R1's format is decided: YAML/PyYAML).

## Phase 1 — Design & Contracts

Complete. [data-model.md](./data-model.md) defines the `.agent-container/` schema
(project / environment / host binding / credential reference / plan) and the
reconcile state machine. [contracts/agent-as-code.md](./contracts/agent-as-code.md)
pins the CLI surface (`apply`/`plan`/`status`/`destroy`), the discovery + precedence
+ validation + credential + **integrity (read-only spec)** contracts, and the
compose-model RO bind. [quickstart.md](./quickstart.md) gives scenarios A–H mapped
to SC-001…SC-007 + the integrity guarantee. (No `update-agent-context` script in
this repo — skipped, as in prior features.)

## Phase 2 — Task planning approach (for /speckit-tasks, NOT executed here)

Tasks will be organized by user story: **US1 discover→validate→apply (MVP)** → US2
credential references (incl. the decrypt-command + refusals) → US3 status/diff +
scoped destroy → US4 declarative host binding/provisioning, on a foundational layer
(discovery + YAML parse/validate + the reconcile/ownership core + the FR-020
read-only mount). All `bin/agent-container` edits are single-file-sequential; test
modules + docs are `[P]`. The real-container acceptance (apply converges +
idempotent; in-container spec read-only; destroy scoped) is the authoritative tier.
