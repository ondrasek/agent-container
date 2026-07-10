# Contract: Driver (internal)

A Driver abstracts *how to build/run/connect* on a Host so local and remote share one path. Resolved from a Host record at call time; never persisted. Implemented as a small set of pure functions returning argv (testable without a runtime — the existing `test_command_construction` pattern).

## Operations

| Operation | Signature (conceptual) | Contract |
|-----------|------------------------|----------|
| `runtime_argv` | `(host) → list[str]` | Base argv targeting the host. docker: `["docker","--context",host.context]`; podman: `["podman","--connection",host.context]`. |
| `compose_argv` | `(host, project, file, *args) → list[str]` | `runtime_argv(host) + ["compose","-p",project,"-f",str(file), *args]`. |
| `up_argv` | `(host, project, file) → list[str]` | `compose_argv(..., "up","-d","--build")`. |
| `down_argv` | `(host, project, file, purge) → list[str]` | `compose_argv(..., "down")` (+ `--volumes` if purge). |
| `ps_on_host` | `(host) → list[container]` | Live query of the host's daemon: which agent-container projects run there. Source of truth for teardown-safety. |
| `reachable_address` | `(host) → str` | `host.address`. |
| `capability_check` | `(host) → None` | Raise a clear Fatal if the target lacks a compose-capable runtime. |

## Invariants

- **No secret on argv** (Constitution III): identity/token material is never a positional/flag; it flows via compose `secrets`/`configs` (files) or env.
- **Pure/derived**: argv builders are deterministic functions of `(host, name)` — no hidden state, unit-testable.
- **Runtime-agnostic identity**: project/port/volume derivation is driver-independent (a Deployment on docker and on podman shares identity values).
- **Fail fast**: an unreachable host or missing runtime surfaces at the driver boundary with a diagnostic, not a partial deploy (FR-022, Edge: unreachable target).

## Driver kinds

- **DockerContextDriver** — primary; supports local and `ssh://` remote; the validated remote path.
- **PodmanConnectionDriver** — local parity; remote best-effort (R1).
- **ExistingSshDriver** — attach-only legacy host; supports `reachable_address` for `attach`, rejects deploy operations with a clear message.
