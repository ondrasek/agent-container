#!/usr/bin/env bash
# entrypoint.sh — STUB. REPLACED BY ITEM C.
#
# Item B (image build) only needs a runnable ENTRYPOINT so the image can be
# smoke-tested for build success and `sshd` foreground startup. The real
# entrypoint logic — git identity, credential helper, tmux session, env-var
# validation, host-key generation — lands in item C, which will OVERWRITE
# this file in place. Keep the path and exec semantics the same so the
# Dockerfile reference doesn't need to change.
#
# Behavior of this stub:
#   1. If /etc/ssh has no host keys, generate them (sshd refuses to start otherwise).
#   2. exec sshd in the foreground so the container's PID 1 is sshd and logs
#      go to the runtime's log stream.
#
# This stub intentionally does NOT:
#   - Read GH_TOKEN / GIT_USER_* / provider keys.
#   - Configure git credential helper.
#   - Start a tmux session.
#   - Validate required env vars.
# All of the above are item C's responsibility.

set -euo pipefail

# Host keys are deliberately absent from the image (see Dockerfile). Generate
# on first launch so each container instance has a distinct identity.
if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
    sudo ssh-keygen -A
fi

# sshd needs /run/sshd to exist for the privilege separation directory.
sudo mkdir -p /run/sshd
sudo chmod 0755 /run/sshd

# Foreground sshd: -D = no daemonize, -e = log to stderr.
exec sudo /usr/sbin/sshd -D -e
