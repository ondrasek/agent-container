# Quickstart: Credential Managers

Validation journeys proving the manager sources work end-to-end. All run inside the Feature
006 declarative model (`.agent-container/` + `apply`). The engine assertions are hermetic
(`bin/tests/test_agent_as_code.py`); the real-container path reuses the 006 acceptance harness.

## Prerequisites

- A working local container runtime for the acceptance journey.
- For a real named source (Scenario B): the manager CLI installed + an **unlocked** session
  (`op signin`, `bw unlock`). The unit + `command`-source acceptance need neither.

## Scenario A — Generic `command` source, no plaintext on disk (US1 / SC-001, SC-002)

```yaml
# .agent-container/project.yaml
environments:
  - name: acme
    host: local
    container: { env_file: ./ci.env }
    credentials:
      - { name: MYSECRET, source: command, argv: ["printf", "sk-from-resolver"] }
```

```bash
agent-container apply -y
```

**Expected**: the secret reaches the running container (`printenv MYSECRET` →
`sk-from-resolver`), and the value appears **nowhere** in the project directory or the
command output (grep finds nothing). A resolver that exits non-zero / is missing / times out
/ returns empty makes `apply` **fail before any change**, naming the credential (SC-002).

## Scenario B — Named manager (1Password / Bitwarden) (US2 / SC-005)

```yaml
credentials:
  - { name: ANTHROPIC_API_KEY, source: onepassword, vault: Personal, item: anthropic, field: key }
  - { name: GH_TOKEN,          source: bitwarden,   item: gh-token, field: password }
```

**Expected**: the tool assembles `op read op://Personal/anthropic/key` /
`bw get password gh-token` (no shell), fetches the secret, and injects it — identically to the
equivalent `command` source. A missing required field (e.g. no `field`) is refused before any
change, naming the field.

## Scenario C — Any other manager via the generic source (SC-004)

```yaml
credentials:
  - { name: DB_PASSWORD, source: command, argv: ["vault", "kv", "get", "-field=password", "secret/db"] }
  - { name: API_KEY,     source: command, argv: ["pass", "show", "acme/api-key"] }
```

**Expected**: `pass`, Vault, KeePassXC, `aws secretsmanager`, `gcloud secrets`, … all work
through the generic `command` source with **zero** change to the tool.

## Scenario D — Migration: `encrypted` is gone (US3 / SC-003)

```yaml
credentials:
  - { name: KEY, source: encrypted, path: ./key.age, decrypt: "age -d -i ~/.age/key" }
```

```bash
agent-container apply -y     # or plan / status
```

**Expected**: refused **before any change** with a message naming the removed source and the
migration (use a manager, the OS keychain, or an external/untracked file) — never a silent
drop.

## Scenario E — Recommended taxonomy (US3)

Read `docs/agent-as-code.md`: the preference hierarchy is explicit — manager / OS keychain /
local / HW-key-backed **recommended**; a plaintext secret tracked in git **refused**; no
encrypted-in-git tier. HW keys (YubiKey) are a **backing** for a resolver, not a source.

## Validation results (T015)

- **A — generic `command` source (CI-safe)** — validated by the real-container acceptance
  `test_declarative_command_source_injects_without_plaintext`: a resolver (`printenv
  RESOLVER_SRC_008`, a pure **locator**) delivers the secret into the container with the
  trailing newline stripped, **no plaintext anywhere in the project dir or the output**
  (SC-001), and a failing resolver **aborts before any change** naming the credential with a
  remediation hint while its stderr is never echoed (SC-002/FR-006). **Green.**
- **B — named managers** — argv assembly (`op read op://{vault}/{item}/{field}`,
  `bw get {field} {item}`) and the required-field refusals are pinned hermetically
  (`test_resolver_argv_assembly`, `test_named_manager_required_fields`,
  `test_named_sources_resolve_identically_to_command` for SC-005). The **live** path needs a
  real unlocked `op`/`bw` session — **opt-in, never CI**.
- **C — any other manager, zero tool change (SC-004)** — verified by validating + assembling
  resolvers for **Vault, pass, KeePassXC, and gcloud secrets** with no code change. **Green.**
- **D — migration refusal (SC-003)** — `test_declarative_encrypted_source_refused_with_migration`
  (real CLI) plus the hermetic `test_encrypted_source_refused_with_migration`: refused by any
  command that loads the spec, naming the migration targets, **not** the generic enum error.
  **Green.**
- **E — taxonomy** — documented in [`docs/agent-as-code.md`](../../docs/agent-as-code.md)
  (recommended / refused / removed tiers, HW-key-as-backing, and the migration recipe).
  **Green.**

## Success signal

All scenarios pass: a secret referenced through a manager applies and reaches the container
with no plaintext on disk or in output; named 1Password/Bitwarden resolve identically to the
equivalent generic resolver; any CLI-based manager works through `command` with no tool
change; the removed `encrypted` source is refused with a migration; and the taxonomy is
documented — matching SC-001…SC-005 and Constitution III.
