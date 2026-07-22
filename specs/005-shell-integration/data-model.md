# Data Model: Shell Integration (Feature 005)

The model is **deploy-time / invocation-time only** — no persistent schema is
added (print stores nothing, FR-005). The entities are the **connection
descriptor** (resolved facts), the **`ShellAction`** (the one definition print and
execute share), the **shell dialect** (renderer), and the **emit result / exit
discipline**. Inherited unchanged: identity/addressing (001), attach/session (004),
the host registry + runtime targeting (001).

## Connection descriptor

The resolved, **non-secret** facts a container/host exposes — the single source
from which both the printed command and the executed command are rendered. Read
from registry/state; **no connection is made** to produce it.

| Field | Meaning | Source |
|-------|---------|--------|
| `user` | SSH login (`dev`) | attach resolution (004) |
| `address` | the host's reachable address (localhost / public) | host record `address` (001) |
| `port` | the container's published port | per-host `<host>/<name>.port` state (001) |
| `session` | canonical tmux session (`main`) | attach/session (004) |
| `driver` | `docker` \| `podman` (\| `existing-ssh`, attach-only) | host record (001) |
| `context_ref` | the registered context/connection name | host record `context` (001) |
| `endpoint` | best-effort raw URI `ssh://<user>@<address>` | derived (R3) |

**Invariant (Constitution III)**: the descriptor carries **only** connection
coordinates. It MUST NOT contain, and no renderer may emit, any secret — push key
or its path, `GH_TOKEN`/API keys, `known_hosts` content, or auth material. Secrets
are out of the descriptor by construction.

## ShellAction

The structured, dialect-agnostic representation of what an operation would do — the
**one definition** rendered to stdout (print) or executed (execute), so the two
never drift (FR-010).

| Part | Shape | Notes |
|------|-------|-------|
| env ops | ordered list of `set(NAME, value)` / `unset(NAME)` | rendered per dialect (`export NAME=…`/`unset NAME`; fish `set -x`/`set -e`) |
| command lines | ordered list of argv lists (e.g. the `ssh … tmux attach` argv) | quoted per dialect; the command line for attach equals `ssh_argv(...)` (parity) |
| comment lines | ordered human-readable notes | rendered as `# …`; optional, informational only |

Rendering rules:

- **POSIX** (default): values/tokens via `shlex.quote`; `export NAME=<q>` / `unset
  NAME`; command lines as space-joined quoted argv; comments as `# …`.
- **fish**: `set -x NAME <q>` / `set -e NAME`; fish-quoted values/tokens; comments
  as `# …`.
- **pwsh** (PowerShell): `$env:NAME = <q>` / `Remove-Item Env:NAME` (tolerant if
  absent); pwsh-quoted values/tokens (single-quote, doubling a literal `'`);
  command lines as space-joined quoted argv; comments as `# …`.
- A rendered block ends with a single trailing newline and contains **only** the
  rendered lines (no banner, no diagnostics — those are stderr).

## Shell dialect

Selected with `--shell` (default `posix`).

| Dialect | Assign | Unset | Quoting | Eval idiom |
|---------|--------|-------|---------|------------|
| **posix** (default) | `export NAME=<q>` | `unset NAME` | stdlib `shlex.quote` | `eval $(…)` |
| **fish** | `set -x NAME <q>` | `set -e NAME` | dedicated fish quoter | `eval (…)` |
| **pwsh** | `$env:NAME = <q>` | `Remove-Item Env:NAME` | pwsh quoter (`''` doubling) | `… \| Invoke-Expression` |

An unrecognized dialect is an error → **empty stdout + non-zero** (never a partial
or wrong-dialect emit).

## Emitted surfaces (this feature)

| Surface | Trigger | ShellAction contents |
|---------|---------|----------------------|
| **attach command** | `attach <name> --print` | one command line = the `ssh … -t tmux attach -t main` argv (parity with execute) |
| **SSH-config stanza** | `attach <name> --ssh-config` | a `Host <name>` block (HostName/User/Port/RequestTTY/RemoteCommand) — printed, not eval-shaped |
| **host env (set)** | `host env <name>` | env op: set `DOCKER_CONTEXT`/`CONTAINER_CONNECTION` (default) or `DOCKER_HOST`/`CONTAINER_HOST` (`--endpoint`) |
| **host env (unset)** | `host env --unset` | env op(s): plain `unset` of the same var(s); no snapshot/restore |

## Emit result & exit discipline

| State | Trigger | Behavior |
|-------|---------|----------|
| **success** | descriptor resolved | render buffered, then written to stdout in full; exit 0; humans (if any) on stderr |
| **unknown target** | name not registered / no state / (attach) no container | **empty stdout**, clear stderr message, **non-zero** exit (`eval` runs nothing) |
| **bad dialect** | `--shell` value unrecognized | empty stdout, stderr message, non-zero |
| **resolution failure** | any error before the block is complete | nothing written to stdout (buffer discarded), stderr message, non-zero |
| **unset with nothing set** | `host env --unset` | harmless — emits the `unset` line(s); a no-op when the vars are unset |

**No side effects (FR-005)**: producing any of the above reads only local
registry/state; it creates, starts, connects, or mutates nothing, and two
consecutive prints are byte-identical.
