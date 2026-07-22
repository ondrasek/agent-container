# Quickstart: Shell Integration (Feature 005)

Runnable validation scenarios, each mapped to Success Criteria in
[spec.md](./spec.md). Prereqs: a built image and a reachable host; for the eval
scenarios, a running container (`agent-container up acme`). The print/emit paths
themselves need no running container to *render* — only to *reach* one.

## Scenario A — Print the attach command, run it verbatim (US1, SC-001)

```bash
agent-container attach acme --print
# -> stdout: ssh dev@localhost -p 2206 -t tmux attach -t main
eval "$(agent-container attach acme --print)"     # or run the line directly
```

**Expected**: stdout is exactly the runnable ssh+tmux line and nothing else;
running it reaches the **same** session `agent-container attach acme` would.

## Scenario B — Byte-for-byte parity with execute (US3, SC-001)

```bash
printed="$(agent-container attach acme --print)"
# compare against what execute runs (captured in the unit/acceptance harness)
```

**Expected**: the printed command equals the argv the execute path runs — no
divergence (they render from the same ShellAction).

## Scenario C — SSH-config stanza (US1, SC-006)

```bash
agent-container attach acme --ssh-config >> ~/.ssh/config
ssh acme        # attaches via the appended Host stanza
```

**Expected**: a valid `Host acme` block is emitted; after appending, `ssh acme`
attaches — no hand-editing of address/port/user.

## Scenario D — Configure the shell to target a host (US2, SC-002)

```bash
eval "$(agent-container host env acme)"     # default: export DOCKER_CONTEXT=…
docker ps                                    # lists that host's containers, no wrapper
eval "$(agent-container host env --unset)"   # plain unset
docker ps                                    # back to the default target
```

**Expected**: after eval, the operator's own `docker` targets the host; the unset
form reverts. (`--endpoint` emits `DOCKER_HOST=ssh://dev@…` instead.)

## Scenario E — stdout is config-only; errors are eval-safe (SC-003/004)

```bash
agent-container attach acme --print 2>/dev/null   # stdout: only the command
agent-container host env does-not-exist ; echo "exit=$?"   # stdout empty, exit!=0
eval "$(agent-container host env does-not-exist)"          # runs nothing
```

**Expected**: in print mode stdout carries only shell-evaluable text; on any error
stdout is empty and the exit code is non-zero, so `eval $(…)` executes nothing.

## Scenario F — fish dialect (SC-002)

```fish
agent-container host env acme --shell fish   # set -x DOCKER_CONTEXT …
eval (agent-container host env acme --shell fish)
docker ps
```

**Expected**: fish-correct assignments (`set -x` / `set -e`), eval-safe in fish.

## Scenario G — No side effects from printing (SC-005)

```bash
a="$(agent-container attach acme --print)"; b="$(agent-container attach acme --print)"
[ "$a" = "$b" ] && echo identical
# nothing created/connected: no new container, context, or file
```

**Expected**: two prints are byte-identical; printing connects/creates/mutates
nothing (registry-only).

## Success signal

All scenarios pass: the printed attach command reaches the same session as execute
(byte-parity), an SSH-config stanza works by alias, `eval $(host env)` retargets the
operator's own `docker` and unset reverts, stdout is config-only with eval-safe
empty-on-error, fish output is correct, and printing has no side effects — matching
SC-001…SC-006.
