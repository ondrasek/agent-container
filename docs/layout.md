# Filesystem layout

The authoritative map of every location the tool owns. One term per location — if you find a
name used two ways anywhere else in the docs, this file wins.

## Vocabulary

| Term | Path | Scope |
|---|---|---|
| **Project root** | the nearest ancestor of your cwd containing `.agent-container/` | one project |
| **Project config** | `<root>/.agent-container/` | one project — **travels with the repository** |
| **User configuration** | `~/.config/agent-container/` | one operator machine — does **not** travel |
| **Derived host state** | `$XDG_STATE_HOME/agent-container/<host>/` | computed; safe to delete |
| **Image sources** | `<checkout>/image/` | the tool's own repo |

"Project directory" is **not** used: it is ambiguous between the first two.

## Your project

```text
my-service/                          ← PROJECT ROOT
├── .agent-container/                ← PROJECT CONFIG — like .git/ or .github/
│   ├── environments.yaml               declarative spec — holds `environments:`
│   ├── prod.environments.yaml          another spec file; specs may be split
│   ├── prod.env                        per-environment env file
│   ├── .env                            shared default for every environment here
│   ├── prod.services.yaml              sidecar override — holds `services:`
│   └── prod.config/                    canonical agent config
├── src/                             ← your code; the tool owns none of it
└── README.md
```

### A YAML file's suffix names the top-level key it contains

One rule, and it is the whole convention:

| Filename | Contains | Read as |
|---|---|---|
| `environments.yaml`, `*.environments.yaml` | `environments:` | the declarative spec |
| `*.services.yaml` | `services:` | a sidecar override |

Both kinds share the directory, which is exactly what the suffix makes possible: before it, the
spec loader claimed *every* `*.yaml` here and refused the sidecar's `services:` key — so a project
could not use both features at once. `.yml` works everywhere `.yaml` does.

Any **other** `*.yaml` in this directory is **refused**, naming it — so `enviroments.yaml` tells
you about the typo instead of silently loading no environments. Pass `--skip-unknown-files` to
downgrade that to a warning if you deliberately keep unrelated YAML here.

> **Migrating.** `project.yaml`, or any other name that used to be read because it merely ended in
> `.yaml`, must be renamed to `environments.yaml` or `<prefix>.environments.yaml`. The tool refuses
> and names the file rather than ignoring it.

Discovery walks **up**, so every command behaves identically from any subdirectory. Nothing
depends on an absolute path — copy or vendor the project anywhere.

**The project config directory is the only tool-owned entry in the project root.**

## Configuration is two levels of one thing

Project level wins; user level is the fallback — the layering Claude Code and similar tools use.

| | Project level | User level |
|---|---|---|
| env | `.agent-container/<name>.env` → `.agent-container/.env` | `~/.config/agent-container/<name>.env` → `~/.config/agent-container/.env` |
| sidecars | `.agent-container/<name>.services.yaml` | `~/.config/agent-container/<name>.services.yaml` |
| agent config | `.agent-container/<name>.config/` | `~/.config/agent-container/<name>.config/` |
| **credential** | **— not permitted —** | `~/.config/agent-container/<name>.<provider>.key` |
| host registry | — | `~/.config/agent-container/hosts.json` |

The **same filename means the same thing at both levels**. That symmetry is what makes them
legible as one layered configuration rather than two conventions.

### Two deliberate asymmetries

**Plaintext credentials are user-level only.** `.agent-container/` travels with your repository,
and the tool's rule is that the repo holds a **locator, never a value**. If keys lived there,
`git add .agent-container/` — the natural action, since it holds your spec — would stage an API
key. To reference a credential from the repo, use a locator source (`file`, `keychain`,
`command`, `onepassword`, `bitwarden`) in `environments.yaml`.

**The host registry is user-level only.** Hosts are a property of your machine, not of a project.

### Env files you name yourself

`-e`/`--env-file` is repeatable and **replaces** the discovery chain, applying files in order
with later ones winning:

```bash
agent-container up dev -e ~/.env -e ./local-overrides.env
```

The file can live anywhere, including outside the project. It is read **client-side**, so it
works against a remote host without existing on that machine.

A bare `./.env` in your project root is **not** read — it belongs to whoever put it there
(Compose, direnv, a framework). If one is present and no agent-container env file resolves, the
tool refuses rather than deploying without it.

## Inside the container

| Path | Holds | Lifetime |
|---|---|---|
| `/workspace` | your working copy | per the `--workspace` mode |
| `/workspace/.agent-container` | your spec, delivered **read-only** | recreated each start |
| `~/.agent-env` | persistent shell environment | the `-shellenv` volume |
| `~/.claude`, `~/.codex`, `~/.pi` | per-agent config + credentials | one volume each |
| `~/.config/opencode`, `~/.local/share/opencode` | opencode config; credentials + sessions | two volumes |
| `/run/agent-container/` | injected secrets | **vanish with the container** |

`/workspace/.agent-container` keeps the name because it *is* your project config delivered
read-only. `~/.agent-env` does not: it is container-local shell state that merely shared a name.

## The tool's own repo

```text
agent-container/
├── image/                  ← the entire build context
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── .dockerignore
├── bin/agent-container     the CLI
├── completions/  docs/  orchestration/  scripts/  specs/
└── CLAUDE.md  README.md  pyproject.toml
```

The build context is `image/`, so it is narrow **by construction** rather than by an allowlist
that must be maintained in step with the Dockerfile. This matters most for a remote host, where
the whole context crosses the network to another daemon.

A checkout is recognised by `image/Dockerfile` **and** `completions/agent-container.bash`.

## Migrating from the pre-011 layout

There is no compatibility mode — the tool **refuses** and names every file that must move.

| Old | New |
|---|---|
| `./agent-container.<name>.env` | `.agent-container/<name>.env` |
| `./.env` | `.agent-container/.env`, or `-e <path>` |
| `./agent-container.<name>.services.yaml` | `.agent-container/<name>.services.yaml` |
| `./agent-container.<name>.config/` | `.agent-container/<name>.config/` |
| `./agent-container.<name>.<provider>.key` | `~/.config/agent-container/<name>.<provider>.key`, or a locator |
| `./Dockerfile`, `./entrypoint.sh` | `image/` |
| `~/.agent-container` (in container) | `~/.agent-env` |

**Container names, ports and volume names are unchanged**, so environments you already run stay
findable and tear down cleanly. Only file locations moved.
