# CLAUDE.md

What this is: [`README.md`](README.md). What follows is what must not be got wrong.

## Hard constraints

1. **No reliance on container persistence.** Every agent must `commit` AND `push` every change. Any
   feature depending on uncommitted state is wrong by construction.
2. **Editor-agnostic, not VSCode-locked.** Devcontainers rejected; no `.devcontainer/`. SSH + tmux is
   the canonical attach path.
3. **Multiple parallel containers.** Naming, ports, volumes and git identity must support N on one
   host without collision.
4. **Push auth must work non-interactively** — agents commit autonomously, so no prompts.

## Decisions

Load-bearing invariants only. Read `docs/` and `specs/<NNN>-*/` before changing behaviour; don't
re-summarise them here.

- **Runtime + base image:** Podman + `debian:12-slim` ([ADR 0001](docs/decisions/0001-runtime-and-base-image.md)).
  Stay Podman-compatible; never depend on Docker Desktop-only behaviour.
- **Layout (011) — [`docs/layout.md`](docs/layout.md) is the one map.** **project root** · **project
  config** `.agent-container/` · **user configuration** `~/.config/agent-container/` · **derived host
  state** · **image sources** `image/`. Never "project directory". Config is two levels, project
  winning, same filename both; **plaintext credentials are user-level only**. Context **is**
  `image/`. **Pre-011 layouts are refused, not ignored.**
- **Run mechanism is compose** (v2), generated and run **on the target host**. A host bind fails over
  a remote context, and `configs: {file:}` **is** a bind (measured); only `{content:}` is
  API-delivered. Inline non-secret injected material — the 001/003 lesson.
- **Credentials are runtime-injected, least-exposure (Constitution III).** Never baked, on argv, or
  printed. Tool-injected secrets land under `/run/agent-container/…`, **never** on a volume; a missing
  referenced file must `die` **before** compose. On-volume `auth.json` is
  **operator-interactive-login only**. Rotate = edit locally + `redeploy`. **`/run` covers INJECTED
  material only** — no private SSH key is injected at all: host (018) and agent (019) are
  container-**generated**, the agent's persisting on the `ssh` volume, so `--purge`/`ssh-key rotate`
  is the revocation boundary and both must say so.
- **The supported-agent list is single-sourced** (`AGENTS`); a test pins the completions' to the
  CLI's. Both fail on drift and name what to update.
- **A named volume's mount point must exist in the image, dev-owned** — else the runtime creates it
  `root:root` and rootless can't write it.
- **Packaging:** PyPI as `agent_container`; `REPO_ROOT` resolves location-independently (only `build`
  needs a checkout). **PyYAML is the one third-party dep**; `yaml.safe_load` **only** — never a regex
  over a structured format. Justify new deps against Constitution VI.
- **Egress enforcement is packet-level and says so.** Default-deny in a netns shared with the
  **egress sidecar**, which alone holds `NET_ADMIN`; squid **splices, never bumps** (a locally-issued
  CN ⇒ the boundary inverted). A declared port selects netfilter over the proxy allowlist; sidecars
  are inside unless declared out. A declaration governs **all** egress (breaking HTTPS `git push`
  unless declared); absent ≠ `allow: []`; the strength claim is tested for **absence** of overclaim.
- **Both SSH identities are CAPTURED, never supplied — only public halves leave.** Host key pinned
  per deploy as `[address]:port`: **mismatch ⇒ refuse, never prompt**; absent ⇒ warn + fingerprint +
  ask (no tty ⇒ refuse) — a pin must **predate** what it checks. The agent key sits at the
  **conventional** `~/.ssh/id_ed25519`, so nothing wires it (`core.sshCommand` empty ⇒ deleted, not
  rewired); in `~/.ssh/config` the **block** is write-once, not the file. A first SSH clone-on-start
  can't clone — exit **3**, worded to forbid the teardown the code invites.
- **The inventory remembers what we CREATED; `panic` acts on it.** Durable but **flat**; capped by
  count, **never age**; not backfilled. `panic` enumerates from it (not "whichever hosts answer"),
  stops by **compose project label**, verifies by **observation** (two queries — `already-stopped`
  needs a pre-snapshot). **Unreachable ⇒ `undetermined`, never `stopped`/`missing`** and fails the
  run; an **unverified destroy writes no outcome**.
- **A run's account outlives its container.** The container writes the record to the runs volume (only
  the entrypoint is there when a detached run ends), the CLI ingests on next contact, and **teardown
  drains before removing volumes**; `task` is verbatim, *unknown* usage never `0`.
- **`doctor` is read-only BY COMPOSITION, not a flag** — never reaches `migrate_flat_state` or any
  writer (a test walks the call graph); `unknown` is first-class and **never exits 1**; a credential is
  checked by DECLARATION, never resolved (resolving is the prompt).
- **Every substantive merge to `main` is a release.** Once `ci` passes, python-semantic-release bumps
  from Conventional Commits (`feat`→minor, `fix`→patch, breaking→minor pre-1.0; docs/chore/test cut
  none), tags and publishes via OIDC. No manual tagging.

### Where the detail lives

All under `docs/`, by feature: `layout.md` 011 · `orchestration.md` 001,002 · `credentials.md`
003,008,019 · `execution.md` 004,010,019 · `shell-integration.md` 005,018 · `agent-as-code.md`
006,008 · `agent-interface.md` 009 · `egress.md` 012 · `doctor.md` 013 · `inventory.md` 014 ·
`observability.md` 016 · specs/007 (wizard) · `threat-model.md` (**reconcile every feature** —
Constitution).

## Architecture — keep these layers separate

**image** (`image/`) · **orchestration** (`bin/agent-container` + compose) · **entrypoint** (git
identity, credential injection, key generation, sshd, tmux) · **attach** (thin, client-side).
Never bake host-specific orchestration into the image.

## Conventions for future work

- **Rootless by decision**: no `sudo`/root at runtime, sshd as `dev` on 2222. **Bake every system dep
  at build time — an agent never `apt install`s.**
- **Commit-and-push** is a property of the agent config, not of git hooks (bypassable).
- **Quality gate — one script, two uses.** `scripts/quality-gate.sh`; Stop hook and CI run the *same*
  script. It **excludes** the CI-authoritative acceptance tier (`pytest -m acceptance bin/tests`; on
  macOS+Lima the work dir must be Lima-shared). **Read its exit code unpiped** (`| tail` reports
  tail's). **Never edit the tree while that tier runs** — it re-reads the CLI per invocation, so a
  mid-edit run measures nothing.
- **Run the full suite, not only your new tests** — a changed contract is exactly when a pre-existing
  test still pins the old shape.
- **Conventional Commits are mandatory** — the CD pipeline reads them. Enforced three ways: the local
  `commit-msg` hook (`core.hooksPath .githooks`, once per clone), the `commits` CI job, and a ruleset
  on `main`; `--no-verify` bypasses only the first.
- **Every short flag needs a long one** (`-y`/`--yes`); a test enforces it, and one proves that check
  can fail.
- **Keep this file under 2000 tokens** — it loads every session, and `chars/4` UNDERSTATES the real
  count by ~7%, so measure with a tokenizer. New detail goes to `docs/`; **prune before adding**.

## Out of scope (don't add unless asked)

IDE integrations beyond SSH/tmux/nvim · multi-user access control (one operator) · Kubernetes.
