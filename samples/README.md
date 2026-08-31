# Samples — agent specifications you can apply

Each subdirectory is a **project**: a folder with a `.agent-container/`
directory holding the YAML the CLI reads. That folder *is* the sample. It is
plain text, git-trackable, and it is what `agent-container apply` reconciles —
nothing here is generated at run time.

```
samples/01-workspace-write/
└── .agent-container/
    ├── environments.yaml            the spec: name, host, container, task,
    │                                credentials, egress
    └── sample01.config/pi/          canonical config, delivered to the agent's
        ├── models.json              home by the <name>.config/<agent>/ convention
        └── settings.json            (used only when agent: pi)
```

| Sample | What it declares | Needs a repo? |
|---|---|---|
| [`01-workspace-write`](01-workspace-write/) | A headless agent, a task, one credential | no |
| [`02-egress-boundary`](02-egress-boundary/) | The same, plus an `egress:` allow-list under `enforcement: strict` | yes |
| [`03-clone-commit-push`](03-clone-commit-push/) | `repo:` clone-on-start, a three-commit pipeline task, a forge token | yes |
| [`04-avl-tree`](04-avl-tree/) | The hardest task — real software, tests and a TUI | yes |

Start with **01**: it needs only a model key.

## Once per machine

```bash
./setup-once.sh
```

The single imperative step, and it exists for a reason worth reading: delivering
a credential needs an operator-**declared** SSH identity (Constitution IX), and
the tool deliberately refuses to generate one — a tool-minted key would be a
standing credential granting entry to every environment it ever deploys. The
script creates one under `~/.config/agent-container/`, declares it in
`settings.yaml` and admits its public half in your key collection. Nothing it
writes goes into this repository.

## Then, per sample

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # or OLLAMA_API_KEY, for agent: pi
export SAMPLE_GH_TOKEN=ghp_...             # samples 02-04 only

cd 01-workspace-write
agent-container plan          # validates and shows absent / matching / drifted
agent-container apply         # converge
```

`plan` mutates nothing, so it is always safe to run first. `apply` is
**idempotent**: a matching spec makes no changes; a drifted one is announced,
then recreated.

**Samples 02–04 need one edit before they will work.** `repo:` points at a
placeholder — change it to a repository you can write to. A throwaway is right;
each run pushes a branch. Prefer a *private* one: a public repo clones happily
with a junk token, which would tell you nothing about whether the credential
path works.

To run `pi` instead of Claude Code, change `agent:` and swap the credential
entry. Both alternatives are written out in comments beside the line you change.

## No secret is in these files, by construction

`credentials:` entries are **locators, never values**:

```yaml
credentials:
  - { name: ANTHROPIC_API_KEY, source: env, var: ANTHROPIC_API_KEY }
```

The variable is read at apply time; the value travels to the container over that
container's own sshd and lands on a per-credential volume. It is never written
into this file, into the compose model the tool generates, or onto a command
line. That is why these samples can be committed and why they ask you to export
a variable instead of filling in a blank.

`source:` also accepts `file`, `keychain`, `command`, `onepassword` and
`bitwarden` — see [`docs/agent-as-code.md`](../docs/agent-as-code.md).

## Cleaning up

```bash
agent-container destroy       # removes only what THIS spec declares and owns
```

## When a sample fails

Not automatically a bug — a model can simply be bad at the task, and 04 is hard
for a small one. The distinction:

- **`apply` failed, or a credential was not delivered** → an `agent-container`
  problem. Re-run with `-v` for the exact commands, and read `logs <name>`.
- **The run succeeded but the output is wrong or incomplete** → usually model
  capability. One model did the first half of 03 faithfully, committed, and
  silently skipped the branch-and-push half; the honest fix was a better model,
  not a smaller task.
