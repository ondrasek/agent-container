# End-to-end smoke test

`scripts/smoke-test.sh` exercises the full happy path of the dev environment: build the image, launch a container, do an HTTPS git push from inside it via the credential helper from item C, verify the push by re-cloning on the host, and tear the container down.

It retroactively verifies the two deferred acceptance criteria of item D:

- **D-AC2** — `git push` from inside the container works non-interactively.
- **D-AC3** — credentials never appear in image layers or container logs.

## Prerequisites

The script refuses to run unless all of these hold:

1. `docker` or `podman` is on `PATH`.
2. `agent-container` is executable.
3. `./.env` exists with `GH_TOKEN`, `GIT_USER_NAME`, `GIT_USER_EMAIL` non-empty.
4. `AGENT_CONTAINER_SMOKE_REPO` env var is set to `owner/name` of a **GitHub repo your `GH_TOKEN` can push to**. The test pushes a heartbeat commit there.

No default is provided for `AGENT_CONTAINER_SMOKE_REPO` on purpose: the script is destructive against that repo (one commit per run).

## Running

```sh
AGENT_CONTAINER_SMOKE_REPO=your-handle/agent-container-smoke-target ./scripts/smoke-test.sh
```

Exit code is 0 on PASS, non-zero on FAIL. On failure the script dumps `agent-container logs smoketest` to stderr before tearing the container down.

## What it does

1. **Pre-flight** — checks runtime, `agent-container`, `.env` keys, target repo env var.
2. **Build** — `agent-container build`.
3. **Up** — `agent-container up smoketest`; reads the assigned port from the state file.
4. **Wait for sshd** — `nc -z localhost <port>` polled up to 30s.
5. **In-container push** — `<runtime> exec -i agent-container-smoketest bash -s <<…` runs a small heredoc that clones the target repo into `/workspace`, appends a timestamped line to `SMOKE_LOG.md`, commits with a `(#1)` reference, and pushes via HTTPS. The credential helper from item C resolves `$GH_TOKEN` at push time. The heredoc is piped over stdin so the token never reaches argv.
6. **Verify on host** — re-clones the target repo into a temp dir using the same credential helper pattern (so the host-side verify does not depend on a long-lived `git credential` config) and greps for the heartbeat line.
7. **Cleanup** — a `trap cleanup EXIT INT TERM` ensures the container and its workspace volume are removed regardless of pass/fail/interrupt.

## Safety properties

- No `echo` / `printf` / `cat` of any secret env var. Phase headers and short status lines only.
- No `--no-verify`, `--amend`, or force-push anywhere.
- Touches host filesystem only under `$(mktemp -d -t agent-container-smoke.XXXXXX)` (always `/tmp` or `$TMPDIR`), which is removed in the trap.
- The `git push` output is grep-filtered to drop anything matching `token|password|x-access-token` (defensive — git itself does not normally echo credentials, but progress lines can be surprising).
- Re-runnable: each run starts from a clean state because pre-flight verifies prereqs and cleanup destroys the previous container + volume.

## What it does NOT verify

- **Parallel-container safety (item E core AC).** Smoke test launches a single instance. Run `agent-container up alpha && agent-container up bravo && agent-container list` separately to confirm.
- **Attach UX (item F).** The smoke test uses `exec` rather than `ssh` to avoid host-key trust setup. Verify attach manually: `agent-container attach smoketest` (or `agent-container attach --local smoketest`) while a container is running.
- **Real image size.** `agent-container build` does not print the resulting size. After a successful run inspect manually: `docker images localhost/agent-container:latest` (or `podman images …`).
