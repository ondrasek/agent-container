---
description: "Task list for Agent Provisioning & Credentialing (specs/003)"
---

# Tasks: Agent Provisioning & Credentialing

**Input**: Design documents from `specs/003-agent-credentialing/` (plan.md, spec.md, research.md, data-model.md, contracts/credentialing.md, quickstart.md).

**Scope**: the credentialing/provisioning layer — *what* a deployment is given (push credential, model/API credential, canonical config) and *how*, under a strict least-exposure discipline. **Inherited from Feature 001** (not re-built): the injected-material delivery seam (compose `configs` referencing locally-staged files that transfer over the runtime context), and the inbound sshd host key / authorized_keys. **Inherited from Feature 002**: `redeploy` (fresh re-delivery). Both credential reversals are **LAYERED** (confirmed at plan time): SSH push added alongside the retained HTTPS+`GH_TOKEN`; file-first API delivery alongside retained env/`.env` + interactive-login "stored authorization".

**Tests**: INCLUDED (Constitution V; the existing `bin/tests/` suite — Python unit + shell suites + acceptance).

## ⚠️ Single-file constraint (read before using [P])

Two files carry almost all implementation: the CLI **`bin/agent-container`** (one PEP 723 file) and the container **`entrypoint.sh`** (one bash file). Tasks that edit **the same file are mutually SEQUENTIAL** — never `[P]` with each other. `[P]` is used ONLY for genuinely separate files: distinct test modules (`test_credentialing.py`, `test_command_construction.py`, the shell suites, `test_acceptance.py`) and docs.

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [ ] T001 [P] Add `bin/tests/test_credentialing.py` (new module) with hermetic fixtures for injected-material staging + the compose-model assertions (reuse the `wiz`/`make_registry` fixtures from `bin/tests/conftest.py`; no live runtime).

**Checkpoint**: a place for the credentialing unit tests exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared net-new engine every credential story consumes — the ephemeral-vs-persistent injected-material taxonomy (data-model), the deterministic inject paths, and the staging + compose-model plumbing. **No user story can begin until this phase is complete.** All `bin/agent-container` tasks here are sequential (same file); test tasks are `[P]`.

- [ ] T002 [P] Write failing tests in `bin/tests/test_credentialing.py` / `bin/tests/test_command_construction.py`: an injected **secret** is staged locally (existence-validated), emitted as a compose `config` at an **ephemeral** `/run/agent-container/...` target, and its value never appears on argv nor inlined in the compose model; an injected **config** may target the canonical-config dir. (FR-010/011/013/014, data-model invariant matrix.)
- [ ] T003 Add the ephemeral inject-path constants — `INJECT_PUSH_KEY_PATH`, `INJECT_KNOWN_HOSTS_PATH`, `INJECT_APIKEY_DIR`, `INJECT_CONFIG_DIR` (all under `/run/agent-container/…`) — kept in sync with `entrypoint.sh`'s `INJECT_DIR`, in `bin/agent-container`.
- [ ] T004 Implement the ephemeral staging helper (mirroring `stage_ssh_injection` but **ephemeral-class**: byte-copy the source **without reading its contents** for secret hygiene, `die` fast if a referenced source is absent (FR-016), stage under `<state>/<host>/<name>.*` so compose ships it over the context (FR-014), and mark it so the entrypoint does **not** persist it to a volume (FR-012)), in `bin/agent-container`.
- [ ] T005 Extend `build_compose_model(...)` to accept and emit the new injected material — push key + known_hosts, model/API key file(s), canonical-config file(s) — as compose `configs` at their targets (ephemeral secrets → `/run/...`; canonical config → `INJECT_CONFIG_DIR`), with **no secret value inlined** and no identity-volume overlap, in `bin/agent-container`.

**Checkpoint**: the taxonomy + staging + compose-model plumbing exist and are unit-tested. User stories can begin.

---

## Phase 3: User Story 1 — Autonomous non-interactive push (Priority: P1) 🎯 MVP

**Goal**: provision an outbound **SSH push key** (distinct from the inbound host key) + known_hosts so the agent commits and pushes with zero prompts. The single most important capability (Constitution I rests on it).

**Independent Test**: provision with a push key; from inside the container clone→commit→push — no passphrase, no host-key confirmation (quickstart A/B/C).

- [ ] T006 [P] [US1] Write failing tests in `bin/tests/test_credentialing.py`: `--push-key`/`--known-hosts` stage + thread into the compose model as ephemeral configs at `INJECT_PUSH_KEY_PATH`/`INJECT_KNOWN_HOSTS_PATH`; the push key is **distinct** from the host key (SC-008); neither key value is on argv nor inlined.
- [ ] T007 [US1] Add `--push-key PATH` / `--known-hosts PATH` options to `up` and `redeploy` (+ env-file channel `SSH_PUSH_KEY_B64` / `PUSH_KNOWN_HOSTS` parity), validate the key (`validate_private_key`; reject encrypted), `die` fast if a referenced file is missing (FR-016), and thread through `compose_up_exec` → `build_compose_model`, in `bin/agent-container`.
- [ ] T008 [US1] Wire `GIT_SSH_COMMAND` in `entrypoint.sh` from the injected push key + known_hosts (`ssh -i <push-key> -o IdentitiesOnly=yes -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=accept-new`), reading the key **in place** from the ephemeral inject path and **NOT** copying it onto the `~/.ssh` volume (FR-012); keep it strictly separate from the inbound host-key install (SC-008); consume `SSH_PUSH_KEY_B64`/`PUSH_KNOWN_HOSTS`. The HTTPS+`GH_TOKEN` helper block is retained unchanged (layered).
- [ ] T009 [P] [US1] Shell test in `bin/tests/test_entrypoint.sh`: with an injected push key, `GIT_SSH_COMMAND` is set to use it with `IdentitiesOnly`, the key is **NOT** written onto the `~/.ssh` volume, and the inbound host-key path is untouched.
- [ ] T010 [P] [US1] Acceptance (opt-in/tokened) in `bin/tests/test_acceptance.py`: from inside a provisioned container, clone→commit→push over SSH completes with **zero** prompts (SC-001); after teardown no push-key copy remains on any volume (SC-004); the push key and host key are two distinct keys (SC-008). Real remote → outside the CI cost boundary.

**Checkpoint**: an agent pushes autonomously over SSH — the shippable MVP.

---

## Phase 4: User Story 2 — Model/API credentials safely (Priority: P1)

**Goal**: deliver each agent its model/API credential **file-by-default** (ephemeral), env-inside-container only where an agent can't read a file (FR-006); keep env/`.env` + interactive-login "stored authorization" as layered alternatives.

**Independent Test**: provision a model/API credential; the agent performs a backend action; the credential is absent from argv, the deployment description, image layers, and persistent volumes (quickstart D/E).

- [ ] T011 [P] [US2] Write failing tests in `bin/tests/test_credentialing.py`: a convention-discovered provider **key file** is staged as an ephemeral config under `INJECT_APIKEY_DIR`, never on argv, never inlined; env/`.env` delivery remains supported (a `.env` key value never reaches argv).
- [ ] T012 [US2] Implement provider-key **file discovery** (convention, mirroring `.env` resolution) + ephemeral staging + `build_compose_model` wiring to `INJECT_APIKEY_DIR`; retain the existing env/`.env` delivery path, in `bin/agent-container`.
- [ ] T013 [US2] Per-agent API-cred wiring in `entrypoint.sh` (file-first, FR-006): Claude → `apiKeyHelper` in `~/.claude/settings.json` that `cat`s the injected file; Codex → `codex login --with-api-key` reading the injected file on **stdin**; pi → `auth.json`/provider; export into the **in-container** env only where a file can't be consumed. Absent injected key → retain env/`.env` + interactive-login (NOTE, not `die`).
- [ ] T014 [P] [US2] Acceptance (opt-in/tokened) in `bin/tests/test_acceptance.py`: a provisioned agent performs a backend-requiring operation (SC-002); assert the key is absent from argv, the compose file, image layers, and persistent volumes (SC-003/SC-004). Never in CI (no cost/secret).

**Checkpoint**: an agent reaches its backend with the credential injected file-first and off every observable surface.

---

## Phase 5: User Story 3 — Canonical config fresh; runtime state persists (Priority: P2)

**Goal**: deliver operator-canonical config fresh on each deploy (edits propagate) while the agent's mutable runtime state survives recreation — the per-agent canonical/runtime split at file granularity.

**Independent Test**: edit canonical config locally, redeploy, see the change; write runtime state, recreate, see it survive (quickstart F).

- [ ] T015 [P] [US3] Write failing tests in `bin/tests/test_credentialing.py`: canonical-config files (per the per-agent manifest) discovered from the `agent-container.<name>.config/` convention are emitted as configs at `INJECT_CONFIG_DIR`; runtime-state paths are NOT delivered.
- [ ] T016 [US3] Implement the per-agent **canonical manifest** (the operator-owned paths per data-model — e.g. `~/.claude/settings.json` + `CLAUDE.md` + MCP defs; `~/.codex/config.toml`; `~/.pi` config) + `agent-container.<name>.config/` → `~/.config/agent-container/<name>.config/` discovery + staging to `INJECT_CONFIG_DIR`, in `bin/agent-container`.
- [ ] T017 [US3] Add the canonical-copy step to `entrypoint.sh`: on each boot, copy the manifest's files from `INJECT_CONFIG_DIR` onto their per-agent volume paths (overwrite the canonical files), leaving all other (runtime-state) files under the home untouched; idempotent so `redeploy` re-applies edits (FR-007/FR-008).
- [ ] T018 [P] [US3] Acceptance in `bin/tests/test_acceptance.py`: edit a canonical file → `redeploy` → the change is reflected in the container; write runtime state → dispose+recreate → the state survives from the per-agent volume (SC-005).

**Checkpoint**: operator config is authoritative and fresh; runtime state is durable — no clobbering.

---

## Phase 6: User Story 4 — Rotation & narrow scoping (Priority: P3)

**Goal**: verify the emergent properties — rotating a secret is a local edit + redeploy with no surviving copy, and the push credential can be scoped narrowly — plus the fail-fast robustness guards.

**Independent Test**: rotate a secret (edit + redeploy) → new value in effect, old gone; a per-repo deploy key grants only intended access (quickstart G).

- [ ] T019 [P] [US4] Write failing tests in `bin/tests/test_credentialing.py`: a deploy referencing a missing `--push-key`/`--known-hosts`/API/canonical file `die`s **before** any compose call (FR-016/SC-007); staging is all-local-before-`compose up` so a later failure leaves nothing running (FR-017).
- [ ] T020 [US4] Ensure the deploy path (`do_up`/`compose_up_exec`) stages+validates **all** injected material before `compose up` (no partially-credentialed agent, FR-017) and that a narrowly-scoped per-repo deploy key is simply a narrower `--push-key` (FR-004/FR-013), in `bin/agent-container`.
- [ ] T021 [P] [US4] Acceptance (opt-in/tokened) in `bin/tests/test_acceptance.py`: rotate a secret (edit local + `redeploy`) → new value in effect, no baked/persisted copy of the old (SC-006); a per-repo deploy key grants only the intended scope (FR-004).

**Checkpoint**: rotation and scoping are proven; fail-fast leaves no half-credentialed agent.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T022 [P] Update `docs/credentials.md` (FR-018): add the **SSH push** section as the documented default (deploy key + known_hosts, ephemeral, `GIT_SSH_COMMAND`), keep **HTTPS+`GH_TOKEN`** as the documented alternative, and record the ephemeral-not-persisted discipline (FR-012) + the two-key distinction (SC-008). Supersede the "SSH push rejected for MVP" note.
- [ ] T023 [P] Update `.env.example` (FR-018): the `SSH_PUSH_KEY_B64` / `PUSH_KNOWN_HOSTS` channel and the file-first API/config notes.
- [ ] T024 [P] Update `README.md` + `CLAUDE.md` (FR-018): the credential model (push key, file-first API, canonical/runtime split) — within `CLAUDE.md`'s 2000-token budget, prune before adding.
- [ ] T025 Run `scripts/quality-gate.sh` (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell suites) and fix all findings.
- [ ] T026 Run quickstart.md Scenarios A–G (local + the opt-in/tokened ones) and record the results in quickstart.md.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (taxonomy + staging + compose-model plumbing).
- **US1 (P3)** → depends on Foundational. **The MVP** (autonomous push).
- **US2 (P4)** → depends on Foundational; independent of US1 (different material, different entrypoint wiring).
- **US3 (P5)** → depends on Foundational; independent of US1/US2 (canonical-config copy, not a secret).
- **US4 (P6)** → depends on US1–US3 existing (it verifies rotation/scoping/fail-fast across the delivered material).
- **Polish (P7)** → after the desired stories.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` / `entrypoint.sh` implementation tasks (each file is single-file-sequential).

### Parallel opportunities (distinct files only)

- Setup: T001 alone.
- Foundational: T002 (tests) ∥ authored alongside; impl T003→T004→T005 sequential (same file).
- US1: T006 ∥ T009 ∥ T010 (distinct test files); impl T007 (CLI) then T008 (entrypoint) — different files, but T008 depends on T007's inject contract, so ordered.
- US2: T011 (tests) ∥ T014 (acceptance); impl T012 (CLI) → T013 (entrypoint).
- US3: T015 ∥ T018; impl T016 (CLI) → T017 (entrypoint).
- US4: T019 ∥ T021; impl T020.
- Polish: T022 ∥ T023 ∥ T024.

## Implementation Strategy

### MVP first (US1 — autonomous non-interactive push)

1. Phase 1 Setup → 2. Phase 2 Foundational (taxonomy + staging + compose-model) → 3. Phase 3 US1 (push key + known_hosts + `GIT_SSH_COMMAND`) → **STOP & VALIDATE** clone→commit→push with zero prompts (quickstart A/B/C) → ship. This alone delivers the capability the ephemeral-container model rests on.

### Incremental delivery

- US1 (push, MVP) → US2 (model/API creds) → US3 (canonical/runtime config split) → US4 (rotation/scoping/fail-fast) → Polish. Each merges independently; `feat:` commits drive semver (Constitution VII).

## Notes

- `[P]` = distinct files only; every `bin/agent-container` edit is sequential, and every `entrypoint.sh` edit is sequential (single-file contracts).
- **Zero new Python dependencies** — new material is compose `configs` + stdlib staging (verify no import creep in T025).
- **Ephemeral discipline is the spine (FR-012)**: the push key and injected API keys land in `/run/agent-container/…` and are **never** copied onto a persistent volume — the deliberate opposite of the inbound host key. The interactive-login "stored authorization" on a per-agent volume is the operator-initiated exception.
- **Least-exposure invariants (FR-010…FR-015)** are cross-cutting, asserted across the unit tests (no argv / no inline — T002/T006/T011), the shell tests (no persist — T009), and acceptance (no bake / no volume copy after teardown — T010/T014), not a standalone task.
- Identity is unchanged (Constitution IV): the outbound push key is a **new, distinct** credential, not a redefinition of the inbound host key (SC-008).
- The backend-reach (SC-002), real-SSH-push (SC-001), and rotation (SC-006) acceptance tests are **opt-in/tokened**, outside the CI cost boundary (no real infra/cost in CI).
- Commit after each task or logical group; keep `main` green (Constitution VII).
