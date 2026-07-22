# Research: Shell Integration (Feature 005)

Decisions resolving the plan's unknowns. This feature **inherits** the identity/
addressing (001), attach/session semantics (004), and the host registry/runtime
targeting (001) — it *exposes* them as emittable configuration and does not
redefine them. All four `/speckit-clarify` decisions (Session 2026-07-22) are
folded in.

**Ground truth (verified in `bin/agent-container`):** `resolve_attach_target(name,
mode, …)` already resolves `(user, host, port, kind)`; `ssh_argv(user, host, port,
window)` builds the canonical `ssh … -t tmux attach -t main`; `driver_runtime_argv(host)`
maps a host record to `docker --context <ctx>` / `podman --connection <ctx>`; host
records carry `driver` (docker|podman|existing-ssh), `context`, and `address`.
`shlex` is not yet imported. So the facts a print needs already exist — this
feature renders them, adding a seam so print and execute share one definition.

---

## R1 — One computed action, two realizations (the print/execute seam)

**Decision**: Each print-capable operation computes a single structured
**`ShellAction`** — an ordered list of *env operations* (set `NAME=value` /
unset `NAME`), *command lines* (argv lists), and *comment lines* — from the
resolved connection facts. That one action is then **realized** either by
**rendering** it for a shell dialect (→ stdout) or by **executing** it (the
existing behavior). Print and execute consume the *same* action, so they cannot
diverge (FR-010).

**Rationale**: FR-010 (no drift) and FR-012 (backend-extensible) both require the
"what should run" to be separated from "how it is realized." A structured action
is the minimal thing that (a) renders deterministically per dialect, (b) is
byte-comparable against the executed argv in a test, and (c) later admits a new
realizer (e.g. an IaC emitter) without touching the compute layer.

**Alternatives rejected**: (a) per-verb string templates for the printed form —
drift-prone, and unprovable against the execute path; (b) separate `print_attach()`
/ `exec_attach()` functions — two sources, exactly the divergence FR-010 forbids;
(c) a full command-object framework — over-built for two surfaces (Constitution VI).

**Validation**: unit — the same `ShellAction` renders to POSIX/fish AND its command
line equals the argv `ssh_argv` produces (parity); acceptance — the printed attach
run verbatim reaches the same session.

---

## R2 — Eval-safe quoting: stdlib `shlex` for POSIX, dedicated quoters for fish and PowerShell

**Decision**: Each dialect quotes every value and argv token with rules for that
shell; no value or command token is ever emitted unquoted:
- **POSIX** — stdlib **`shlex.quote`**; assign `export NAME=<q>`, unset `unset NAME`.
- **fish** — a **dedicated fish quoter** (single-quoted; escape only `\` and `'`
  with a backslash); assign `set -x NAME <q>`, unset `set -e NAME`.
- **PowerShell (pwsh)** — a **dedicated pwsh quoter** (single-quoted; escape a
  literal `'` by **doubling** it `''`; single quotes suppress `$` expansion);
  assign `$env:NAME = <q>`, unset `Remove-Item Env:NAME` (tolerant if absent).

**Rationale**: `shlex.quote` is the correct stdlib (Constitution VI) POSIX quoter;
fish and PowerShell are not POSIX-compatible for quoting *or* assignment/unset, so
each needs its own small renderer — but the *action* is identical, only the
rendering differs. Doubling `''` is PowerShell's literal-single-quote rule and
blocks injection/expansion (FR-004).

**Alternatives rejected**: (a) shelling out to the target shell to quote — requires
that shell present on the host and is slow/fragile; (b) hand-rolled POSIX escaping —
reinvents `shlex` and invites injection bugs; (c) one quoter for all shells — wrong,
each shell mis-parses the others' escaping (POSIX `$'…'`, fish backslash, pwsh `''`).

**Validation**: unit — feed adversarial tokens (`a b`, `a;rm -rf ~`, `$(touch x)`,
`a'b"c`, `$env:x`, unicode) through each renderer and assert the rendered line, when
parsed by the target shell, yields the original token verbatim with no extra
words/side effects.

---

## R3 — `host env` target form (by driver) + endpoint fallback, registry-only

**Decision** (clarify Q1 + Q2): `host env <name>` emits, **by default**, the host's
**registered runtime reference** — docker → `DOCKER_CONTEXT=<ctx>`, podman →
`CONTAINER_CONNECTION=<ctx>` — reusing the exact connection the tool established
(mirrors `driver_runtime_argv`). `--endpoint` instead emits the **raw endpoint** —
docker → `DOCKER_HOST=ssh://<user>@<address>`, podman →
`CONTAINER_HOST=ssh://<user>@<address>` — a best-effort, context-free
reconstruction for portability. Output is derived **from the registry/state only —
no reachability probe, no connection** (clarify Q2): an **unknown/unregistered**
host emits nothing and exits non-zero; a registered-but-unreachable host still
emits (its unreachability surfaces later in the operator's own `docker`).

**Rationale**: the context-ref is authoritative — it reuses whatever connection the
tool built (including a forwarded socket), so parity is guaranteed and the emitted
line is short. The endpoint form is the escape hatch when the context is not
registered locally, at the cost that `ssh://user@address` may not replicate a
socket-forward (the documented tradeoff of the clarify decision). Registry-only
keeps print truly side-effect-free (FR-005) and instant.

**Alternatives rejected**: (a) endpoint-only (minikube-style DOCKER_HOST) — loses
the tool's exact connection setup; (b) probing reachability — a connection, breaking
FR-005 "no connect"; (c) docker-only (DOCKER_CONTEXT) — ignores podman hosts.

**Validation**: unit — docker host → `DOCKER_CONTEXT`; podman host →
`CONTAINER_CONNECTION`; `--endpoint` → `DOCKER_HOST`/`CONTAINER_HOST=ssh://…`;
unknown name → empty stdout + non-zero; no probe issued (no socket/network call).

---

## R4 — Stdout/stderr discipline + eval-safety on error

**Decision**: In print mode, **stdout carries only the shell-evaluable text**; every
human-readable message/hint/warning/error goes to **stderr**. The renderer **buffers**
the full output and writes it to stdout **only on complete success**; any failure
(`die`) writes to stderr and exits non-zero **having written nothing to stdout** —
so `eval $(…)` on an error runs nothing. A trailing newline terminates the emitted
block; nothing else touches stdout on the print path.

**Rationale**: FR-002/003 and SC-003/004 — the invariant that makes `eval $(…)` safe
is "stdout is config-or-empty, never partial." Buffer-then-write guarantees no
half-emitted line escapes when resolution fails midway.

**Alternatives rejected**: streaming to stdout as the action is built — a mid-build
failure would leave partial config on stdout, breaking eval-safety.

**Validation**: unit — every error path (unknown host, no state, invalid dialect)
leaves captured stdout empty and returns non-zero; success paths put zero non-config
bytes on stdout.

---

## R5 — Attach: print vs execute toggle (execute stays default)

**Decision**: `attach <name>` keeps **executing** by default (unchanged handover,
004). It gains **`--print`** (render the ssh+tmux `ShellAction` to stdout, do
nothing else) and **`--ssh-config`** (render an SSH-config `Host` stanza). Both
derive from the same connection descriptor the execute path uses. `--shell posix|
fish` selects the dialect for `--print`.

**Rationale**: the spec assumption — existing verbs keep their execute default and
gain opt-in print; the capability is the shared action, execute is pre-existing
(FR-009). This preserves current behavior and matches the `eval $(…)` idiom
(opt-in).

**Alternatives rejected**: making print the default for `attach` — a breaking change
to the canonical human path (004); a separate `show-attach` verb — redundant with a
flag on the verb that already owns attach.

**Validation**: unit — `attach --print` builds the same argv the execute path runs
(parity); acceptance — running the printed line reaches the same session.

---

## R6 — SSH-config `Host` stanza

**Decision**: `attach <name> --ssh-config` emits a valid `Host` stanza the operator
appends to `~/.ssh/config` to `ssh <alias>` later: `Host <name>` with `HostName`
(reachable address), `User`, `Port` (published port), `RequestTTY yes`, and
`RemoteCommand tmux attach -t main` so `ssh <name>` reproduces the attach. It is
printed to stdout (it is configuration), humans to stderr.

**Rationale**: FR-007 — the direct analog of `limactl show-ssh`'s config form; the
stanza is derived from the same descriptor, so alias/host/port/user never need
hand-editing (SC-006).

**Alternatives rejected**: emitting a bare `ssh` command only — misses the
paste-into-config workflow the spec calls out; a Match/Include file — heavier than
the single-stanza append the request describes.

**Validation**: unit — the stanza parses as a valid single `Host` block with the
resolved fields; acceptance — appending it and running `ssh <name>` attaches.

---

## R7 — Shell dialects shipped

**Decision** (clarify Q4 + later direction): ship **POSIX sh (default)**, **fish**,
and **PowerShell (pwsh)**. POSIX covers bash/zsh; fish and pwsh each get their own
renderer (fish `set -x`/`set -e`; pwsh `$env:NAME=…`/`Remove-Item Env:NAME`) and
quoter (R2). `--shell posix|fish|pwsh` selects; an unrecognized value is an error
(empty stdout + non-zero). csh and other dialects are **deferred** behind the same
selector seam (not built here). Note the eval idiom differs by shell — POSIX/fish
`eval $(…)` vs PowerShell `… | Invoke-Expression` (`iex`); the emitted text is a
valid fragment for the selected shell regardless.

**Rationale**: bash/zsh + fish + PowerShell cover the operator population across
Unix and Windows/cross-platform pwsh; the seam (R1) makes adding a dialect a new
renderer + quoter, no action-layer change. Keeping csh out holds scope (deferred).

**Alternatives rejected**: POSIX+fish only — excludes PowerShell operators (now
in scope by direction); all dialects now — csh/tcsh are niche and cost scope for
little reach.

**Validation**: unit — POSIX, fish, and pwsh renderers each produce eval-correct
output for the *same* action (POSIX/fish eval-safe under `eval`, pwsh under
`Invoke-Expression`); `--shell csh` → clear error, empty stdout, non-zero.
