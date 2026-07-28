# Phase 0 Research: Filesystem Layout

**Feature**: 011-filesystem-layout | **Date**: 2026-07-27

Every finding below was checked against the code, not inferred from the spec.

---

## R1 (CRITICAL) — The repo-checkout marker keys on `Dockerfile` at the root

`_is_repo_checkout()` decides what a checkout *is*:

```python
return (base / "Dockerfile").is_file() and (base / "completions" / "agent-container.bash").is_file()
```

Moving `Dockerfile` into `image/` **invalidates the marker**, and the blast radius is larger than
it looks:

- `REPO_ROOT = _find_repo_root()` runs **at import**, before `Fatal`/`die` exist — the docstring
  says so explicitly. A broken marker cannot fail loudly there; it returns `None`.
- `REPO_ROOT` feeds `completions` (falls back to bundled package data) and `build` (which dies
  actionably when `None`). So a stale marker degrades to *"no checkout reachable"* — `build`
  fails with a message about a missing checkout while standing **inside** one.
- `AGENT_CONTAINER_REPO` validation reuses it, and its `die` text names
  `"missing Dockerfile/completions/agent-container.bash"`.
- `bin/tests/test_packaging.py:139` **constructs** a fake checkout from the same two files.

**Decision**: the marker becomes `image/Dockerfile` + `completions/agent-container.bash`, updated
in the function, the `die` text, and the test's fixture, in one change. This is the single
highest-risk edit in the feature: get it wrong and the tool stops recognising its own repo.

**Rationale for keeping a Dockerfile in the marker at all**: the docstring records that the pair
was chosen over a generic `Dockerfile` + `completions/` because unrelated trees have both.
`image/Dockerfile` is *more* specific than `Dockerfile`, so the property improves.

---

## R2 (DECIDED, reversing an earlier recommendation) — the bare `./.env` is dropped

Four project-level resolution sites move into `.agent-container/`:

| Line | Today | After |
|---|---|---|
| 693 | `cwd / f"agent-container.{name}.<provider>.key"` | `.agent-container/<name>.<provider>.key` |
| 738 | `cwd / f"agent-container.{name}.config"` | `.agent-container/<name>.config/` |
| 2007 | `cwd / f"agent-container.{name}.services.yaml"` | `.agent-container/<name>.services.yaml` |
| 662 | `cwd / ".env"` | **removed — see below** |

**Decision (operator, 2026-07-28)**: the tool **stops reading the bare `./.env`**. A bare
`.env` in a project root is a shared ecosystem convention that belongs to whoever put it there;
claiming it is not conventional behaviour for a tool like this. An operator who wants an
agent-container env file puts it in an agent-container location — project or user level.

**I had recommended the opposite** (keep reading it, on the grounds that it is not tool-owned).
That reasoning was half right and led to the wrong conclusion: `./.env` not being ours is
precisely the argument for **not reading** it, not for continuing to.

The resulting chain is symmetric, which the old one was not:

| Level | Per-environment | Shared default |
|---|---|---|
| **Project** | `.agent-container/<name>.env` | `.agent-container/.env` |
| **User** | `~/.config/agent-container/<name>.env` | `~/.config/agent-container/.env` |

The two user-level entries already satisfied the requirement and are unchanged. Only the bare
`./.env` is removed, and a project-level shared default is added so both levels have the same
two slots.

### R2a — Dropping it silently would be the same bug FR-004 exists to prevent

The env file carries `GH_TOKEN`, git identity and provider API keys. So "stop reading `./.env`"
cannot mean "ignore it": an operator who relies on it today would get an agent deployed **without
their token or keys**, with nothing said — exactly the failure mode that justified the loud
refusal for `*.key` files.

But refusing on **any** `./.env` is also wrong: Compose projects legitimately have one that was
never meant for us, and refusing would make the tool hostile to the directory it shares.

**Decision**: refuse **only when the tool would otherwise start with no env file at all while a
`./.env` sits in the project root.** That is precisely the "you believe this is being used and it
is not" case.

| `./.env` | an agent-container env file resolves | Behaviour |
|---|---|---|
| present | **no** | **refuse** — name it, and name where it belongs |
| present | yes | ignore silently — the stray `.env` is someone else's business |
| absent | either | unaffected |

**Alternative considered and rejected**: warn instead of refuse. A warning on a deploy that then
proceeds is how a missing `GH_TOKEN` becomes a push failure twenty minutes later, inside a
container, in an agent's log.

### R2b — Repeatable `-e` fits the existing machinery exactly

Three facts checked in the code, not assumed:

- **`-e` is free.** Short flags in use: `-a -C -d -f -i -L -N -o -p -q -R -s -t -T -w -y`.
- **The compose model already emits a list**: `service["env_file"] = [str(env_file)]`. Stacking
  means filling that list, and Compose's own `env_file:` semantics are exactly "apply in order,
  later wins" — so the ordering requirement needs no logic of ours.
- **It is remote-safe.** `build_compose_model`'s docstring records that `env_file` is *"read
  client-side by compose and merged into the service environment"*. The file therefore never
  has to exist on the target daemon, so `-e ~/.env` works against a remote host.

`--env-file` already exists on `up` and `redeploy` as a single-valued "bypass resolution"
option. Making it repeatable preserves that bypass meaning and adds ordering.

**Decision**: explicit files **replace** the discovery chain rather than layering on top of it.
Naming files is a statement that the operator is in control; silently merging discovered files
underneath would make the effective environment depend on directory contents the operator was
trying to bypass.

### R2c — Project-local plaintext credentials are removed, not relocated

`discover_apikey_files` (line ~681) globs `agent-container.<name>.<provider>.key` project-local
**first**, then `<name>.<provider>.key` under the user config dir. The project-local half is a
plaintext **value** living in the repository.

Feature 008 settled the principle — *"the repo stores only a locator, never a value"*, and
`docs/agent-as-code.md` states each credential entry is *"a reference to a source, never a
value"*. `_refuse_git_tracked_plaintext` exists as the backstop for when that principle is
violated by accident.

**The consolidation would have made that accident easier, not harder.** `.agent-container/` is
by definition the directory that travels with the repository; moving plaintext keys into it
means `git add .agent-container/` — the natural action, since the directory holds the spec —
stages an API key. The existing refusal fires at *deploy* time, by which point the secret is
already in git history.

**Decision (operator, 2026-07-28)**: drop project-local key discovery entirely, with **no
replacement inside `.agent-container/`**. Secret values come from user level or a locator.

**This is less work, not more**: the project-local branch of the two-element loop in
`discover_apikey_files` is deleted rather than repointed, and the `.gitignore` mitigation the
analysis was about to propose becomes unnecessary. The layout then *expresses* Feature 008's
principle instead of quietly undercutting it.

**Cost, accepted**: no per-project plaintext key files. Environment names are unique, so the
user-level `<name>.<provider>.key` is already effectively per-project, and anyone wanting the
credential referenced from the repo uses a locator source.

---

## R3 — The shell-env rename moves a mount point, never an identity

| | Value | Changes? |
|---|---|---|
| Volume **name** | `agent-container-<name>-shellenv` | **No** — Constitution IV, FR-010 |
| Mount **point** | `/home/dev/.agent-container` → `/home/dev/.agent-env` | Yes |

Because the name is unchanged, an existing volume simply mounts at the new path on recreate —
**contents are not stranded**, they reappear elsewhere. Touchpoints:

- `bin/agent-container` — `all_volume_mounts()` (and its doctest, which pins the full string).
- `Dockerfile` — the `mkdir -p` / `chown` / `chmod 0755` lists and two comments.
- `entrypoint.sh` — `AGENT_CONTAINER_ENV_FILE="${AGENT_CONTAINER_HOME}/.agent-container/env"`,
  the `mkdir -p`, and the block comment describing the persistent shell env.

**Feature 010's lesson applies directly**: the new mount point MUST be pre-created **dev-owned**
in the image. Verified there that a volume mounted at a path the image does not create comes up
`root:root` and the rootless user cannot write it — *including* under an already dev-owned parent.

**Operator-visible break**: anything in an operator's persisted `~/.agent-container/env` that
refers to the old path by name keeps working (same file, new location), but shell snippets they
wrote referencing `~/.agent-container` do not. The hard-cut posture covers this.

---

## R4 — Moving the build context makes FR-007 structural

`build_compose_model` emits `"build": {"context": str(build_context)}`, and `do_build` resolves
the context to the checkout root. After the move it resolves to `<root>/image`.

Today `.dockerignore` is a **deny-all allowlist** and is genuinely load-bearing: measured during
Feature 009, an unprotected context transferred **2234 files / 23.4 MB** — including a planted
`.env` and an API key — to the daemon, which may be **remote**. With the allowlist: 2 files /
9.5 kB.

After the move the context *is* `image/`, so narrowness follows from the directory boundary
rather than from a list that must be maintained in step with the Dockerfile. That is FR-007
("narrow by construction, not by an allowlist"). `.dockerignore` moves along and stays as
defence in depth — it is no longer the only thing between the operator's secrets and a remote
daemon.

---

## R5 — The hard cut needs a detector, and it must run before anything deploys

FR-003 removes the old resolution paths; FR-004 requires a **loud refusal** rather than silence.
Those are two different pieces of work: deleting the lookup is not enough, because a deleted
lookup is exactly what "silently ignored" looks like from the operator's side.

**Decision**: one `die`-ing check over the project root for the three superseded prefixed names,
listing **every** offender with its destination, run on every command that resolves per-
environment files (`up`, `redeploy`, and the declarative verbs).

**Why it is load-bearing rather than pedantic**: the superseded set includes
`agent-container.<name>.<provider>.key`. Silently ignoring one starts an agent **unauthenticated
while the operator believes a key was injected** — a Constitution III failure that is invisible
until the agent misbehaves. This is the requirement that justifies the hard cut being safe.

---

## R6 — Two in-container paths deliberately do not move

- `INJECT_AAC_DIR = "/workspace/.agent-container"` — the delivered spec. It *should* echo the
  project config name because it is literally that directory delivered read-only. FR-012
  requires its read-only guarantee survive unchanged; not touching it is the cheapest way to
  honour that.
- `/run/agent-container/` — ephemeral injected secrets. Already unambiguous by its `/run`
  prefix, and renaming it would churn the Feature 003 credential machinery for no clarity gain.

---

## R7 — Identity verification is already mechanised

SC-003 ("byte-identical container name, port and volume names") does not need new machinery: the
existing `--self-test` doctests pin `per_container_volumes`, `all_volume_mounts` and the port
corpus. Only the shell-env **mount string** inside `all_volume_mounts` changes; every **name** is
asserted unchanged.

---

## R8 — This is the project's first genuinely breaking change

Constitution VII: python-semantic-release reads Conventional Commits. Removing the previous
layout with no fallback breaks any operator on the old layout, so the commit MUST carry `!` /
`BREAKING CHANGE`. Pre-1.0 that cuts a **minor**, not a major — the operator should know the
version will read as routine even though the change is not.
