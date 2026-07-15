# Contract: Agent Provisioning & Credentialing (Feature 003)

Extends Feature 001's injected-material contract and Feature 002's verbs. Only
the **net-new** surface is specified here; `up`/`redeploy`/`down`/`wipe`,
per-`(host,name)` staging, and transfer-over-context are inherited.

## CLI flags (on `up` and `redeploy`)

| Flag | Meaning |
|------|---------|
| `--push-key PATH` | Outbound SSH push key (private). Staged as an **ephemeral** secret; wired via `GIT_SSH_COMMAND`. Distinct from `--host-key` (inbound). Validated (`validate_private_key`) before any compose call. |
| `--known-hosts PATH` | Trusted remote host identity for the push remote. Ephemeral `config`. Enables non-interactive push (FR-003). |

Model/API keys keep their existing delivery (env-file values) and gain a
convention-discovered file mode; **canonical config** is convention-discovered —
no new required flags, so the common `up <name>` path is unchanged. All new flags
carry secret hygiene: the CLI passes **paths, never values**, and never reads a
secret's contents (existence/format checks only).

## Env-file channel (parity with the shipped `SSH_*` envs)

| Variable | Consumed by | Purpose |
|----------|-------------|---------|
| `SSH_PUSH_KEY_B64` | entrypoint | base64 outbound push key (ephemeral; never written to a persistent volume) |
| `PUSH_KNOWN_HOSTS` | entrypoint | known_hosts lines for the push remote |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / provider keys | entrypoint / agents | **retained** env delivery (layered fallback) |
| `GH_TOKEN` | entrypoint | **retained** HTTPS push (github.com-scoped helper) |

## Injected in-container paths (ephemeral — `/run/agent-container`)

| Constant | Path | Class |
|----------|------|-------|
| `INJECT_HOST_KEY_PATH` (F001) | `/run/agent-container/ssh_host_ed25519_key` | secret → copied to `~/.ssh` volume (identity) |
| `INJECT_AUTHORIZED_KEYS_PATH` (F001) | `/run/agent-container/authorized_keys` | config → `~/.ssh` volume |
| **`INJECT_PUSH_KEY_PATH`** | `/run/agent-container/push_ed25519_key` | secret → **stays ephemeral** (FR-012) |
| **`INJECT_KNOWN_HOSTS_PATH`** | `/run/agent-container/known_hosts` | config → ephemeral |
| **`INJECT_APIKEY_DIR`** | `/run/agent-container/apikeys/<provider>` | secret → ephemeral |
| **`INJECT_CONFIG_DIR`** | `/run/agent-container/config/<agent>/…` | config → copied fresh onto the per-agent volume each boot |

All are delivered as compose `configs` (not `secrets`) referencing locally-staged
files — the portable choice established in 001 (an absolute-target compose
`secret` crash-loops some engines).

## Entrypoint wiring contract (`entrypoint.sh`)

1. **Push (US1)**: if a push key is present (inject path or `SSH_PUSH_KEY_B64`),
   export `GIT_SSH_COMMAND="ssh -i <push-key> -o IdentitiesOnly=yes -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=accept-new"`.
   The key is read **in place** from the ephemeral path and **not** copied to the
   `~/.ssh` volume (FR-012). The inbound host-key install step is untouched and
   never conflated with this (SC-008). HTTPS helper block retained.
2. **API creds (US2)**: for each agent, prefer the file mechanism —
   Claude `apiKeyHelper` → the injected key file; Codex `codex login --with-api-key`
   reading the injected file on stdin; pi `auth.json`/provider. Where a file is
   not consumable, export the key into the **in-container** environment (never the
   host launch, never argv). Absent injected keys → the shipped env/`.env` and
   interactive-login paths still work (NOTE, not `die`).
3. **Canonical config (US3)**: for each path in the per-agent canonical manifest,
   copy the file from `INJECT_CONFIG_DIR` onto its volume path (overwrite),
   leaving all other (runtime-state) files under the home untouched. Idempotent;
   runs every boot so `redeploy` re-applies edits.

## Failure contract (robustness)

| Condition | Contract |
|-----------|----------|
| referenced file missing at deploy | CLI `die`s with the looked-at paths **before** `compose up` (FR-016/SC-007) |
| push key malformed/encrypted | CLI `die`s before compose (FR-016) |
| a staging step fails | abort before container creation; no half-credentialed agent (FR-017) |
| unreachable/remote host | inherited from 001 — material transfers over the context or the deploy fails; never a local-only empty reference (FR-014) |

## Documentation contract (FR-018)

Any change to *what* is injected, *how*, or its exposure posture updates, in the
same change: `docs/credentials.md` (add the SSH-push section; keep HTTPS as the
documented alternative), `.env.example` (push-key env channel), `README.md`,
`CLAUDE.md`, and this spec.
