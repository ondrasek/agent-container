# CLAUDE.md

## Project intent

Build a **containerized development environment** that runs remotely (e.g., Hetzner VPS) as an always-on container the user attaches to and detaches from over SSH. Inside, AI coding agents (Claude Code, Codex, pi-coding-agent, opencode) and nvim run under tmux. Multiple such containers may run in parallel, each holding working copies of one or more git repositories.

## Hard constraints

Load-bearing design decisions, not preferences:

1. **No reliance on container persistence.** Every agent must `commit` AND `push` every change.
   The container is ephemeral; if it dies, no work is lost. Any feature that depends on
   uncommitted state is wrong by construction.
2. **Editor-agnostic, not VSCode-locked.** Devcontainers were explicitly rejected — tooling
   outside VSCode is nonexistent. No `.devcontainer/`; SSH + tmux is the canonical attach path.
3. **Multiple parallel containers.** Naming, ports, volumes and git identity must all support N
   containers on one host without collision.
4. **Push auth must work non-interactively.** Agents commit autonomously, so git credentials
   inside the container must push without prompts (injected at runtime — see Decisions).

## Decisions

Load-bearing invariants only — read `docs/` and `specs/<NNN>-*/` before changing behaviour in an
area, and do not re-summarise them here.

- **Runtime + base image:** Podman + `debian:12-slim` ([ADR 0001](docs/decisions/0001-runtime-and-base-image.md)).
  Stay Podman-compatible — never depend on Docker Desktop-only behaviour.
- **Layout (specs/011) — [`docs/layout.md`](docs/layout.md) is the one map.** **project root** ·
  **project config** `.agent-container/` (travels with the repo) · **user configuration**
  `~/.config/agent-container/` · **derived host state** · **image sources** `image/`. Never "project
  directory". Config is two levels, project winning, same filename both; **plaintext credentials are
  user-level only**. Context **is** `image/`. **Pre-011 layouts are refused, not ignored.**
- **Run mechanism is compose** (v2), generated and run **on the target host**. A host bind fails over
  a remote context, and `configs: {file:}` **is** a bind (measured); only `{content:}` is
  API-delivered. Inline non-secret injected material; the 001/003 lesson.
- **Credentials are runtime-injected, least-exposure (Constitution III).** Never baked, on argv,
  or printed. Tool-injected secrets land under `/run/agent-container/…`, **never** on a volume; a
  missing referenced file must `die` **before** compose. On-volume `auth.json` is
  **operator-interactive-login only**; a private SSH **host** key is never injected at all. Rotate = edit locally + `redeploy`.
- **The supported-agent list is single-sourced** (`AGENTS`); a sibling test pins the completions'
  command list to the CLI's. Both fail on drift and name what to update.
- **A named volume's mount point must exist in the image, dev-owned** — else the runtime creates it
  `root:root` and rootless cannot write it.
- **Packaging:** PyPI as `agent_container`; `REPO_ROOT` resolves location-independently (only `build`
  needs a checkout). **PyYAML is the one third-party dep**; `yaml.safe_load` **only** — never a regex
  over structured formats. Justify any new dep against Constitution VI. MIT.
- **Egress enforcement is packet-level and says so.** Default-deny in a netns shared with the
  **egress sidecar**, which alone holds `NET_ADMIN`; squid **splices, never bumps** — a locally-issued
  CN means the boundary inverted. A declared port selects netfilter over the proxy allowlist; sidecars
  are inside unless declared out. A declaration governs **all** egress (it breaks HTTPS `git push`
  unless declared); absent ≠ `allow: []`; the strength statement is tested for **absence** of
  overclaim.
- **Host identity is CAPTURED, never supplied.** Each deploy pins the container's **public** key as
  `[address]:port` in derived host state. **Mismatch ⇒ refuse, never a prompt**; absent ⇒ warn +
  fingerprint + ask (no tty ⇒ refuse) — a pin must **predate** what it checks.
- **The inventory remembers what we CREATED; `panic` acts on it.** Durable but **flat** (an entry
  outlives its host); capped by count, **never age**; not backfilled. `panic` enumerates from it (not
  "whichever hosts answer"), stops by **compose project label** (the compose file dies with its
  host), and verifies by **observation** — two host queries, since `already-stopped` needs a
  pre-snapshot. **Unreachable ⇒ `undetermined`, never `stopped`/`missing`**, one undetermined fails
  the run, and an **unverified destroy writes no outcome**.
- **A run's account outlives its container.** The container writes the record to the runs volume
  (only the entrypoint is there when a detached run ends), the CLI ingests on next contact, and
  **teardown drains before it removes volumes**; `task` is the one operator-authored field,
  recorded verbatim, and *unknown* usage is never `0`.
- **Every substantive merge to `main` is a release.** Once `ci` passes, python-semantic-release bumps
  from Conventional Commits (`feat`→minor, `fix`→patch, breaking→minor pre-1.0; docs/ci/chore/test/
  style cut none), tags and publishes via OIDC. No manual tagging.

### Where the detail lives

`docs/layout.md` (the location map · 011) · `docs/orchestration.md` (hosts, compose/quadlet,
lifecycle, volumes · 001,002) · `docs/credentials.md` (injection, managers · 003,008) ·
`docs/execution.md` (modes, `--agent`/`--task`/`--workspace`, clone-on-start · 004,010) ·
`docs/shell-integration.md` (`attach --print`, `host env`, verified attach · 005,018) · `docs/agent-as-code.md`
(declarative `.agent-container/` · 006,008) · `docs/agent-interface.md` (`--json`, `context`,
`skill` · 009) · `docs/egress.md` (declaration, enforcement, honesty · 012) ·
`docs/observability.md` (016) · `docs/inventory.md` (record, reconcile, retention · 014) ·
`docs/threat-model.md` (**reconcile every feature** — Constitution) · specs/007 (wizard).

## Architecture (keep these layers separate)

- **Container image** (`image/`) — base OS, tmux, sshd, nvim, git, the agent CLIs.
- **Orchestration** (`bin/agent-container` + compose) — launch, name, attach, tear down.
- **Entrypoint** — git identity, credential injection, sshd + default tmux session.
- **Attach** — thin client-side `ssh … -t tmux attach` across hosts/containers.

Don't bake host-specific orchestration into the image.

## Conventions for future work

- **Rootless by decision**: no `sudo`/root at runtime, sshd as `dev` on 2222. **Bake every system dep
  at build time — agents never `apt install` at runtime.**
- **Commit-and-push** is a property of the agent config, not of git hooks (bypassable).
- **Quality gate — one script, two uses.** `scripts/quality-gate.sh` owns the fast checks (the
  roster is the script's, not this file's). The local Stop hook runs it; CI runs the *same*
  script as a hard gate.
  It **excludes** the CI-authoritative acceptance tier (`pytest -m acceptance bin/tests`; on
  macOS+Lima the work dir must be Lima-shared). **Read its exit code unpiped** — `| tail` reports
  tail's status, not the gate's.
- **Run the full suite, not just your new tests** — a changed contract is exactly when a
  pre-existing test still pins the old shape.
- **Conventional Commits are mandatory** — the CD pipeline reads them. Enforced three ways: the
  local `commit-msg` hook (`git config core.hooksPath .githooks`, once per clone), the `commits`
  CI job, and a ruleset on `main`. `--no-verify` bypasses only the first.
- **Every short flag needs a long one** (`-y`/`--yes`); a test enforces it, and one proves that
  check can fail.
- **Keep this file under 2000 tokens.** It is loaded every session; new detail goes to `docs/` and
  `specs/`, at most a one-line invariant here.

## Out of scope (don't add unless asked)

- IDE integrations beyond SSH/tmux/nvim.
- Multi-user / multi-tenant access controls — single operator (the user) is assumed.
- Kubernetes manifests — the target is a single VPS, not a cluster.
