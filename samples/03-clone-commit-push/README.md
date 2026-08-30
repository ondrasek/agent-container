# 03 — clone, generate, transform, report, push

```bash
export SAMPLE_REPO=https://github.com/<you>/<scratch-repo>
export SAMPLE_GH_TOKEN=ghp_...
./run.sh claude     # or: ./run.sh pi
```

## What it proves

Clone-on-start and push, end to end, with **evidence that outlives the
container**. A commit made inside a container that is torn down seconds later
proves nothing to anyone looking at the repository afterwards — so the branch is
read back from the forge.

Use a **private** repository if you can. A public clone succeeds with a junk
token, so it would exercise none of the credential path.

## Why three commits, and why the data matters

A single "write this string to a file" commit proves the plumbing and nothing
about the agent: it cannot distinguish an agent that worked from one that echoed
its instructions back.

Here **step 2 must read what step 1 produced** and compute over it. That makes
the result checkable *against the agent's own data*:

```bash
cat data/<agent>-<token>/summary.md
awk -F, 'NR>1 {n++; s+=$3} END {print "ROWS="n; print "TOTAL="s}' data/<agent>-<token>/input.csv
```

Checking that `summary.md` merely *exists* would accept any number in it.
Recomputing the sum is what separates an agent that processed the data from one
that wrote a plausible-looking file. `run.sh` prints these commands when it
finishes.

Each run pushes its **own branch**. A shared branch would make two agents racing
the same remote a source of flakiness that says nothing about either.

## Files

| File | Purpose |
|---|---|
| `task.txt` | The three-step task; `@TOKEN@`, `@BRANCH@`, `@DIR@` substituted per run |
| `run.sh` | Deploys with `--repo`, passes `GH_TOKEN` via `--env-file`, prints verification commands |

## A failure worth recognising

A model once did the first half faithfully — created the file, staged it,
committed — and dropped the branch-and-push half. The run exited 0 with a commit
in the record and **nothing on the forge**. That is model capability on a
five-step task, not a tool defect, and the fix was a better model rather than a
task trimmed until the model could pass it.
