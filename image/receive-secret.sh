#!/usr/bin/env bash
# Receive ONE secret over SSH and store it where it belongs (Constitution IX).
#
# The CONTAINER owns the layout, not the CLI. The tool hands over a logical name and
# the value on stdin; deciding where that lands, with what mode, is this script's job.
# Without this seam the CLI would have to know in-container paths, and every change to
# them would be a change to the deployment side too.
#
# Invoked as:  agent-container-receive-secret <kind>/<name>   (value on STDIN)
#
# STDIN, never argv: an argument is world-readable through the process table for as
# long as the process lives.
set -euo pipefail

SECRETS_DIR="${AGENT_CONTAINER_SECRETS_DIR:-/run/agent-container-secrets}"

die() { printf 'receive-secret: %s\n' "$*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "usage: agent-container-receive-secret <kind>/<name>"
ref="$1"

# A strict charset, anchored, with no '.' at all — so '..' cannot appear and the ref
# can never escape SECRETS_DIR. Rejecting is safe here: the tool controls these names,
# so a rejection means a bug rather than an operator mistake.
[[ "${ref}" =~ ^[a-z0-9]([a-z0-9_-]*)?(/[a-z0-9]([a-z0-9_-]*)?)?$ ]] \
    || die "refusing malformed secret ref: ${ref}"

case "${ref%%/*}" in
    apikey|sentinel) ;;
    *) die "unknown secret kind: ${ref%%/*}" ;;
esac

# <ref>/value: each credential is mounted as its OWN volume, and a volume mounts as a
# directory, so the value lives in a file inside it. That mount point is also the
# lifecycle handle — `docker volume rm` on it revokes exactly this one credential.
target="${SECRETS_DIR}/${ref}/value"
umask 077
mkdir -p "$(dirname "${target}")"

# The directory is created dev-owned in the image; refuse if something replaced it
# with a symlink or handed it to someone else, rather than writing through it.
[[ -L "${target}" ]] && die "refusing: ${target} is a symlink"

if [[ "${ref}" == sentinel* ]]; then
    mkdir -p "$(dirname "${target}")"
    : > "${target}"
else
    cat > "${target}"
    chmod 0400 "${target}"
fi
