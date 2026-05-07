# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project intent

Build a **containerized development environment** designed to run remotely (e.g., Hetzner VPS) as an always-on container that the user attaches to and detaches from over SSH. Inside, multiple AI coding agents (Claude Code, Codex, pi-coding-agent) and editors (nvim) run under tmux. Multiple such containers may run in parallel, each holding working copies of one or more git repositories.

This is a greenfield repo — no code has been written yet. Treat the section below as the design contract, not a description of existing code.

## Hard constraints

These are load-bearing design decisions, not preferences:

1. **No reliance on container persistence.** Every agent must `commit` AND `push` every change. The container is treated as ephemeral; if it dies, no work is lost. Any feature or workflow that depends on uncommitted state is wrong by construction.
2. **Editor-agnostic, not VSCode-locked.** The user explicitly rejected devcontainers because tooling support outside VSCode is nonexistent. Do not introduce `.devcontainer/` configs or any design that assumes a VSCode client. SSH + tmux is the canonical attach path.
3. **Multiple parallel containers.** Naming, port allocation, volume mounts, and git identity must all support N containers running simultaneously on the same host without collision.
4. **Push auth must work non-interactively.** Agents commit autonomously, so SSH keys / git credentials inside the container must be configured to push without prompts. Never embed long-lived secrets in the image — inject at runtime.

## Architecture sketch (to be built)

Expect the repo to grow into roughly:

- **Container image** — base OS + tmux + SSH server + nvim + git + the agent CLIs (Claude Code, Codex, pi-coding-agent) and their language runtimes.
- **Orchestration layer** — scripts or compose/quadlet definitions to launch, name, attach to, and tear down containers on the remote host.
- **Bootstrap / entrypoint** — sets up git identity, injects credentials, starts sshd + a default tmux session, optionally clones configured repos.
- **Attach tooling** — a thin client-side helper for `ssh user@host -t tmux attach -t <session>` style flows across multiple hosts/containers.

When adding a component, keep these layers separate. Don't bake host-specific orchestration into the image.

## Conventions for future work

- Prefer **rootless / Podman-compatible** patterns where reasonable; avoid features that only work on Docker Desktop.
- Treat the **commit-and-push discipline** as a property of the agent configuration, not something to enforce via git hooks alone (hooks can be bypassed; the agents themselves should be configured to push).
- When proposing a tool or dependency, justify it against the constraints above — especially the "not VSCode-locked" one.

## Out of scope (don't add unless asked)

- IDE integrations beyond plain SSH/tmux/nvim.
- Multi-user / multi-tenant access controls — single operator (the user) is assumed.
- Kubernetes manifests — the target is a single VPS running a container runtime, not a cluster.
