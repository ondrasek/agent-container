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

# `-r` REMOVES instead of storing. Revocation goes through the same script as
# delivery so the container keeps owning its layout: the CLI names a credential, it
# does not name a path. Deleting the value takes effect on a RUNNING container, which
# `docker volume rm` cannot do while the volume is in use.
remove=0
if [[ "${1:-}" == "-r" ]]; then remove=1; shift; fi
[[ $# -eq 1 ]] || die "usage: agent-container-receive-secret [-r] <kind>/<name>"
ref="$1"

# A strict charset, anchored, with no '.' at all — so '..' cannot appear and the ref
# can never escape SECRETS_DIR. Rejecting is safe here: the tool controls these names,
# so a rejection means a bug rather than an operator mistake.
# UPPERCASE is allowed as well as lowercase, because an `env/<NAME>` ref carries the
# environment-variable name verbatim and those are conventionally uppercase. Case is
# the only thing that widened: still no '.' at all, so '..' cannot appear and the ref
# cannot escape SECRETS_DIR.
[[ "${ref}" =~ ^[A-Za-z0-9]([A-Za-z0-9_-]*)?(/[A-Za-z0-9]([A-Za-z0-9_-]*)?)?$ ]] \
    || die "refusing malformed secret ref: ${ref}"

# `env` joins `apikey`: a credential the agent reads from the ENVIRONMENT (GH_TOKEN,
# a provider key with no entry in the tool's provider table). It arrives the same way
# every other secret does — over this container's own sshd, onto its own volume —
# rather than through a staged file the compose model references (Constitution IX).
case "${ref%%/*}" in
    apikey|env|sentinel) ;;
    *) die "unknown secret kind: ${ref%%/*}" ;;
esac

# <ref>/value: each credential is mounted as its OWN volume, and a volume mounts as a
# directory, so the value lives in a file inside it. That mount point is also the
# lifecycle handle — `docker volume rm` on it revokes exactly this one credential.
target="${SECRETS_DIR}/${ref}/value"

if ((remove)); then
    rm -f "${target}"
    exit 0
fi
umask 077
mkdir -p "$(dirname "${target}")"

# The directory is created dev-owned in the image; refuse if something replaced it
# with a symlink or handed it to someone else, rather than writing through it.
[[ -L "${target}" ]] && die "refusing: ${target} is a symlink"

if [[ "${ref}" == sentinel* ]]; then
    # The sentinel carries the DELIVERY ID, not just existence: the container must be
    # able to tell "a delivery already happened" (restart — proceed) from "a NEW
    # delivery is coming" (rotation — wait, or the old value is read first and the
    # rotation silently does not take effect).
    mkdir -p "$(dirname "${target}")"
    cat > "${target}"
else
    # REPLACE, never append or open-for-write: the previous value is stored 0400, so
    # `cat >` onto it fails with EACCES even for its owner — which broke ROTATION,
    # since re-delivering a changed key is exactly an overwrite. Written to a temp and
    # moved so a reader never sees a half-written credential.
    rm -f "${target}.new"
    cat > "${target}.new"
    chmod 0400 "${target}.new"
    mv -f "${target}.new" "${target}"
fi
