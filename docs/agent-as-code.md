# Agent-as-Code — declarative `.agent-container/` projects (Feature 006)

Alongside the imperative CLI, a **`.agent-container/` project config directory** can *be*
the desired state for one or more agent environments. Run the tool inside such a
directory and it **discovers → validates → plans → reconciles** reality to the
spec. This is the "as code" model (Compose/Terraform-adjacent): the directory is a
single, portable, reviewable, version-controllable source of truth.

**Additive**: with no `.agent-container/` up the tree, the tool behaves exactly as
it does today — the declarative verbs are inert.

## The project config directory

Discovery walks **upward** from the working directory to the nearest ancestor
containing a `.agent-container/` directory; that ancestor is the project root (the
tool reports which one it chose). Git-independent.

```yaml
# .agent-container/environments.yaml
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
    egress:                    # where this environment may go (Feature 012)
      allow:                   #   ONE list; the entry shape says what it is
        - { provider: anthropic }        # model vendor, by name — tool supplies the hosts
        - { host: github.com }           # the git remote over HTTPS — the declaration
                                         #   governs ALL egress, not just providers
        - { host: github.com, port: 22 } # a port selects netfilter, not the proxy
      enforcement: advisory    #   advisory (default) | strict
```

A spec file is identified by **kind**: `environments.yaml`, or `<prefix>.environments.yaml` when
you split the spec across files. The suffix names the top-level key the file contains — the same
rule that makes `prod.services.yaml` a sidecar override — so both kinds live in
`.agent-container/` without colliding. See [`docs/layout.md`](layout.md).

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
(e.g. a `bind` workspace over the project config directory) — use `persistent`/`ephemeral`
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
| `keychain` | OS store — macOS `security find-generic-password -w`, Linux `secret-tool lookup` (by `service`+`account`). On macOS this surfaces iCloud-synced generic passwords. |
| `command` | run an operator-declared **`argv`** list and take its **stdout** — the generic resolver; covers every manager with a CLI |
| `onepassword` | `op read op://{vault}/{item}/{field}` — assembled from the typed fields |
| `bitwarden` | `bw get {field} {item}` — assembled from the typed fields |

### Credential managers (Feature 008)

The repository holds a **locator**; the secret is fetched **host-side at apply** from
wherever it actually lives. This is git's credential-helper model:

```yaml
credentials:
  # named managers — structured, typed fields
  - { name: ANTHROPIC_API_KEY, source: onepassword, vault: Personal, item: anthropic, field: key }
  - { name: GH_TOKEN,          source: bitwarden,   item: gh-token, field: password }
  # generic resolver — any manager with a CLI, zero tool changes
  - { name: DB_PASSWORD, source: command, argv: ["vault", "kv", "get", "-field=password", "secret/db"] }
  - { name: API_KEY,     source: command, argv: ["pass", "show", "acme/api-key"] }
```

The resolver runs **directly — never through a shell** (no injection surface), with
**stdin closed** (non-interactive: unlock the manager first, e.g. `op signin` / `bw
unlock`) and a **30 s bound** so a wedged CLI can never hang an apply. A failure
(missing binary, non-zero exit, timeout, empty or whitespace-only output) **aborts
before any change**, names the credential, and carries a remediation hint — but the
resolver's own **stderr is never echoed**, since it may contain secret material. A
pipe/filter belongs in an operator wrapper script referenced by the `argv`, not inline.

**Only `apply` resolves.** The read-only `plan`/`status` validate the schema but never
invoke a resolver, so previewing a spec never triggers a manager prompt or a
hardware-key touch. Resolution is also **not cached**: a credential declared in two
environments is fetched twice (two touches) — deliberate, to keep the secret's
in-memory lifetime short.

**HW keys (YubiKey) are a *backing*, not a source** — a manager unlocked by the key, or
an SSH key resident on it. Nothing extra to declare.

**Delivery** reuses Feature 003's channels: a **provider API key** (name
`ANTHROPIC_API_KEY`/`anthropic`, `OPENAI_API_KEY`/`openai`) is delivered **file-first**
(a read-only compose config → `/run/agent-container/apikeys/<provider>`, never even
the environment); any other credential is delivered as an **environment variable**
via a per-deployment secrets env-file (mode 0600, in the state dir — not the project).
Multi-line values, and values with characters an env-file parser would mangle
(leading/trailing whitespace, an inline ` #`, a leading quote), are **rejected** for
env delivery — deliver those as a provider API key (file channel), or, for an SSH key,
give the credential an explicit **`target`** (below).

**SSH-key credentials** — a credential with `target: authorized_key` is routed to
the Feature 003 ssh-injection channel instead of an env var (the multi-line delivery
the env-file rejects): it declares an **inbound principal** (`--authorized-key`,
accumulates). The resolved key stays in memory then a 0600 staged file; it never
touches the project, logs, argv, or registry.

**Two targets were removed, and both are REFUSED rather than silently dropped** —
silently dropping one would leave you believing your key is in use:

- `target: host_key`, until **Feature 018** removed private-host-key injection. The
  container generates its own host key and the tool captures the public half.
- `target: push_key`, until **Feature 019** removed the last private-key channel. The
  container generates its **own** SSH key pair; the private half never leaves it, and
  the public half is what you register:

  ```sh
  agent-container ssh-key show acme    # paste this into the forge as a deploy key
  ```

  A per-container key registered on one repository authorises **one repository** —
  where a declared `push_key` was in practice the operator's personal key, which
  authorises everything that key reaches.

There is nothing left to supply for either: what the container needs, it makes.

```yaml
credentials:
  # REFUSED since 019 — there is no private key to deliver.
  - { name: git-push, source: onepassword, vault: Infra, item: deploy-key, field: private_key, target: push_key }
  # Still valid: an inbound principal allowed to reach the container.
  - { name: laptop, source: file, path: ~/.ssh/id_ed25519.pub, target: authorized_key }
```

## Where secrets should live — the recommended taxonomy

| Tier | Sources | Posture |
|------|---------|---------|
| ✅ **Recommended** | `onepassword`, `bitwarden`, `command` (any manager CLI), `keychain`, `env`, `file` *outside the project or untracked* | The secret lives in your OS keychain, a password manager, or a HW-key-backed store. **The repo holds only a locator** — safe to commit and review. |
| ⛔ **Refused** | a plaintext secret **file tracked in git** inside the project | Blocked with remediation — the tool will not deploy it. |
| 🚫 **Removed** | ~~`encrypted`~~ (age/sops on a committed ciphertext) | **Gone as of Feature 008.** Secrets do not belong in the git remote, even encrypted. |

### Migrating off `encrypted`

A spec still declaring `source: encrypted` is **refused** (naming the migration) by any
command that loads it. Move the secret out of the repository:

```bash
# 1. decrypt once, locally
age -d -i ~/.age/key ./secret.age            # or: sops -d ./secret.enc

# 2. put it where it belongs — pick one
op item create --category=password --title=acme-key password=<value>   # 1Password
bw create item ...                                                     # Bitwarden
security add-generic-password -s acme -a bot -w <value>                # macOS keychain

# 3. point the spec at it, then delete the committed ciphertext
#    - { name: K, source: onepassword, vault: Personal, item: acme-key, field: password }
git rm ./secret.age
```

**Notes.** All declared credentials are resolved **up front** — before any container
is deployed — so a missing source never leaves an earlier environment partially
applied. Resolved values are staged as 0600 files under your private state dir
(`$XDG_STATE_HOME`), the same posture as the Feature 003 injected material; they are
regenerated each `apply`. Don't both declare a provider credential *and* drop a
convention `~/.config/agent-container/<name>.<provider>.key` file for the same provider — they
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

**Feature 008 (credential managers)** layers on: the generic `command` resolver + named
`onepassword`/`bitwarden` sources, and the **removal** of `encrypted` — see the taxonomy
and migration above.

See [`specs/006-agent-as-code/`](../specs/006-agent-as-code/) for the full spec,
plan, and contract.
