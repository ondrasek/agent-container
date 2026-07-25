---
description: "Task list for Credential Managers (specs/008)"
---

# Tasks: Credential Managers

**Input**: Design documents from `specs/008-credential-managers/` (plan.md, spec.md, research.md, data-model.md, contracts/credential-managers.md, quickstart.md).

**Scope**: make credential **managers** first-class in the Feature 006 credential model — a generic **`command`** source (an **argv list run directly, no shell**), named **`onepassword`**/**`bitwarden`** sources assembling that argv from structured typed fields, and the **removal** of the encrypted-in-repo `encrypted` source (refused with a migration). A **surgical extension** of existing code: `validate_credential`, `resolve_credential_value`, and `_run_decrypt` → generalized **`_run_resolver`**. Delivery (003 channels), up-front resolution, and the git-tracked-plaintext refusal are **unchanged**. **No new dependency** (Constitution VI) — managers are external CLIs the operator already has.

**Tests**: INCLUDED (Constitution V; the validation logic is pure and the resolver is mockable — the exposure guarantees must be pinned by tests).

## ⚠️ Single-file constraint (read before using [P])

All implementation is in the one PEP 723 file **`bin/agent-container`**. Tasks that edit it are mutually **SEQUENTIAL** — never `[P]` with each other. `[P]` is ONLY for genuinely separate files: the test modules (`bin/tests/test_agent_as_code.py`, `bin/tests/test_acceptance.py`) and docs (`docs/agent-as-code.md`, `README.md`, `CLAUDE.md`).

**Least exposure is the gate (Constitution III)**: every new path must keep the resolved value out of the repo, argv, logs, and the registry — and must never echo a resolver's stderr. Tests assert this explicitly.

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [ ] T001 Add the module constant `RESOLVER_TIMEOUT = 30` (seconds) near the other credential constants in `bin/agent-container`, with a comment citing the research R5 rationale (a pre-unlocked manager resolves fast; 30 s covers a network round-trip while guaranteeing a wedged CLI can never hang an apply, FR-005).

**Checkpoint**: the bound the shared runner enforces exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the one shared, audited resolver every new source funnels through, plus the schema constants. **No user story can begin until this phase is complete.** All `bin/agent-container` tasks are sequential (same file); test tasks are `[P]`.

- [ ] T002 [P] Write failing tests in `bin/tests/test_agent_as_code.py` for `_run_resolver`: runs the argv **directly with no shell** (assert no `shell=True`; a metacharacter in an argument is passed through literally, never interpreted); **`stdin` is closed** (non-interactive, FR-005); a **timeout** raises a `die` rather than hanging (FR-005); a **missing binary**, a **non-zero exit**, and an **empty stdout** each `die` naming the credential (FR-004); the resolver's **stderr is NEVER echoed** into the message (FR-006, Constitution III) — assert a secret planted on the resolver's stderr does not appear in the raised message.
- [ ] T003 Add `_run_resolver(argv, name, *, timeout=RESOLVER_TIMEOUT) -> str` in `bin/agent-container` — `subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=…)`, no shell; on `TimeoutExpired`/`OSError`/non-zero/empty-when-required `die` with a **generic, secret-free** message naming the credential (never include the resolver's stderr); return stdout. Generalized from the existing `_run_decrypt`.
- [ ] T004 Update the source schema constants in `bin/agent-container`: `CRED_SOURCES = ("env", "file", "keychain", "command", "onepassword", "bitwarden")` (**remove `encrypted`**), and extend the per-source required-field map in `validate_credential` — `command`→`("argv",)`, `onepassword`→`("vault", "item", "field")`, `bitwarden`→`("item", "field")` — keeping `env`/`file`/`keychain` unchanged.

**Checkpoint**: one audited, bounded, non-interactive, secret-free resolver exists and the schema knows the new sources. User stories can begin.

---

## Phase 3: User Story 1 — Reference a secret from any credential manager (Priority: P1) 🎯 MVP

**Goal**: a spec names *which* secret to fetch via a generic resolver; the tool fetches it host-side at apply and injects it — the secret never enters the repository.

**Independent Test**: declare a credential whose `argv` resolver prints a known value, apply, and confirm the value reaches the running environment and appears **nowhere** in the project directory, the output, or the tool's state (quickstart A/C).

- [ ] T005 [P] [US1] Write failing tests in `bin/tests/test_agent_as_code.py` for the **`command`** source: `validate_credential` accepts a well-formed `{source: command, argv: [...]}` and **rejects** a non-list `argv`, an **empty** list, and a **non-string element** — each `die`ing naming the field (FR-015); unknown keys still rejected. `resolve_credential_value` runs **exactly the declared argv** (assert the argv passed to a mocked `_run_resolver`) and returns its stdout; a failing resolver `die`s **before any change** naming the credential and source (FR-004); the resolved value never appears in any log/`die` message (Constitution III).
- [ ] T006 [US1] Add the `command` branch to `resolve_credential_value` in `bin/agent-container` (dispatch `cred["argv"]` → `_run_resolver`), and add the **argv-list type validation** to `validate_credential` (non-empty list of strings, else `die` naming the field).
- [ ] T007 [P] [US1] Acceptance in `bin/tests/test_acceptance.py`: a declarative project whose credential uses `{source: command, argv: ["printf", "<known>"]}` applies; the value is present in the running container (verifiable in-container) and **no plaintext appears in the project dir or the captured output** (SC-001); a resolver that exits non-zero fails the apply **before any change**, naming the credential (SC-002). Reuse the Feature 006 declarative acceptance harness.

**Checkpoint**: any CLI-based manager (1Password, Bitwarden, pass, gopass, Vault, cloud stores) is usable through the generic source, with secrets never in the repo — the shippable MVP.

---

## Phase 4: User Story 2 — Name the common managers directly (Priority: P2)

**Goal**: reference 1Password/Bitwarden by name with structured typed fields; the tool assembles the correct no-shell invocation.

**Independent Test**: declare a named-manager credential with its typed fields and confirm the tool assembles the expected argv and resolves identically to the equivalent generic resolver; a missing required field is refused naming it (quickstart B).

- [ ] T008 [P] [US2] Write failing tests in `bin/tests/test_agent_as_code.py` for the **named** sources: `onepassword` requires `vault`/`item`/`field` and `bitwarden` requires `item`/`field` — a missing field `die`s **before any change** naming it (FR-007/015); `resolve_credential_value` assembles **exactly** `["op", "read", "op://{vault}/{item}/{field}"]` and `["bw", "get", field, item]` (assert the argv passed to a mocked `_run_resolver`); the result is **identical** to the equivalent `command` source (SC-005); no shell is involved.
- [ ] T009 [US2] Add the `onepassword` and `bitwarden` branches to `resolve_credential_value` in `bin/agent-container` — assemble the argv per research R3 and delegate to `_run_resolver`; the generic `command` source remains the extensible escape hatch for unnamed managers (FR-008).

**Checkpoint**: the two most common managers are a one-line declaration; everything else still works via `command` with zero tool change.

---

## Phase 5: User Story 3 — Retire encrypted-in-repo and publish the taxonomy (Priority: P3)

**Goal**: the tool stops offering secrets-in-git (even encrypted) and gives an upgrading operator an actionable migration plus a documented recommended posture.

**Independent Test**: apply a spec still using `source: encrypted` and confirm it is refused before any change with a message naming the migration; confirm the retained sources still work and the taxonomy documents the hierarchy (quickstart D/E).

- [ ] T010 [P] [US3] Write failing tests in `bin/tests/test_agent_as_code.py`: a spec declaring `{source: encrypted, …}` is **refused before any change** with a message naming the removed source **and** the migration path (manager / keychain / external-untracked file) — not the generic enum error (FR-009/SC-003); the retained `env`/`file`/`keychain` sources still validate and resolve (regression guard); a **git-tracked plaintext** `file` secret in the project is still refused (FR-011).
- [ ] T011 [US3] Remove the `encrypted` source from `bin/agent-container`: delete `_run_decrypt` and the `encrypted` branch of `resolve_credential_value`, and add the **special-cased migration refusal** in `validate_credential` — checked **before** the generic source-enum error so an upgrading operator gets the actionable message (FR-009).
- [ ] T012 [P] [US3] Update `docs/agent-as-code.md`: document the **recommended credential taxonomy** as an explicit preference hierarchy (recommended: manager / OS keychain / local / HW-key-backed, the repo holding only a **locator**; refused: a plaintext secret tracked in git; **no encrypted-in-git tier**), the new `command`/`onepassword`/`bitwarden` sources with examples, the note that `keychain` already reaches the macOS Keychain (incl. iCloud-synced generic passwords) and the Linux Secret Service, that HW keys (YubiKey) are a **backing** for a resolver rather than a source, and the **`encrypted` removal + migration recipe** (FR-014).

**Checkpoint**: the model is coherent — there is no supported way to put a secret in the git remote, and the recommended posture is written down.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T013 Run `scripts/quality-gate.sh` (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell) and fix all findings; confirm **bandit is clean** (no `shell=True` anywhere in the new resolver paths) and that `resolve_credential_value` stays within xenon rank B (extract per-source helpers if the added branches push it over).
- [ ] T014 [P] Update `README.md` and the `CLAUDE.md` Decisions bullet for Feature 006/008: the credential sources now include the no-shell `command` resolver + named `onepassword`/`bitwarden`, `encrypted` is **removed** (breaking, with a migration refusal), and the repo stores only a **locator** — within the CLAUDE.md 2000-token budget (prune before adding).
- [ ] T015 Run quickstart.md Scenarios A–E (the named-manager scenario is opt-in — it needs a real, unlocked `op`/`bw` session; the rest are CI-safe) and record the results in quickstart.md.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → the timeout constant. Trivially blocks the runner.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (the shared `_run_resolver` + the source schema constants).
- **US1 (P3)** → depends on Foundational. **The MVP** (the generic `command` source).
- **US2 (P4)** → depends on Foundational + US1's dispatch shape (named sources assemble an argv and reuse the same runner).
- **US3 (P5)** → depends on Foundational (the `encrypted` removal edits the same validator/resolver); independent of US1/US2 in behavior, but sequenced last so a migration message can point at the shipped alternatives.
- **Polish (P6)** → after the desired stories.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` implementation task (single-file-sequential).

### Parallel opportunities (distinct files only)

- Foundational: T002 (tests, `[P]`); impl T003→T004 sequential (same file).
- US1: T005 ∥ T007; impl T006.
- US2: T008 ∥; impl T009.
- US3: T010 ∥ T012; impl T011.
- Polish: T014 `[P]`; T013/T015 sequential (gate, then record).

## Implementation Strategy

### MVP first (US1 — the generic resolver)

1. Phase 1 Setup → 2. Phase 2 Foundational (`_run_resolver` + schema constants) → 3. Phase 3 US1 (the `command` source) → **STOP & VALIDATE** a manager-referenced secret applies and reaches the container with **no plaintext on disk or in output** (quickstart A/C) → ship. This alone delivers the headline "secrets never in the repo" value and covers **every** CLI-based manager.

### Incremental delivery

US2 (named 1Password/Bitwarden sugar) and US3 (the `encrypted` removal + the documented taxonomy) each layer onto the same validator/resolver, and each is independently testable at the unit tier. Polish (gate, docs, quickstart run) closes the feature.
