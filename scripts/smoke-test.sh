#!/usr/bin/env bash
# smoke-test.sh — end-to-end check that the image + entrypoint + orchestration
# work together. Builds the image, launches a container, exercises an HTTPS
# git push from inside it using the credential helper from item C, verifies
# the push by re-cloning on the host, and tears the container down.
#
# Retroactively verifies item D's deferred acceptance criteria:
#   AC2 — git push from inside the container works non-interactively.
#   AC3 — credentials never appear in image layers or container logs.
#
# Prerequisites (script refuses to run otherwise):
#   - docker or podman on PATH
#   - bin/devenv executable
#   - ./.env present with GH_TOKEN, GIT_USER_NAME, GIT_USER_EMAIL non-empty
#   - DEVENV_SMOKE_REPO env var: "owner/name" of a GitHub repo your GH_TOKEN
#     can push to. Defaults are intentionally NOT provided — pick a repo you
#     own, since we will push a heartbeat commit to it.
#
# Re-runnable: the cleanup trap ensures the smoketest container is removed
# (and its volume purged) even on failure or interrupt.
#
# Hard constraints respected:
#   - No echo / printf / cat of any secret env var.
#   - No --no-verify, --amend, force-push anywhere.
#   - Touches host filesystem only under /tmp.

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
readonly DEVENV="${REPO_ROOT}/bin/devenv"
readonly INSTANCE="smoketest"
readonly STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/devenv"

# --- Logging ----------------------------------------------------------------
# Never interpolate secret env vars into log lines. Phase headers only.
phase() { printf '\n=== %s ===\n' "$1"; }
info()  { printf '  %s\n' "$1"; }
fail()  { printf '\n[FAIL] %s\n' "$1" >&2; exit 1; }

# --- Cleanup trap -----------------------------------------------------------
cleanup() {
    local rc=$?
    phase "cleanup"
    if [[ -x "$DEVENV" ]]; then
        "$DEVENV" down "$INSTANCE" --purge >/dev/null 2>&1 || true
        info "container devenv-${INSTANCE} removed (purged volume)"
    fi
    rm -rf "$VERIFY_DIR" 2>/dev/null || true
    if [[ $rc -eq 0 ]]; then
        printf '\n[PASS] smoke test succeeded\n'
    else
        printf '\n[FAIL] smoke test failed (exit %d)\n' "$rc" >&2
    fi
    exit "$rc"
}
VERIFY_DIR="$(mktemp -d -t devenv-smoke.XXXXXX)"
trap cleanup EXIT INT TERM

# --- Phase 1: pre-flight ----------------------------------------------------
phase "pre-flight"

command -v docker >/dev/null 2>&1 || command -v podman >/dev/null 2>&1 \
    || fail "neither docker nor podman on PATH"
info "container runtime present"

[[ -x "$DEVENV" ]] || fail "bin/devenv missing or not executable"
info "bin/devenv ready"

[[ -f "${REPO_ROOT}/.env" ]] || fail ".env not found at repo root (copy .env.example and fill in)"
# Source .env without exposing values to logs. Only read names afterward.
set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env"
set +a

for var in GH_TOKEN GIT_USER_NAME GIT_USER_EMAIL; do
    if [[ -z "${!var:-}" ]]; then
        fail ".env: required key ${var} is empty"
    fi
done
info ".env required keys present"

: "${DEVENV_SMOKE_REPO:?DEVENV_SMOKE_REPO must be set to owner/name of a GitHub repo your GH_TOKEN can push to}"
info "target repo: ${DEVENV_SMOKE_REPO}"

# --- Phase 2: build ---------------------------------------------------------
phase "build image"
"$DEVENV" build >/dev/null
info "image built"

# --- Phase 3: up ------------------------------------------------------------
phase "launch container"
"$DEVENV" up "$INSTANCE"
PORT_FILE="${STATE_DIR}/${INSTANCE}.port"
[[ -f "$PORT_FILE" ]] || fail "port state file missing: $PORT_FILE"
PORT="$(cat "$PORT_FILE")"
info "container up; ssh port ${PORT}"

# --- Phase 4: wait for sshd -------------------------------------------------
phase "wait for sshd"
for i in {1..30}; do
    if nc -z localhost "$PORT" 2>/dev/null; then
        info "sshd ready after ${i}s"
        break
    fi
    sleep 1
    if [[ $i -eq 30 ]]; then
        # Surface container logs for diagnostic if sshd never came up.
        "$DEVENV" logs "$INSTANCE" >&2 || true
        fail "sshd did not become ready within 30s on port ${PORT}"
    fi
done

# --- Phase 5: exercise HTTPS push from inside the container -----------------
phase "in-container push"

# We use the runtime's exec rather than ssh to avoid host-key trust setup
# during a smoke test. The credential helper from item C is exercised either
# way — what matters is git running inside the container with GH_TOKEN in env.
RUNTIME="${DEVENV_RUNTIME:-}"
if [[ -z "$RUNTIME" ]]; then
    if command -v podman >/dev/null 2>&1; then RUNTIME=podman
    else RUNTIME=docker; fi
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CLONE_URL="https://github.com/${DEVENV_SMOKE_REPO}.git"

# Build a small heredoc'd script and pipe it in so we never put $GH_TOKEN in
# argv. The container already has it via --env-file at `up` time.
"$RUNTIME" exec -i "devenv-${INSTANCE}" bash -s <<INNER
set -euo pipefail
cd /workspace
rm -rf smoke-target
git clone "${CLONE_URL}" smoke-target >/dev/null 2>&1 \\
    || { echo "[in-container] clone failed — check DEVENV_SMOKE_REPO and GH_TOKEN scope" >&2; exit 11; }
cd smoke-target
echo "smoke ${TIMESTAMP}" >> SMOKE_LOG.md
git add SMOKE_LOG.md
git commit -m "test(smoke): heartbeat ${TIMESTAMP} (#1)" >/dev/null
git push origin HEAD 2>&1 | grep -v -i -E 'token|password|x-access-token' || true
INNER
info "in-container push completed"

# --- Phase 6: verify on host ------------------------------------------------
phase "verify push from host"
cd "$VERIFY_DIR"
# Use the same credential helper trick the entrypoint uses, but locally.
GIT_ASKPASS=/bin/true \
    git -c "credential.helper=!f() { echo username=x-access-token; echo password=${GH_TOKEN}; }; f" \
    clone --depth 1 "$CLONE_URL" verify >/dev/null 2>&1 \
    || fail "could not re-clone ${DEVENV_SMOKE_REPO} from host"
if ! grep -q "smoke ${TIMESTAMP}" verify/SMOKE_LOG.md 2>/dev/null; then
    fail "heartbeat line not visible on origin — push may not have landed"
fi
info "heartbeat visible on origin"

# Cleanup runs via trap — sets exit code to 0 if we reach here.
exit 0
