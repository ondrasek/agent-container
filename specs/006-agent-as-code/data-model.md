# Data Model: Agent-as-Code (Feature 006)

The model is the **`.agent-container/` project spec** (the desired state, on disk,
parsed with `yaml.safe_load`) plus the **reconcile entities** (plan, ownership) the tool
computes at runtime. **No new persistent state** is stored — ownership/drift derive
from the deterministic identity (Constitution IV). Inherited: host/registry (001),
lifecycle (002), credential inject channels (003), execution/workspace (004).

## Project specification (on disk)

Rooted at the **`.agent-container/` marker directory** (nearest ancestor of the
working dir, FR-001). One or more declarative **YAML** files (parsed with
`yaml.safe_load`) collectively define the desired environment(s). Portable,
optionally git-tracked. **Read only from the operator's host-side copy** — never a
container's copy (FR-020).

### Schema (YAML — illustrative; the schema, not the loader, is the contract)

```yaml
# .agent-container/project.yaml
environments:
  - name: acme                  # -> the deterministic identity (container/volumes/port)
    host: hz1                   # host binding: a registered/known host name (US1)
    # host: { provision: hetzner, server_type: cax11, location: nbg1 }   # US4
    container:                  # the up-surface (Features 002/004)
      mode: interactive         # interactive | headless
      agent: claude             # claude | codex | pi
      task: "@task.md"          # optional
      workspace: persistent     # persistent | bind | ephemeral
      repo: https://github.com/you/acme   # clone-on-start (004)
      env_file: ./acme.env      # non-secret env
    credentials:                # US2 — references, never values
      - name: ANTHROPIC_API_KEY
        source: env             # env | file | keychain | encrypted
        var: ANTHROPIC_API_KEY
      # - { name: OPENAI, source: file, path: ~/secrets/openai.key }        # outside the tracked dir
      # - { name: X, source: keychain, service: anthropic, account: acme }  # OS secret store
      # - { name: Y, source: encrypted, path: .agent-container/y.age, decrypt: "age -d -i ~/.age/key" }
```

| Key | Meaning | Maps to |
|-----|---------|---------|
| `environments[]` | one desired agent setup; the unit of apply/status/destroy | a deterministic identity (name → container/volumes/port) |
| `host` | host binding — a **referenced** (externally owned) or **provisioned** (spec-owned) host | 001 registry / provisioner (FR-017) |
| `container` | the deploy surface | `up` flags (002/004): mode/agent/task/workspace/repo/env |
| `credentials[]` | a named credential **reference + source** — never the value | 003 inject channels (FR-011/012) |

## Credential reference

| Field | Meaning |
|-------|---------|
| `name` | the credential the environment needs (agent API key / git push identity / SSH key) |
| `source` | `env` \| `file` (external, outside the dir) \| `keychain` (OS store) \| `encrypted` (committable file + `decrypt` command) |
| source detail | `var` / `path` / `service`+`account` / `path`+`decrypt` |

Resolved **at apply, in memory**, injected via 003; **never** written to disk, log,
registry, or argv (FR-013/014). A missing source → fail before any change, named
(FR-016). A git-tracked plaintext secret in the project → **refused** with
remediation (FR-015).

## Host binding

| Kind | Meaning | Teardown |
|------|---------|----------|
| **referenced** | an existing/known host name | externally owned — **never** deprovisioned by `destroy` (FR-017) |
| **provisioned** | a host the spec declares to create (US4) | spec-owned — MAY be deprovisioned on `destroy` with operator intent |

## Plan / diff (computed, not stored)

The per-resource delta between desired (spec) and actual (live), presented before
any mutation (FR-007/008).

| Resource state | Meaning |
|----------------|---------|
| **absent** | declared, not present live → apply creates |
| **matching** | declared config == live → apply makes no change (idempotent, SC-002) |
| **drifted** | present but differs → apply converges (recreate if not updatable-in-place; said before doing it) |

Ownership for status/destroy is the **deterministic identity** of each declared
name (Constitution IV) — no state file. `destroy` acts only on owned identities
(SC-007).

## Reconcile state machine

```text
discover(.agent-container/)  → report root  (absent → today's imperative behavior, FR-004)
      → parse+validate (yaml.safe_load)             (error → offending file/field, NO partial change, FR-003)
      → resolve host binding + precedence    (spec wins for its scope, reported, FR-018)
      → compute_plan(declared, live)         (absent/matching/drifted per resource)
      → apply:   preview + confirm → drive do_up / provisioner ; integrity: RO .agent-container bind (FR-020)
        status:  print plan, mutate nothing
        destroy: remove owned identities only (referenced host untouched; provisioned host on intent)
      → on partial failure: report exactly what changed / did not (FR-010)
```

## Spec-integrity invariant (FR-020)

The `.agent-container/` subtree, when present in a deployed container's `/workspace`,
is bind-mounted **read-only** (compose bind `<host-side .agent-container>:/workspace/.agent-container:ro`),
kernel-enforced for every uid. The tool reads the spec **only** host-side and
**refuses to deploy** if the subtree would be agent-writable. This is the model's
Least-Privilege gate: the untrusted agent cannot re-govern itself.
