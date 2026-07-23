---
description: "Task list for Agent-as-Code (specs/006)"
---

# Tasks: Agent-as-Code (declarative project directory)

**Input**: Design documents from `specs/006-agent-as-code/` (plan.md, spec.md, research.md, data-model.md, contracts/agent-as-code.md, quickstart.md).

**Scope**: a **declarative** `.agent-container/` project directory as desired state, reconciled (`apply`/`plan`/`status`/`destroy`) as an **orchestrator** over the existing internals — **additive** to today's imperative CLI (no spec present ⇒ unchanged behavior, FR-004). **Inherited** (driven, not rebuilt): host registry/driver/provisioner (001), lifecycle + `build_compose_model` (002), credential inject channels (003), execution/workspace/clone-on-start (004). **New dependency**: PyYAML (`yaml.safe_load`) — the operator's chosen format (Constitution-VI deviation, recorded).

**Tests**: INCLUDED (Constitution V; the existing `bin/tests/` suite — Python unit + acceptance).

## ⚠️ Single-file constraint (read before using [P])

Almost all implementation is in the one PEP 723 file **`bin/agent-container`**; the only container-image touch is a set of **read-only compose `configs`** for `/workspace/.agent-container` (FR-020) — no `entrypoint.sh` logic. Tasks that edit `bin/agent-container` are mutually **SEQUENTIAL** — never `[P]` with each other. `[P]` is ONLY for genuinely separate files: distinct test modules (`test_agent_as_code.py`, `test_command_construction.py`, `test_acceptance.py`), docs, and `pyproject.toml`.

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [X] T001 Add **PyYAML** as a dependency: the PEP 723 inline `# /// script` metadata block in `bin/agent-container` (e.g. `pyyaml>=6,<7`), `pyproject.toml` `[project].dependencies`, and note the new `--with pyyaml` pin for the hermetic test invocation (conftest docstring + `scripts/quality-gate.sh`). Use `yaml.safe_load` ONLY (never `yaml.load`).
- [X] T002 [P] Add `bin/tests/test_agent_as_code.py` (new module) with hermetic fixtures (reuse `wiz`/`make_registry` from `bin/tests/conftest.py`; a `tmp_path` project-dir factory; no live runtime).

**Checkpoint**: the YAML parser is available and a place for the declarative unit tests exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared declarative core every story consumes — discovery, YAML parse + validation, the reconcile/ownership computation, and the FR-020 read-only spec delivery (compose configs). **No user story can begin until this phase is complete.** All `bin/agent-container` tasks here are sequential (same file); test tasks are `[P]`.

- [X] T003 [P] Write failing tests in `bin/tests/test_agent_as_code.py` / `bin/tests/test_command_construction.py`: `find_project_root` walks upward to a `.agent-container/` dir (same root from nested subdirs; **None** when absent); `load_project_spec` uses `yaml.safe_load` (a `!!python/object` payload does NOT construct an object) and a schema validator **dies naming the offending file+field with no partial change** on a bad spec; a declared `name` maps to the tool's deterministic identity (`container_name`/`volume_name`); `compute_plan` classifies absent/matching/drifted; `build_compose_model` delivers each `.agent-container/` file as a **read-only compose `config`** (never a host bind — remote-context-safe) targeting `/workspace/.agent-container/<rel>` when the workspace carries one, and the verify step **refuses** if any spec file would be agent-writable (FR-020).
- [X] T004 Add `import yaml` and `find_project_root(start=cwd)` — walk upward to the nearest ancestor containing a `.agent-container/` directory, return it (or None → declarative model inert, FR-004); every declarative op reports the selected root (FR-019); in `bin/agent-container`.
- [X] T005 Add `load_project_spec(root)` — read the `.agent-container/` YAML file(s) with **`yaml.safe_load`** and **validate** against the **pinned schema** (the required/optional fields, types, and enums in contracts/agent-as-code.md §Schema — `environments[].name/host` required; `mode`/`agent`/`workspace`/`source` enums; unknown keys rejected): on any syntactic/semantic error `die` naming the **offending file and field**, making **no partial change** (FR-003); in `bin/agent-container`.
- [X] T006 Add the reconcile core: a declared-name→deterministic-identity map (ownership, Constitution IV — **no state file**) and `compute_plan(declared, live)` returning per-declared-resource **absent | matching | drifted** (+ a human-readable delta), driving the existing live-state queries; in `bin/agent-container`.
- [X] T007 Add the **FR-020 spec-integrity** wiring: (1) the tool reads the spec ONLY host-side (never a container copy — load-bearing); (2) deliver each host-side `.agent-container/` file **read-only** via the existing `injected_configs` channel (compose `configs`, remote-context-safe — **not** a host bind) targeting `/workspace/.agent-container/<rel>`; (3) a **verify** step asserts every declared spec file is delivered via a read-only channel and no writable `/workspace` mount exposes it, **refusing to deploy** otherwise (M3); in `bin/agent-container`.

**Checkpoint**: a spec can be discovered, parsed+validated, planned, and its identity/ownership computed; the RO spec `configs` are in the model. User stories can begin.

---

## Phase 3: User Story 1 — Declare an environment and bring it up (Priority: P1) 🎯 MVP

**Goal**: a `.agent-container/` directory as desired state → discover, validate, preview, and (on confirm) converge to a running environment; a second run is a no-op.

**Independent Test**: in a scratch dir with a minimal valid spec targeting a local host, `apply` brings the declared container up; an immediate second `apply` reports "no changes" (quickstart A/B).

- [X] T008 [P] [US1] Write failing tests in `bin/tests/test_agent_as_code.py`: `apply` discovers→validates→computes a plan→(confirm)→drives `do_up` for absent/drifted and **no-ops on matching** (idempotent, SC-002); an invalid spec is refused (no runtime call); **no `.agent-container/` up the tree ⇒ today's behavior** (FR-004); the chosen **root + host are reported**; a spec-vs-registry host conflict resolves **spec-wins and reports it** (FR-018).
- [X] T009 [US1] Add the declarative verbs `apply` / `plan` / `status` to `bin/agent-container`: discover → `load_project_spec` → `compute_plan` → **preview + confirm** (honor the `-y`/headless convention, FR-007) → for `apply`, drive the existing `do_up`/`compose_up_exec` per resource (matching = no change); `plan`/`status` print the plan and mutate nothing; apply the spec-wins **precedence** (reported); report the root + host for every op (FR-019); inert when no spec (FR-004).
- [X] T010 [P] [US1] Acceptance in `bin/tests/test_acceptance.py`: `apply` on a minimal spec (local host) brings the declared container up (SC-001); a second `apply` is a **no-op** (SC-002); an invalid spec is refused with no partial change; **the in-container `/workspace/.agent-container` is read-only** — a write fails (FR-020).

**Checkpoint**: a directory reconciles to a running environment, idempotently — the shippable MVP.

---

## Phase 4: User Story 2 — Declare the credentials, safely (Priority: P2)

**Goal**: the spec declares credentials by **reference to a source**; the tool resolves each at apply and injects it at runtime, never letting a plaintext value touch the directory/logs/registry.

**Independent Test**: a spec referencing an API key via env + a git identity via an external key path applies; the secret reaches the container, no plaintext appears in the dir, and a would-be-committed plaintext secret is rejected (quickstart E).

- [X] T011 [P] [US2] Write failing tests in `bin/tests/test_agent_as_code.py`: `resolve_credential_value` resolves **env / file(external) / keychain / encrypted** sources — the `encrypted` source runs the operator **decrypt command** and holds plaintext **in memory only (never written to disk)**; a **missing/unavailable** source `die`s **before any change** naming it (FR-016); a **git-tracked plaintext** secret in the project is **refused** with remediation (FR-015); the resolved value reaches the 003 inject channel and never appears in the compose model / argv / logs (FR-013/014).
- [X] T012 [US2] Add `resolve_credential_value(ref)` and wire it into the apply path: env (read var) / file (external path) / keychain (`security find-generic-password -w` | `secret-tool lookup`) / encrypted (run the operator `decrypt` command, in memory) → the appropriate **Feature 003** inject channel by target — agent **API keys** → apikeys channel, everything else → a per-deployment 0600 secrets env-file (mangle-unsafe values rejected for env delivery); the missing-source + git-tracked-plaintext refusals; in `bin/agent-container`. **SSH-key routing to `--push-key`/`--host-key` is NOT in scope here** — carved into T012a below (it was over-claimed in the original task text; the shipped code fails closed on multi-line values).
- [ ] T012a [US2] **(follow-on)** Route an SSH-key credential reference (git push identity → `--push-key`, host SSH identity → `--host-key`/`--authorized-key`) through the existing Feature 003 ssh-injection paths — the multi-line delivery the env-file channel deliberately refuses today (L2). Not required for the US2 checkpoint; tracked so tasks.md matches shipped scope (H1).
- [X] T013 [P] [US2] Acceptance in `bin/tests/test_agent_as_code.py` (acceptance-marked): `apply` with an env-referenced key injects it into the running container (verifiable in-container) while **no plaintext value appears in the project dir / captured output** (SC-004); a missing source fails before any change and names it (SC-005).

**Checkpoint**: credentialed environments apply with secrets injected at runtime and never on disk.

---

## Phase 5: User Story 3 — See drift, converge, tear down from the spec (Priority: P3)

**Goal**: report per-resource drift, converge on apply, and `destroy` exactly the owned resources (nothing else).

**Independent Test**: bring an environment up; out-of-band change it; `status` reports the drift; `apply` converges; `destroy` removes only the declared resources (quickstart F).

- [X] T014 [P] [US3] Write failing tests in `bin/tests/test_agent_as_code.py`: `status` prints the per-resource plan (matching/drifted with a delta) and **mutates nothing**; `destroy` targets **only owned identities** (an identically-shaped but unrelated container is untouched, SC-007); a drift requiring recreate is **announced before** doing it; partial failure reports exactly what changed/did not (FR-010); **portability (FR-005/SC-003)** — the same spec parsed from a **fresh checkout at a different path** (same external secret sources) yields **identical `status`/plan output** (ownership is identity-derived, so location does not affect the plan).
- [X] T015 [US3] Add the `destroy` verb (scoped to owned deterministic identities — reuse `down_container`/`per_container_volumes`; a **referenced** host is never deprovisioned) and complete `status`/diff deltas + the partial-failure reporting (FR-010); in `bin/agent-container`.
- [X] T016 [P] [US3] Acceptance in `bin/tests/test_acceptance.py`: bring up via `apply`; out-of-band change → `status` reports drift; `apply` converges; `destroy` removes **only** the declared resources and leaves an unrelated container/host untouched (SC-006/007).

**Checkpoint**: the model is trustworthy over time — drift-visible, convergeable, scoped teardown.

---

## Phase 6: User Story 4 — Declare the host/provisioning in the spec (Priority: P3)

**Goal**: the spec binds an environment to a host — an existing context (referenced, externally owned) or one to provision (spec-owned) — capturing the whole stack from bare host to running agent.

**Independent Test**: a spec declaring a to-be-provisioned host + a container applies (host provisioned/registered then deployed); `destroy` deprovisions only the spec-created host, leaving a merely-referenced host intact (quickstart H).

- [ ] T017 [P] [US4] Write failing tests in `bin/tests/test_agent_as_code.py`: a **referenced** host binding deploys onto that host and is **never** deprovisioned by `destroy`; a **provisioned** host binding provisions/registers first (drives the 001 registry/provisioner) then deploys; `destroy --deprovision` removes **only** the spec-created host (FR-017). No real cloud call in the unit tier (the provisioner is stubbed).
- [ ] T018 [US4] Add host-binding resolution to the apply/destroy paths: `referenced` (existing/known host — externally owned) vs `provisioned` (drive the 001 `host add`/provisioner, spec-owned); `destroy --deprovision` removes a spec-created host only with explicit intent (FR-017); in `bin/agent-container`.
- [ ] T019 [P] [US4] Acceptance in `bin/tests/test_acceptance.py`: a **referenced**-host spec deploys and `destroy` leaves the host intact. The **provisioned**-host end-to-end (real Hetzner) is **opt-in/tokened** (billable — never in CI; behind `HCLOUD_TOKEN` + the existing acceptance opt-in guards).

**Checkpoint**: a single directory captures the whole stack; teardown deprovisions only what the spec created.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T020 [P] Update `README.md`: the declarative model (`apply`/`plan`/`status`/`destroy`), the `.agent-container/` YAML schema, credential references, and the **spec-integrity** (read-only in-container) guarantee.
- [X] T021 [P] Update `CLAUDE.md` Decisions (agent-as-code: `.agent-container/` desired-state, reconcile-as-orchestrator, ownership-via-identity/no-state-file, credential references + decrypt-command, FR-020 RO spec, PyYAML dep) within the 2000-token budget — prune before adding.
- [X] T022 [P] Add `docs/agent-as-code.md`: the schema, the apply/status/destroy contract, the credential sources (incl. the decrypt command), precedence, the read-only-spec integrity guarantee (host-side-only read + read-only compose-`configs` delivery, remote-context-safe), and the **documented boundary of the plaintext-secret detection** — what it can and cannot catch (FR-015, L1).
- [X] T023 Run `scripts/quality-gate.sh` (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell) and fix all findings; ensure the **PyYAML** pin is threaded into the gate's hermetic `--with` invocation and that bandit is clean (no `yaml.load`).
- [ ] T024 Run quickstart.md Scenarios A–H (local; the provisioned-host + real-agent ones are opt-in/tokened) and record the results in quickstart.md.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → PyYAML dep + the test module. Blocks parsing.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (discovery + parse/validate + reconcile/ownership + the FR-020 RO spec `configs`).
- **US1 (P3)** → depends on Foundational. **The MVP** (apply/plan/status).
- **US2 (P4)** → depends on Foundational + US1's apply path (credential resolution feeds apply).
- **US3 (P5)** → depends on US1 (a running environment to diff/destroy); reuses the reconcile core.
- **US4 (P6)** → depends on US1; drives the 001 registry/provisioner for host binding.
- **Polish (P7)** → after the desired stories.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` implementation task(s) (single-file-sequential).

### Parallel opportunities (distinct files only)

- Setup: T001 (deps, touches bin + pyproject) then T002 (new test file, `[P]`).
- Foundational: T003 (tests) alongside; impl T004→T005→T006→T007 sequential (same file).
- US1: T008 ∥ T010; impl T009.
- US2: T011 ∥ T013; impl T012.
- US3: T014 ∥ T016; impl T015.
- US4: T017 ∥ T019; impl T018.
- Polish: T020 ∥ T021 ∥ T022.

## Implementation Strategy

### MVP first (US1 — declare + apply)

1. Phase 1 Setup → 2. Phase 2 Foundational (discovery + YAML parse/validate + reconcile + RO spec `configs`) → 3. Phase 3 US1 (`apply`/`plan`/`status`) → **STOP & VALIDATE** a directory reconciles to a running environment idempotently (quickstart A/B) and the in-container spec is read-only (FR-020) → ship. This alone delivers the headline "as code" value.

### Incremental delivery

- US1 (declare+apply, MVP) → US2 (credentials) → US3 (drift/destroy) → US4 (host provisioning) → Polish. Each merges independently; `feat:` commits drive semver (Constitution VII).

## Notes

- `[P]` = distinct files only; every `bin/agent-container` edit is sequential. The only image touch is the RO `.agent-container` compose `configs` (FR-020) — no `entrypoint.sh` change.
- **One new dependency — PyYAML** (`yaml.safe_load` ONLY, never `yaml.load` — bandit/security, asserted in T003). Recorded Constitution-VI deviation.
- **Load-bearing invariants** (asserted across tiers, not standalone tasks): validate-before-act / no partial change (FR-003, T003/T005); **no secret to disk/log/registry/argv** (Constitution III, T011/T012); **spec immutable from the container** (FR-020, T003/T007/T010); ownership-scoped teardown (SC-007, T014/T015); every op reports root+host (FR-019, T008/T009).
- **Ownership derives from the deterministic identity** (Constitution IV) — **no state/lock file** is created (assert in T006/T014).
- The **real provisioning** (US4) and any **real-agent/model** acceptance are **opt-in/tokened**, never in CI (billable / secret) — consistent with the HCLOUD policy.
- Commit after each task or logical group; keep `main` green (Constitution VII).
