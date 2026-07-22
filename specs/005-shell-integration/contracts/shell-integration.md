# Contract: Shell Integration (Feature 005)

Adds a **print mode** to the tool's attach path and a new **`host env`** emitter.
Only the net-new surface is specified; identity/addressing (001), attach/session
(004), and the host registry/runtime targeting (001) are inherited and unchanged —
this feature *exposes* them.

## CLI surface

| Command / flag | Meaning |
|----------------|---------|
| `attach <name> --print` | Emit the runnable `ssh … -t tmux attach -t main` command to **stdout only**; do not connect. Execute stays the default (no `--print`). |
| `attach <name> --ssh-config` | Emit a `~/.ssh/config` `Host <name>` stanza to stdout (append-and-`ssh <name>` later). |
| `attach <name> --shell posix\|fish\|pwsh` | Dialect for `--print` (default `posix`). |
| `host env <name>` | Emit env assignments that retarget the operator's `docker`/`podman` at host `<name>` (prints by default — it exists to be `eval`'d). |
| `host env <name> --endpoint` | Emit the **raw endpoint** form (`DOCKER_HOST`/`CONTAINER_HOST=ssh://…`) instead of the default context reference. |
| `host env --unset` | Takes **no name**. Emit a **plain unset** of **all** vars `host env` can set (`DOCKER_CONTEXT`, `DOCKER_HOST`, `CONTAINER_CONNECTION`, `CONTAINER_HOST`) — reverts to the shell/daemon default regardless of driver/form; no snapshot/restore. |
| (`host env` has **no execute mode**) | Emit-only by nature — a child process cannot set the parent shell's env; that is why it exists to be `eval`'d. Only operations with an execute path (e.g. `attach`) offer print-vs-execute (FR-009). |
| `host env <name> --shell posix\|fish\|pwsh` | Dialect for the emitted assignments (default `posix`). |

## Emitted formats

**Attach command** (`attach acme --print`, posix):

```sh
ssh dev@localhost -p 2206 -t tmux attach -t main
```

The command line is **byte-for-byte** the argv the execute path runs
(`ssh_argv(...)`), space-joined with `shlex.quote` on each token (FR-010).

**SSH-config stanza** (`attach acme --ssh-config`):

```sshconfig
Host acme
    HostName localhost
    User dev
    Port 2206
    RequestTTY yes
    RemoteCommand tmux attach -t main
```

**host env — default (context reference)**, by driver:

```sh
# docker host
export DOCKER_CONTEXT=agent-container-hz1
# podman host
export CONTAINER_CONNECTION=agent-container-hz1
```

**host env — `--endpoint` (raw endpoint, best-effort)**:

```sh
# registered context is itself an ssh:// URI -> used verbatim (user preserved,
# any password stripped for least exposure):
export DOCKER_HOST=ssh://ops@vps.example.com
# a named / socket-forwarded context -> address-only reconstruction (the
# operator's ~/.ssh/config supplies the user; this cannot reproduce a
# socket-forward, so the default context-ref form remains authoritative):
export DOCKER_HOST=ssh://vps.example.com
# podman uses CONTAINER_HOST identically.
```

The endpoint form is **best-effort** (clarify Q1): it faithfully reproduces a
target only when the registered context is an `ssh://user@host` URI. For a named
or socket-forwarded context it emits `ssh://<address>` (no user, no socket-forward)
— use the default context-reference form there. A password in an `ssh://` context
is **stripped** before emit (Constitution III).

**host env — fish** (`--shell fish`): `set -x DOCKER_CONTEXT agent-container-hz1`;
unset: `set -e DOCKER_CONTEXT`.

**host env — pwsh** (`--shell pwsh`, evaluated with `| Invoke-Expression`):

```powershell
$env:DOCKER_CONTEXT = 'agent-container-hz1'
# host env --unset (name-free) clears all four candidate vars:
Remove-Item Env:DOCKER_CONTEXT,Env:DOCKER_HOST,Env:CONTAINER_CONNECTION,Env:CONTAINER_HOST -ErrorAction SilentlyContinue
```

**attach — pwsh** (`attach acme --print --shell pwsh`): the same `ssh … -t tmux
attach -t main` command line, pwsh-quoted (single quotes, `''` doubling on a literal
quote).

**host env — `--unset` (posix)**, name-free, clears all four candidate vars:

```sh
unset DOCKER_CONTEXT DOCKER_HOST CONTAINER_CONNECTION CONTAINER_HOST
```

(fish: `set -e DOCKER_CONTEXT DOCKER_HOST CONTAINER_CONNECTION CONTAINER_HOST`; pwsh:
`Remove-Item Env:DOCKER_CONTEXT,Env:DOCKER_HOST,Env:CONTAINER_CONNECTION,Env:CONTAINER_HOST -ErrorAction SilentlyContinue`.)

## Stream & exit contract (the eval invariant)

| Rule | Contract |
|------|----------|
| stdout content | In print mode, **only** shell-evaluable text on stdout — zero non-config bytes (FR-001/002, SC-003). |
| humans | All messages/hints/warnings/errors go to **stderr**, never stdout (FR-002). |
| error → eval-safe | On **any** failure, **nothing** is written to stdout and the exit code is **non-zero** (FR-003, SC-004). Output is buffered and flushed only on complete success. |
| eval-safety | Every value/token is quoted for the target dialect (`shlex.quote` / fish quoter / pwsh `''`-doubling quoter) so a name/path/address cannot word-split, expand, or inject (FR-004) — under `eval $(…)` (POSIX/fish) or `Invoke-Expression` (pwsh). |
| no side effects | Printing creates/starts/connects/mutates nothing; **registry-only, no reachability probe**; two prints are identical (FR-005). |
| no secrets | **No** secret is ever emitted to stdout — only connection coordinates (Constitution III). |
| parity | The printed command is generated from the **same** `ShellAction`/descriptor the execute path uses; they cannot diverge (FR-010, SC-001). |

## Target-resolution contract

| Condition | Contract |
|-----------|----------|
| unknown/unregistered `<name>` (or, for attach, no such container) | empty stdout, clear stderr message, non-zero exit — `eval` runs nothing |
| registered-but-unreachable host | **still emits** (print does not probe, R3/clarify Q2); unreachability surfaces later in the operator's own `docker`/`ssh` |
| `--shell` unrecognized | empty stdout, stderr message, non-zero |
| `host env --unset` with nothing set | emits the `unset` line(s); harmless no-op on eval |

## Extensibility contract (FR-012)

The compute step yields a `ShellAction`; realization (render-posix / render-fish /
execute) is a separate step. Adding a realizer (e.g. a future IaC emitter) MUST NOT
require changing how an action is computed. **No IaC backend is built in this
feature** — only the seam that admits one.

## Documentation contract (FR-013)

Any change to the print/eval contract or the operations that expose it updates, in
the same change: `README.md`, `CLAUDE.md`, the relevant `docs/`, and this spec.
