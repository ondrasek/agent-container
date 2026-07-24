# Data Model: Credential Managers (Phase 1)

Extends the Feature 006 credential schema. A credential is always a **locator**, never a
value. All validation happens before any action (FR-015); resolution is in memory (III).

## Credential sources (after this feature)

`CRED_SOURCES = ("env", "file", "keychain", "command", "onepassword", "bitwarden")`
— `encrypted` is **removed** (refused with a migration message).

| `source` | Required fields | Resolves by |
|----------|-----------------|-------------|
| `env` | `var` | reading the environment variable |
| `file` | `path` | reading the file (git-tracked-plaintext-in-project refused) |
| `keychain` | `service`, `account` | macOS `security` / Linux `secret-tool` |
| **`command`** | `argv` (list of strings) | running `argv` **directly, no shell**; stdout = secret |
| **`onepassword`** | `vault`, `item`, `field` | `op read op://{vault}/{item}/{field}` |
| **`bitwarden`** | `item`, `field` | `bw get {field} {item}` |
| ~~`encrypted`~~ | — | **removed** — `source: encrypted` dies with a migration message |

Optional cross-source field (unchanged from Feature 006 T012a): `target ∈ {push_key,
host_key, authorized_key}` routes the resolved value to an SSH channel instead of env/apikey.

### Validation rules (`validate_credential`)

- `name` required; `source` ∈ `CRED_SOURCES` (else the enum error) — **except** `source:
  encrypted`, which is special-cased to a migration `die` (FR-009) **before** the enum check.
- Each source's required fields must be present and truthy (else `die` naming the field).
- **`command.argv`** must be a **non-empty list of strings** — a non-list, an empty list, or
  a non-string element `die`s naming the field.
- Unknown keys (beyond `name`, `source`, `target`, and the source's fields) are rejected.
- No partial change: any error `die`s naming the offending file+field before anything runs.

## Resolver

The host-side executor shared by `command` / `onepassword` / `bitwarden`.

**`_run_resolver(argv, name, *, timeout=RESOLVER_TIMEOUT) -> str`** (`RESOLVER_TIMEOUT = 30`):

| Property | Rule |
|----------|------|
| execution | `argv` run **directly** — no `/bin/sh`, no `shell=True` (II/III) |
| input | `stdin=DEVNULL` — **non-interactive**, no TTY prompt (FR-005) |
| bound | `timeout` seconds; `TimeoutExpired` → `die` (never hang the apply, FR-005) |
| failure | missing binary / non-zero exit / empty-when-required → `die`, **generic + secret-free** message naming the credential; the resolver's **stderr is never echoed** (FR-004/006) |
| output | stdout is the secret value, returned **in memory only** |

`resolve_credential_value(cred, root)` dispatches: `command` → `_run_resolver(cred["argv"])`;
`onepassword` → `_run_resolver(["op","read", f"op://{vault}/{item}/{field}"])`; `bitwarden`
→ `_run_resolver(["bw","get", field, item])`. Delivery of the returned value is **unchanged**
(Feature 006: provider name → the apikey file channel; SSH `target` → the ssh channels; else
a per-deployment 0600 secrets env-file). All credentials are resolved **up front** before any
container is deployed (FR-014, inherited).

## Credential taxonomy (documented, not code)

The recommended preference hierarchy a repo reviewer applies:

1. **Recommended — never a value in the repo**: `env`, `keychain`, `command`,
   `onepassword`/`bitwarden` (and other managers via `command`), `file` outside/untracked.
   HW keys (YubiKey) are a **backing** for a resolver, not a source.
2. **Refused**: a plaintext secret **file tracked in git** inside the project (unchanged).
3. **Gone**: the encrypted-in-git tier (`encrypted`) — removed.
