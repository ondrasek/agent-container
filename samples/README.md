# Samples — run the real-agent tests yourself

Each subdirectory is **one real-agent scenario**, with the configuration files it
needs and a `run.sh` that wires them together. These are the same scenarios the
acceptance tier runs in CI, extracted so you can run them without pytest.

They use a **real agent against a real model**, so every run **costs money** and
none of them is deterministic. That is the point: everything else in this
repository's test suite stubs the agent binary with a shell script, which proves
the plumbing and nothing about whether an agent can actually work in here.

| Sample | What it proves | Needs a repo? |
|---|---|---|
| [`01-workspace-write`](01-workspace-write/) | The whole stack: credential delivery, canonical config, a real model, tool use, a run record | no |
| [`02-egress-boundary`](02-egress-boundary/) | The same work done from **behind a declared egress boundary** — and that the boundary was really there | yes |
| [`03-clone-commit-push`](03-clone-commit-push/) | Clone on start → generate data → transform it → report → **push**, as three commits | yes |
| [`04-avl-tree`](04-avl-tree/) | The agent writes **working software** — an AVL tree, unit tests, a TUI — verified by running it | yes |

Start with **01**. It needs nothing but a model key, and if it fails, none of the
others will tell you anything you did not already learn.

## Prerequisites

1. **A container runtime** — Podman (the default) or Docker, with `compose` v2.
2. **A model credential**, exported for the agent you want to run:

   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...          # claude, API key
   export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-...    # claude, subscription — preferred if you have one
   export OLLAMA_API_KEY=...                    # pi, via Ollama Cloud
   ```

   With a subscription token present, the samples select it and set
   `claude_auth: oauth`; otherwise they use the API key. **Exactly one is wired** —
   Claude refuses to be told twice.

3. **For samples 02–04, a git repository you can write to**, plus a token:

   ```bash
   export SAMPLE_REPO=https://github.com/<you>/<a-scratch-repo>
   export SAMPLE_GH_TOKEN=ghp_...     # PAT with 'repo' scope
   ```

   There is deliberately **no default repository**. Every run pushes a new
   branch, so use a throwaway. A *private* repo is the better test: a public one
   would clone happily with a junk token and tell you nothing about whether the
   credential path works.

## Running one

```bash
cd samples/01-workspace-write
./run.sh claude      # or: ./run.sh pi
```

## Where things go, and what never leaves your machine

Every sample stages its configuration into a **disposable root**:

```
~/.cache/agent-container-samples/<sample-name>/{config,state,data}
```

`AGENT_CONTAINER_ROOT` relocates config, state and data together, so a sample
**cannot disturb your real setup**, and cleaning up is `rm -rf` on one directory.
Override it if you want them elsewhere.

**No credential is ever written into this repository.** The samples read keys
from your environment and write them into that disposable root at `0600` — which
is why you will not find an `.env` file here to fill in. The one place a key
would be easy to commit by accident is the one place these samples refuse to put
it.

## What the samples deliberately do NOT do

They touch **no undocumented surface**. Nothing writes into a container by hand,
nothing edits a compose file, nothing sets a private variable. Configuration
travels the same conventions the documentation describes:

- the credential rides `<name>.<provider>.key` onto its own volume, delivered
  over the container's own sshd under a declared identity (Constitution IX);
- agent config rides `<name>.config/<agent>/…` onto the agent's home;
- the egress policy is declared in `.agent-container/environments.yaml`.

If one of those conventions breaks, a sample breaks with it. That is the second
reason these exist.

## If a sample fails

A failure here is **not automatically a bug in agent-container** — a model can
simply be bad at the task, and sample 04 is a genuinely hard one for a small
model. The distinction to draw:

- **The run failed, or a credential was not delivered** → an `agent-container`
  problem. `logs <name>` and the run record will say where it stopped.
- **The run succeeded but the output is wrong or incomplete** → usually model
  capability. Sample 03 caught exactly this once: a model did the first half of
  the task, committed, and silently skipped the branch-and-push half. The honest
  fix was a better model, not a smaller task.
