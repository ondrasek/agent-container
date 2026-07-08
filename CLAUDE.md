# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project intent

Build a **containerized development environment** designed to run remotely (e.g., Hetzner VPS) as an always-on container that the user attaches to and detaches from over SSH. Inside, multiple AI coding agents (Claude Code, Codex, pi-coding-agent) and editors (nvim) run under tmux. Multiple such containers may run in parallel, each holding working copies of one or more git repositories.

This is a greenfield repo — no code has been written yet. Treat the section below as the design contract, not a description of existing code.

## Hard constraints

These are load-bearing design decisions, not preferences:

1. **No reliance on container persistence.** Every agent must `commit` AND `push` every change. The container is treated as ephemeral; if it dies, no work is lost. Any feature or workflow that depends on uncommitted state is wrong by construction.
2. **Editor-agnostic, not VSCode-locked.** The user explicitly rejected devcontainers because tooling support outside VSCode is nonexistent. Do not introduce `.devcontainer/` configs or any design that assumes a VSCode client. SSH + tmux is the canonical attach path.
3. **Multiple parallel containers.** Naming, port allocation, volume mounts, and git identity must all support N containers running simultaneously on the same host without collision.
4. **Push auth must work non-interactively.** Agents commit autonomously, so SSH keys / git credentials inside the container must be configured to push without prompts. Never embed long-lived secrets in the image — inject at runtime.

## Decisions

- **Runtime + base image:** Podman + `debian:12-slim`. See [`docs/decisions/0001-runtime-and-base-image.md`](docs/decisions/0001-runtime-and-base-image.md).
- **Rootless container, no runtime apt:** the image has NO `sudo`/root at runtime — `sshd` runs as the `dev` user on unprivileged port **2222** (host port maps `<hostport>:2222`), host key + `authorized_keys` on the dev-owned `~/.ssh` volume. Consequently **all system deps are baked at build time; agents never `apt install` at runtime** — add packages to the `Dockerfile` apt layer, never via runtime install.
- **SSH identity persists + is injectable:** the `-ssh` per-container volume (`~/.ssh`) keeps a stable host key + `authorized_keys` across recreation. Inject three ways (all land there): env-file (`SSH_AUTHORIZED_KEYS`, `SSH_HOST_ED25519_KEY_B64`), `up --host-key/--authorized-key`, or `keys <name>` (live, no recreate). Seven per-container volumes total: `workspace, claude, codex, pi, shellenv, tmux, ssh`.
- **CLI:** a single tool, `agent-container` (`bin/agent-container`) — a PEP 723 uv script (Typer + questionary + rich) covering the whole lifecycle (build/up/attach/logs/down/purge) plus an interactive wizard. Its on-disk contract (container names `agent-container-<name>`, the `2200 + name-hash` port, `$XDG_STATE_HOME/agent-container/<name>.port` state files, `~/.config/agent-container/hosts.conf`) is the single source of truth; the shell completions read the same state files. Runtime default is platform-aware (docker-first on macOS, podman-first on Linux); override with `AGENT_CONTAINER_RUNTIME`.
- **Packaging + release:** ships to PyPI as the `agent_container` module via a hatchling `force-include` wheel (`bin/agent-container` → `agent_container/__init__.py`; completions → `agent_container/completions/*` package data). `REPO_ROOT` resolves location-independently (`AGENT_CONTAINER_REPO` → `Dockerfile`+`completions/` marker → `None`) so a **non-editable** PyPI install works standalone (`up/down/list/attach/logs/purge/completions`); only `build` needs a checkout (via `AGENT_CONTAINER_REPO`/`--context`). `uv tool install --editable .` remains the dev path. Licensed **MIT** ([`LICENSE`](LICENSE)).
- **CI/CD — Continuous Deployment:** `ci.yml` runs parallel jobs on every push/PR (`lint` = ruff check + format --check · `test` = pytest across the 3.11/3.12/3.13 matrix · `shell` = the bash suites · `build` = `uv build` · `acceptance` = real-container validation). On a **merge to `main`, once `ci` passes** (`release.yml` fires via `workflow_run`), **python-semantic-release** computes the strict-semver bump from Conventional Commits (`feat`→minor, `fix`→patch, breaking→minor while pre-1.0; docs/ci/chore/test/style cut **no** release), bumps `pyproject.toml [project].version` + `CHANGELOG.md`, commits `chore(release): X.Y.Z [skip ci]`, tags `vX.Y.Z`, and publishes to PyPI via **OIDC Trusted Publishing** (no stored token). Version is single-sourced in `pyproject.toml`; the CLI reports it via `--version`. So **every substantive merge to main is a release** — no manual tagging, no release PR. (Prereq: the PyPI project's Trusted Publisher must point at `release.yml` + the `release` environment.)

## Architecture sketch (to be built)

Expect the repo to grow into roughly:

- **Container image** — base OS + tmux + SSH server + nvim + git + the agent CLIs (Claude Code, Codex, pi-coding-agent) and their language runtimes.
- **Orchestration layer** — scripts or compose/quadlet definitions to launch, name, attach to, and tear down containers on the remote host.
- **Bootstrap / entrypoint** — sets up git identity, injects credentials, starts sshd + a default tmux session, optionally clones configured repos.
- **Attach tooling** — a thin client-side helper for `ssh user@host -t tmux attach -t <session>` style flows across multiple hosts/containers.

When adding a component, keep these layers separate. Don't bake host-specific orchestration into the image.

## Conventions for future work

- The container is **rootless by decision** (see Decisions): no `sudo`/root at runtime, sshd as `dev` on port 2222. Keep it that way — don't reintroduce root-only steps; bake deps at build. Also avoid features that only work on Docker Desktop (stay Podman-compatible).
- Treat the **commit-and-push discipline** as a property of the agent configuration, not something to enforce via git hooks alone (hooks can be bypassed; the agents themselves should be configured to push).
- **Quality gate — one script, two uses.** `scripts/quality-gate.sh` is the single source of truth for the fast checks (ruff check + format, `--self-test`, hermetic pytest, shell suites; ~7s). The local Claude Code **Stop hook** runs it and feeds failures back for auto-fix (`exit 2`); the **CI `quality-gate` job** runs the *same* script as a hard gate. Register the hook per-clone (`.claude/` is gitignored) — see the header of `scripts/quality-gate.sh`. The gate excludes the slow **acceptance** layer (real containers): that is the authoritative CI-only tier (`pytest -m acceptance bin/tests`; on macOS+Lima its work dir must be Lima-shared — defaults to `~/.cache/agent-container-acceptance`, override `AGENT_CONTAINER_ACCEPTANCE_TMPDIR`). `ci.yml` also runs the cross-version pytest matrix, `commits`, `build`, and `acceptance`; a gate failure blocks the release (Principle VII).
- **Conventional Commits are mandatory** — the CD pipeline (Principle VII) reads them to compute releases. Enforced three ways: (1) a local `commit-msg` hook (`.githooks/`, via `git config core.hooksPath .githooks` — run once per clone) that runs `commitizen` (`cz check`); (2) the `commits` CI job validating a PR's commits; (3) a GitHub **ruleset** rejecting non-conforming commits on push to `main` (`.github/conventional-commits-ruleset.json`; apply with `gh api -X POST /repos/ondrasek/agent-container/rulesets --input .github/conventional-commits-ruleset.json`). Types: `feat`/`fix`/`docs`/`style`/`refactor`/`perf`/`test`/`build`/`ci`/`chore`/`revert` (+ `!`/`BREAKING CHANGE` for breaking). Merge/revert messages pass. `--no-verify` bypasses the local hook only.
- When proposing a tool or dependency, justify it against the constraints above — especially the "not VSCode-locked" one.

## Out of scope (don't add unless asked)

- IDE integrations beyond plain SSH/tmux/nvim.
- Multi-user / multi-tenant access controls — single operator (the user) is assumed.
- Kubernetes manifests — the target is a single VPS running a container runtime, not a cluster.
