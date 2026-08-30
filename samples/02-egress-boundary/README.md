# 02 — the same work, from behind a declared egress boundary

```bash
export SAMPLE_REPO=https://github.com/<you>/<scratch-repo>
export SAMPLE_GH_TOKEN=ghp_...
./run.sh claude     # or: ./run.sh pi
```

## What it proves

That an agent can do **real work through an enforced boundary** — and, just as
importantly, that the boundary was actually there. A passing run with no sidecar
proves nothing about egress, so the sample checks for the sidecar explicitly and
fails if it is missing.

This exercises a **different path** from a port-based rule. The destinations are
declared *without a port*, which puts them in the **proxy** allowlist rather than
the netfilter one: the agent's TLS is redirected to squid, which **splices** it.
TLS is never terminated and never inspected — a decrypting proxy would see every
`Authorization` header and create a new plaintext credential location inside the
component meant to reduce exposure.

It also puts **credential delivery under a boundary**, which moves the published
port to the sidecar — the agent container has none of its own. Delivery has to
connect to that port, so this is where those two features have to agree.

## The declaration is the whole policy

```yaml
egress:
  allow:
    - provider: anthropic      # or:  - host: ollama.com
    - host: github.com
```

Everything not named is refused at the **packet level**, in a namespace the agent
shares with a sidecar that alone holds `NET_ADMIN`. `github.com` is declared
alongside the model API because this sample clones and pushes — a run that only
talked to its model would reach one destination and prove much less.

## Files

| File | Purpose |
|---|---|
| `environments.yaml.template` | The declarative environment; `run.sh` fills in the name, agent and allow-list |
| `run.sh` | Builds a project dir, deploys from inside it, checks the sidecar, prints the egress record |

The task is shared with sample 03 — same work, one with a boundary and one
without, which is what makes the comparison meaningful.

## Reading the result

`egress <name>` reports **undeclared** egress: what the boundary refused, and
anything it permitted that the declaration does not name. **Silence is the good
outcome** — it means nothing was refused. When an environment has no boundary at
all, it says so rather than answering nothing.
