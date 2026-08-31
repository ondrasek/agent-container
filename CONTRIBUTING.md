# Contributing to agent-container

Thanks for looking. This is a small, opinionated project with a written design
contract, so the fastest way to get a change merged is to read the contract
first and then match it.

- **Design contract:** [`CLAUDE.md`](CLAUDE.md) — the load-bearing invariants.
  Anything that contradicts it needs an argument, not just a patch.
- **Feature specs:** [`specs/<NNN>-*/`](specs/) — one directory per feature,
  with its requirements and checklists.
- **Reference docs:** [`docs/`](docs/) — the durable explanation of each
  subsystem.

## Ground rules

These four constraints are not negotiable; they define what the project *is*.

1. **No reliance on container persistence.** Every agent must `commit` **and**
   `push` every change. A feature that depends on uncommitted state is wrong by
   construction.
2. **Editor-agnostic, not VSCode-locked.** No `.devcontainer/`. SSH + tmux is
   the canonical attach path.
3. **Multiple parallel containers.** Naming, ports, volumes and git identity
   must support N containers on one host without collision.
4. **Push auth must work non-interactively.** Agents commit autonomously, so no
   interactive prompts anywhere in that path.

A fifth, softer one: **defaults belong at the surface, and each one is named.**
A reader reports *absence*; absent, defaulted, declared-empty and unexamined are
four different answers and the code says which.

## Getting set up

You need [uv](https://docs.astral.sh/uv/) and Python **3.14** (uv will fetch it).
A container runtime — Podman or Docker with Compose v2 — is needed only for the
acceptance tier.

```bash
git clone https://github.com/ondrasek/agent-container.git
cd agent-container
uv tool install --editable .        # puts `agent-container` on PATH, tracking your checkout
git config core.hooksPath .githooks # enables the commit-message hook
```

The CLI is a single PEP 723 script, [`bin/agent-container`](bin/agent-container).
You can always run it in place without installing anything:

```bash
uv run --script bin/agent-container --help
```

## The quality gate

**One script, two uses.** [`scripts/quality-gate.sh`](scripts/quality-gate.sh) is
what the Claude Code Stop hook runs locally *and* what the `quality-gate` CI job
runs. There is no second list of "what must pass", so local and CI cannot
diverge.

```bash
scripts/quality-gate.sh     # read the exit code UNPIPED
```

It runs `ruff check`, `ruff format`, `ty`, `bandit`, `vulture`, `xenon`,
`refurb`, the CLI's own `--self-test` doctests, the pytest suite, and the shell
suites (entrypoint, execution, completions, tmux layout, repository capture).
It stops at the first failure and prints that check's full output plus a hint
for fixing it.

**Never fix style by hand** — let `ruff` do it:

```bash
uv run --no-project --with ruff ruff check --fix
uv run --no-project --with ruff ruff format
```

### The acceptance tier

The gate deliberately **excludes** the slow, authoritative real-container tier.
CI is the authority on it; run it locally when you touch the entrypoint, the
credential channel, or the SSH identity flows:

```bash
uv run --no-project --python 3.14 --with pytest \
  --with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' \
  --with 'rich>=13,<15' --with 'pyyaml>=6,<7' \
  pytest bin/tests -m acceptance
```

Two cautions. **Never edit the tree while that tier runs** — it re-reads the CLI
on every invocation. And on macOS + Lima, the working directory must be one Lima
shares into the VM.

### Run the full suite, not just your new tests

A changed contract is exactly the moment a pre-existing test still pins the old
shape. `scripts/quality-gate.sh` runs everything fast; use it.

## Conventional Commits are mandatory

The CD pipeline **reads** your commit messages: python-semantic-release computes
the version bump from them. A local `commit-msg` hook, a CI job and a `main`
branch ruleset all enforce the format (`--no-verify` bypasses only the hook, not
the other two).

```
feat(cli): add `host show --json`
fix(entrypoint): do not clobber an existing ~/.ssh/config block
docs(readme): document the egress allow-list
```

| Type | Effect on the release |
|---|---|
| `feat` | minor bump |
| `fix` | patch bump |
| breaking change (`!` **and** a `BREAKING CHANGE:` body) | **minor** while pre-1.0 |
| `docs`, `chore`, `ci`, `test`, `style`, `refactor` | no release |

**A breaking change must say so in the body.** Pre-1.0 the version number only
moves the minor digit, so the message is the only place the break is recorded.

Write commit messages **from a file** (`git commit -F msg.txt`), not with `-m`:
backticks in a `-m` string are command substitution in your shell.

### Never let a commit message contain a skip-workflow marker

GitHub recognises five markers — the bracketed `skip ci`, `ci skip`, `no ci`,
`skip actions` and `actions skip` — and matches them **anywhere in the message**,
not just the subject line. For a pull request it checks the **HEAD** commit.

So a message that merely *quotes* one, while explaining CI behaviour, silences its
own CI. That is worse than it sounds here: `publish.yml` chains off `ci` with
`workflow_run`, so a skipped `ci` means no release, which means no site rebuild —
the whole ladder goes quiet and the PR looks like it is simply still waiting. If
you need to write about the markers, describe them instead of pasting them.

(`python-semantic-release` puts one in its own release commit on purpose, so that
commit does not re-trigger the pipeline that created it.)

## Where a change goes

Keep the layers separate; this is the architecture, not a preference.

| Layer | Where | Rule |
|---|---|---|
| **image** | [`image/`](image/) | bake every system dependency at build; no runtime `apt` |
| **orchestration** | [`bin/agent-container`](bin/agent-container) + compose | never bake host-specific orchestration into the image |
| **entrypoint** | [`image/entrypoint.sh`](image/) | git identity, credential injection, key generation, sshd, tmux |
| **attach** | client-side | stays thin |

A few specifics that trip people up:

- **The supported-agent list is single-sourced** (`AGENTS` in the CLI). Tests pin
  the completions and every Dockerfile against it.
- **Mirror any CLI surface change in both completions** (bash *and* zsh). The
  tests catch parity, not staleness.
- **Short flags need a long form** (`-y`/`--yes`). `-v`/`--verbose` is injected
  onto every command, not declared per command.
- **Group verbs:** `ls` reads; destructive verbs are spelled out. A rename keeps
  the old spelling as a hidden alias.
- **PyYAML is the one third-party parsing dependency**, and only
  `yaml.safe_load`. Never run a regex over a structured format — it silently
  misses flow style and quoted keys.
- **Credentials are least-exposure.** Never baked into an image, never on argv,
  never printed, never on a volume. No private SSH key is ever injected.

## Documentation

Docs are part of the change, not a follow-up.

- New durable explanation goes in [`docs/`](docs/), by feature.
- [`CLAUDE.md`](CLAUDE.md) holds invariants only and must stay under 2000
  tokens — **prune before you add**.
- A decision with alternatives gets an ADR under
  [`docs/decisions/`](docs/decisions/).
- The threat model is reconciled for **every** feature:
  [`docs/threat-model.md`](docs/threat-model.md).

The website under [`site/`](site/) renders the repo's own markdown, so updating
`README.md` or anything in `docs/` updates the published site on the next push.

## Pull requests

1. Branch off `main`.
2. Make the change, with tests.
3. `scripts/quality-gate.sh` green.
4. Conventional Commit messages.
5. Open the PR. CI runs the gate, the commit-message check, a pinned-interpreter
   pytest run, the build, and the real-container acceptance suite.

Every substantive merge to `main` is a release — CI green triggers
python-semantic-release, which bumps the version, writes the changelog, tags,
creates the GitHub Release and publishes to PyPI. There is no separate "cut a
release" step, which is precisely why the commit messages matter.

## Reporting bugs and asking for features

Open an [issue](https://github.com/ondrasek/agent-container/issues). For a bug,
the useful report includes the output of:

```bash
agent-container doctor
agent-container --version
```

plus the failing command re-run with `-v` (which prints the exact commands the
tool issued). **Redact nothing but secrets** — the verbose output is designed not
to contain any.

## Security

Please do not open a public issue for a vulnerability. Email
`ondrej.krajicek@ideastatica.com` instead. The threat model this project holds
itself to is written down in [`docs/threat-model.md`](docs/threat-model.md); a
report that shows a gap between that document and the code is the most useful
kind.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
