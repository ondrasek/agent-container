# Implementation Plan: Agent Provisioning & Credentialing

**Branch**: `003-agent-credentialing` | **Date**: 2026-07-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-agent-credentialing/spec.md`

## Summary

Give each deployed container everything an agent needs to function — its **push
credential**, its **model/API credential**, and its **canonical configuration**
— provisioned at runtime under a strict least-exposure discipline, with the
agent's **mutable runtime state** persisted across recreation.

Technical approach (see [research.md](./research.md)): extend Feature 001's
injected-material seam (compose `configs` referencing locally-staged files that
transfer over the runtime context) with two secret classes and a config-manifest.
The load-bearing new discipline is **ephemeral delivery** — the outbound SSH push
key and injected model/API keys land in `/run/agent-container/…` and are **never**
copied onto a persistent volume (the opposite of the inbound host key, which
persists for identity), so the operator's local copy is the sole durable copy
(FR-012/SC-004). Both credential reversals are **layered**: the SSH push key
(default) sits alongside the retained HTTPS+`GH_TOKEN` path; file-by-default API
delivery sits alongside the retained env/`.env` and interactive-login
"stored-authorization" modes. Canonical config is copied fresh from the ephemeral
inject dir onto the per-agent volume on each boot (edits propagate on redeploy)
while runtime state on the volume is untouched. Zero new Python dependencies.

## Technical Context

**Language/Version**: Python ≥ 3.14 (single-file host CLI `bin/agent-container`,
PEP 723); container-side wiring in `entrypoint.sh` (bash) against the baked agents
(Node 22 / Python 3 in the image).

**Primary Dependencies**: none new. Typer + questionary + rich (existing CLI);
the container runtime's **Compose v2** (`configs` delivery); stdlib only for
staging (`pathlib`, `subprocess`, `base64`). Agent credential mechanisms:
Claude `apiKeyHelper`, `codex login --with-api-key`, pi `auth.json` — all baked,
no new tool installs (Constitution II).

**Storage**: injected secrets → **ephemeral** compose `configs` at
`/run/agent-container/…` (vanish with the container); canonical config → same
ephemeral surface, copied onto the per-agent volume by the entrypoint each boot;
runtime state → the shipped seven per-container named volumes.

**Testing**: hermetic unit (`bin/tests/` — compose-model construction asserts
push key / API key / canonical config ride as `configs` at the right targets and
never appear on argv or as inlined values; the `entrypoint.sh` shell suite covers
`GIT_SSH_COMMAND`, `apiKeyHelper`, and the canonical-copy step). Acceptance
(`-m acceptance`, real container): non-interactive SSH push, config-fresh-on-
redeploy, and no-secret-on-teardown. The backend-reachability check (SC-002) is
an **opt-in tokened** acceptance test (like the Hetzner one) — CI never runs it
(no cost, no secret in CI).

**Target Platform**: the host CLI runs on the operator machine (macOS/Linux);
delivery works local and over a remote docker context (FR-014, inherited).

**Project Type**: single-file CLI + container image (no web/mobile split).

**Performance Goals**: N/A (provisioning is one-shot at deploy; no hot path).

**Constraints**: least-exposure invariants FR-010…FR-015 are hard constraints,
not goals — no secret on argv, in an image layer, in a persistent volume, or
distributed beyond the one deployment. Zero new Python dependencies (Constitution
VI). The rootless/immutable-runtime rules hold: all agent tooling is baked; the
entrypoint only wires already-present mechanisms (Constitution II).

**Scale/Scope**: single operator; the three baked agents (Claude Code, Codex,
pi-coding-agent); N parallel deployments, each independently credentialed.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after design. Constitution v2.1.0.*

| Principle | Assessment |
|-----------|------------|
| **I. Ephemerality** | ✅ Strengthened. Secrets are ephemeral; the only durable copy is the operator's. Runtime state is the sole thing persisted, and its loss is a non-event. |
| **II. Least Privilege, Immutable Runtime** | ✅ No runtime `apt`/installs; every agent credential mechanism (`apiKeyHelper`, `codex login`, `auth.json`) is already baked. The entrypoint wires, it does not reshape the runtime. |
| **III. Least Exposure** | ✅ **This feature's governing principle.** File-not-argv, ephemeral-not-persistent, per-deployment scope, github.com-scoped credential, `IdentitiesOnly` push. Exposure minimized in scope and reach. |
| **IV. Deterministic Identity** | ✅ No change to the name/port/volume identity contract. Injected paths are deterministic per `(host,name)`; the outbound push key is explicitly a *distinct* credential from the inbound host key (SC-008), not a redefinition. |
| **V. Durable Spec, Disposable Code** | ✅ Verification is acceptance-weighted (push works with zero prompts; secrets absent from all surfaces) — checks that survive a re-implementation, over argv-pinned internals. |
| **VI. Least Dependencies** | ✅ Zero new Python deps; reuses the compose `configs` seam and stdlib staging. |
| **VII. Continuous Deployment** | ✅ Ships as a `feat` minor (→ 0.7.0) on merge; docs updated in-change (FR-018). |

**Result: PASS, no violations.** No entries in Complexity Tracking. Re-checked
after Phase 1 design — still PASS (the design adds no new dependency, no new
privilege, no identity-contract change).

## Project Structure

### Documentation (this feature)

```text
specs/003-agent-credentialing/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R7 decisions
├── data-model.md        # Phase 1 — injected-material entities + manifests
├── quickstart.md        # Phase 1 — validation scenarios A..G
├── contracts/
│   └── credentialing.md # Phase 1 — CLI flags, env channel, injected paths, entrypoint wiring
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
bin/agent-container          # single-file CLI — the only Python edited:
                             #   • --push-key / --known-hosts on up/redeploy
                             #   • stage_push_injection(...) (ephemeral target, mirrors stage_ssh_injection)
                             #   • model/API key + canonical-config staging (ephemeral configs)
                             #   • build_compose_model(): new configs (push key, known_hosts, api keys, canonical config)
                             #   • constants: INJECT_PUSH_KEY_PATH, INJECT_KNOWN_HOSTS_PATH, INJECT_APIKEY_DIR, INJECT_CONFIG_DIR
entrypoint.sh                # container wiring (bash):
                             #   • GIT_SSH_COMMAND from the injected push key + known_hosts (never persisted)
                             #   • per-agent API-cred wiring (Claude apiKeyHelper / codex login / pi) — file-first, env fallback
                             #   • copy canonical config from the inject dir onto the per-agent volume each boot
docs/credentials.md          # FR-018: SSH push section added; HTTPS kept as the documented alternative
.env.example                 # FR-018: push-key env channel + notes
README.md, CLAUDE.md         # FR-018: the credential model
bin/tests/
├── test_command_construction.py   # compose-model + staging unit tests (new configs, no-argv, no-inline)
├── test_credentialing.py          # NEW — push/api/config staging + manifest classification
├── test_entrypoint.*  (shell)     # GIT_SSH_COMMAND / apiKeyHelper / canonical-copy wiring
└── test_acceptance.py             # real-container: SSH push, redeploy-fresh-config, teardown-no-secret (+ opt-in tokened backend reach)
```

**Structure Decision**: unchanged from 001/002 — one CLI file plus the container
`entrypoint.sh`. No new module; the injection seam and the seven volumes already
exist. New behavior is additive staging + entrypoint wiring, single-file-
sequential for the CLI (no `[P]` on `bin/agent-container` edits).

## Complexity Tracking

> No Constitution violations — this section is intentionally empty.

## Phase 0 — Outline & Research

Complete. See [research.md](./research.md): R1 (SSH push, layered over HTTPS),
R2 (ephemeral delivery / FR-012 discipline), R3 (API creds file-by-default +
fallbacks), R4 (canonical-fresh vs runtime-persist split), R5 (injected-material
taxonomy on the configs seam), R6 (rotation/scoping/fail-fast — emergent),
R7 (CLI + env-file surface). No NEEDS CLARIFICATION remain (the two shipped-
reversal decisions were confirmed as **layered** at plan time).

## Phase 1 — Design & Contracts

Complete. [data-model.md](./data-model.md) defines the injected-material entities
(secret vs config classes), the push-credential pair, the per-agent API-cred
modes, and the canonical/runtime manifest. [contracts/credentialing.md](./contracts/credentialing.md)
pins the CLI flags, the env-file channel, the injected `/run` paths, and the
entrypoint wiring contract. [quickstart.md](./quickstart.md) gives runnable
validation scenarios mapped to SC-001…SC-008.

## Phase 2 — Task planning approach (for /speckit-tasks, NOT executed here)

Tasks will be organized by user story (US1 push → US2 API → US3 config → US4
rotation/scoping) on the foundational staging/taxonomy work, each an independently
testable increment (MVP = US1, non-interactive push). `bin/agent-container` edits
are sequential (single file); test modules and docs are the `[P]` opportunities.
The backend-reach and SSH-push acceptance tests are opt-in/tokened, outside the
CI cost boundary.
