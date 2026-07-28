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
   **tool-injected secret** (the outbound push key, an API-key file) lands under
   `/run/agent-container/…` — an ephemeral tmpfs-style path that **vanishes with
   the container** and is **never** copied onto a persistent per-container volume
   (least-exposure invariant **FR-012**). The CLI passes **paths, never secret
   values** (never on argv — FR-011), and never inlines a secret into the
   generated compose file.

**Least-exposure discipline** (Constitution III): no secret is baked into an
image layer (FR-010), placed on a process command line (FR-011), or left in a
host persistent volume by the tool (FR-012). The operator's local copy remains
the **sole durable copy**; rotating a secret is a local edit + `redeploy`
(FR-015). The one deliberate exception is the **inbound sshd host key**, which
persists on the `~/.ssh` volume **by design** so the container keeps a stable
identity — it is distinct from every outbound/ephemeral credential below (SC-008).

## What's in `.env`

| Variable             | Purpose                                                                                                        |
|----------------------|----------------------------------------------------------------------------------------------------------------|
| `GH_TOKEN`           | GitHub Personal Access Token. Used by the git credential helper for HTTPS pushes to github.com.                |
| `GIT_USER_NAME`      | Becomes `user.name` in the container's `~/.gitconfig`.                                                          |
| `GIT_USER_EMAIL`     | Becomes `user.email` in `~/.gitconfig`.                                                                         |
| `ANTHROPIC_API_KEY`  | Claude Code authentication (layered fallback; the file-first channel is preferred — see below).                 |
| `OPENAI_API_KEY`     | Codex (`@openai/codex`) authentication (layered fallback).                                                      |
| (other provider keys) | `pi-coding-agent` and `opencode` are multi-provider; add whichever provider keys you point them at (e.g. `GOOGLE_API_KEY`). |
| `SSH_PUSH_KEY_B64`   | base64 of an unencrypted **outbound** SSH push key (Feature 003). Ephemeral — consumed at boot, **never** persisted. Env-file parity for `up --push-key`. |
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

### SSH push (default)

An **outbound SSH deploy key** injected at runtime as an ephemeral secret. This
is the documented default — it matches the SSH-first design and needs no
long-lived token.

```bash
agent-container up acme --push-key ~/.ssh/agent_push_ed25519 \
                        --known-hosts ~/.ssh/known_hosts.github
```

- The key is validated (`validate_private_key`; encrypted keys are **rejected**)
  and its path (never its bytes) is threaded through; a **missing** file makes
  the deploy `die` before any container is created (FR-016).
- It is delivered to `INJECT_PUSH_KEY_PATH` = `/run/agent-container/push_ed25519_key`
  — **ephemeral** (FR-012). The entrypoint reads it **in place** and sets:

  ```sh
  git config --global core.sshCommand \
    "ssh -i <push-key> -o IdentitiesOnly=yes \
         -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=accept-new"
  ```

  `IdentitiesOnly=yes` stops SSH from offering any other key; the seeded
  `known_hosts` (from `--known-hosts` / `PUSH_KNOWN_HOSTS`) means the first push
  to the remote does not stall on unknown-host verification (FR-003).
- The push key is **never** written onto the `~/.ssh` volume, and is a **distinct
  credential from the inbound sshd host key** — different key, different role,
  never interchanged (FR-002 / SC-008). After teardown no copy survives on any
  volume; `~/.ssh/agent_push_ed25519` on the operator's machine is the sole
  durable copy (SC-004).
- **Env-file parity:** `SSH_PUSH_KEY_B64` (base64 private key) + `PUSH_KNOWN_HOSTS`
  deliver the same via the env channel — the natural fit for the Quadlet path.
- **Scoping (FR-004):** the default is a single user key; a **narrowly-scoped
  per-repository deploy key** is simply a narrower key passed to the same
  `--push-key` flag, limiting blast radius.

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
| **Env-file** | `SSH_AUTHORIZED_KEYS` (newline-separated public keys), `SSH_HOST_ED25519_KEY_B64` (base64 of an unencrypted ed25519 **private** host key) | At boot, from the same `.env` / `EnvironmentFile=` channel as the other credentials — the natural fit for the Quadlet path. |
| **`up --host-key FILE --authorized-key FILE`** | file paths (repeatable `--authorized-key`) | Bind-mounted read-only; installed at boot before sshd starts. |
| **`agent-container keys <name> --host-key FILE --authorized-key FILE`** | file paths | Injected into an **already-running** container (no recreate); sshd is reloaded in place. Secrets are streamed over stdin, never on argv. |

**Host-key precedence** (highest first): `up --host-key` bind-mount >
`SSH_HOST_ED25519_KEY_B64` env > the already-persisted key on the volume > a
freshly generated ed25519 key. Only the last two are auto-created; an
injected or persisted key is left untouched. **`authorized_keys`** is a
deduped union of the persisted file plus every injected source.

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
each agent's model/API credential **as a file by default** — and, crucially, the
tool-injected credential is **ALWAYS ephemeral** (FR-006 / FR-012): it lands under
`INJECT_APIKEY_DIR` = `/run/agent-container/apikeys/<provider>` and is **never**
written onto a per-agent volume by the tool. This is the **H1 rule**: because
some agents' native auth form is a file on their home volume, injecting a key by
running a non-interactive `login` would persist it — so instead the entrypoint
**redirects that agent's home** to an ephemeral `/run` dir for the injected mode.

### Convention-discovered key files (no flags)

Drop a per-provider key file under `~/.config/agent-container/`; `up`/`redeploy`
discover and stage it automatically — one file per provider:

```
~/.config/agent-container/<name>.<provider>.key
#   <provider> ∈ anthropic | openai | …   (lower-case)
```

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
  and tool/MCP definitions (e.g. `~/.claude/settings.json` + `CLAUDE.md`;
  `~/.codex/config.toml` + `AGENTS.md`; pi config). Delivered **fresh on each
  deploy** to `INJECT_CONFIG_DIR` and copied onto the volume every boot, so a
  local edit propagates on the next `up`/`redeploy` (FR-007).
- **Runtime state** — history, caches, learned state, and interactive OAuth
  credentials. **Persists** on the per-agent volume across recreation; the fresh
  canonical copy overwrites only the manifest's files and leaves everything else
  untouched (FR-008), so neither clobbers the other.

Discovery mirrors the `.env`/sidecar convention (project-local first):

```
.agent-container/<name>.config/…   →  ~/.config/agent-container/<name>.config/…
```

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
| Tool-injected push key / API-key file    | **Eliminated by design**  | Delivered under `/run/agent-container/…` (ephemeral); never copied to a volume (FR-012). Vanishes with the container; the operator's local copy is the sole durable copy (SC-004). |

If hardening the HTTPS path is needed later, the upgrade path is: switch `GH_TOKEN` to a compose `secrets:` block (or `podman secret` on the VPS), keep `.env` for non-secret config, and read `/run/secrets/gh-token` in the entrypoint instead of `$GH_TOKEN`. One-line change in the helper. (The SSH push key already rides the ephemeral-config channel.)

### Agent provider auth: three layered options

Model/API credentials have three layered delivery paths; pick per agent:

1. **File-first injection (default)** — a convention-discovered per-provider key
   file (or `SSH_PUSH_KEY_B64`-style env), delivered **ephemerally** (see
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
credential is required for autonomous push — either the SSH deploy key (default)
or `GH_TOKEN` (HTTPS alternative).

## Out of scope (deferred)

- **Per-remote** credential routing (a different push credential per git remote).
  Per-**repo** scoping is supported — a narrowly-scoped deploy key via `--push-key`.
- External secret managers (Vault, 1Password, AWS Secrets Manager).
- Encrypted-at-rest `.env` (e.g. `sops`, `age`) — operator can adopt later without changing the container contract.

> **Superseded:** earlier revisions listed "SSH-based git push — explicitly
> rejected for the MVP." Feature 003 makes an **ephemeral SSH deploy key the
> documented default**; HTTPS + `GH_TOKEN` is the retained alternative.
