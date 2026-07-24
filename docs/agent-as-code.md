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
| `agent-container plan` / `status` | Show the per-environment plan (**absent** / **matching** / **drifted**, with a field-level delta) — mutates nothing. |
| `agent-container apply` | Discover → validate → plan → (confirm) → converge: bring up each declared environment. **Idempotent** — a matching spec makes no changes; a drifted one is announced then recreated. |
| `agent-container destroy` | Remove **only** the resources the spec declares and owns. |

**Drift is field-level (US3).** `status` inspects each running container's live agent-config
(`mode` / `agent` / clone `repo`) and reports exactly which fields diverge from the spec
(`agent: 'claude'→'codex'`); `apply` announces a drifted environment before recreating it to
converge. A partial failure (one environment of several fails to reconcile) reports precisely
which converged and which did not, then exits non-zero — never a silent half-apply (FR-010).
A spec naming `host: local` resolves to the implicit local host with no registration needed,
so a fresh checkout reconciles identically regardless of where it lives (FR-005/SC-003).

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
| `file` | read a file at `path` (typically outside the project). A plaintext file that is **git-tracked inside the project** is **refused** with remediation (FR-015); an external file, or a project-local file that is **untracked/gitignored**, is allowed. Detection boundary: only files inside the project tree and known to git are flagged. |
| `keychain` | OS store — macOS `security find-generic-password -w`, Linux `secret-tool lookup` (by `service`+`account`) |
| `encrypted` | run the operator's `decrypt` command on `path` (e.g. `age -d -i key`, `sops -d`); the file may be committed, the plaintext stays in memory |

**Delivery** reuses Feature 003's channels: a **provider API key** (name
`ANTHROPIC_API_KEY`/`anthropic`, `OPENAI_API_KEY`/`openai`) is delivered **file-first**
(a read-only compose config → `/run/agent-container/apikeys/<provider>`, never even
the environment); any other credential is delivered as an **environment variable**
via a per-deployment secrets env-file (mode 0600, in the state dir — not the project).
Multi-line values, and values with characters an env-file parser would mangle
(leading/trailing whitespace, an inline ` #`, a leading quote), are **rejected** for
env delivery — deliver those as a provider API key (file channel), or, for an SSH key,
give the credential an explicit **`target`** (below).

**SSH-key credentials** — a credential with `target: push_key | host_key |
authorized_key` is routed to the Feature 003 ssh-injection channels instead of an env
var (the multi-line delivery the env-file rejects): `push_key` → the outbound git push
identity (`--push-key`, ephemeral `/run`), `host_key` → the inbound sshd host identity
(`--host-key`, persisted to the `~/.ssh` volume), `authorized_key` → an inbound
principal (`--authorized-key`, accumulates). The resolved key stays in memory then a
0600 staged file; it never touches the project, logs, argv, or registry. A
passphrase-protected private key is (correctly) refused for `push_key` — pre-decrypt
via `source: encrypted`.

```yaml
credentials:
  - { name: git-push, source: encrypted, path: ./deploy.key.age, decrypt: "age -d -i ~/.age/key", target: push_key }
```

**Notes.** All declared credentials are resolved **up front** — before any container
is deployed — so a missing source never leaves an earlier environment partially
applied. Resolved values are staged as 0600 files under your private state dir
(`$XDG_STATE_HOME`), the same posture as the Feature 003 injected material; they are
regenerated each `apply`. Don't both declare a provider credential *and* drop a
convention `agent-container.<name>.<provider>.key` file for the same provider — they
target the same in-container path.

## Host binding — referenced vs provisioned (US4)

An environment's `host` is either a **name** (referenced — an existing/known host,
externally owned) or a **provision table** (spec-owned):

```yaml
environments:
  - name: acme
    host: { provision: hetzner, name: acme-box, server_type: cax11, location: nbg1 }
```

`apply` **provisions + registers** a spec-owned host (driving the Feature 001 Hetzner
provisioner) **before** deploying onto it — **idempotently**: a second `apply` reuses
the already-provisioned server rather than allocating (and billing) another. A
provisioned host needs `HCLOUD_TOKEN` in the environment (a `--host` override bypasses
provisioning and needs none). The host registry name is the table `name`, or the env
name if it is RFC-1123 (Hetzner rejects underscores — an underscore-bearing env needs
an explicit `host.name`). `plan`/`status` **never allocate** — a to-be-provisioned host
is reported as intent only.

**`destroy`** removes the container. **`destroy --deprovision`** *also* removes a
spec-**provisioned** host — containers first, then the server — reusing the Feature 001
fail-closed teardown (tool-created **and** provably-empty, or it refuses). A
**referenced** host is **never** deprovisioned regardless of the flag (FR-017).

## Roadmap

**Shipped: US1–US4** — declare → validate → idempotent `apply`/`plan`/`status`/`destroy`
with read-only spec integrity (US1); credential resolution incl. SSH-key `target`
routing (US2 + T012a); field-level drift → converge + scoped teardown + partial-failure
reporting (US3); declarative host provisioning with `destroy --deprovision` (US4). The
real-Hetzner provisioned-host acceptance is opt-in/tokened (billable — never CI).

See [`specs/006-agent-as-code/`](../specs/006-agent-as-code/) for the full spec,
plan, and contract.
