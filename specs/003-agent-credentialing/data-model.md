# Data Model: Agent Provisioning & Credentialing (Feature 003)

Entities are **injected material** and their classification, plus the per-agent
manifests that decide delivery. No persistent schema is added — the model is the
staging + compose-`configs` shape (inherited from 001) with two secret classes
and a config manifest. Identity values (name/port/volume names) are unchanged
(Constitution IV).

## Injected material (base entity)

Any file delivered into a deployment at runtime, sourced from the operator's
machine, staged locally under `<state>/<host>/<name>.*`, and referenced by a
compose `config` so it transfers over the runtime context (FR-014).

| Field | Values |
|-------|--------|
| `class` | `secret` (private, read-only) or `config` (non-secret) |
| `persistence` | `ephemeral` (target under `/run/agent-container/…`, vanishes with the container) or `volume` (copied onto a persistent per-agent volume by the entrypoint) |
| `source` | absolute path on the operator machine (existence validated before any compose call — FR-016) |
| `target` | absolute in-container path (the compose `config` target) |
| `scope` | exactly one `(host, name)` deployment (FR-013) |

**Classification rule (FR-009)**: material that *carries* a secret (e.g. an MCP
definition embedding a token) is `class = secret`, never `config` — the manifest
marks such paths.

**Invariant matrix (FR-010…FR-015)** — enforced by construction:

| Item | class | persistence | never on argv | never baked | never on persistent volume |
|------|-------|-------------|:---:|:---:|:---:|
| inbound host key (F001) | secret | **volume** (identity) | ✅ | ✅ | ⚠️ persists by design (documented exception) |
| **outbound push key** | secret | ephemeral | ✅ | ✅ | ✅ |
| **known_hosts (push)** | config | ephemeral | ✅ | ✅ | ✅ |
| **model/API key (injected)** | secret | ephemeral | ✅ | ✅ | ✅ |
| **canonical agent config** | config | ephemeral → copied fresh onto volume each boot | ✅ | ✅ | n/a (non-secret) |
| stored-auth `auth.json` | secret | **volume** (operator-chosen) | ✅ | ✅ | ⚠️ operator-initiated exception |
| agent runtime state | — | volume | — | — | n/a (non-secret) |

## Push credential (US1)

The outbound git-push identity. **Distinct** from the inbound sshd host key
(FR-002, SC-008): different injected path, different role, never interchanged.

| Field | Value |
|-------|-------|
| `push_key` | private SSH key (unencrypted; `validate_private_key` rejects encrypted) — `class=secret`, `persistence=ephemeral`, target `INJECT_PUSH_KEY_PATH` = `/run/agent-container/push_ed25519_key` |
| `known_hosts` | trusted remote host identity for the push remote (FR-003) — `class=config`, ephemeral, target `INJECT_KNOWN_HOSTS_PATH` = `/run/agent-container/known_hosts` |
| `scope` | default single **user key**, or a narrowly-scoped per-repository **deploy key** (FR-004) — same mechanism, narrower key |
| wiring | entrypoint sets `GIT_SSH_COMMAND="ssh -i <push_key> -o IdentitiesOnly=yes -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=accept-new"` |

**Layered fallback**: the shipped HTTPS + `GH_TOKEN` github.com-scoped credential
helper is retained; the operator selects by remote URL scheme. A deployment may
carry SSH, HTTPS, or both.

## Model/API credential (US2)

The authorization an agent needs to reach its backend. Delivered file-by-default
(`class=secret`, ephemeral), consumed per agent:

| Agent | Default (file) | Fallback (env, in-container) | Stored-auth (volume, operator-chosen) |
|-------|----------------|------------------------------|----------------------------------------|
| Claude Code | `apiKeyHelper` → `cat` the injected key file | `ANTHROPIC_API_KEY` | `/login` OAuth on `~/.claude` |
| Codex | `codex login --with-api-key` reads the injected file on **stdin** → `~/.codex/auth.json` | `OPENAI_API_KEY` exported into the in-container env | `codex login` on `~/.codex` |
| pi-coding-agent | `~/.pi/agent/auth.json` (per provider) | provider key in the in-container env | `/login` on `~/.pi` |

**FR-006**: file is the default; the credential is placed into the **in-container**
environment (never the host-side launch, never argv) only where an agent cannot
consume a file (Codex is the nuance case — its durable form is a file, populated
via stdin). Env/`.env` delivery of these keys remains supported (layered).

## Canonical config vs runtime state (US3)

One agent home is split at **file/path granularity** by a per-agent **canonical
manifest** — the set of operator-owned paths delivered fresh each deploy; every
other path under the home is runtime state persisted on the per-agent volume.

| Agent home (volume) | Canonical (fresh each deploy) | Runtime state (persists) |
|---------------------|-------------------------------|--------------------------|
| `~/.claude` | `settings.json`, `CLAUDE.md`, MCP defs | history, todos, projects, OAuth creds |
| `~/.codex` | `config.toml`, `AGENTS.md` | `auth.json`, session/rollout logs |
| `~/.pi` | agent config, provider defs (non-secret) | `agent/auth.json`, history/caches |

**Delivery**: canonical files ride as compose `configs` to `INJECT_CONFIG_DIR`
(`/run/agent-container/config/…`); the entrypoint copies them onto the volume
paths on each boot (overwrite canonical, leave runtime untouched). A local edit
therefore propagates on the next `up`/`redeploy` (FR-007); runtime state survives
recreation (FR-008).

**Source discovery** (convention, mirrors `.env`/sidecar — 002 R5):
`./agent-container.<name>.config/…` → `~/.config/agent-container/<name>.config/…`.
Deliberately thin; **Feature 006 (agent-as-code)** formalizes the whole-directory
model on top of this manifest.

## Deploy-time validation states (US robustness)

| State | Trigger | Behavior |
|-------|---------|----------|
| **missing material** | a referenced `--push-key`/`--known-hosts`/canonical/API file is absent | `die` before any compose call (FR-016/SC-007) — no partially-credentialed agent |
| **malformed key** | push key fails `validate_private_key` (encrypted / not a key) | `die` before compose (FR-016) |
| **staging failure** | any item fails to stage | abort before `compose up`; nothing created (FR-017) |
| **rotation** | operator edits a local secret and `redeploy`s | ephemeral secrets re-delivered; no prior copy survives (FR-015/SC-006) |
