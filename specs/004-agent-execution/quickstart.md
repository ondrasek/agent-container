# Quickstart: Agent Execution & Session Management (Feature 004)

Runnable validation scenarios, each mapped to Success Criteria in
[spec.md](./spec.md). Prereqs: a built image (`agent-container build`) and a
reachable host. Scenarios needing a real model backend (the agent actually
*responding*) are **opt-in** (tokened) and never run in CI; the mechanics
(sessions, headless exit code, workspace modes, clone-on-start) are verifiable
without a real agent.

## Scenario A — Interactive: attach and drive the agent (US1, SC-001)

```bash
agent-container up acme --mode interactive --agent claude
agent-container attach acme          # lands in tmux 'main' with the agent window
# (tokened) issue a prompt to the agent and see it respond
```

**Expected**: within seconds, an interactive agent session in a persistent
terminal. With `--task "<t>"`, the agent begins that task without an attach (FR-003).

## Scenario B — Detach / reattach keeps the agent running (US2, SC-002/003)

```bash
agent-container attach acme          # start a long action, then disconnect (Ctrl-b d / close ssh)
agent-container list                 # confirm acme still running
agent-container attach acme          # reattach — same 'main' session, action still progressing
# from a second machine: agent-container attach acme  -> identical session
```

**Expected**: the session and in-progress work survive disconnect; reattach lands
on the same session from any machine.

## Scenario C — Reattach to a dead session is never silent (US2, SC-003, FR-008)

```bash
# end the session (agent exited / tmux kill-session), then:
agent-container attach acme
```

**Expected**: a clear "nothing running" report (or a freshly (re)started session) —
never a silent empty shell.

## Scenario D — Headless foreground (US3, SC-004/005)

```bash
agent-container up acme --mode headless --agent claude --task "run the tests" --foreground
echo "exit=$?"
```

**Expected**: output streams; control returns when the run finishes; the exit code
distinguishes success from failure; the container is not auto-restarted on success.

## Scenario E — Headless detached + retrieve result (US3, SC-004/005)

```bash
agent-container up beta --mode headless --agent claude --task "@task.md"
# control returns immediately; later:
agent-container logs beta            # streamed output retrievable
agent-container list                 # shows exited status/code
```

**Expected**: control returns at once; output and final result are retrievable
afterward; a successful run is not resurrected. A re-`up beta` on the exited
deployment reports the prior exit status/code (not a silent re-run) — use
`agent-container redeploy beta` to run the task again.

## Scenario F — Workspace persistence vs ephemeral (US4, SC-006)

```bash
agent-container up p --workspace persistent
# write a file into /workspace, then recreate:
agent-container down p && agent-container up p   # prior working copy still present
agent-container up e --workspace ephemeral --repo https://github.com/you/repo
# write a file, then teardown:
agent-container wipe e -y             # the workspace does not survive
```

**Expected**: persistent retains the working copy across recreation; ephemeral is
gone after teardown.

## Scenario G — Bind workspace: local honored, remote refused (US4, SC-007)

```bash
agent-container up b --workspace bind --workspace-dir "$PWD/work"   # local: edits appear on disk
agent-container up b --workspace bind --workspace-dir "$PWD/work" --host vps   # -> refused
```

**Expected**: a bind workspace edits the operator's local filesystem on a local
host, and is **refused with a clear message** on a non-local host.

## Scenario H — Clone-on-start populate + fail-fast (US4, SC-008)

```bash
# HTTPS (GH_TOKEN, always present):
agent-container up h1 --workspace ephemeral --repo https://github.com/you/repo   # /workspace populated on start
# SSH URL with a push key:
agent-container up h2 --workspace persistent --repo git@github.com:you/repo --push-key ~/pk
# SSH URL WITHOUT a push key -> fail fast:
agent-container up h3 --workspace ephemeral --repo git@github.com:you/repo
```

**Expected**: HTTPS/SSH-with-key clones populate `/workspace` on start; an SSH-URL
clone with no injected push key fails **before** starting an empty-workspace agent.

## Success signal

All scenarios pass: interactive sessions attach/detach/reattach (incl. dead-session
clarity), headless runs report a result and are not resurrected on success, the
three workspace modes behave per their durability, bind is local-only, and
clone-on-start populates (or fails fast) by URL scheme — matching SC-001…SC-008.

## Validation status

The mechanisms are covered at three tiers, all green:

- **Hermetic unit** (`bin/tests/test_execution.py`, `test_compose.py`,
  `test_command_construction.py`): the compose model (per-mode restart, workspace
  mount + conditional volume, mode/agent/clone env, task inject), `ExecSpec`
  validation incl. the `--foreground` guard, `resolve_workspace` (bind-on-remote
  refusal), clone-credential fail-fast, the foreground exit-code argv, the
  dead-session probe mapping, and the FR-016 mode×workspace independence matrix.
- **Entrypoint shell** (`bin/tests/test_entrypoint_execution.sh`): the mode branch
  (interactive agent-in-window seeded with the task / headless workload + exit
  code / no sshd in headless) and clone-on-start (HTTPS clone, SSH-no-key
  fail-fast, idempotent skip).
- **Acceptance, real Lima containers** (`bin/tests/test_acceptance.py`,
  `-m acceptance`): interactive agent launch (Scenario A), detach/reattach +
  dead-session signal (B/C), headless foreground exit code (D), workspace
  persistent/ephemeral (F), bind reflects the local dir (G), and clone-on-start
  SSH fail-fast (H). The agent actually **responding** (SC-001) and the
  headless-**success**-not-resurrected path need a real model key and remain the
  opt-in/tokened extension (never run in CI).
