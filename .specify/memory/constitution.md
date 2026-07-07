<!--
SYNC IMPACT REPORT
==================
Version change: 1.1.0 → 2.0.0   (MAJOR)
Bump rationale: Principle I was REDEFINED (a MAJOR event): "Ephemerality &
  Commit-Push Discipline" → "Ephemerality". The principle was raised to the
  invariant altitude and stripped of all technology-specific mechanism (SCM /
  git / commit-push / named volumes), stating the broad rule instead: a
  container is a disposable holder of short-lived working copies, no correctness
  may rest on in-container persistence, durable state is externalized
  continuously in small increments, and the system actively supports
  ephemeralization. The commit-and-push mechanism now lives only in lower-
  altitude guidance (Development Workflow section, CLAUDE.md).

Amendments in 2.0.0:
  Principle I REDEFINED & RENAMED — "Ephemerality & Commit-Push Discipline" →
  "Ephemerality". Broadened to a technology-agnostic invariant; the git
  commit-push mechanism is no longer part of the principle text.

Amendments carried from 1.1.0:
  #1 Accuracy fix — the intro agent list wrongly named "opencode". Ground
     truth (Dockerfile Layer 3, lines 51-57) installs exactly three agent CLIs:
     Claude Code, Codex, pi-coding-agent. "opencode" removed; not installed.
  #2 Principle IV — added a stable identity contract MUST clause: the
     name/port/volume/XDG on-disk identifiers MUST NOT change the value
     computed for an existing name without a versioned migration path, and any
     change MUST be mirrored in the shell completions. Prevents orphaning live
     containers/volumes, which would silently violate Principle I.
  #3 New Core Principle VI "Idiomatic Python on uv" — promoted from the
     "Platform & Interface Constraints" bullet of the same name; that bullet's
     substance was moved into Principle VI to avoid duplication; the platform-
     default and non-editable-PyPI-install facts are preserved in the new
     principle.

Principles (post-amendment):
  I.   Ephemerality                                          (redefined 2.0.0)
  II.  Rootless by Construction, Build-Time Dependencies
  III. Secrets Injected at Runtime — Never Baked, Never on Argv
  IV.  Parallel-Safe by Construction, One Source of Truth
  V.   Hermetic, Contract-Pinned Testing & Real-Build Verification
  VI.  Idiomatic Python on uv                                (new)

Sections:
  "Platform & Interface Constraints"     (Idiomatic-Python bullet promoted out)
  "Development Workflow & Quality Gates"

Templates reviewed:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate is
     generic ("Gates determined based on constitution file"); no hardcoded
     principle names, so it remains aligned. No edit required.
  ✅ .specify/templates/spec-template.md — no constitution references; aligned.
  ✅ .specify/templates/tasks-template.md — no constitution references; aligned.
  ✅ CLAUDE.md — hard constraints + decisions already encode these principles,
     including the uv/PyPI packaging facts now formalized in Principle VI.

Deferred TODOs: none.
-->

# agent-container Constitution

A containerized development environment that runs interactive and headless AI
coding agents (Claude Code, Codex, pi-coding-agent) inside disposable
containers, driven over SSH + tmux and managed by a single CLI. This
constitution encodes the non-negotiable rules that keep that system safe,
reproducible, and parallel by construction. It supersedes convenience and habit.

## Core Principles

### I. Ephemerality

A container is disposable: it holds short-lived working copies and nothing
durable. No correctness may rest on its storage surviving — in-container
persistence is a convenience, never a contract. Durable state MUST live in an
authoritative store beyond the container, kept current in small, continuous
increments, so nothing of value is ever *only* local. Containers MUST be cheap
to create and destroy; the system actively favors the short-lived over the
long-lived.

**Rationale:** a container discardable at any instant without loss is resilient
by construction — recreation becomes a non-event, and host loss, corruption, and
drift cease to be failure modes.

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
what the CLI produces. This on-disk contract is a **stable identity contract**:
no change may alter the value computed for an existing name — the
`agent-container-<name>` container (and `.service`) name, the
`2200 + (ASCII-sum mod 100)` port formula, the seven per-container volume
suffixes and their mount targets, or the XDG state/config paths (`<name>.port`,
`<name>.authorized_keys`, `hosts.conf`) and the env-file resolution order —
without a versioned migration path that renames or re-links live containers and
volumes, and every such change MUST be mirrored in the shell completions that
recompute the same values. An in-place change would orphan already-running
containers and their named volumes, silently violating Principle I.

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

### VI. Idiomatic Python on uv

The CLI is a single-file PEP 723 uv script (`bin/agent-container`, Typer +
questionary + rich) carrying a `uv run --script` shebang and an inline metadata
block that pins `requires-python = ">=3.11"` and its dependencies; that same
file ships unchanged as the `agent_container` wheel via a hatchling
`force-include`, so the PEP 723 dependency block MUST stay byte-for-byte in sync
with `[project].dependencies` in `pyproject.toml`. The CLI MUST work as a
non-editable PyPI / pipx install for every client subcommand through
location-independent `REPO_ROOT` resolution; only `build` may require a checkout
(supplied via `--context` / `AGENT_CONTAINER_REPO`). Runtime defaults MUST be
platform-aware (docker-first on macOS, podman-first on Linux) and overridable
via `AGENT_CONTAINER_RUNTIME`. Code MUST be idiomatic and stdlib-first: fully
type-annotated signatures using PEP 604 unions under
`from __future__ import annotations`, `pathlib.Path` in place of `os.path`
munging, and module-scope constants plus compiled regexes as the single source
of truth — with no third-party runtime dependency where the standard library
suffices (`hosts.conf` is hand-parsed, not delegated to a config library).
`subprocess` MUST always be invoked with an argv list and never `shell=True`,
keeping secrets and user/host/window values off any shell line. Pure,
side-effect-free helpers MUST stay separated from the runtime/subprocess,
command, and wizard layers, MUST raise the custom `Fatal` exception rather than
calling `sys.exit`, and MUST carry doctests that serve as their executable
contract (hardened by the pinned `--self-test` corpus). Diagnostics SHOULD go to
stderr while machine-readable output (`--json`, completion scripts) goes to
stdout, so the two streams stay cleanly separable.

**Rationale:** a single directly-executable uv script with pinned inline
metadata is reproducible and needs no separate install step, while the
stdlib-first, strongly-typed, doctested, layered style keeps the testable core
hermetic (Principle V) and makes the on-disk contract (Principle IV) verifiable
without ever touching a container runtime.

## Platform & Interface Constraints

- **Editor-agnostic, SSH + tmux only.** The canonical attach path is
  `ssh user@host -t tmux attach`. No `.devcontainer/` configs, no VSCode-locked
  tooling, no design that assumes a particular editor client.
- **Single operator.** One operator (the user) is assumed; multi-user / multi-
  tenant access controls, and Kubernetes/cluster orchestration, are out of scope
  unless explicitly requested.

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

**Version**: 2.0.0 | **Ratified**: 2026-07-06 | **Last Amended**: 2026-07-07
