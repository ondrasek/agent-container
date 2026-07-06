# Credential injection contract

## Mechanism

A single `.env` file. All container-side credentials and identity strings are loaded from it. Git push uses HTTPS authenticated with a GitHub Personal Access Token, not SSH.

This is the simplest mechanism that works under the operator's Lima + docker-cli setup without `docker swarm init`, and maps directly to `EnvironmentFile=` in a Podman Quadlet unit on the VPS.

## What's in `.env`

| Variable             | Purpose                                                                                                        |
|----------------------|----------------------------------------------------------------------------------------------------------------|
| `GH_TOKEN`           | GitHub Personal Access Token. Used by the git credential helper for HTTPS pushes to github.com.                |
| `GIT_USER_NAME`      | Becomes `user.name` in the container's `~/.gitconfig`.                                                          |
| `GIT_USER_EMAIL`     | Becomes `user.email` in `~/.gitconfig`.                                                                         |
| `ANTHROPIC_API_KEY`  | Claude Code authentication.                                                                                     |
| `OPENAI_API_KEY`     | Codex (`@openai/codex`) authentication.                                                                         |
| (other provider keys) | `pi-coding-agent` is multi-provider; add whichever provider keys you point pi at (e.g. `GOOGLE_API_KEY`).      |

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

## Git push contract

HTTPS, not SSH. The entrypoint configures a git credential helper that returns `$GH_TOKEN` from process env on demand, **scoped to `https://github.com`** so the token is never offered to any other host:

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
| Agent OAuth credential on a named volume | **Accepted**              | Interactive `claude`/`codex`/`pi` login persists to a per-container volume (inside the Lima VM on macOS). Restrict access to the runtime's volume storage. `down --purge` deletes it. |

If hardening is needed later, the upgrade path is: switch `GH_TOKEN` to a compose `secrets:` block (or `podman secret` on the VPS), keep `.env` for non-secret config, and read `/run/secrets/gh-token` in the entrypoint instead of `$GH_TOKEN`. One-line change in the helper.

### Agent provider auth: keys vs. interactive login

`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in `.env` are **optional**. The
recommended path — especially for Claude/Codex **subscription** accounts — is to
log in interactively inside the container (`claude` → `/login`, `codex login`).
Each container has its own persistent credential volume (`~/.claude`, `~/.codex`,
`~/.pi`), so you log in once and the agent auto-refreshes the token across
restarts; per-container volumes give per-account isolation. `GH_TOKEN` and git
identity remain **required** (git push is non-interactive by design).

## Out of scope (deferred)

- Per-repo / per-remote credential routing.
- External secret managers (Vault, 1Password, AWS Secrets Manager).
- SSH-based git push — explicitly rejected for the MVP.
- Encrypted-at-rest `.env` (e.g. `sops`, `age`) — operator can adopt later without changing the container contract.
