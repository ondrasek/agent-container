# Research: Credential Managers (Phase 0)

Decisions that resolve the plan's unknowns. Every one extends the **existing** Feature 006
credential code (`validate_credential`, `resolve_credential_value`, `_run_decrypt`,
`stage_declared_credentials`) — this feature adds sources, not a new subsystem.

## R1 — Generic resolver: an argv list run directly, no shell

- **Decision**: The `command` source declares `argv: ["op", "read", "op://…"]`; the tool
  runs it **directly** (`subprocess.run(argv, …)`) with **no `/bin/sh`**. A pipe/filter is an
  operator wrapper script referenced by the argv, never an inline shell string.
- **Rationale**: No shell → no injection surface and fully deterministic (Constitution
  II/III). Matches the clarified spec (FR-001) and how `op`/`bw` are actually invoked. bandit
  stays clean (no `shell=True`).
- **Validation**: `argv` must be a **non-empty list of strings** — a non-list, an empty list,
  or a non-string element `die`s naming the field (FR-015), before any run.
- **Alternatives rejected**: a shell command string (injection surface, non-deterministic —
  clarified against); a git-credential-helper stdin key-value protocol (out of scope — one-
  shot argv→stdout suffices).

## R2 — One shared runner: generalize `_run_decrypt` → `_run_resolver`

- **Decision**: Replace the `encrypted`-only `_run_decrypt(decrypt_cmd, enc_path, name)` with
  a general `_run_resolver(argv, name, *, timeout=RESOLVER_TIMEOUT) -> str`: run `argv`
  directly, **`stdin=DEVNULL`** (non-interactive, FR-005), `capture_output`, `timeout`; on
  non-zero exit / `TimeoutExpired` / missing binary → `die` with a **generic, secret-free**
  message naming the credential (never echo the resolver's stderr — it may hold secret
  material, FR-006). Return stdout.
- **Rationale**: `command`, `onepassword`, and `bitwarden` all reduce to "run an argv,
  capture stdout" — one audited runner enforces the least-exposure + non-interactive +
  bounded guarantees in a single place. `_run_decrypt` already did exactly this for the
  decrypt command; generalizing it removes duplication and the now-dead `encrypted` path.
- **Empty output**: a resolver that exits 0 with empty stdout when a value is required
  `die`s (FR-004) — a secret is never legitimately empty.
- **Alternatives rejected**: a per-source bespoke runner (duplicates the exposure/timeout
  logic three times — easy to get one wrong).

## R3 — Named sources assemble a no-shell argv

- **Decision**:
  - **`onepassword`** (`vault`/`item`/`field`) → `["op", "read", f"op://{vault}/{item}/{field}"]`.
  - **`bitwarden`** (`item`/`field`) → `["bw", "get", field, item]` (`bw get <field> <item>`
    covers password/username/uri/totp/notes without a shell/jq).
  Each named source validates its required fields up front, then delegates to `_run_resolver`.
- **Rationale**: The tool assembles the exact invocation from **structured typed fields**
  (clarified FR-007), individually validated — no shell, no free-form command. The generic
  `command` source remains the escape hatch for any manager not named (FR-008) with **zero**
  tool change.
- **Alternatives rejected**: a single provider-native reference string (clarified against —
  the operator chose structured fields); shelling out to `jq` for arbitrary Bitwarden fields
  (adds a shell + a dependency — the supported `bw get <field>` set is enough).

## R4 — Remove `encrypted`, refuse with a migration message

- **Decision**: Drop `encrypted` from `CRED_SOURCES` and its `required_by_source` entry, and
  delete `_run_decrypt`. In `validate_credential`, **special-case** `source: encrypted`
  BEFORE the generic enum error, with an actionable migration `die`: "the `encrypted` source
  was removed — migrate to a manager (`onepassword`/`bitwarden`), the OS `keychain`, or an
  external/untracked `file`; see docs/agent-as-code.md".
- **Rationale**: Storing secrets in the git remote (even encrypted) is the discouraged tier;
  removing it makes the model coherent (spec US3). A generic "not one of {…}" error would not
  guide an upgrading operator — the special case is the FR-009 requirement.
- **Alternatives rejected**: keeping `encrypted` deprecated (the user chose full removal);
  silently ignoring it (a spec must never silently drop a credential — FR-003/015).

## R5 — Timeout: a fixed 30-second bound

- **Decision**: `RESOLVER_TIMEOUT = 30` seconds, module constant, not operator-configurable.
- **Rationale**: The operator pre-unlocks the manager (non-interactive), so resolution is a
  quick fetch — but a manager may do a network round-trip (Vault, cloud secret store). 30 s
  covers that while guaranteeing a wedged CLI can never hang an apply (FR-005). A fixed bound
  keeps the guarantee simple and testable; revisit only if a real manager needs longer.
- **Alternatives rejected**: no timeout (a blocking CLI hangs apply); a per-credential
  timeout field (needless surface for an edge that hasn't appeared).

## R6 — Testing: mock the runner in the hermetic tier

- **Decision**: Hermetic unit tests (extend `test_agent_as_code.py`):
  - `validate_credential`: the new source enums; `command` requires a **list** `argv` (reject
    non-list/empty/non-string); `onepassword`/`bitwarden` required-field validation; the
    `encrypted` **migration refusal**; unknown keys rejected.
  - `resolve_credential_value`: `command` runs the given argv; `onepassword`/`bitwarden`
    assemble the **expected argv** (assert the argv, mock `_run_resolver`); a non-zero /
    timeout / empty result `die`s with a **secret-free** message; stderr never echoed.
  - `stage_declared_credentials`: unchanged routing still delivers the resolved value (a
    provider name → apikey file channel; else env var) — a regression guard.
  - Acceptance (`test_acceptance.py`): a declarative project with a `command` source whose
    resolver prints a known value applies; the value reaches the container and **no plaintext
    appears in the project dir / output** (SC-001) — reuse the 006 declarative harness.
- **Rationale**: The exposure/validation logic is pure or mockable; a real manager CLI is not
  needed in CI (Constitution V) — the generic `command` source with a trivial resolver
  (`printf`) exercises the whole path at the acceptance tier.
- **Alternatives rejected**: requiring `op`/`bw` in CI (external accounts/secrets — never in
  CI); only unit tests (misses the real end-to-end injection — the `command`+`printf`
  acceptance covers it cheaply).
