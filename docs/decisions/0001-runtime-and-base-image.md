# 0001 — Container runtime and base image

- **Status:** accepted
- **Date:** 2026-05-29
- **Drives:** epic #1 work items B (image), C (entrypoint), D (credentials), E (orchestration)

## Context

This is the first decision for the remote persistent dev environment described in `CLAUDE.md`. The image must host AI coding agents (Claude Code, Codex, pi-coding-agent), `nvim`, `tmux`, `git`, and an OpenSSH server, and be runnable as one or more **always-on, parallel** containers on a personal Linux VPS (Hetzner-class). The operator attaches over SSH and detaches via `tmux`. Devcontainers were rejected upstream because tooling support outside VSCode is nonexistent.

Two coupled choices are settled here:

1. The **container runtime** that hosts these containers on the VPS.
2. The **base image** used by the Dockerfile/Containerfile in subsequent work.

## Decision

- **Runtime: Podman.**
- **Base image: `debian:12-slim` (bookworm).**

## Rationale

### Runtime — Podman

- **Daemonless.** Each container is a normal process tree under the operator's user. No privileged long-running daemon to harden, secure, or restart. Better fit for a single-operator VPS than a Docker daemon.
- **Rootless first-class.** Hard constraint #3 from `CLAUDE.md` requires N parallel containers without collision; rootless containers under the operator account give a clean isolation boundary without sudo gymnastics.
- **Quadlet integration with systemd.** Quadlet `.container` units make "always-on" a first-class concept: the host's init system supervises the container, restarts it on failure, captures logs in `journald`, and applies resource limits — none of which Docker does as cleanly. This is exactly the lifecycle the epic requires.
- **OCI image compatibility.** Anything we build for Podman runs under Docker too, so the choice is reversible at the orchestration layer if Quadlet turns out to be a poor fit.

### Base image — `debian:12-slim`

- **glibc, not musl.** Both Node (Claude Code, Codex) and Python (pi-coding-agent) ecosystems ship binary wheels and prebuilt artifacts assuming glibc. Alpine/musl works but introduces friction for at least one of these CLIs at install or runtime, against no concrete size budget that justifies it.
- **Predictable, conservative package set.** Debian stable's repo gives us `tmux`, `openssh-server`, `git`, `python3`, `nodejs` (or via NodeSource), and supporting tooling without surprise breakage. The release cadence matches "build once, run for months" — appropriate for an always-on dev container.
- **Modest size.** `debian:12-slim` is ~30 MB compressed; once the agent CLIs and language runtimes land, the image will be dominated by those, not the base.
- **`nvim` caveat.** Debian 12's repo `nvim` is too old to be useful. Mitigation: install the upstream `nvim` release tarball (or AppImage) to `/usr/local` in the Dockerfile. This is documented as a known wart, not a deal-breaker.

## Alternatives considered

### Docker + Ubuntu 24.04 LTS — rejected

- **Pro:** Most familiar toolchain; Docker Desktop / OrbStack make local builds on a macOS laptop frictionless.
- **Pro:** Ubuntu's `nvim` package is closer to current than Debian's, though still typically behind upstream.
- **Con:** Requires the Docker daemon — a privileged long-running service to operate on the VPS. Adds attack surface and operational complexity for a single-operator setup.
- **Con:** No clean "always-on supervised by host init" story. Docker has restart policies but they're inferior to systemd Quadlet for service lifecycle, log routing, and resource control.
- **Con:** Ubuntu base is slightly larger than Debian without compensating benefit; Ubuntu's snap/cloud-init defaults are noise we don't need in a container.

### Podman + Alpine 3.x — rejected

- **Pro:** Smallest image of any candidate; package manager is fast.
- **Pro:** `nvim` is reasonably current in Alpine's community repo.
- **Con:** musl libc breaks or destabilizes Node prebuilds and Python wheels. Each agent CLI install becomes a "does it have a musl variant?" question. The operational fragility outweighs the size win for a dev environment image where size is not on the constraint list.
- **Con:** BusyBox userland is fine for production microservices but inconvenient interactively (e.g., for the operator inside `tmux`).

### Docker + Debian 12 — rejected

- **Pro:** Same base as the chosen option; same glibc and package benefits.
- **Con:** Loses the daemonless, rootless, and Quadlet advantages of Podman without offering anything in return. If we prefer Docker familiarity later, this is the cheapest pivot — but it should not be the default.

## Trade-offs

| Factor                              | **Podman + Debian 12** (chosen) | Docker + Ubuntu 24.04 | Podman + Alpine | Docker + Debian 12 |
|-------------------------------------|---------------------------------|-----------------------|-----------------|--------------------|
| Rootless support                    | Native                          | Bolt-on               | Native          | Bolt-on            |
| Daemon footprint                    | Daemonless                      | Daemon                | Daemonless      | Daemon             |
| Always-on lifecycle (host init)     | Quadlet/systemd, native         | Restart policies only | Quadlet/systemd | Restart policies only |
| macOS client local-build ergonomics | Lima + docker-cli (operator's existing setup) | Docker Desktop / OrbStack | Lima + docker-cli or `podman machine` | Docker Desktop / OrbStack |
| Image size (base)                   | ~30 MB                          | ~80 MB                | ~5 MB           | ~30 MB             |
| Node/Python binary compatibility    | Excellent (glibc)               | Excellent (glibc)     | Quirky (musl)   | Excellent (glibc)  |
| `nvim` recency from repo            | Outdated → install upstream     | Outdated → install upstream | Reasonable | Outdated → install upstream |
| Familiarity (operator)              | Lower                           | Highest               | Lower           | Highest            |

## Consequences

- Item **B** (build the image) writes a `Dockerfile` (not `Containerfile`) targeting `debian:12-slim`. The universal `Dockerfile` name lets `docker build` work without `-f`, and Podman accepts the same file unchanged — zero-cost compatibility for both halves of the toolchain.
- Item **E** (host-side orchestration) defaults to **Podman Quadlet `.container` units** under the operator's user systemd, with a thin wrapper script offering `up`/`down`/`attach`/`list`. `compose` is left as a possible escape hatch but not the primary interface.
- Item **C** (entrypoint) is implemented as a single shell script that starts `sshd`, then a named `tmux` session — same regardless of runtime, so this decision doesn't constrain it.
- **Local development on macOS uses Lima + docker-cli** (the operator's existing setup). Local validation steps in docs and smoke scripts assume `docker build` / `docker run` from a Lima-backed Docker socket. The image is OCI-portable, so the same artifact runs under Podman on the VPS.
- **Reversibility:** moving from Podman to Docker on the VPS is cheap (image is OCI; entrypoint is portable); moving from Debian 12 to another glibc distro is moderate; moving to musl is expensive. The base-image choice is the higher-stakes half of this decision.

## Open questions deferred to later items

- Exact `nvim` install method (release tarball vs AppImage vs source build) — settled in item **B**.
- Whether to ship a pinned Node/Python via `mise`/`asdf` or use distro packages — settled in item **B**.
- Quadlet unit layout and naming convention for parallel containers — settled in item **E**.
