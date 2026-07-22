# Feature Specification: Shell Integration (emit eval-able env + commands; optional execute)

**Feature Branch**: `005-shell-integration`

**Created**: 2026-07-12

**Status**: Draft

**Input**: User description: "Instead of invoking tools such as tmux, docker or ssh internally, the tool should help me configure my shell environment by providing command lines to run and environment variables to set, so I can run `eval $(agent-container …)`. As an option, the tool would also invoke these commands. Similar to `limactl show-ssh default`."

## Context & Boundary

Today the tool **invokes** external tools on the operator's behalf: `attach` execs `ssh … tmux attach`; deploy drives `docker compose` over a context; provisioning drives `ssh`/`docker context`. This feature adds a **print mode**: for those tool-invoking operations, the tool **emits shell-evaluable configuration** — environment variables to set and/or command lines to run — so the operator can `eval $(agent-container …)`, paste it into a script/alias/ssh-config, or read it. Executing the commands itself remains available (opt-in or as the existing default). Models `limactl show-ssh`, `eval $(minikube docker-env)`, and `docker context`.

**This feature owns** the print/eval contract and which operations expose it. It does **not** change what those operations *do* — hosts/identity/addressing (001), lifecycle (002), credentialing (003), and attach/session semantics (004) are unchanged; this feature *exposes* them.

**A paradigm shift, not just a flag.** This feature begins reframing the tool's primary role: from a wrapper that *invokes* `ssh`/`docker`/`tmux` on the operator's behalf, to an **environment configurator and command-line builder** — it computes *what* should run and hands the operator ready-to-eval configuration; **executing it directly becomes one backend among several**, not the defining behavior. That framing is deliberately forward-looking: the same "compute the action, then choose how to realize it" seam is intended to later accept **infrastructure-as-code emitters** (e.g. Terraform, ARM/Bicep, other IaC) as additional backends — so a future provision could *emit* Terraform instead of driving a cloud API directly. Those IaC drivers are **out of scope for this feature**, but the print/emit abstraction must not preclude them.

**Why this matters:** (1) **transparency** — the operator sees exactly what would run; (2) **composability** — the emitted config drops into the operator's own shells, aliases, scripts, and CI; (3) **robustness** — when the operator's *own* shell runs the emitted `ssh`/`docker` command, their existing ssh-agent, smartcard, `known_hosts`, and `~/.ssh/config` handle the connection, so environment-specific invocation quirks that are hard for the tool to drive correctly everywhere simply work in the operator's terminal (a friction this project hit driving `ssh`/`docker context` internally during cloud provisioning).

## Clarifications

### Session 2026-07-22

- Q: What should `host env <name>` emit to retarget the operator's docker/podman at the host? → A: **Both, selectable** — default to the host's **registered runtime reference** (`DOCKER_CONTEXT` / the podman connection), which reuses the exact connection the tool established (including any socket-forward); a flag emits the **raw endpoint** form instead (`DOCKER_HOST=ssh://…` / `CONTAINER_HOST=…`) for portability where the registered context is not present.
- Q: Should `host env` verify reachability at print time? (Edge Cases require print to "not connect"; US2-AC3 said an *unreachable* host emits nothing — a contradiction.) → A: **Registry-only, no probe** — emit purely from registry/state with **no connection**, so print stays side-effect-free. Only an **unknown/unregistered** host emits nothing and exits non-zero; a registered-but-unreachable host still emits — the operator's own `docker ps` surfaces unreachability.
- Q: What does the `--unset` form do? → A: **Plain unset** — emit `unset` of the vars, reverting to the shell/daemon default (like `minikube docker-env --unset`); it does **not** snapshot or restore a prior custom value, and stores no new state.
- Q: Which shell dialects ship in this feature? → A: **POSIX (default) + fish + PowerShell (pwsh)**; csh and other dialects remain deferred behind the same selector seam. (PowerShell added by later direction — the eval idiom there is `Invoke-Expression`/`iex`.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Print the attach command instead of running it (Priority: P1)

The operator asks for the SSH/tmux command that would attach to a container, rather than having the tool exec it. The tool prints a ready-to-run command (and/or an SSH-config stanza) to stdout and nothing else there, so the operator can run it, alias it, script it, or drop it into `~/.ssh/config`. This is the direct analog of `limactl show-ssh`.

**Why this priority**: This is the smallest, most useful slice and the clearest analog to the referenced tools. It immediately unblocks scripting/aliasing the canonical attach path and lets the operator's own SSH stack (agent, smartcard, config) handle auth.

**Independent Test**: `attach <name> --print` on a running container emits a single runnable `ssh … -t tmux attach` line to stdout; running that line verbatim attaches to the same session `attach` would; any diagnostics appear only on stderr; nothing is created or connected by the print itself.

**Acceptance Scenarios**:

1. **Given** a running container, **When** the operator requests the attach command in print mode, **Then** stdout contains exactly the runnable SSH+tmux command (with the correct user, reachable address, and port) and nothing else.
2. **Given** that printed command, **When** the operator runs it verbatim, **Then** it attaches to the *same* tmux session the tool's own `attach` would reach.
3. **Given** a container on a remote host, **When** print mode is requested, **Then** the command targets the host's reachable public address and the container's published port (parity with the tool's attach).
4. **Given** the operator wants an SSH-config form, **When** they request it, **Then** a valid `Host` stanza is emitted that they can append to `~/.ssh/config` to `ssh <alias>` later.

---

### User Story 2 - Configure the shell to target a host directly (Priority: P2)

The operator runs `eval $(agent-container host env <name>)` and their **own** `docker`/`compose` then targets that host directly (no tool wrapper), exactly like `eval $(minikube docker-env)`. A matching **unset** form reverts the environment.

**Why this priority**: It lets the operator use their native `docker`/`compose` against a registered or provisioned host without the tool in the loop — the "help me configure my shell" core of the request — but it depends on the print/eval contract from US1 being solid.

**Independent Test**: `eval $(agent-container host env <name>)` sets the environment so `docker ps` lists that host's containers; the unset form (`eval $(agent-container host env --unset)`) reverts so `docker ps` targets the default again.

**Acceptance Scenarios**:

1. **Given** a registered/provisioned host, **When** the operator evals the host-env output, **Then** subsequent `docker`/`compose` commands in that shell target the host.
2. **Given** an active host-env, **When** the operator evals the unset output, **Then** the environment reverts to the prior/default target.
3. **Given** an **unknown/unregistered** host, **When** host-env is requested, **Then** nothing is emitted to stdout and the command exits non-zero (so `eval` runs nothing). A **registered-but-unreachable** host still emits (print does not probe, per FR-005); the operator's own `docker`/`compose` surfaces the unreachability after eval.

---

### User Story 3 - Toggle between print and execute (Priority: P3)

The same operation can either **print** the commands for the operator to run or **execute** them itself. Operators who want the current one-shot behavior keep it; operators who want to drive their own shell get the printable form. The choice is explicit and predictable.

**Why this priority**: Convenience layered on US1/US2; the underlying capability is the print contract, and executing is the pre-existing behavior. Valuable but not required to prove the feature.

**Independent Test**: For a print-capable operation, the default/execute mode runs it (reaching the live effect), while the print mode only emits the commands (no effect); both derive from the same command definition.

**Acceptance Scenarios**:

1. **Given** a print-capable operation, **When** the operator selects execute, **Then** the tool runs the command and produces the live effect (e.g. attaches).
2. **Given** the same operation, **When** the operator selects print, **Then** the tool emits the commands and does nothing else.
3. **Given** both modes, **When** compared, **Then** the printed command is byte-for-byte what the execute mode runs (no divergence).

---

### Edge Cases

- **Eval safety**: on any error, **nothing** is written to stdout and the exit code is non-zero, so `eval $(…)` never executes partial or broken configuration; the error explanation goes to stderr.
- **Stream discipline**: in print mode, stdout carries *only* the shell-evaluable text; every human-readable message, hint, or warning goes to stderr.
- **Quoting/escaping**: emitted commands and values are safe to `eval` in the target shell (no word-splitting or injection from names, paths, addresses).
- **No side effects from printing**: requesting the command/env does not create, connect, start, or mutate anything; running it twice yields identical output.
- **Shell dialects**: the default output is POSIX (bash/zsh); operators using another shell can request a compatible dialect (**fish** or **PowerShell/pwsh**), as `minikube docker-env --shell` does. Each dialect's quoting differs (POSIX `shlex`; fish single-quote escaping of `\`/`'`; PowerShell single-quote doubling `''`) and must be eval-safe in that shell.
- **Unset with nothing set**: the unset form is harmless (a no-op eval) when no env was set.
- **Target not found**: an **unknown/unregistered** name (or, for attach, no container) emits nothing to stdout, a clear stderr message, and a non-zero exit. Print does **not** probe reachability (registry-only) — a registered-but-unreachable/stopped host still emits its coordinates; only genuinely absent targets suppress output.
- **Parity source**: the printed form is generated from the *same* single definition the execute path uses, so they can never drift (Constitution IV/V).

## Requirements *(mandatory)*

### Functional Requirements

**Print mode (the eval contract)**

- **FR-001**: For its tool-invoking operations, the tool MUST offer a **print mode** that writes shell-evaluable configuration — environment-variable assignments and/or command lines — to **stdout only**, with no other content on stdout.
- **FR-002**: In print mode, all human-readable output (messages, hints, warnings, errors) MUST go to **stderr**, never stdout.
- **FR-003**: On any failure in print mode, the tool MUST emit **nothing to stdout** and exit **non-zero**, so `eval $(…)` executes nothing on error.
- **FR-004**: Emitted output MUST be **safe to `eval`** in the target shell — values and commands are quoted/escaped so a name, path, or address can never cause word-splitting or command injection.
- **FR-005**: Print mode MUST have **no side effects** — it does not create, start, connect, or mutate anything, and repeated invocations produce identical output.

**Attach / SSH (US1)**

- **FR-006**: The tool MUST be able to print the **runnable SSH+tmux attach command** for a container (correct user, the host's reachable address, the published port, and the tmux session), equivalent to what its own `attach` would run.
- **FR-007**: The tool MUST optionally emit an **SSH-config `Host` stanza** for a container so the operator can append it to their SSH config and connect by alias later.

**Host environment (US2)**

- **FR-008**: The tool MUST provide an **eval-able host environment** form that, when evaluated, makes the operator's own container tooling target a named host directly, plus a **matching unset** form that reverts it. The **default** output references the host's **registered runtime target** (docker `DOCKER_CONTEXT` / the podman connection), reusing the exact connection the tool established (including any socket-forward); a **flag** MUST offer the **raw-endpoint** form instead (`DOCKER_HOST=ssh://…` / `CONTAINER_HOST=…`) for portability where the registered context is absent. The output is derived **from registry/state only — no reachability probe, no connection** (consistent with FR-005): an **unknown** host emits nothing and exits non-zero, while a registered-but-unreachable host still emits.
- **FR-008a**: The **unset** form MUST be a **plain unset** of the variables it sets, reverting to the shell/daemon default (mirroring `minikube docker-env --unset`); it MUST NOT snapshot or restore a prior custom value and stores no new state, and is a harmless no-op when nothing was set.

**Execute toggle (US3)**

- **FR-009**: For print-capable operations the tool MUST let the operator choose to **execute** the commands itself instead of printing (preserving the existing one-shot behavior), with the selection explicit and predictable.
- **FR-010**: The printed commands MUST be generated from the **same single definition** the execute path uses, so print and execute never diverge.

**Cross-cutting**

- **FR-011**: The tool MUST support a **shell dialect selector** offering **POSIX sh (default), fish, and PowerShell (pwsh)** so the emitted assignments/commands fit the operator's shell — each rendered with that shell's own assignment/unset syntax and eval-safe quoting (e.g. PowerShell `$env:NAME='…'` / `Remove-Item Env:NAME`, evaluated via `Invoke-Expression`); additional dialects (csh, etc.) are deferred behind the same selector and are out of scope for this feature.
- **FR-012**: The print/emit seam MUST be **backend-extensible** — computing the action is separated from realizing it (print shell config, or execute), so additional emit backends (e.g. infrastructure-as-code such as Terraform or ARM/Bicep) can be added later without redesigning the action layer. Those IaC backends are **out of scope for this feature**; only the seam that admits them is in scope.
- **FR-013**: Documentation (README, CLAUDE.md, this spec) MUST be updated in the same change as any change to the print/eval contract or the operations that expose it.

### Key Entities *(include if data involved)*

- **Shell configuration output**: the eval-able artifact — zero or more environment-variable assignments and/or command lines, rendered for a target shell dialect, escaped to be `eval`-safe. Written to stdout; the sole stdout content in print mode.
- **Connection descriptor**: the resolved facts a container/host exposes — SSH user, reachable address, published port, tmux session name, and the host's container-runtime target (both its **registered context/connection reference** and its **raw endpoint**) — derived from the existing identity/addressing (001) and attach/session (004), read from registry/state without connecting. The single source from which both the printed command and the executed command are rendered, and from which host-env renders either the context-reference (default) or raw-endpoint (flagged) form.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running the printed attach command verbatim reaches the **same session** the tool's own attach reaches, in 100% of cases (byte-for-byte command parity with the execute path).
- **SC-002**: After `eval $(agent-container host env <name>)`, the operator's native container tooling targets that host (its containers are listed) with **no** tool wrapper; the unset form reverts it.
- **SC-003**: In print mode, stdout contains **only** shell-evaluable text — verifiable as zero non-config bytes on stdout across all print operations.
- **SC-004**: On every error path in print mode, stdout is **empty** and the exit code is **non-zero**, so `eval $(…)` never executes broken configuration — 100% of error cases.
- **SC-005**: Print produces **no side effects** — no container, connection, context, or file is created/changed by printing, and two consecutive prints are identical.
- **SC-006**: An operator can turn any print-capable operation into a shell alias/script and a matching `~/.ssh/config` entry using only the tool's emitted output (no hand-editing of addresses/ports/users).

## Assumptions

- **Default dialect POSIX; fish + PowerShell included**: emitted assignments/commands default to POSIX-sh (bash/zsh compatible) and this feature also ships **fish** and **PowerShell (pwsh)** dialects (selectable, mirroring `minikube docker-env --shell`); csh and other dialects are deferred behind the same selector. In PowerShell the eval idiom is `Invoke-Expression`/`iex` (there is no `eval $(…)`), so the emitted text must be a valid pwsh script fragment.
- **Existing verbs keep executing by default**: operations that execute today (notably `attach`) keep that default and gain an opt-in print flag; new emit-oriented subcommands (host-env, ssh-config, show-ssh-style) print by default because they exist to be evaluated. This preserves current behavior and matches the `eval $(…)` idiom.
- **Depends on 001/004**: reachable address, published port, host runtime target, and the canonical SSH+tmux attach come from Features 001 and 004; this feature exposes them and does not redefine addressing or session semantics.
- **Robustness benefit is inherent, not a new mechanism**: because the operator's own shell runs the emitted `ssh`/`docker`, their ssh-agent/smartcard/known_hosts/ssh-config handle the connection — the tool need not correctly drive those in every environment for the print path.
- **Single operator**: interactive and scripted use by one operator; no multi-user concerns.
- **No new stored state or secrets**: printing reads existing registry/state and emits text; it stores nothing new and never emits a secret to stdout (only connection coordinates and commands).
- **Scope of "tools"**: the print/eval surface targets the SSH/tmux attach path and host/container-runtime targeting first; extending print mode to other operations (e.g. logs, up) is possible later but not required for this feature.
- **Future IaC backends (anticipated, out of scope now)**: the same compute-action-then-realize seam is intended to later accept infrastructure-as-code emitters (Terraform, ARM/Bicep, others) — e.g. a provision that emits Terraform rather than driving a cloud API directly. This feature only establishes the seam (FR-012); no IaC backend is built here. This direction is also the strategic answer to the friction of the tool driving `ssh`/`docker context` internally (surfaced during cloud provisioning): emit for the operator's environment, or emit IaC, rather than invoke.
