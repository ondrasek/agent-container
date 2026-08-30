# Credential injection contract

## Mechanism

Two delivery channels feed a deployment, both **runtime-only** (nothing is ever
baked into an image):

1. **The env-file** (`.env`). All container-side credentials and identity strings
   can be loaded from a single file — the simplest mechanism that works under the
   operator's Lima + docker-cli setup without `docker swarm init`, and maps
   directly to `EnvironmentFile=` in a Podman Quadlet unit on the VPS.
2. **Runtime-injected ephemeral material** (Feature 003). `up`/`redeploy` stage
   selected files on the operator's machine and ship them to the target host as
   compose `configs`, so they travel over a **remote** runtime context too. A
   **tool-injected secret** (an API-key file) lands under `/run/agent-container/…`
   — an ephemeral tmpfs-style path that **vanishes with the container** and is
   **never** copied onto a persistent per-container volume (least-exposure
   invariant **FR-012**). The rule is about material the **tool injects**: since
   Feature 019 the agent's own SSH key is *generated inside the container* and
   deliberately persists on the `ssh` volume, which no injection channel touches. The CLI passes **paths, never secret
   values** (never on argv — FR-011), and never inlines a secret into the
   generated compose file.

**Least-exposure discipline** (Constitution III): no secret is baked into an
image layer (FR-010), placed on a process command line (FR-011), or left in a
host persistent volume by the tool (FR-012). The operator's local copy remains
the **sole durable copy**; rotating a secret is a local edit + `redeploy`
(FR-015). Two deliberate exceptions persist on the `~/.ssh` volume **by design**,
and both are **container-generated, never injected**: the **inbound sshd host
key** (a stable identity to attach to) and, since Feature 019, the **agent's own
SSH key pair** (a stable identity to *register* — regenerating it each boot would
silently invalidate whatever the operator registered on the forge). They are
distinct keys with distinct roles, never interchanged (SC-008).

## What's in `.env`

| Variable             | Purpose                                                                                                        |
|----------------------|----------------------------------------------------------------------------------------------------------------|
| `GH_TOKEN`           | GitHub Personal Access Token. Used by the git credential helper for HTTPS pushes to github.com.                |
| `GIT_USER_NAME`      | Becomes `user.name` in the container's `~/.gitconfig`.                                                          |
| `GIT_USER_EMAIL`     | Becomes `user.email` in `~/.gitconfig`.                                                                         |
| `ANTHROPIC_API_KEY`  | Claude Code authentication (layered fallback; the file-first channel is preferred — see below).                 |
| `OPENAI_API_KEY`     | Codex (`@openai/codex`) authentication (layered fallback).                                                      |
| (other provider keys) | `pi-coding-agent` and `opencode` are multi-provider; add whichever provider keys you point them at (e.g. `GOOGLE_API_KEY`). |
| `PUSH_KNOWN_HOSTS`   | `known_hosts` lines for the push remote, so outbound push never stalls on unknown-host verification. Env-file parity for `up --known-hosts`. |

See `.env.example` at the repo root for the canonical template. The actual `.env` is gitignored.

## How `.env` reaches the container

**Local (Lima + docker-cli):**

```bash
docker run --env-file .env ...
```

or in compose:

```yaml
services:
  agent-container:
    env_file: .env
```

**VPS (Podman + Quadlet, per ADR 0001):**

```ini
[Container]
EnvironmentFile=/etc/agent-container/agent-container.env
```

The host-side file path is operator-managed; the container only sees env vars.

## Git push credential (outbound)

The whole ephemeral-container model rests on agents pushing autonomously and
**non-interactively** — no passphrase prompt, no host-key confirmation stall
(hard constraint #4; FR-001). Two push channels are supported and **layered**;
the operator selects by the remote's URL scheme, and a deployment may carry
either or both.

### SSH — the agent's own key pair (default)

Since **Feature 019** the container **generates its own** ed25519 key pair on
first boot at the conventional identity path `~/.ssh/id_ed25519`, and the
**private half never leaves it**. The operator's part is to take the **public**
half and register it wherever the agent must reach:

```bash
agent-container ssh-key show acme        # the line to paste into the forge
agent-container list --json              # same value, as agent_ssh_public_key
```

- **Captured, not supplied.** The tool reads the *public* key back through the
  runtime at deploy time and stores it in host state, so `ssh-key show` answers
  with the environment **stopped** or its host unreachable — which is exactly when
  an operator needs it.
- **Nothing wires it.** The conventional path is the whole mechanism: `git`,
  `ssh`, `scp` and `rsync` all find it with no configuration. `core.sshCommand` is
  **empty**, and its emptiness is asserted by a test — with a value there the key
  could be working through scaffolding this feature claims to have deleted.
- **`~/.ssh/config` is written once**, and write-once applies to the **block**,
  not the file: a config the agent wrote first still gains the tool's block, and
  the agent's own entries survive a recreate. The block is explicit —
  `IdentityFile`, `IdentitiesOnly yes`, `UserKnownHostsFile`,
  `StrictHostKeyChecking accept-new` (ssh's default is `ask`, which for a
  non-interactive agent means *fail*).
- **Rotation is explicit**: `agent-container ssh-key rotate <name>` replaces the
  key **without destroying the workspace**, and says the previous registration is
  now dead. `down --purge` also rotates it — by destroying the volume, which is
  the wrong tool when the work is worth keeping — and warns that it did.
- **Least privilege.** A per-container key registered as a repository deploy key
  authorises **one repository**. The removed `--push-key` was in practice handed
  the operator's *personal* key, so the container received everything that key
  authorised.
- **A first boot with an SSH `--repo` cannot clone** — the key cannot exist before
  the container does. That invocation starts the container anyway, prints the key,
  and exits with the *pending registration* code; see `docs/execution.md`.

**Four channels were removed**, each refusing with an explanation rather than a
bare "no such option" — the operator who used them had a reason, and it is now
served without a private key on their disk:

| Removed | Replacement |
|---|---|
| `up --push-key` / `redeploy --push-key` | `ssh-key show`, then register the public half |
| `SSH_PUSH_KEY_B64` (env-file parity) | as above — there is no private key to carry |
| declarative `target: push_key` | as above; a declared `push_key` is **refused**, not ignored |
| `clone_credential_precheck` | the two-phase clone (FR-013) — the premise inverted |

`--known-hosts` / `PUSH_KNOWN_HOSTS` **stay**: they verify the **forge**, which is
the opposite direction and public data.

Any agent SSH private key staged by a pre-019 release is **deleted on the next
deploy, loudly** — `--purge` never removed that file, so a release that merely
stopped writing it would leave the exposure on every machine that used the flag.

### HTTPS + `GH_TOKEN` (alternative)

The original channel, retained. The entrypoint configures a git credential
helper that returns `$GH_TOKEN` from process env on demand, **scoped to
`https://github.com`** so the token is never offered to any other host:

```sh
git config --global credential.https://github.com.helper \
  '!f() { echo "username=x-access-token"; echo "password=$GH_TOKEN"; }; f'
```

The URL scope is a deliberate safeguard: a global `credential.helper` would hand `$GH_TOKEN` to git for any HTTPS host it authenticates against, so an agent tricked into fetching `https://attacker.example/repo` would leak the token. No global helper is set, so non-GitHub hosts get no credential at all.

The token stays in process memory; it is **not** written to `~/.git-credentials` or any file in the container's writable layer.

GitHub's HTTPS endpoint accepts `x-access-token` as the username for any PAT.

## SSH access (host key + authorized keys)

The container is **rootless**: sshd runs as the `dev` user on the unprivileged
port **2222** (the operator-facing host port — the hashed `2200 +` value — is
unchanged; the CLI publishes `<hostport>:2222`). The whole SSH identity —
`authorized_keys` plus the host key under `hostkeys/` — lives on a dedicated
per-container `-ssh` volume mounted at `~/.ssh` and **persists across
`down`/`up`**. Inject your key **once**; a recreate keeps the same host key, so
clients never see `REMOTE HOST IDENTIFICATION HAS CHANGED`.

Nothing SSH-related is baked into the image. Three injection channels feed the
`~/.ssh` volume, and all are installed by the entrypoint before sshd starts:

| Channel | What it takes | When it applies |
|---------|---------------|-----------------|
| **Env-file** | `SSH_AUTHORIZED_KEYS` (newline-separated public keys) | At boot, from the same `.env` / `EnvironmentFile=` channel as the other credentials — the natural fit for the Quadlet path. |
| **`up --authorized-key FILE`** | file paths (repeatable) | Delivered read-only; installed at boot before sshd starts. |
| **`agent-container keys <name> --authorized-key FILE`** | file paths | Injected into an **already-running** container (no recreate); sshd is reloaded in place. Streamed over stdin, never on argv. |

Every channel above carries **public** keys only.

### Secrets are delivered to the container, not described (Constitution IX)

A provider API key never appears in the compose file that describes a deployment, and
is never staged in a file for that description to reference. It is pushed **into the
already-running container over SSH — the container's own sshd**, which is why sshd
now runs in every mode including headless.

**Not over the container runtime's channel**, even though that is often SSH too. The
runtime's transport is whatever your context happens to be: `unix://` and `ssh://`
are fine, `tcp://` is cleartext. The tool can only *check* that channel; it cannot
provide it. Over the container's own sshd the transport is SSH by construction, and
the daemon never sees the value.

Both directions are established without the tool holding anything it minted:

| Direction | How | From |
|---|---|---|
| Is this the right container? | its host key, generated inside it, public half captured and pinned | 018 |
| May the tool log in? | an **operator-declared** identity the key collection authorises | 020 |

**You must declare the identity** — the tool will not generate one, because a
tool-minted private key is a standing credential granting entry to every environment
it deploys:

```yaml
# ~/.config/agent-container/settings.yaml
delivery_identity: ~/.ssh/id_automation
```

Put its **public** half in your key collection so environments admit it. Use a
dedicated file-based key, not an approval-gated agent key: delivery runs unattended
with `IdentitiesOnly=yes` and `IdentityAgent=none` precisely so an agent key can never
silently satisfy the authentication instead.

**With secrets declared and no identity, the deploy refuses** — it does not fall back
to a weaker channel.

**The container decides where credentials belong, not the CLI.** Delivery invokes
`agent-container-receive-secret <kind>/<name>` over SSH with the value on stdin; that
script — root-owned 0755, so the agent cannot rewrite it — validates the ref and
stores the value. Without that seam the CLI would have to know in-container paths, and
every change to them would be a change to the deployment side too.

Values land in `/run/agent-container-secrets`, created **dev-owned 0700 in the image**,
at mode 0400. Two paths were rejected: `/run/agent-container` is the runtime's own
root-owned mount point for compose configs and delivery arrives as `dev` with no sudo;
and `/dev/shm`, used by an earlier version, is shared and world-writable, so a 0700
subdir there still sits in a namespace every other process in the container uses.

**Credentials PERSIST, one volume each.** A container whose credentials died with it
could not survive a reboot, a daemon restart, or `restart: unless-stopped` — nothing
would be present to re-deliver them. So each credential gets its own volume:

```
agent-container-<name>-cred-apikey-anthropic   ->  …/apikey/anthropic/value
```

**Revoke through the CLI:**

```sh
agent-container creds ls acme                        # what it holds, and whether config agrees
agent-container creds rm acme apikey/anthropic       # revoke one
agent-container creds rm acme --all
```

`creds rm` does **both halves**: it deletes the value inside the **running**
environment (so revocation takes effect now, without a recreate) and drops the volume
(so it does not come back on restart). If the credential is still declared in your
config it says so — otherwise the next deploy would silently put it back and the
revocation would look like it had failed.

`docker volume rm agent-container-acme-cred-apikey-anthropic` also works, and the
naming is deliberate so it can. But it cannot take effect while the container is
running, because the volume is in use. Prefer `creds rm`.

`creds ls` reads the **volumes**, not the config, because the two can differ — a
credential still held but no longer declared is exactly what you need to see.
`--purge` and `wipe` find these volumes by prefix, so teardown still removes
everything.

**Persistence is only safe because every deploy reconciles.** A volume outlives the
container, so without pruning, a credential you stopped declaring would still be
mounted — the config would say it was gone while the container still held it, which is
exactly the bug Feature 020 removed from `authorized_keys`. Each deploy removes the
volume of any credential it no longer names, so **the declaration stays the
authority**. Stop declaring a key and it is gone on the next deploy.

These volumes are deliberately **not** part of the fixed ten-volume identity contract:
they are dynamic, one per declared credential, so they are addressed by prefix instead.


The container waits for delivery before consuming credentials, but **only when the
tool says to expect it**, so a deployment declaring no secrets is unaffected. The
completion sentinel is written last, after every value lands — releasing the wait
early would hand the container a partial set that looks, from inside, exactly like a
completed delivery.

**Two clocks, and they must not be collapsed into one.** The container's sentinel
wait is **90 s**, and it starts when the entrypoint reaches that point — that is,
*after* the container is running. The tool's own wait covers everything **before**
that, and a deploy may include an **image build**: minutes, not seconds. It is
therefore a separate, longer budget, named `BUILD_WAIT_TIMEOUT` (30 minutes) and
overridable per run:

```bash
AGENT_CONTAINER_BUILD_TIMEOUT=3600 agent-container up acme
```

Bounding the whole wait by the container's 90 s was a real defect, and its failure
mode is the one worth remembering: a deploy that rebuilt the image exhausted the
wait *before the container existed*, the delivery thread gave up, the container
waited its own 90 s and continued **without the pushed secrets** — and the agent
then reported "no API key" for a credential that had been discovered, staged, and
never sent. Measured; a rebuild alone was enough, so a **first** deploy with
credentials was the likeliest case to hit it. The two clocks now start together
rather than one inside the other.

### Claude Code: API key or OAuth token (`claude_auth`)

Claude Code accepts two credentials and they are **not** interchangeable:

| credential file | how it reaches Claude | what it is |
|---|---|---|
| `<name>.anthropic.key` | `apiKeyHelper` — file-first, bytes never touch the `-claude` volume | an Anthropic API key |
| `<name>.claude-oauth.key` | `CLAUDE_CODE_OAUTH_TOKEN` in the environment | a Claude Code OAuth token, tied to a subscription |

Declare which one in `settings.yaml`:

```yaml
claude_auth: oauth      # or: api-key
```

**Exactly one is wired.** Claude itself refuses to be told twice —
*"Both apiKeyHelper and ANTHROPIC_API_KEY set · auth may not work as expected"* —
so the unchosen credential is delivered to its volume but never exported, and the
entrypoint says which it skipped and why.

**Undeclared is a third state, not a default.** With only one credential present
that one is used; the setting exists for when both are, where guessing would pick
one silently and leave the operator debugging the wrong half.

### The key collection — declare devices once (Feature 020)

An `authorized_keys` file at either config level is auto-injected into every
environment the tool creates, with no per-deployment flag:

| Level | Path |
|---|---|
| Project | `<project root>/.agent-container/authorized_keys` |
| User | `~/.config/agent-container/authorized_keys` |

Plain OpenSSH `authorized_keys` format, so enrolling a device is
`cat ~/.ssh/id_ed25519.pub >> ~/.config/agent-container/authorized_keys`. No tool
command needs to have written the file.

**The project file REPLACES the user file entirely** — it is not merged per key. A
collection is one value, so a project can *narrow* the set and not merely widen it;
a client repository must not inherit an operator's personal phone.

**Three states, kept distinct** (Constitution VIII):

| State | Behaviour |
|---|---|
| No file at either level | Undeclared. No auto-injection — exactly today's behaviour. |
| File exists, no entries | **Declared empty**: admits nobody. Honoured, and **warned about**. |
| File with entries | Those keys are admitted. |

Declared-empty is warned about and undeclared is silent, and that asymmetry is
deliberate: a hand-edited file can be truncated by accident, and where there is no
file there is nothing to truncate.

**`--authorized-key` is now PER DEPLOYMENT.** It used to be sticky: inject once and
the key stayed on the volume forever. It no longer does — pass it on every recreate,
or put the key in the collection and never pass it again. This is the same change as
"removal revokes", seen from the other side: a key that outlived every later
declaration is exactly what made removal impossible.

**Removal revokes.** The container rewrites a delimited region of its
`authorized_keys` on every boot, so a key removed from the collection is gone after
a recreate. Content *outside* that region — anything you added by hand inside the
environment — is preserved byte-for-byte. The tool removes what it wrote and
nothing else.

**The two managed blocks have OPPOSITE update rules**, which is worth knowing before
editing either. The `authorized_keys` region is **replaced every boot** (a region
never rewritten could not revoke). The `~/.ssh/config` block is **write-once** (an
agent's own settings must survive). Both carry `# BEGIN agent-container` markers, and
both say in-line which they are.

Inspect and grant:

```sh
agent-container keys show <name>    # projected vs observed, and whether they agree
agent-container keys ls             # every environment on a host
agent-container keys add <name> --authorized-key k.pub   # until the next recreate
```

`keys show` prints both what the collection *says* and what the environment
*actually holds*, because answering from the collection alone would compare a
projection with itself. A stopped or unreachable environment reads `undetermined`,
never "empty" — "nobody is authorised" and "we did not look" are different answers.

**A `keys add` grant lasts only until the next recreate.** The tool does not create
access it cannot withdraw; to make a key permanent, put it in the collection.

`start` resumes and does not re-apply the collection, so if the collection changed
it **warns** and names `redeploy`. Without that warning the environment would come
back admitting its old set while looking freshly configured.

**A malformed entry, or a PRIVATE key, refuses the deploy before anything is
created** — naming the file and line. A key that silently fails to admit is a
lockout discovered from the device that cannot fix it.

### The host key is captured, not supplied (Feature 018)

The container **generates its own** ed25519 host key on the persisted `~/.ssh`
volume and it **never leaves**. Identity is therefore stable across `down`/`up`
exactly as before — only `down --purge` changes it.

At every deploy the tool reads the **public** half through the container runtime and
pins it in `$XDG_STATE_HOME/agent-container/<host>/known_hosts`; `attach` verifies
against that file and **refuses** a mismatch.

**Three channels were REMOVED**, as a breaking change:

| Removed | Why |
|---|---|
| `up --host-key` | staged a plaintext **private** key at mode 0644 under the state dir, which `--purge` did not delete |
| `keys --host-key` | installed a **private** key into a live container |
| `SSH_HOST_ED25519_KEY_B64` | put a base64 **private** key in an env file |
| `target: host_key` in `.agent-container/` | the declarative form of the same thing — now **refused**, not ignored |

All of them cost a private key on your disk and bought **nothing**, because nothing
verified against it: their only realised effect was a stable identity, which
in-container generation already provides. Using one now fails with a message saying
so. An upgrade **deletes** any `<state>/<host>/<name>.host_key` left behind and tells
you it did — treat that key as exposed if copies exist elsewhere.

The mode was not fixable in place, which is why removal was the answer: compose
exposes the source file's mode into the container, `dev`'s uid need not match the host
uid that ran `up`, and `mode:` on a config reference was measured to be **ignored** in
favour of the source's mode. A 0600 staged key simply crash-looped the entrypoint.

### Security notes

- **The private host key at rest** lives only in operator-controlled places: the
  operator-managed env-file (base64) or the operator's own key file passed to
  `up`/`keys`. It is **never** baked into the image and **never** placed on
  argv (`keys` streams it over stdin; the entrypoint reads it from a bind-mount
  or env var). Inside the container it lands 0600 on the dev-owned `~/.ssh`
  volume — same storage-access trust boundary as the OAuth credential volumes
  below.
- **`authorized_keys` are public** — no secrecy requirement; they are only
  deduped so repeated boots and overlapping sources don't accumulate duplicates.
- **ed25519-only.** The host key is validated at boot (`ssh-keygen -y`); an
  invalid or encrypted key fails fast rather than as an opaque sshd error.

## Model/API credentials — file-first delivery (H1)

An agent that cannot reach its model cannot work at all (US2). The tool delivers
each agent's model/API credential **as a file**, on **its own volume**, one per
credential (FR-012a): `/run/agent-container-secrets/apikey/<provider>/value`.

It **persists**, deliberately — a container whose credentials died with it could not
survive a reboot or a daemon restart, since nothing would be there to re-deliver them.
Earlier versions of this document said the injected credential was "ALWAYS ephemeral"
(FR-012); that was a misreading and is reversed. **What FR-012 was protecting still
holds**: the credential is never written onto a per-**agent** volume (`-claude`,
`-codex`, `-pi`). That is the **H1 rule** — some agents' native auth form is a file on
their home volume, so a non-interactive `login` would persist it *there*, mixing
tool-injected material with an operator's own stored authorization. The entrypoint
**redirects that agent's home** instead.

### Convention-discovered key files (no flags)

Drop a per-provider key file under `~/.config/agent-container/`; `up`/`redeploy`
discover and stage it automatically — one file per provider:

```
~/.config/agent-container/<name>.<provider>.key
#   <provider> ∈ anthropic | openai | …   (lower-case)
```

**The provider name IS the environment variable**, derived rather than enumerated:
`<provider>` is upper-cased, `-` becomes `_`, and `_API_KEY` is appended — so
`acme.anthropic.key` exports `ANTHROPIC_API_KEY`, and `acme.google.key` exports
`GOOGLE_API_KEY` with nothing to add anywhere. This replaced a hardcoded pair
(anthropic, openai): every other provider's key was delivered to its volume and
then silently never exported, which for a multi-provider agent like `pi` or
`opencode` meant a credential the operator could see on disk and the agent could
not see at all.

**One provider is mapped explicitly, and deliberately:** `claude-oauth` exports
`CLAUDE_CODE_OAUTH_TOKEN`, not `CLAUDE_OAUTH_API_KEY`. A subscription token is not
an API key, and bending it into the naming rule would produce a variable Claude
Code does not read — the kind of nearly-true thing that costs an afternoon.

**User level only** (Feature 011, FR-001f). There is deliberately no project-local
equivalent: `.agent-container/` travels with the repository, and the repo holds a
**locator, never a value** — so a key placed there would be staged by `git add`.
To reference a credential *from* the repo, declare a locator source
(`file`/`keychain`/`command`/`onepassword`/`bitwarden`) in the spec instead.

### Per-agent wiring (all ephemeral)

| Agent | Tool-injected default (**ephemeral**) | Operator stored-auth (volume) |
|-------|----------------------------------------|-------------------------------|
| **Claude Code** | an `apiKeyHelper` is written into the fresh canonical `settings.json` that `cat`s the injected key at `INJECT_APIKEY_DIR/anthropic`; the `~/.claude` volume never receives the key | interactive `/login` OAuth persists on `~/.claude` |
| **Codex** | `CODEX_HOME` is redirected to an ephemeral `/run` dir + `codex login --with-api-key` reads the injected file on **stdin** (or `OPENAI_API_KEY` in the in-container env); the `-codex` volume is never written | interactive `codex login` persists on `~/.codex` |
| **pi-coding-agent** | `PI_CODING_AGENT_DIR` is redirected to an ephemeral `/run` dir (or the provider key in the in-container env); the `-pi` volume is never written | interactive `/login` persists on `~/.pi` |
| **opencode** | The provider key is delivered **in the in-container env only** — `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, read from the ephemeral injected file. **No `$HOME`/config redirect**, and none should be added: the redirect exists for Codex/pi purely to keep an injected key out of their on-volume auth store, and opencode (verified by running it) never writes an env-supplied key to `~/.local/share/opencode/auth.json`. Env delivery alone is strictly *less* exposure here | interactive `opencode auth login` persists on `~/.local/share/opencode` |

A non-interactive `login` that writes the **persistent** per-agent volume is
**not** a permitted tool default (SC-004). On-volume `auth.json` arises **only**
from an operator's **interactive** login (their own action on their own
credential — the documented FR-012 exception). Env/`.env` delivery of these keys
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, provider keys) remains supported as a
layered fallback for agents that read the credential from the environment.

## Canonical config vs runtime state

An agent's home mixes two kinds of data, split at **file granularity** by a
per-agent **canonical manifest** (US3):

- **Canonical config** — operator-owned, non-secret settings, project guidance,
  and tool/MCP definitions. Delivered **fresh on each deploy** to
  `INJECT_CONFIG_DIR` and copied onto the volume every boot, so a local edit
  propagates on the next `up`/`redeploy` (FR-007).

  **The manifest is exact, per agent — these directories and these filenames and
  no others:**

  | Agent | Home dir | Canonical filenames |
  |---|---|---|
  | `claude` | `~/.claude` | `settings.json`, `CLAUDE.md`, `mcp.json`, `*.mcp.json` |
  | `codex` | `~/.codex` | `config.toml`, `AGENTS.md` |
  | `pi` | `~/.pi/agent` | `models.json`, `settings.json` |

  **`~/.pi/agent`, not `~/.pi`** — pi keeps its configuration in `getAgentDir()`,
  one level below its home volume. The manifest previously pointed at `~/.pi` and
  named `config.json` / `config.toml` / `config.yaml` / `config.yml`, none of which
  pi reads: a file placed by the convention landed at `~/.pi/<name>` and was
  ignored, so canonical config delivery **could never work for pi at all**. It
  failed silently, because delivering a file nobody reads looks exactly like
  delivering a file.

  `models.json` declares custom providers; `settings.json` holds the settings,
  including the model default that a headless `pi -p` depends on (it takes no
  `--model`). `auth.json` and `trust.json` sit in the same directory and are
  deliberately **absent** from the manifest: the first is a credential store and
  canonical config is non-secret by definition (FR-007), the second is runtime
  state (FR-008).
- **Runtime state** — history, caches, learned state, and interactive OAuth
  credentials. **Persists** on the per-agent volume across recreation; the fresh
  canonical copy overwrites only the manifest's files and leaves everything else
  untouched (FR-008), so neither clobbers the other.

Discovery mirrors the `.env`/sidecar convention (project-local first):

```
.agent-container/<name>.config/…   →  ~/.config/agent-container/<name>.config/…
```

### First-run state is SEEDED in-container, not delivered (Feature 003 boundary)

An agent that has never run shows its onboarding flow, and a credentialed agent
showing a setup wizard is indistinguishable — to the operator attaching — from an
agent that received no credential at all. So the entrypoint seeds the minimum
first-run state at boot: for Claude Code, `hasCompletedOnboarding`,
`hasTrustDialogAccepted`, and the `customApiKeyResponses.approved` entry for the
key actually injected.

**Why this does not contradict FR-008.** That requirement governs what the tool
*delivers from the host* — runtime state is never shipped onto a volume, and it
still isn't. This is different in kind: the state is **synthesised inside the
container at boot**, from a decision the operator already made by supplying the
credential. Nothing is read from the host, nothing new crosses the boundary, and
the file stays the agent's own.

Two properties keep it honest:

- **Merged, never overwritten.** An existing `~/.claude.json` keeps every key it
  has; only absent keys are filled in. An operator's interactive login, MCP
  approvals, and history survive a redeploy.
- **It approves exactly the key that was injected**, identified by that key's own
  trailing characters. It cannot pre-approve a credential the container was not
  given, so it grants no access the deployment did not already carry.

If seeding fails the entrypoint says so and continues — the agent then shows its
first-run prompts, which is the pre-existing behaviour and not a broken container.

**Secret-bearing config (FR-009):** a config file that *carries* a secret (e.g. an
MCP definition embedding a token) is classified and delivered **as a secret**
(ephemeral), never as persistable canonical config. Feature 006 (agent-as-code)
formalizes the whole-directory model on top of this thin manifest.

## Required prerequisites

1. **Create a GitHub PAT.** Settings → Developer settings → Personal access tokens.
   - Scope: `repo` (push/pull).
   - Optional: `workflow` if agents need to modify GH Actions workflow files.
   - Set an explicit expiration (90 days is a reasonable default).
2. **Copy and fill the template:**
   ```bash
   cp .env.example .env
   chmod 0600 .env
   $EDITOR .env
   ```
3. **Wire into the launcher:** `--env-file .env` (local) or `EnvironmentFile=` (VPS Quadlet unit).

## Restart behavior

- `.env` lives on the host; the container reloads it on every launch.
- No re-supply needed across container restarts — only when you rotate the PAT.

## Revocation

1. Revoke the PAT on GitHub. Immediate effect on any new push attempt.
2. Update `.env` with a new PAT.
3. Restart the container so the new value is picked up.

## Security trade-offs (acknowledged)

| Concern                                  | Status                    | Notes                                                                                                   |
|------------------------------------------|---------------------------|---------------------------------------------------------------------------------------------------------|
| Token in `docker inspect`'s env section  | **Accepted**              | Inherent to env-var mechanisms. Restrict who can talk to the local docker socket / VPS podman storage.   |
| Token in `/proc/<pid>/environ`           | **Accepted**              | Restrict who can SSH into the container.                                                                |
| Token via `git config --list`            | Mitigated                 | Helper is a shell function, not a stored value; `git config --list` only shows the helper line.          |
| Token in image layers                    | Not possible              | `.env` is injected at runtime, not built in.                                                            |
| Token in container logs                  | Operator responsibility   | Don't `echo $GH_TOKEN`. Entrypoint scripts avoid logging env contents.                                  |
| Long-lived broad-scope PAT               | Mitigated by hygiene      | Use `repo`-scoped PATs with explicit expiration. Rotate.                                                |
| Agent OAuth credential on a named volume | **Accepted**              | Interactive `claude`/`codex`/`pi`/`opencode` login persists to a per-container volume (inside the Lima VM on macOS). Restrict access to the runtime's volume storage. `down --purge` deletes it. |
| Tool-injected API-key file               | **Eliminated by design**  | Delivered under `/run/agent-container/…` (ephemeral); never copied to a volume (FR-012). Vanishes with the container; the operator's local copy is the sole durable copy (SC-004). |
| Agent SSH **private** key on the operator's disk | **Eliminated by design** (019) | The tool has no channel that accepts one. The key is generated in the container and never leaves it; only the public half is read back. |
| Agent SSH private key on a persisted volume | **Accepted, deliberately** (019) | It must outlive a recreate or every recreate invalidates the operator's registration. `--purge` (or `ssh-key rotate`) is the revocation boundary, and both say so. Restrict access to the runtime's volume storage. |

If hardening the HTTPS path is needed later, the upgrade path is: switch `GH_TOKEN` to a compose `secrets:` block (or `podman secret` on the VPS), keep `.env` for non-secret config, and read `/run/secrets/gh-token` in the entrypoint instead of `$GH_TOKEN`. One-line change in the helper. (The agent's SSH key is not affected — it is generated in the container and never travels.)

### Agent provider auth: three layered options

Model/API credentials have three layered delivery paths; pick per agent:

1. **File-first injection (default)** — a convention-discovered per-provider key
   file (or a provider-key env var), delivered **ephemerally** (see
   *Model/API credentials — file-first delivery* above). Rotates by a local edit +
   `redeploy`; never persisted by the tool.
2. **Interactive login** — especially for Claude/Codex **subscription** accounts,
   `claude` → `/login`, `codex login` inside the container. The credential lands
   on that container's persistent `~/.claude` / `~/.codex` / `~/.pi` volume and
   the agent auto-refreshes it; per-container volumes give per-account isolation.
   This on-volume persistence is the operator's own action — the documented
   FR-012 exception.
3. **Env / `.env`** — `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / provider keys as a
   layered fallback for agents that read the credential from the environment.

Git identity (`GIT_USER_NAME` / `GIT_USER_EMAIL`) is always **required**. A push
credential is required for autonomous push — either the container's own SSH key
registered on the remote (default) or `GH_TOKEN` (HTTPS alternative).

## Out of scope (deferred)

- **Per-remote** credential routing (a different push credential per git remote).
  Per-**repo** scoping is supported, and is now the default shape: register the
  container's own key (`ssh-key show`) as a deploy key on one repository.
- External secret managers (Vault, 1Password, AWS Secrets Manager).
- Encrypted-at-rest `.env` (e.g. `sops`, `age`) — operator can adopt later without changing the container contract.

> **Superseded:** earlier revisions listed "SSH-based git push — explicitly
> rejected for the MVP." Feature 003 makes an **ephemeral SSH deploy key the
> documented default**; HTTPS + `GH_TOKEN` is the retained alternative.

## Providers are not credentials (Feature 012)

Declaring `egress.allow` says **where an environment may go**. It does not say what authorises
it, and it never implies storing a key.

The two are neighbours in the same file, not a hierarchy — and the tool deliberately does **not**
infer one from the other:

- a provider can be reached **with no credential at all** (that is the defect Feature 012 exists to
  surface — `opencode`'s built-in default);
- a credential can exist for a provider that is not declared;
- no provider→credential mapping exists, and inventing one would false-positive on the first case.

So a credential failure names **the credential and its source**, never the `egress` declaration.
Blaming the provider list for a credential problem sends you to edit the one part that is correct.

Secret values still live where they always did: user level, or behind a locator. `.agent-container/`
travels with the repository and holds a locator, never a value — declaring a provider changes
nothing about that.
