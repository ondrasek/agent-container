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
  Stay Podman-compatible; never depend on Docker-Desktop-only behaviour.
- **Layout (011) — [`docs/layout.md`](docs/layout.md) is the one map.** Never "project directory".
  Config is two levels, project winning, same filename both; **plaintext credentials are user-level
  only**. Build context **is** the image directory. **Pre-011 layouts are refused, not ignored.**
- **Run mechanism is compose** (v2), generated and run **on the target host**. `configs: {file:}` **is**
  a bind and fails over a remote context (measured); only `{content:}` is API-delivered — the 001/003
  lesson.
- **Secrets go to the CONTAINER over ITS OWN sshd** (Constitution IX) — not the runtime channel, whose
  security is the operator's context, not ours. A description is a PLAN outliving the need: nothing
  secret inlined in it nor staged for it. Auth is an operator-**declared** identity (`delivery_identity`);
  the tool **never mints a key**. Undeclared ⇒ refuse. `configs: {file:}` is a daemon-side bind,
  **measured** not to cross; `{content:}` crosses but is PUBLIC-only. sshd runs in **every** mode.
- **Credentials are least-exposure (Constitution III).** Never baked, on argv, or printed; **never** on
  a volume. On-volume `auth.json` is **operator-login only**; a `--task` is **not** a credential
  channel. **No private SSH key is injected at all.**
- **The supported-agent list is single-sourced** (`AGENTS`); tests pin completions + every Dockerfile.
  **Mirror any CLI surface change in both completions** — tests catch parity, not staleness.
- **Defaults belong at the SURFACE** (Constitution VIII) — each **named**. A reader reports
  **absence**; absent ≠ defaulted ≠ declared-empty ≠ unexamined.
- **Packaging:** PyPI as `agent_container`; `REPO_ROOT` resolves location-independently. **PyYAML is
  the one third-party dep**; `yaml.safe_load` **only** — never a regex over a structured format.

- **Egress enforcement is packet-level and says so.** Default-deny in a netns shared with the **egress
  sidecar**, which alone holds `NET_ADMIN`; squid **splices, never bumps**. A declaration governs
  **all** egress; the strength claim is tested for **absence** of overclaim.
- **Both SSH identities are CAPTURED, never supplied — only public halves leave.** Host key pinned per
  deploy: **mismatch ⇒ refuse, never prompt**; absent ⇒ warn + ask (no tty ⇒ refuse) — a pin must
  **predate** what it checks. The agent key sits at the **conventional** `~/.ssh/id_ed25519`, so
  nothing wires it; the `~/.ssh/config` **block** is write-once. `--purge`/`ssh-key rotate` is the
  revocation boundary. A first SSH clone-on-start can't clone — exit **3**, worded to forbid the
  teardown it invites.
- **The admit set is DECLARED; the region is REWRITTEN (020).** `authorized_keys` both levels, project
  **replaces** user; resolve+validate at the SURFACE. The container replaces a sentinel region each boot,
  preserving all outside it — a union can't revoke. Same idiom as `~/.ssh/config`, **opposite** rule;
  markers by **prefix**. No access the tool can't withdraw. **Projected AND observed**; stopped ⇒
  `undetermined`.
- **The inventory remembers what we CREATED; `panic` acts on it.** Verifies by **observation**;
  **unreachable ⇒ `undetermined`, never `stopped`**; an **unverified destroy writes no outcome**.
- **Observability is TWO LEGS, ONE PAYLOAD** (017). Local trail unconditional; export is `curl`,
  **write-time**, **fail-open**, **zero** deps — protocol only, **never** a backend package.
  `accepted` = *this endpoint accepted this record*, nothing more; **2xx is not acceptance**;
  `rejected`≠`failed`. `task` exports by default, excluded **by name never pattern**, `run_id` always.
  `collect` **names what it missed**; reconcile's window is the last **reconcile**.
- **A control plane is an ordinary environment holding a standing key** (017). Second image, **no
  agents** but it DOES need a runtime client. Passphrase in-container, printed **once**, **no
  recovery**; the authorised key **is** the boundary, `revoke` the only narrowing. `panic` from inside
  **excludes itself and says so**. Role **inheritable**, provenance **persisted**.
- **Every substantive merge to `main` is a release.** python-semantic-release bumps from Conventional
  Commits (`feat`→minor, `fix`→patch, **breaking→minor pre-1.0**) — so a breaking change must SAY so in
  the body; the version won't.

### Where the detail lives

All under `docs/`, by feature: `layout.md` 011 · `orchestration.md` 001,002 · `credentials.md`
003,008,019 · `execution.md` 004,010,019 · `shell-integration.md` 005,018 · `agent-as-code.md`
006,008 · `agent-interface.md` 009 · `egress.md` 012 · `doctor.md` 013 · `inventory.md` 014 ·
`observability.md` 016,017 · `control-plane.md` 017 · specs/007 (wizard) · `threat-model.md`
(**reconcile every feature** — Constitution).

## Architecture — keep these layers separate

**image** (`image/`) · **orchestration** (`bin/agent-container` + compose) · **entrypoint** (git
identity, credential injection, key generation, sshd, tmux) · **attach** (thin, client-side).
Never bake host-specific orchestration into the image.

## Conventions for future work

- **Rootless by decision**: no `sudo`/root at runtime, sshd as `dev` on 2222. **Bake every system dep at
  build.**

- **Commit-and-push** is a property of the agent config, not git hooks (bypassable).

- **Quality gate — one script, two uses.** `scripts/quality-gate.sh`; Stop hook and CI run the *same*
  script. It **excludes** the CI-authoritative acceptance tier (`pytest -m acceptance bin/tests`; on
  macOS+Lima the work dir must be Lima-shared). **Read its exit code unpiped.** **Never edit the tree
  while that tier runs** — it re-reads the CLI per invocation.
- **Run the full suite, not only your new tests** — a changed contract is exactly when a pre-existing
  test still pins the old shape.
- **Conventional Commits are mandatory** — the CD pipeline reads them; a local `commit-msg` hook,
  a CI job and a `main` ruleset enforce it (`--no-verify` bypasses only the hook).
- **CLI surface, test-enforced.** Short flags need a long form (`-y`/`--yes`). `-v`/`--verbose` works
  on **every** command — injected, not declared per command. Group verbs: **`ls` reads, spelled-out
  destructive**; a rename keeps the old name as a hidden alias.
- **Keep this file under 2000 tokens** — `chars/4` UNDERSTATES by ~7%; measure with a tokenizer. New
  detail goes to `docs/`; **prune before adding**.

## Out of scope

IDE integrations beyond SSH/tmux/nvim · multi-user access control · Kubernetes.

