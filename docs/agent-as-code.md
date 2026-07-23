# Agent-as-Code — declarative `.agent-container/` projects (Feature 006)

Alongside the imperative CLI, a **`.agent-container/` project directory** can *be*
the desired state for one or more agent environments. Run the tool inside such a
directory and it **discovers → validates → plans → reconciles** reality to the
spec. This is the "as code" model (Compose/Terraform-adjacent): the directory is a
single, portable, reviewable, version-controllable source of truth.

**Additive**: with no `.agent-container/` up the tree, the tool behaves exactly as
it does today — the declarative verbs are inert.

## The project directory

Discovery walks **upward** from the working directory to the nearest ancestor
containing a `.agent-container/` directory; that ancestor is the project root (the
tool reports which one it chose). Git-independent.

```yaml
# .agent-container/project.yaml
environments:
  - name: acme                 # -> the deterministic identity (container/volumes/port)
    host: local                # a registered/known host name
    container:
      mode: interactive        # interactive | headless
      agent: claude            # claude | codex | pi
      workspace: persistent    # persistent | bind | ephemeral
      repo: https://github.com/you/acme   # optional clone-on-start
      env_file: ./acme.env     # non-secret env (relative to the project root)
    credentials:               # references, never values (US2 — see Roadmap)
      - { name: ANTHROPIC_API_KEY, source: env, var: ANTHROPIC_API_KEY }
```

Parsed with **`yaml.safe_load`** (never `yaml.load` — an untrusted `!!python/...`
tag can never construct an object or run code). The spec is **validated before any
action**: on a bad field the tool refuses and names the offending file + field,
making no partial change. Unknown keys and out-of-range enums are errors.

## The verbs (active only inside a project)

| Command | What it does |
|---------|--------------|
| `agent-container plan` / `status` | Show the per-environment plan (**absent** / **matching** / **drifted**) — mutates nothing. |
| `agent-container apply` | Discover → validate → plan → (confirm) → converge: bring up each declared environment. **Idempotent** — a matching spec makes no changes. |
| `agent-container destroy` | Remove **only** the resources the spec declares and owns. |

Ownership is derived from the tool's **deterministic identity** (Constitution IV) —
a declared `name` maps to the same container/volume identity the imperative CLI
computes. There is **no state/lock file**: the directory and the running containers
are the only state, so a fresh checkout on another machine plans identically.

Precedence: inside a project, the **spec wins for its scope** — a host it names
overrides a same-named global-registry host (the override is reported), never a
silent merge.

## Spec integrity — the agent cannot re-govern itself (FR-020)

A repo can carry its own `.agent-container/` and *become* the agent's workspace. An
untrusted agent must not be able to rewrite the spec that governs it (its host
binding, credentials, container config) and push that back. Two guarantees:

1. **Host-side-only read (load-bearing).** The tool reads the spec **only** from the
   operator's host-side `.agent-container/`, never a container's copy. A spec change
   is a host-side git edit you review — an agent edit or `git push` cannot re-govern.
2. **Read-only in-container delivery (defense-in-depth).** The declared spec files
   are delivered into the container **read-only** via the compose-`configs` channel
   (which mounts read-only and — unlike a host bind — works over a **remote
   context**). Kernel-enforced for every uid; the rootless agent cannot modify them.

The tool **refuses to deploy** a configuration that would expose the spec writable
(e.g. a `bind` workspace over the project directory) — use `persistent`/`ephemeral`
for a self-hosting repo.

> **Scope of the in-container guarantee.** The read-only delivery protects the
> *declared spec files* (the agent cannot modify them). The containing
> `/workspace/.agent-container/` directory itself lives on the writable workspace,
> so the agent could create unrelated sibling files there — but that changes
> nothing, because the tool reconciles **only** the operator's host-side copy and
> never reads the container's. The host-side-only read is the load-bearing gate;
> the read-only delivery is defense-in-depth.

## Credentials — resolved at apply, injected at runtime (US2)

Each `credentials[]` entry is a **reference to a source**, never a value. At `apply`
the tool resolves it **in memory** and injects it via the existing runtime channels
— the plaintext never touches the tracked directory, logs, argv, or the registry
(FR-013/014). A missing/unavailable source **fails before any change** and names it
(FR-016).

| `source` | Resolution |
|----------|-----------|
| `env` | read the named environment variable (`var`) |
| `file` | read an external file (`path`) **outside** the project — a git-tracked plaintext file *inside* the project is **refused** with remediation (FR-015) |
| `keychain` | OS store — macOS `security find-generic-password -w`, Linux `secret-tool lookup` (by `service`+`account`) |
| `encrypted` | run the operator's `decrypt` command on `path` (e.g. `age -d -i key`, `sops -d`); the file may be committed, the plaintext stays in memory |

**Delivery** reuses Feature 003's channels: a **provider API key** (name
`ANTHROPIC_API_KEY`/`anthropic`, `OPENAI_API_KEY`/`openai`) is delivered **file-first**
(a read-only compose config → `/run/agent-container/apikeys/<provider>`, never even
the environment); any other credential is delivered as an **environment variable**
via a per-deployment secrets env-file (mode 0600, in the state dir — not the project).
Multi-line values, and values with characters an env-file parser would mangle
(leading/trailing whitespace, an inline ` #`, a leading quote), are **rejected** for
env delivery — deliver those as a provider API key (file channel). SSH-key routing
to `--push-key`/`--host-key` is a follow-on.

**Notes.** All declared credentials are resolved **up front** — before any container
is deployed — so a missing source never leaves an earlier environment partially
applied. Resolved values are staged as 0600 files under your private state dir
(`$XDG_STATE_HOME`), the same posture as the Feature 003 injected material; they are
regenerated each `apply`. Don't both declare a provider credential *and* drop a
convention `agent-container.<name>.<provider>.key` file for the same provider — they
target the same in-container path.

## Roadmap (this feature ships incrementally)

Shipped: **US1** (declare → validate → idempotent `apply`/`plan`/`status`/`destroy`
with the read-only spec integrity) and **US2** (credential resolution, above).
Still layering on:

- **US3 — full drift deltas** (field-level) and richer `status` output.
- **US4 — declarative host provisioning**: a `host: { provision: hetzner, … }`
  table provisions/registers the host before deploy; `destroy --deprovision` removes
  only a spec-created host (a *referenced* host is externally owned, never removed).
- SSH-key credential routing to `--push-key`/`--host-key`, and the read-only
  acceptance test (T010/T013).

See [`specs/006-agent-as-code/`](../specs/006-agent-as-code/) for the full spec,
plan, and contract.
