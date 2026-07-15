# Research: Agent Provisioning & Credentialing (Feature 003)

Decisions resolving the spec's planning-time unknowns. This feature **inherits**
Feature 001's injected-material delivery seam (compose `configs`/`secrets`
referencing locally-staged files that transfer over the runtime context) and
Feature 002's `redeploy` (fresh re-delivery). It does **not** redefine those.

**Posture (operator decisions, confirmed at plan time): both reversals are
LAYERED, not replacements.** The spec's file-first / SSH-first models become the
documented defaults, but every shipped mechanism keeps working — so no existing
`.env`/HTTPS/interactive-login setup breaks.

---

## R1 — Outbound push credential: SSH deploy key, layered over the shipped HTTPS

**Decision**: Provision an **outbound SSH push key** as the documented default
for git push, delivered as runtime-injected material and wired via
`GIT_SSH_COMMAND`. **Retain** the shipped HTTPS + `GH_TOKEN` github.com-scoped
credential helper as a supported fallback (operator selects by remote URL scheme:
`git@github.com:` → SSH key, `https://github.com/` → token). The two are
independent; a deployment may carry either or both.

The push key is **distinct** from Feature 001's inbound sshd host key (FR-002,
SC-008): different injected path, different role, never interchanged. The
entrypoint keeps them separate.

**Non-interactive push** (FR-001, SC-001): the entrypoint sets
`GIT_SSH_COMMAND="ssh -i <injected-key> -o IdentitiesOnly=yes -o UserKnownHostsFile=<injected-known_hosts> -o StrictHostKeyChecking=accept-new"`.
`IdentitiesOnly=yes` stops the agent offering other keys; the pre-seeded
known_hosts (FR-003) means the remote's identity is already trusted, so push
never stalls on unknown-host verification. No passphrase (the key is unencrypted
injected material; `validate_private_key` already rejects encrypted keys).

**Rationale**: matches the SSH-first design the spec cites, gives per-repo
scoping for free (FR-004 — point `--push-key` at a repo deploy key), and reuses
the exact staging seam already built for the inbound host key. HTTPS is kept
because it is shipped, documented, and simpler for a single user PAT — removing
it would break working setups for no security gain (a scoped token and a scoped
deploy key are comparable exposure).

**Alternatives rejected**: (a) *SSH-only, remove HTTPS* — reverses the shipped
MVP decision (`docs/credentials.md` line 154) and breaks `.env`/`GH_TOKEN`
setups. (b) *Keep HTTPS only, drop SSH from the spec* — contradicts the
SSH-first design and forgoes per-repo deploy-key scoping. (c) *Copy the push key
onto the `~/.ssh` volume like the host key* — violates FR-012 (see R2).

**Validation**: acceptance (opt-in) — from inside a container provisioned with a
push key, clone→commit→push over SSH completes with zero prompts; unit — the
compose model carries the push key as a config at the ephemeral target and never
on argv; SC-008 — inbound host key and outbound push key are asserted distinct.

---

## R2 — Push key and API keys are delivered EPHEMERALLY (never on a persistent volume)

**Decision**: Secrets that FR-012 forbids from resting on the host (the **push
key** and **injected model/API keys**) are delivered to the **ephemeral inject
dir** `/run/agent-container/…` (compose `configs`, read-only, present only while
the container lives) and are **NOT** copied onto any of the seven persistent
per-container volumes. `GIT_SSH_COMMAND` points `ssh` directly at the injected
`/run` path; the Claude `apiKeyHelper` `cat`s the injected `/run` path.

This is the **key discipline shift** from Feature 001: the inbound **host key**
is deliberately install-copied onto the persisted `~/.ssh` volume (stable
container identity across recreation — an accepted, documented trust boundary).
Outbound push and API secrets are the opposite: they must vanish with the
container so the operator's local copy is the sole durable copy (SC-004).

**Rationale**: `/run/agent-container` is already the injection surface
(`INJECT_DIR`), tmpfs-like in effect (a compose config, not a named volume), so
it satisfies FR-012 with no new mechanism. Delivering fresh each deploy also
gives rotation for free (R6/FR-015).

**Alternatives rejected**: (a) *Persist on the volume* — FR-012 violation,
SC-004 failure. (b) *A dedicated `tmpfs:` mount* — extra compose surface; the
`/run` config delivery already vanishes with the container. (c) *Env-file only*
— env keys are fine for the fallback but a file is the FR-006 default and keeps
the value off the process environment table for agents that read a file.

**Validation**: acceptance — after teardown, grep the host volumes and image
layers for the injected key material → zero copies (SC-003/SC-004).

---

## R3 — Model/API credentials: file-by-default per agent, env-inside-container fallback, stored-auth retained

**Decision**: Deliver each model/API credential as a **runtime file-secret**
(ephemeral, R2) and wire each baked agent to consume it by its own file
mechanism where clean, exporting into the **in-container environment** only where
an agent cannot read a file (FR-006). All three agents were verified file-capable
at plan time:

| Agent | File-by-default mechanism | Fallback |
|-------|---------------------------|----------|
| **Claude Code** | `apiKeyHelper` in `~/.claude/settings.json` → `cat /run/agent-container/anthropic_api_key` (helper reads the ephemeral file on demand) | `ANTHROPIC_API_KEY` env |
| **Codex** | `~/.codex/auth.json` populated via `codex login --with-api-key` reading the ephemeral file on **stdin** (never argv) | `OPENAI_API_KEY` exported into the in-container env from the ephemeral file |
| **pi-coding-agent** | `~/.pi/agent/auth.json` (per-provider), or provider key exported into the in-container env from the ephemeral file | provider env var |

**Layered**: the shipped modes stay first-class — (a) **env/`.env`** delivery of
`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/provider keys (unchanged), and (b)
**interactive-login "stored authorization"**: the operator runs `/login` inside
the container once and the credential persists+auto-refreshes on the per-agent
volume. (b) is the spec's "equivalent stored authorization" entity — a
deliberate, operator-initiated persistence for subscription accounts, and the
one sanctioned exception to R2's no-persist rule (the operator, not the tool,
chose to store it).

**Rationale**: file-by-default keeps the value off the process env table and off
argv for the common case; the env fallback is honest about Codex's stdin-login
nuance; retaining env/`.env` + stored-auth means the reversal breaks nothing.

**Alternatives rejected**: (a) *Env-only* — value sits in the environment of
every process; weaker than a file the agent reads on demand. (b) *File-only,
drop env + stored-auth* — breaks `.env` setups and the preferred subscription
path. (c) *Bake a provider key* — Constitution III / FR-010 violation.

**Validation**: acceptance (opt-in, tokened — never in CI, no cost) — a
provisioned agent performs a backend-requiring operation (SC-002); unit — the
key is a config at an ephemeral target, absent from argv and from the compose
`environment:` literal (SC-003).

---

## R4 — Canonical config delivered fresh each deploy; runtime state persists (the US3 split)

**Decision**: Split each agent's home between **canonical config** (operator-owned,
non-secret — `settings.json`, project guidance like `CLAUDE.md`/`AGENTS.md`, MCP
server definitions, `config.toml`) and **runtime state** (agent-written — history,
todos, caches, logs, and stored-auth `auth.json`). Canonical config is delivered
as compose `configs` to the **ephemeral inject dir** and the entrypoint **copies
it fresh onto the per-agent volume paths on every boot** (overwriting only the
canonical files); runtime state on the volume is never touched. So a local edit
propagates on the next `up`/`redeploy` (FR-007) while history survives recreation
(FR-008).

The split is applied at **file/path granularity** (spec assumption), driven by a
small per-agent **canonical manifest** (which paths are operator-owned). The
copy-from-`/run`-on-boot mechanism mirrors the shipped host-key install and
avoids compose mount-overlap between a read-only config target and a volume mount.

**Source of canonical config**: discovered by convention next to the deployment
(`./agent-container.<name>.config/…` → `~/.config/agent-container/<name>.config/…`),
mirroring `.env`/sidecar discovery (002 R5). Deliberately thin — the richer
whole-directory model is **Feature 006 (agent-as-code)**, which builds on this
manifest, not a competing design.

**Rationale**: copy-fresh-on-boot is the same primitive already used for the host
key, needs no YAML/model, and makes "fresh each deploy" literal. A manifest keeps
the canonical/runtime boundary explicit and inspectable.

**Alternatives rejected**: (a) *Mount each config file as a read-only compose
config directly over a path inside the volume* — brittle mount-overlap, and
read-only would block the agent writing adjacent state. (b) *Whole-directory
fresh delivery* — clobbers runtime state (FR-008 violation). (c) *Persist
everything (status quo)* — local edits don't propagate (FR-007 failure).

**Validation**: acceptance — edit a canonical file locally, `redeploy`, assert
the change is in the container; write runtime state, recreate, assert it survived
(SC-005).

---

## R5 — Injected-material taxonomy formalized on the existing configs seam

**Decision**: Model every injected item as one of two classes on the **compose
`configs`** mechanism already used for the host key (chosen in 001/002 because a
compose `secret` with an absolute target crash-loops some engines):

- **secret** — private, read-only, **ephemeral** (`/run/agent-container/…`, never
  on a persistent volume): push key, model/API key. (The inbound host key is the
  documented exception that persists for identity.)
- **config** — non-secret, delivered fresh: known_hosts, canonical agent config.

Material that *carries* a secret (e.g. an MCP definition embedding a token) is
classified **secret**, not config (FR-009) — the manifest marks such paths.

**Rationale**: one seam, one staging path pattern, one transfer-over-context
guarantee (FR-014, inherited). No new compose surface; the class only decides the
target path (ephemeral vs volume) and whether the entrypoint persists it.

**Alternatives rejected**: (a) *Use compose `secrets:` for the private items* —
the absolute-target crash-loop 001 already worked around; `configs` is the
portable choice. (b) *A bespoke secret store* — Constitution VI; the operator's
local file is the source of truth.

**Validation**: unit — each injected class lands at the right target with the
right persistence; the compose model never inlines a secret value.

---

## R6 — Rotation, scoping, fail-fast, partial-provisioning (emergent + robustness)

**Decision**: These fall out of the injection model and are *verified*, not newly
built:

- **Rotation (FR-015/SC-006)**: change the local file, `redeploy` (002) — the
  ephemeral secrets are re-delivered; no baked/persisted copy survives (R2).
- **Scoping (FR-004/FR-013)**: a per-repo deploy key is just a narrower
  `--push-key`; per-`(host,name)` staging already scopes each secret to the one
  deployment that needs it.
- **Fail-fast (FR-016/SC-007)**: staging validates every referenced file exists
  and (for keys) is well-formed **before** any compose call; a missing item
  `die`s before the agent starts — no partially-credentialed agent.
- **No half-credentialed running agent (FR-017)**: all staging happens locally
  before `compose up`; a staging failure aborts before the container is created,
  and `up` is atomic (compose brings the project up with all configs or fails).

**Validation**: acceptance — a deploy referencing a missing key fails before
container creation (SC-007); rotation acceptance (SC-006).

---

## R7 — CLI surface and env-file channel (parity with the shipped SSH-material UX)

**Decision**: Mirror the existing `--host-key`/`--authorized-key` +
`SSH_HOST_ED25519_KEY_B64`/`SSH_AUTHORIZED_KEYS` UX. Add to `up`/`redeploy`:

- `--push-key PATH` (the outbound SSH deploy key), `--known-hosts PATH`
  (trusted remote identity for push).
- Model/API keys and canonical config are **discovered by convention** (env-file
  as today for the key values; the `<name>.config/` dir for canonical config) —
  no new required flags, so the common path is unchanged.
- Env-file channel parity: `SSH_PUSH_KEY_B64`, `PUSH_KNOWN_HOSTS` consumed by the
  entrypoint, matching the existing `SSH_*` envs.

**Rationale**: least surprise; the credential UX already has an established shape.
Zero new Python dependencies — argv builders + staging + stdlib, exactly as 001/002.

**Alternatives rejected**: a subcommand (`agent-container creds …`) — heavier than
the injection points need; the flags + convention discovery match the shipped feel.

**Validation**: unit — the new flags stage material and thread it into the compose
model; `--self-test` doctests for any new path derivation.
