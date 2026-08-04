# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project intent

Build a **containerized development environment** designed to run remotely (e.g., Hetzner VPS) as an always-on container that the user attaches to and detaches from over SSH. Inside, AI coding agents (Claude Code, Codex, pi-coding-agent, opencode) and editors (nvim) run under tmux. Multiple such containers may run in parallel, each holding working copies of one or more git repositories.

## Hard constraints

Load-bearing design decisions, not preferences:

1. **No reliance on container persistence.** Every agent must `commit` AND `push` every change.
   The container is ephemeral; if it dies, no work is lost. Any feature that depends on
   uncommitted state is wrong by construction.
2. **Editor-agnostic, not VSCode-locked.** Devcontainers were explicitly rejected — tooling
   outside VSCode is nonexistent. No `.devcontainer/`, no design assuming a VSCode client.
   SSH + tmux is the canonical attach path.
3. **Multiple parallel containers.** Naming, ports, volumes and git identity must all support N
   containers on one host without collision.
4. **Push auth must work non-interactively.** Agents commit autonomously, so git credentials
   inside the container must push without prompts. Never embed long-lived secrets in the image —
   inject at runtime.

## Decisions

Load-bearing invariants only. **Per-feature detail lives in `docs/` and `specs/<NNN>-*/`** — read
those before changing behaviour in that area; do not re-summarise them here.

- **Runtime + base image:** Podman + `debian:12-slim` ([ADR 0001](docs/decisions/0001-runtime-and-base-image.md)).
  Stay Podman-compatible — never depend on Docker Desktop-only behaviour.
- **Layout (specs/011) — [`docs/layout.md`](docs/layout.md) is the one map.** **project root** ·
  **project config** `.agent-container/` (travels with the repo) · **user configuration**
  `~/.config/agent-container/` · **derived host state** · **image sources** `image/`. Never
  "project directory". Config is two levels, project winning, same filename both. **Plaintext
  credentials are user-level only** (repo holds a locator, never a value). `-e` is repeatable and
  replaces discovery; bare `./.env` unread. Context **is** `image/`. Shell env at `~/.agent-env`. **Pre-011 layouts are refused, not ignored.**
- **Run mechanism is compose** (Compose v2), generated and run **on the target host** — context
  and injected files travel to that daemon. A **host bind fails over a remote context** — and
  `configs: {file:}` **is** a bind (measured); only `configs: {content:}` is API-delivered. Inline
  non-secret injected material; the 001/003 lesson.
- **Credentials are runtime-injected, least-exposure (Constitution III).** Never baked, on argv,
  or printed. Tool-injected secrets land under `/run/agent-container/…`, **never** on a volume; a
  missing referenced file must `die` **before** compose. On-volume `auth.json` is
  **operator-interactive-login only**. Rotate = edit locally + `redeploy`.
- **The supported-agent list is single-sourced.** `AGENTS` in `bin/agent-container` is canonical;
  tests fail on drift across entrypoint, Dockerfile, completions, help and docs, and name what to
  update. A sibling test pins the completions' command list to the CLI's.
- **A named volume's mount point must exist in the image, dev-owned** — else the runtime creates
  it `root:root` and rootless cannot write it, even under a dev-owned parent. `opencode` is the
  only agent with two volumes (XDG splits config from credentials).
- **Packaging:** PyPI as `agent_container`; `REPO_ROOT` resolves location-independently so a
  non-editable install works standalone — only `build` needs a checkout. **PyYAML is the one
  third-party dep**; `yaml.safe_load` **only** — never a regex over structured formats. MIT.
- **Egress enforcement is proxy-level and says so.** A declaration governs **all** egress (it
  breaks HTTPS `git push` unless declared — checked at deploy); absent ≠ `providers: []`; the
  strength statement is tested for **absence** of overclaim.
- **Every substantive merge to `main` is a release.** Once `ci` passes, python-semantic-release
  bumps from Conventional Commits (`feat`→minor, `fix`→patch, breaking→minor pre-1.0;
  docs/ci/chore/test/style cut none), tags, and publishes via OIDC Trusted Publishing. No manual
  tagging. (`publish.yml` keeps its name to match the PyPI binding.)

### Where the detail lives

`docs/layout.md` (the location map · 011) · `docs/orchestration.md` (hosts, compose/quadlet,
lifecycle, volumes · 001,002) · `docs/credentials.md` (injection, managers · 003,008) ·
`docs/execution.md` (modes, `--agent`/`--task`/`--workspace`, clone-on-start · 004,010) ·
`docs/shell-integration.md` (`attach --print`, `host env` · 005) · `docs/agent-as-code.md`
(declarative `.agent-container/` · 006,008) · `docs/agent-interface.md` (`--json`, `context`,
`skill` · 009) · `docs/egress.md` (declaration, enforcement, honesty · 012) · specs/007 (wizard).

## Architecture (keep these layers separate)

- **Container image** (`image/`) — base OS, tmux, sshd, nvim, git, the agent CLIs.
- **Orchestration** (`bin/agent-container` + compose) — launch, name, attach, tear down.
- **Entrypoint** — git identity, credential injection, sshd + default tmux session.
- **Attach** — thin client-side `ssh … -t tmux attach` across hosts/containers.

Don't bake host-specific orchestration into the image.

## Conventions for future work

- **Rootless by decision**: no `sudo`/root at runtime, sshd as `dev` on 2222. **Bake every system
  dep at build time — agents never `apt install` at runtime.** Add packages to the `Dockerfile`.
- Treat **commit-and-push** as a property of the agent config, not something enforced by git
  hooks alone (they can be bypassed).
- **Quality gate — one script, two uses.** `scripts/quality-gate.sh` is the single source of
  truth for the fast checks (ruff · ty · bandit · vulture · xenon · refurb · `--self-test` ·
  pytest · shell suites). The local Stop hook runs it; CI runs the *same* script as a hard gate.
  It **excludes** the CI-authoritative acceptance tier (`pytest -m acceptance bin/tests`; on
  macOS+Lima the work dir must be Lima-shared). A gate failure blocks the release. **Read its exit
  code unpiped** — `| tail` reports tail's status, not the gate's.
- **Run the full suite, not just your new tests** — changing a shared contract is exactly when a
  pre-existing test still pins the old shape.
- **Conventional Commits are mandatory** — the CD pipeline reads them. Enforced three ways: the
  local `commit-msg` hook (`git config core.hooksPath .githooks`, once per clone), the `commits`
  CI job, and a ruleset on `main`. `--no-verify` bypasses only the first.
- **Every short flag needs a long one** (`-y`/`--yes`); a test enforces it, plus one proving that
  check can fail.
- Justify any new tool or dependency against the constraints above — especially "not
  VSCode-locked" and Constitution VI.
- **Keep this file under 2000 tokens.** It is loaded every session. New feature detail belongs in
  `docs/` and `specs/`, with at most a one-line invariant here.

## Out of scope (don't add unless asked)

- IDE integrations beyond SSH/tmux/nvim.
- Multi-user / multi-tenant access controls — single operator (the user) is assumed.
- Kubernetes manifests — the target is a single VPS, not a cluster.
