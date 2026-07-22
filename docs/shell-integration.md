# Shell integration — print/emit mode (Feature 005)

Instead of only *invoking* `ssh`/`tmux`/`docker` on your behalf, `agent-container`
can **emit shell-evaluable configuration** — a command line to run, or environment
assignments to set — so you can `eval $(agent-container …)`, alias it, script it,
or drop it into `~/.ssh/config`. Modeled on `limactl show-ssh`, `eval $(minikube
docker-env)`, and `docker context`. Executing directly stays the default where it
already existed (notably `attach`); this is host-side only — nothing about the
container changes.

## Print the attach command — `attach --print`

```bash
agent-container attach acme --print
# -> ssh dev@localhost -p 2206 -t tmux attach -t main
eval "$(agent-container attach acme --print)"     # or run/alias the line yourself
```

The printed command is **byte-for-byte what `attach` would execute** (they render
from one definition, so they can never drift). Running it in *your* shell means
your own ssh-agent / smartcard / `known_hosts` / `~/.ssh/config` handle the
connection — the invocation quirks the tool is hard-pressed to drive correctly in
every environment just work in your terminal.

## An SSH-config stanza — `attach --ssh-config`

```bash
agent-container attach acme --ssh-config >> ~/.ssh/config
ssh acme        # attaches via the appended Host stanza
```

Emits a `Host <name>` block (HostName / User / Port / `RequestTTY yes` /
`RemoteCommand tmux attach -t main`) so you connect by alias later — no hand-editing
of addresses/ports/users.

## Target a host with your own docker/podman — `host env`

```bash
eval "$(agent-container host env hz1)"     # export DOCKER_CONTEXT=agent-container-hz1
docker ps                                   # lists that host's containers, no wrapper
eval "$(agent-container host env --unset)"  # revert
```

- **Default** emits the host's **registered runtime reference** — docker
  `DOCKER_CONTEXT`, podman `CONTAINER_CONNECTION` — reusing the exact connection the
  tool established (including a socket-forward). This is the authoritative form.
- **`--endpoint`** emits the **raw endpoint** (`DOCKER_HOST` / `CONTAINER_HOST` =
  `ssh://…`) for portability where the registered context is not present. It is
  **best-effort**: it reproduces a working target only when the registered context
  is itself an `ssh://user@host` URI; for a named or socket-forwarded context it
  emits `ssh://<address>` (your `~/.ssh/config` supplies the user, and it cannot
  reproduce a socket-forward). Any password in an `ssh://` context is **stripped**.
- **`--unset`** takes no name and clears **all four** vars `host env` can set
  (`DOCKER_CONTEXT`, `DOCKER_HOST`, `CONTAINER_CONNECTION`, `CONTAINER_HOST`),
  reverting to your default — like `minikube docker-env --unset`.

`host env` is **print-only** by nature: a child process cannot change your parent
shell's environment (that is exactly why it exists to be `eval`'d).

## Shell dialects — `--shell posix|fish|pwsh`

Default **posix** (bash/zsh). Also **fish** (`set -x` / `set -e`) and **PowerShell
/ pwsh** (`$env:NAME = '…'` / `Remove-Item Env:NAME`). PowerShell has no
`eval $(…)`; the idiom is `Invoke-Expression`:

```powershell
agent-container host env hz1 --shell pwsh | Invoke-Expression
```

Each dialect quotes with its own rules (POSIX via `shlex`; fish backslash-escaping;
pwsh `''`-doubling) so the emitted text is **eval-safe** against any name/path/
address — a value can never word-split, expand, or inject.

## The eval contract (why `eval $(…)` is safe)

- **stdout is config-only.** In print mode, stdout carries *only* the shell-evaluable
  text; every human-readable message goes to **stderr**.
- **Errors emit nothing.** On any failure (unknown host, bad `--shell`, …) stdout is
  **empty** and the exit code is **non-zero**, so `eval $(…)` runs nothing.
- **No side effects.** Printing reads only the local registry/state — it never
  connects, creates, or mutates anything, and two prints are byte-identical.
- **No secrets.** Only connection coordinates are ever emitted — never a push key,
  token, `known_hosts`, or password (Constitution III).

## Design note (extensibility)

Each print-capable operation computes one structured **`ShellAction`** (env
set/unset ops + command lines), then either renders it for a dialect or executes it.
That "compute the action, then choose how to realize it" seam is deliberately
backend-extensible: a future emitter (e.g. infrastructure-as-code) could realize the
same action differently. No such backend is built in this feature — only the seam
that admits one. See [`specs/005-shell-integration/`](../specs/005-shell-integration/).
