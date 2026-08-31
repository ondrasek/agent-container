# 01 — a real agent runs headless and writes to the workspace

The whole spec is [`.agent-container/environments.yaml`](.agent-container/environments.yaml).
Read it first; it is 25 lines and it is the entire sample.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
agent-container plan
agent-container apply
```

**Needs a model key only** — no repository, no forge token, no boundary.

## What it declares

| Field | Why it is there |
|---|---|
| `mode: headless` | the agent **is** the workload; the container exits with the agent's exit code |
| `agent: claude` | the primary agent — change this line to run `pi` |
| `workspace: persistent` | a named volume, so the result outlives the container |
| `task:` | the job, in the spec rather than on a command line |
| `credentials:` | a **locator** — the variable name, never the key |

## Checking it worked

The container exits when the agent does, so look at the volume rather than the
container:

```bash
agent-container runs ls sample01      # the run record: exit code, task, timing
docker run --rm -v agent-container-sample01-workspace:/w:ro alpine:3 cat /w/proof.txt
```

Use `podman` there if that is your runtime — `agent-container context` says which
one is in play, and `runtime:` in `settings.yaml` sets it.

**A run that reports success while `proof.txt` is absent is the interesting
failure**: the agent said it was done and wrote nothing.

## Re-running

`apply` is idempotent — a matching spec makes no changes, so a second `apply`
will *not* re-run the agent. To make it run again:

```bash
agent-container destroy && agent-container apply
```
