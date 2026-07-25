# Contract: Credential Managers

Extends the Feature 006 credential contract. Symbols live in `bin/agent-container`; the
schema is declared in a project's `.agent-container/` spec under `environments[].credentials`.

## 1. Schema (validated before any action — FR-015)

```yaml
credentials:
  # generic resolver — an argv list, run directly (no shell)
  - { name: ANTHROPIC_API_KEY, source: command,
      argv: ["op", "read", "op://Personal/anthropic/key"] }
  # named managers — structured typed fields
  - { name: ANTHROPIC_API_KEY, source: onepassword, vault: Personal, item: anthropic, field: key }
  - { name: GH_TOKEN,          source: bitwarden,   item: gh-token, field: password }
  # retained
  - { name: GH_TOKEN, source: env, var: GH_TOKEN }
  - { name: KEY, source: keychain, service: acme, account: bot }
  - { name: KEY, source: file, path: ~/.secrets/key }   # git-tracked-in-project → refused
```

| `source` | Required keys | Notes |
|----------|---------------|-------|
| `command` | `argv` | **non-empty list of strings**; non-list/empty/non-string → die naming the field |
| `onepassword` | `vault`, `item`, `field` | → `op read op://{vault}/{item}/{field}` |
| `bitwarden` | `item`, `field` | → `bw get {field} {item}` |
| `env` / `file` / `keychain` | (unchanged) | retained |
| `encrypted` | — | **removed** — dies: migrate to a manager / keychain / untracked file (FR-009) |

Optional `target ∈ {push_key, host_key, authorized_key}` (Feature 006 T012a) still routes to
the SSH channels. Unknown keys are rejected.

## 2. Resolution guarantees (`_run_resolver`, `resolve_credential_value`)

- Runs the argv **host-side at apply**, **directly (no shell)**, **`stdin` closed**
  (non-interactive), **30 s-bounded** — a hung CLI fails, never hangs the apply (FR-002/005).
- On missing binary / non-zero exit / timeout / **empty-or-whitespace-only** output → **fail
  before any change**, naming the failing credential and source; the resolver's **stderr is
  never echoed** (FR-004/006). The emptiness check tests the **stripped** output, so a
  whitespace-only result cannot become an empty secret once delivery strips the newline.
- Delivery is **unchanged** (Feature 003 channels, FR-012): a provider name → the apikey
  file channel; an SSH `target` → the ssh channels; otherwise the per-deployment 0600
  secrets env-file. A resolver's trailing newline is **stripped** for apikey/env and
  **ensured** for SSH-key delivery.
- The resolved value lives **only in memory** and the existing private 0600 staged files;
  it **never** appears in the repo, argv, logs, or the registry (Constitution III).
- All credentials are resolved **up front** before any container deploys (FR-014, inherited);
  delivery reuses the Feature 003 channels unchanged.

## 3. CLI / behavior

- No new command or flag — the schema is consumed by the existing `apply`/`plan`/`status`
  path (a credential is a locator the reconcile already resolves).
- A named manager the tool does not ship (`pass`, Vault, KeePassXC, cloud stores) is reached
  through the generic `command` source with **zero** tool change (FR-008/SC-004).
- **Migration**: a spec still declaring `source: encrypted` is refused with an actionable
  message; the operator moves the secret into a manager, the OS keychain, or an
  external/untracked file (docs/agent-as-code.md carries the recipe).

## 4. Least-exposure invariants (the load-bearing gate — Constitution III)

- The repo spec contains only a **locator** (which manager / item / field, or which argv) —
  never a secret value, so a spec is safe to commit and review (FR-013).
- The **argv** passed to a resolver is a locator; the **secret** originates from the
  resolver's stdout and is captured in memory — never placed back on any argv or logged.
- A plaintext secret **file tracked in git** inside the project stays **refused** (FR-011).
