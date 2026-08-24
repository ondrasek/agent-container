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

**Classification rule (FR-009)**: secrets and canonical config travel *separate,
well-defined channels* — the ephemeral **key-file** channel (US2) carries every
tool-injected secret, while **canonical config** is non-secret *by definition*
(FR-007: "settings, project guidance, tool/MCP definitions **without embedded
secrets**"), so MCP definitions are canonical config (delivered and consumed).
A config file that nonetheless *carries* a token cannot be detected content-free
without reading it (a secret-hygiene violation), and consuming a secret-bearing
config would contradict FR-012 (agents read config from the persistent volume);
so richer auto-classification is deferred to **Feature 006** (agent-as-code). The
operator externalizes real secrets through the key-file channel.

**Invariant matrix (FR-010…FR-015)** — enforced by construction:

| Item | class | persistence | never on argv | never baked | never on persistent volume |
|------|-------|-------------|:---:|:---:|:---:|
| inbound host key (F001) | secret | **volume** (identity) | ✅ | ✅ | ⚠️ persists by design (documented exception) |
| **outbound push key** | secret | ephemeral | ✅ | ✅ | ✅ |
| **known_hosts (push)** | config | ephemeral | ✅ | ✅ | ✅ |
| **model/API key (injected)** | secret | ephemeral | ✅ | ✅ | ✅ |
| **canonical agent config** | config | ephemeral → copied fresh onto volume each boot | ✅ | ✅ | n/a (non-secret) |
| stored-auth `auth.json` | secret | **volume** (operator-chosen) | ✅ | ✅ | ⚠️ **operator interactive login only** — never tool-injected (H1) |
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

| Agent | Tool-injected default (**own per-credential volume**, FR-012a — never a per-AGENT volume) | Operator stored-auth (agent volume, **interactive only**) |
|-------|-------------------------------------------------------|------------------------------------------------------|
| Claude Code | `apiKeyHelper` (in the fresh canonical `settings.json`) → `cat` the injected key at `INJECT_APIKEY_DIR`; the `~/.claude` volume never receives the key | interactive `/login` OAuth persists on `~/.claude` |
| Codex | `CODEX_HOME` redirected to an **ephemeral** `/run` dir + `codex login --with-api-key` reading the injected file on **stdin** → `auth.json` in that ephemeral dir (or `OPENAI_API_KEY` in the in-container env if honored); the `-codex` volume is never written | interactive `codex login` persists on `~/.codex` |
| pi-coding-agent | `PI_CODING_AGENT_DIR` redirected to an **ephemeral** `/run` dir (per-provider `auth.json` there), or the provider key in the in-container env; the `-pi` volume is never written | interactive `/login` persists on `~/.pi` |

**FR-006 / FR-012 (the H1 rule)**: the **tool-injected** credential is ALWAYS
ephemeral. For agents whose auth form is a file on the per-agent volume
(Codex/pi `auth.json`), the tool redirects that agent's home
(`CODEX_HOME` / `PI_CODING_AGENT_DIR`) to an ephemeral `/run` dir for the injected
mode, so the credential vanishes with the container (FR-012, SC-004). A
non-interactive `login` that writes the **persistent** per-agent volume is NOT a
permitted default. On-volume `auth.json` arises **only** from an operator's
**interactive** login (stored authorization) — the operator's own action, outside
FR-012. Env/`.env` delivery of these keys remains supported (layered).

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
