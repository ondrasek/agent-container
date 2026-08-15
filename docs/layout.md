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
| **Run records** | `$XDG_DATA_HOME/agent-container/runs/<host>/<environment>/` | one operator machine — **durable**; outlives every container |
| **Egress events** | `$XDG_DATA_HOME/agent-container/egress/<host>/<environment>/` | one operator machine — **durable**; a sibling of the run records, never inside them |
| **Inventory** | `$XDG_DATA_HOME/agent-container/inventory/` | one operator machine — **durable**; a third sibling, and **flat**: it must outlive the host |
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

## The pinned host key IS derived host state — and that is the exact inverse of a run record

`$XDG_STATE_HOME/agent-container/<host>/known_hosts` — the tool-owned file `attach` verifies
against (Feature 018). One file per host, one line per environment, keyed `[address]:port`.

**No new location.** It belongs in *derived host state* because *computed; safe to delete* is
literally true of it: delete it and the next deploy re-captures the container's public key through
the runtime. It is also correctly per-host — when a host goes, its containers go, so its pins are
meaningless.

Read this next to the run records below, because the two answer the same *shaped* question with
opposite lifetimes:

| | Pinned host key | Run record / egress event / inventory entry |
|---|---|---|
| Answers | *is this the container I created?* | *what did we ever create / run?* |
| Tense | present — worthless once the container is gone | past — most valuable long after |
| Recomputable | **yes**, from the running container | **no**, the run has ended |
| So it lives in | derived host state | durable data |

That is why the same argument lands in different places, and why "make them consistent" would be
a regression in either direction.

**Never the operator's `~/.ssh/known_hosts`.** The tool manages its own file and leaves the
operator's byte-identical. It *emits* text for them to place (an `ssh` config stanza, a
`known_hosts` line); it never writes into files they own.

## The inventory is a THIRD tenant of the durable location — and the odd one out

`$XDG_DATA_HOME/agent-container/inventory/<entry-id>.json` — one entry per **deployment** the tool
made: what, where, when, and what became of it (Feature 014). It sits beside `runs/` (016) and
`egress/` (012 US3), sharing the location and the atomic write path but **not** their schema or their
retention.

**It is FLAT, and that is load-bearing.** Its siblings are `<host>/<environment>/`; this one keys on a
generated entry id with host as an *attribute*:

```text
runs/<host>/<environment>/<run-id>.json      egress/<host>/<environment>/…
inventory/<entry-id>.json                     ← no <host>/ level
```

An inventory entry must **outlive its host's removal** — that is the question it exists to answer
(*"is something still billing me on a host I removed?"*). A per-host directory is deleted with its
host, destroying exactly the entries the requirement exists to keep. Do not "fix" the inconsistency.

**Retention is also not shared.** `runs/` prunes by age *and* count, because a run's value decays once
its commits are ordinary history. The inventory prunes by **count only, never by age**: the entry most
worth having is the one you forgot six months ago, so a time criterion would delete the feature's whole
value first.

## Run records are observations — not state, not configuration

`$XDG_DATA_HOME/agent-container/runs/<host>/<environment>/<run-id>.json` — one JSON file per agent
run, on the operator's machine (`~/.local/share/...` when `XDG_DATA_HOME` is unset).

**Not derived host state**, though both are XDG and both are per-machine: that location is
documented *computed; safe to delete*, and a record of a run that already ended cannot be
recomputed. Keeping records there would make this file's own description of it false.

**Not user configuration**, which is what the operator *writes*; a record is what the tool
*observes*, and a directory holding both cannot be hand-edited safely. **Not project config**,
which travels with the repository and would commit one machine's observations to everyone's.

The container writes each record to a volume first, because when a detached run ends the entrypoint
is the only thing left to write anything. The tool drains that volume into this store on its next
contact with the host — and teardown drains **before** removing volumes, or the account of the run
being torn down goes with it.

`egress/` beside it holds **egress events** (Feature 012): the same placement and the same
write-safety, a different schema and a different retention, because they have a different producer
(the boundary, not the agent) and a different lifetime (continuous, not at run end). They arrive by
a different route — the tool distils the boundary container's own log, so they need **no volume** at
all. One non-record file lives there too, a `watermark` holding how far that log has been read;
deleting it costs a re-read and nothing else. See [egress.md](egress.md).

## Inside the container

| Path | Holds | Lifetime |
|---|---|---|
| `/workspace` | your working copy | per the `--workspace` mode |
| `/workspace/.agent-container` | your spec, delivered **read-only** | recreated each start |
| `~/.agent-env` | persistent shell environment | the `-shellenv` volume |
| `~/.claude`, `~/.codex`, `~/.pi` | per-agent config + credentials | one volume each |
| `~/.config/opencode`, `~/.local/share/opencode` | opencode config; credentials + sessions | two volumes |
| `/var/lib/agent-container/runs` | run records awaiting ingestion | the `-runs` volume |
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
