# End-to-end smoke test

`scripts/smoke-test.sh` exercises the full happy path of the dev environment: build the image, launch a container, do an HTTPS git push from inside it via the credential helper from item C, verify the push by re-cloning on the host, and tear the container down.

It retroactively verifies the two deferred acceptance criteria of item D:

- **D-AC2** — `git push` from inside the container works non-interactively.
- **D-AC3** — credentials never appear in image layers or container logs.

## Prerequisites

The script refuses to run unless all of these hold:

1. `docker` or `podman` is on `PATH`.
2. `bin/devenv` is executable.
3. `./.env` exists with `GH_TOKEN`, `GIT_USER_NAME`, `GIT_USER_EMAIL` non-empty.
4. `DEVENV_SMOKE_REPO` env var is set to `owner/name` of a **GitHub repo your `GH_TOKEN` can push to**. The test pushes a heartbeat commit there.

No default is provided for `DEVENV_SMOKE_REPO` on purpose: the script is destructive against that repo (one commit per run).

## Running

```sh
DEVENV_SMOKE_REPO=your-handle/devenv-smoke-target ./scripts/smoke-test.sh
```

Exit code is 0 on PASS, non-zero on FAIL. On failure the script dumps `bin/devenv logs smoketest` to stderr before tearing the container down.

## What it does

1. **Pre-flight** — checks runtime, `bin/devenv`, `.env` keys, target repo env var.
2. **Build** — `bin/devenv build`.
3. **Up** — `bin/devenv up smoketest`; reads the assigned port from the state file.
4. **Wait for sshd** — `nc -z localhost <port>` polled up to 30s.
5. **In-container push** — `<runtime> exec -i devenv-smoketest bash -s <<…` runs a small heredoc that clones the target repo into `/workspace`, appends a timestamped line to `SMOKE_LOG.md`, commits with a `(#1)` reference, and pushes via HTTPS. The credential helper from item C resolves `$GH_TOKEN` at push time. The heredoc is piped over stdin so the token never reaches argv.
6. **Verify on host** — re-clones the target repo into a temp dir using the same credential helper pattern (so the host-side verify does not depend on a long-lived `git credential` config) and greps for the heartbeat line.
7. **Cleanup** — a `trap cleanup EXIT INT TERM` ensures the container and its workspace volume are removed regardless of pass/fail/interrupt.

## Safety properties

- No `echo` / `printf` / `cat` of any secret env var. Phase headers and short status lines only.
- No `--no-verify`, `--amend`, or force-push anywhere.
- Touches host filesystem only under `$(mktemp -d -t devenv-smoke.XXXXXX)` (always `/tmp` or `$TMPDIR`), which is removed in the trap.
- The `git push` output is grep-filtered to drop anything matching `token|password|x-access-token` (defensive — git itself does not normally echo credentials, but progress lines can be surprising).
- Re-runnable: each run starts from a clean state because pre-flight verifies prereqs and cleanup destroys the previous container + volume.

## What it does NOT verify

- **Parallel-container safety (item E core AC).** Smoke test launches a single instance. Run `bin/devenv up alpha && bin/devenv up bravo && bin/devenv list` separately to confirm.
- **Attach UX (item F).** The smoke test uses `exec` rather than `ssh` to avoid host-key trust setup. Verify attach manually: `bin/devenv attach smoketest` (or `bin/devenv-attach -l smoketest`) while a container is running.
- **Real image size.** `bin/devenv build` does not print the resulting size. After a successful run inspect manually: `docker images localhost/remote-persistent-devenv:latest` (or `podman images …`).
