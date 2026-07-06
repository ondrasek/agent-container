<!--
SYNC IMPACT REPORT
==================
Version change: (template) → 1.0.0   (initial ratification)
Bump rationale: First concrete constitution; establishes the five core
  principles and governance. MAJOR baseline.

Principles defined:
  I.   Ephemerality & Commit-Push Discipline
  II.  Rootless by Construction, Build-Time Dependencies
  III. Secrets Injected at Runtime — Never Baked, Never on Argv
  IV.  Parallel-Safe by Construction, One Source of Truth
  V.   Hermetic, Contract-Pinned Testing & Real-Build Verification

Sections:
  Added: "Platform & Interface Constraints"
  Added: "Development Workflow & Quality Gates"

Templates reviewed:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate is
     generic ("Gates determined based on constitution file"); no hardcoded
     principle names, so it remains aligned. No edit required.
  ✅ .specify/templates/spec-template.md — no constitution references; aligned.
  ✅ .specify/templates/tasks-template.md — no constitution references; aligned.
  ✅ CLAUDE.md — hard constraints + decisions already encode these principles.

Deferred TODOs: none.
-->

# agent-container Constitution

A containerized development environment that runs interactive and headless AI
coding agents (pi-coding-agent, opencode, Codex, Claude Code) inside disposable
containers, driven over SSH + tmux and managed by a single CLI. This
constitution encodes the non-negotiable rules that keep that system safe,
reproducible, and parallel by construction. It supersedes convenience and habit.

## Core Principles

### I. Ephemerality & Commit-Push Discipline

The container is disposable and treated as ephemeral at all times. Every agent
and workflow MUST `commit` **and** `push` every change; durable state lives in
git remotes, never in the container. Persistent volumes hold scratch and
in-flight work only — they are a convenience, not a system of record, and any
feature that depends on uncommitted or unpushed state to be correct is wrong by
construction. If the container dies, no work may be lost.

**Rationale:** the environment targets always-on remote containers that are
routinely recreated; correctness cannot hinge on a filesystem that can vanish.

### II. Rootless by Construction, Build-Time Dependencies

The container image has NO `sudo` and NO root at runtime. `sshd` runs as the
non-root `dev` user on an unprivileged port; SSH host key and `authorized_keys`
live on a dev-owned volume. All system dependencies MUST be installed at image
**build** time (the Dockerfile apt/download layers) — agents MUST NOT
`apt install` or otherwise mutate system packages at runtime. Rootless-friendly,
Podman-compatible patterns are required; Docker-Desktop-only features are
prohibited.

**Rationale:** untrusted agent code runs inside; removing runtime root removes
the escalation surface, and baking deps at build keeps the image reproducible
and the runtime immutable.

### III. Secrets Injected at Runtime — Never Baked, Never on Argv

No secret (tokens, API keys, private keys) may be baked into the image or
committed to the repo. Secrets are injected at run time via `--env-file` /
`EnvironmentFile=` or dedicated volumes, and MUST never appear on a process
command line (`argv`) — secret material is streamed over stdin or read from
files/env inside the container. Credential grants MUST be scoped to their
intended host/service (e.g. the git helper is bound to `github.com`, not global).

**Rationale:** this is a single-operator system running autonomous agents;
argv, image layers, and over-broad credential scope are the leak vectors that
matter, so they are closed by rule, not by care.

### IV. Parallel-Safe by Construction, One Source of Truth

N containers MUST run concurrently on one host without collision: naming
(`agent-container-<name>`), port allocation (`2200 + name-hash`), per-container
volumes, and per-container SSH identity are all derived deterministically from
the container name. The single-file CLI's on-disk contract — container names,
ports, `$XDG_STATE_HOME` state files, and `~/.config/agent-container/hosts.conf`
— is the authoritative source of truth; shell completions, orchestration
templates (Compose/Quadlet), and any other consumer MUST read that same contract
rather than reimplementing it. Orchestration templates MUST stay at parity with
what the CLI produces.

**Rationale:** divergent copies of "where the port/volume/name comes from" are
how parallel-safety and persistence guarantees silently rot.

### V. Hermetic, Contract-Pinned Testing & Real-Build Verification

The pytest suite MUST run without docker, podman, ssh, or network access:
runtime-facing behavior is verified by capturing and pinning the exact `argv`
handed to the runtime/ssh, and the on-disk contract is pinned by doctests. Shell
suites cover completions and the entrypoint. Every one of these MUST run in CI.
Behavior that only a real container can prove (rootless sshd, key persistence,
injection) MUST be verified against an actual `docker`/`podman` build before the
change is considered done — riskiest unknowns first. A change that cannot be
observed working is not done.

**Rationale:** hermetic tests make the suite fast and portable; byte-level
pinning turns the on-disk contract into an executable spec; real-build checks
catch what mocks cannot.

## Platform & Interface Constraints

- **Editor-agnostic, SSH + tmux only.** The canonical attach path is
  `ssh user@host -t tmux attach`. No `.devcontainer/` configs, no VSCode-locked
  tooling, no design that assumes a particular editor client.
- **Single operator.** One operator (the user) is assumed; multi-user / multi-
  tenant access controls, and Kubernetes/cluster orchestration, are out of scope
  unless explicitly requested.
- **Idiomatic Python on uv.** The CLI is a single PEP 723 uv script
  (`bin/agent-container`, Typer + questionary + rich) that also ships as a wheel.
  It MUST work as a non-editable PyPI install for the client subcommands
  (location-independent `REPO_ROOT` resolution); only `build` may require a
  checkout. Runtime defaults are platform-aware (docker-first on macOS,
  podman-first on Linux) and overridable via `AGENT_CONTAINER_RUNTIME`.

## Development Workflow & Quality Gates

- **Green before commit.** The full suite (hermetic pytest + shell suites +
  self-test) MUST pass, and non-trivial runtime changes MUST be exercised
  against a real build, before a change is committed.
- **CI is the gate.** `ci.yml` runs the pytest and shell suites plus `uv build`
  on every push/PR; releases go to PyPI via Trusted Publishing (OIDC, no stored
  secrets) on `v*` tags, re-running the suite first.
- **Docs track code.** README, `docs/`, and CLAUDE.md MUST be updated in the same
  change when behavior, setup, the on-disk contract, or the security posture
  changes. Stale docs are treated as defects.
- **Commit and push.** Consistent with Principle I, work is committed and pushed;
  the commit-and-push discipline is a property of agent configuration, not
  enforced by hooks alone.

## Governance

This constitution supersedes other practices when they conflict. Amendments MUST
be made by editing this file with a documented rationale, a semantic version
bump, and synchronized updates to any dependent templates and guidance
(`.specify/templates/*`, CLAUDE.md).

**Versioning policy (semantic):**
- **MAJOR** — removing or redefining a principle, or any backward-incompatible
  governance change.
- **MINOR** — adding a principle/section or materially expanding guidance.
- **PATCH** — clarifications, wording, and non-semantic refinements.

**Compliance:** every PR and review MUST verify compliance with these
principles; deviations MUST be justified in the change (see the plan template's
Constitution Check / Complexity Tracking). Unjustified complexity is rejected.
Runtime, day-to-day development guidance lives in **CLAUDE.md**, which MUST stay
consistent with this constitution.

**Version**: 1.0.0 | **Ratified**: 2026-07-06 | **Last Amended**: 2026-07-06
