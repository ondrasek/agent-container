# 02 — the same work, from behind a declared egress boundary

```bash
$EDITOR .agent-container/environments.yaml     # set repo: to your own
export ANTHROPIC_API_KEY=sk-ant-... SAMPLE_GH_TOKEN=ghp_...
agent-container plan
agent-container apply
```

## What makes this one different

One block:

```yaml
egress:
  allow:
    - { provider: anthropic }
    - { host: github.com }
  enforcement: strict
```

That list is the **whole policy**. Everything not named is refused at the packet
level, in a network namespace the agent shares with a sidecar that alone holds
`NET_ADMIN`.

Both entries are declared **without a port**, which is what selects the **proxy**
path rather than a netfilter rule: the agent's TLS is redirected to squid, which
**splices** it. It is never terminated and never inspected — a decrypting proxy
would see every `Authorization` header and create a new plaintext credential
location inside the component meant to reduce exposure.

`{ provider: anthropic }` names a *provider*; the tool supplies the hosts.
`{ host: github.com }` is a plain destination — the declaration governs **all**
egress, not just the model API, which is why the forge has to be named too.

## Proving the boundary was really there

A passing run with no sidecar proves nothing about egress:

```bash
docker ps -a --filter name=agent-egress-sample02   # the sidecar must exist
agent-container egress sample02                    # what it refused
```

`egress` reports **undeclared** egress — what was refused, and anything permitted
that the declaration does not name. **Silence is the good outcome.** When an
environment has no boundary at all it says so, rather than answering nothing.

## Try breaking it

Delete the `- { host: github.com }` line, `destroy`, `apply` again. The model
call still works and the push fails — and `agent-container egress sample02` names
github.com as refused. That is the boundary doing its job, and it is a more
convincing demonstration than a run that passes.
