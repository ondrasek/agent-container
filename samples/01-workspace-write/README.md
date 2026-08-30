# 01 — a real agent runs and writes to the workspace

```bash
./run.sh claude     # or: ./run.sh pi
```

**Needs:** a model key only. No repository, no token, no boundary.

## What it proves

The whole stack at once, with a real model doing real work:

- a credential discovered by convention, delivered over the container's own sshd,
  landing on its own volume — and **resolved by the agent**;
- canonical config reaching the agent's home (for `pi`, which needs it);
- the agent **using its tools** to create a file;
- a completed run record with the task verbatim and exit code 0.

## How it is checked

It asserts a **side effect, never the model's prose**. An LLM's wording is not
deterministic; a file it was asked to write is. The token is random per run, so
the check cannot pass on a file left behind by an earlier run — the workspace
volume persists, which is exactly how that would happen.

The check reads the workspace **volume** from a throwaway container rather than
asking the agent's container: a headless container has already exited by then,
and starting it again would re-run the agent.

## Files

| File | Purpose |
|---|---|
| `task.txt` | The task, with `@TOKEN@` substituted per run |
| `run.sh` | Stages config, runs `up --mode headless --foreground`, verifies |

Configuration comes from [`../_common/`](../_common/) — the pi provider
declaration and the shared staging logic.

## Reading the result

```
delivered 1 credential          the delivery path worked
Delivered operator-canonical…   pi's models.json/settings.json arrived
PASS — the agent used its tools the file is really on the volume
```

A run that reports success while the `PASS` line does not appear is the
interesting failure: the agent said it was done and wrote nothing.
