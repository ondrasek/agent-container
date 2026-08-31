# 03 — clone, generate, transform, report, push

```bash
$EDITOR .agent-container/environments.yaml     # set repo: to your own
export ANTHROPIC_API_KEY=sk-ant-... SAMPLE_GH_TOKEN=ghp_...
agent-container plan && agent-container apply
```

## What it declares

`repo:` gives clone-on-start, and `GH_TOKEN` arrives as a declared credential —
delivered as an environment variable because it is not a provider API key, which
is what the git credential helper reads for the HTTPS push.

Use a **private** repository if you can. A public clone succeeds with a junk
token, so it would exercise none of the credential path.

## Why the task has three steps

A single "write this string to a file" commit proves the plumbing and nothing
about the agent: it cannot distinguish an agent that worked from one that echoed
its instructions back.

Step 2 must **read what step 1 produced** and compute over it, which makes the
result checkable against the agent's own data:

```bash
git clone --branch sample03-pipeline <your repo> /tmp/check && cd /tmp/check
cat data/sample03/summary.md
awk -F, 'NR>1 {n++; s+=$3} END {print "ROWS="n; print "TOTAL="s}' data/sample03/input.csv
```

Checking that `summary.md` merely *exists* would accept any number in it.
Recomputing the sum is what separates an agent that processed the data from one
that wrote a plausible-looking file.

## A failure worth recognising

A model once did the first half faithfully — created the file, staged it,
committed — and dropped the branch-and-push half. The run exited 0 with a commit
in the record and **nothing on the forge**. That is model capability on a
five-step task, not a tool defect, and the fix was a better model rather than a
task trimmed until the model could pass it.
