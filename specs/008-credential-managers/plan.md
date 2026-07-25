# Implementation Plan: Credential Managers

**Branch**: `008-credential-managers` | **Date**: 2026-07-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-credential-managers/spec.md`

## Summary

Make credential **managers** first-class in the agent-as-code credential model (Feature
006), following git's credential-helper pattern: the repo holds only a **locator**, and
the secret is fetched **host-side at apply** from wherever it truly lives. Concretely:

1. Add a generic **`command`** source — an operator-declared **argv list** run directly
   (no shell) whose stdout is the secret.
2. Add **named** sources **`onepassword`** (`vault`/`item`/`field`) and **`bitwarden`**
   (`item`/`field`) that assemble the correct no-shell argv.
3. **Remove** the `encrypted` (age/sops committed-ciphertext) source, refusing it with an
   actionable migration message (breaking, acceptable pre-1.0).
4. Retain `env`/`file`/`keychain`; document the recommended credential **taxonomy**.

This is a **surgical extension** of the existing 006 credential code: `validate_credential`
gains the new source enums + per-source required fields (and a special-cased `encrypted`
migration refusal); `resolve_credential_value` gains the `command`/`onepassword`/`bitwarden`
branches; and the existing `_run_decrypt` (which ran the operator's decrypt command and
captured stdout) is **generalized into `_run_resolver`** — one host-side, non-interactive,
bounded, secret-free-on-failure runner reused by all three new sources. Everything
downstream (in-memory resolution up front, delivery via the 003 channels, the
git-tracked-plaintext refusal) is unchanged.

## Technical Context

**Language/Version**: Python ≥ 3.14 — the single-file PEP 723 script `bin/agent-container`.

**Primary Dependencies**: Typer, questionary, rich, PyYAML (all already present). **No new
dependency** (Constitution VI) — credential managers are **external CLIs the operator
already has** (`op`, `bw`/`rbw`, …), invoked via argv.

**Storage**: None new. The resolved secret lives only in memory + the existing private,
per-deployment 0600 staged files under `$XDG_STATE_HOME` (Feature 006 posture).

**Testing**: pytest hermetic unit tests (`bin/tests/test_agent_as_code.py` — the 006
credential suite, extended): `validate_credential` enums/fields/migration-refusal;
`resolve_credential_value` argv assembly + `_run_resolver` behavior (mocked subprocess);
plus a real-container acceptance that a `command` source injects a known value with no
plaintext on disk (reuse the 006 declarative acceptance harness).

**Target Platform**: the operator's host (macOS + Linux) at apply time.

**Project Type**: single CLI tool.

**Performance Goals**: resolution is a quick host-side fetch; **`_run_resolver` is bounded**
by a fixed timeout (see Decision below) so a hung/blocking manager CLI fails rather than
hanging the apply (FR-005).

**Constraints**: **no shell** — the resolver is an argv list run directly (no `/bin/sh`,
no injection surface, Constitution II/III); **non-interactive** — `stdin` is closed, no TTY
prompt (FR-005); the resolver's **stderr is never echoed** (may carry secret material,
FR-006); the resolved value **never** reaches the repo, argv, logs, or the registry
(Constitution III); no new dependency (VI).

**Scale/Scope**: single operator; a handful of credentials per project; three new sources.

### Resolver timeout (the deferred clarification)

**Decision**: `_run_resolver` uses a fixed **30-second** timeout. Rationale: the operator
pre-unlocks the manager (non-interactive assumption), so resolution is a quick fetch, but a
manager may make a network round-trip (Vault, a cloud secret store) — 30 s is generous
enough for that yet bounded enough that a wedged CLI never hangs an apply. Not
operator-configurable in this feature (a fixed bound keeps the guarantee simple); revisit
only if a real manager needs longer.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|-----------|-----------|
| **I — Ephemerality & Commit-Push** | Unaffected — resolution is transient; nothing durable is added. ✅ |
| **II — Least Privilege / Immutable Runtime** | The resolver is an **argv list run directly with no shell** — the minimal execution surface; no injection, no `/bin/sh`. ✅ |
| **III — Least Exposure** | **The load-bearing gate.** The repo stores only a **locator**; the resolved secret lives only in memory + the existing 0600 staged files; the resolver **stderr is never echoed**; the secret never reaches argv/logs/registry. Every new path preserves this. ✅ |
| **IV — Deterministic Identity** | No identity surface touched. ✅ |
| **V — Hermetic, Contract-Pinned Testing** | `validate_credential` is pure; `resolve_credential_value`/`_run_resolver` shell out but are mocked in the hermetic tier; a real `command` source is exercised at the acceptance tier. ✅ |
| **VI — Least Dependencies** | **No new dependency** — managers are external CLIs the operator already has, invoked via argv. ✅ |
| **VII — Continuous Deployment** | A `feat` merge auto-releases; the removal of `encrypted` is a breaking change (pre-1.0 → still a minor bump), called out in the release notes. ✅ |

**Result**: PASS — no violations, no Complexity Tracking entries. The one notable event is
the **breaking removal of `encrypted`** (an intentional, spec-mandated change, refused with a
migration message — not a constitution deviation).

## Project Structure

### Documentation (this feature)

```text
specs/008-credential-managers/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions (argv-no-shell, _run_resolver, named argv, timeout, removal, testing)
├── data-model.md        # Phase 1 — the credential schema (sources, per-source fields, the resolver)
├── quickstart.md        # Phase 1 — validation scenarios (command / named / migration-refusal / no-plaintext)
├── contracts/
│   └── credential-managers.md  # Phase 1 — the credential schema + resolution contract
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

All implementation lands in the existing single-file CLI + the 006 credential test suite:

```text
bin/agent-container            # CRED_SOURCES (remove `encrypted`, add `command`/`onepassword`/
                               #   `bitwarden`); validate_credential (per-source fields +
                               #   argv-list type check + encrypted-migration refusal);
                               #   resolve_credential_value (the three new branches);
                               #   _run_decrypt → generalized _run_resolver (no-shell,
                               #   non-interactive, 30s-bounded, secret-free failure)
bin/tests/test_agent_as_code.py   # extend the 006 credential unit tests
bin/tests/test_acceptance.py      # a `command`-source declarative acceptance (reuse the 006 harness)
docs/agent-as-code.md             # the taxonomy + the new sources + the encrypted-removal migration
```

**Structure Decision**: Single-file CLI (no `src/` tree — the tool is one script by
decision, see CLAUDE.md). The feature is a focused edit to the 006 credential block plus its
test suite and docs. `_run_resolver` is the one new shared helper (a generalization of the
existing `_run_decrypt`, which is removed).

## Complexity Tracking

> No Constitution Check violations — this section is intentionally empty. (The breaking
> removal of `encrypted` is spec-mandated and refused with a migration message; it is a
> release-note item, not a complexity/deviation entry.)

## Phase notes

- **Phase 0 (research.md)** — the argv-no-shell resolver decision + the `_run_resolver`
  generalization; the named-source **argv assembly** (`op read op://vault/item/field`;
  `bw get <field> <item>`); the **30 s timeout**; the **encrypted removal + migration**
  refusal wording; and the testing approach (mock the runner in the hermetic tier).
- **Phase 1 (data-model, contracts, quickstart)** — the credential schema (sources +
  per-source required fields + the argv-list type rule); the resolution contract (host-side,
  non-interactive, bounded, secret-free-on-failure, in-memory → 003 channels); and quickstart
  journeys (a `command` source, a named source, the migration refusal, no-plaintext-on-disk).
- **Agent context update** — no `update-agent-context` script exists in this repo; skipped.
