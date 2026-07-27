# Phase 0 Research: Filesystem Layout

**Feature**: 011-filesystem-layout | **Date**: 2026-07-27

Every finding below was checked against the code, not inferred from the spec.

---

## R1 (CRITICAL) — The repo-checkout marker keys on `Dockerfile` at the root

`_is_repo_checkout()` decides what a checkout *is*:

```python
return (base / "Dockerfile").is_file() and (
    base / "completions" / "agent-container.bash").is_file()
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

## R2 (OPEN QUESTION) — `./.env` is not a tool-owned file

Four project-level resolution sites move into `.agent-container/`:

| Line | Today | After |
|---|---|---|
| 693 | `cwd / f"agent-container.{name}.<provider>.key"` | `.agent-container/<name>.<provider>.key` |
| 738 | `cwd / f"agent-container.{name}.config"` | `.agent-container/<name>.config/` |
| 2007 | `cwd / f"agent-container.{name}.services.yaml"` | `.agent-container/<name>.services.yaml` |
| 662 | **`cwd / ".env"`** | **← see below** |

The first three carry the `agent-container.` prefix: unambiguously this tool's. The fourth does
not. `./.env` is a **shared ecosystem convention** — Docker Compose reads it, as do direnv,
dotenv libraries and most application frameworks.

**Decision**: `./.env` **stays where it is** and continues to be read.

**Rationale**: FR-002 says no *tool-owned* file may remain loose in the project root. `./.env` is
not tool-owned — the tool is one of several readers. Moving it would mean either abandoning a
convention operators already rely on, or worse, having the tool refuse to start (FR-004) because
of a file that Docker Compose put there legitimately. The hard-cut refusal must fire **only** on
the three prefixed names, never on `.env`.

**Alternative considered and rejected**: treat `./.env` as tool-owned and require
`.agent-container/.env`. Cleaner on paper, but it makes the tool hostile to every other tool
sharing the directory, and FR-004's refusal would then trigger on a file the operator never
created for us.

**This is the one decision in the plan a reviewer should challenge if they disagree** — it is the
difference between "the tool tidies its own files" and "the tool claims the project root".

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
