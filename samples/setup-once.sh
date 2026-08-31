#!/bin/sh
# The ONE imperative step, run once per machine — everything else is YAML.
#
# It exists because a delivery identity is machine-local and must NEVER be
# committed. Constitution IX: secrets travel to a container over that
# container's own sshd, authenticated by an operator-DECLARED identity. The tool
# deliberately will not generate one for you — a tool-minted key would be a
# standing credential granting entry to every environment it ever deploys — so
# somebody has to declare one, and that somebody is you.
#
# Writes, at the USER config level (never into this repository):
#   ~/.config/agent-container/delivery_key{,.pub}   the identity
#   ~/.config/agent-container/settings.yaml         declares it
#   ~/.config/agent-container/authorized_keys       admits its public half
set -eu

# The SAME resolution the CLI uses, in the same order. Missing the
# AGENT_CONTAINER_ROOT step here would write the delivery identity somewhere the
# CLI does not read — and the symptom would be `apply` reporting "no delivery
# identity" while the file plainly exists, which sends you to look at the file
# rather than at the two different paths.
if [ -n "${AGENT_CONTAINER_CONFIG_DIR:-}" ]; then
    CFG="$AGENT_CONTAINER_CONFIG_DIR"
elif [ -n "${AGENT_CONTAINER_ROOT:-}" ]; then
    CFG="$AGENT_CONTAINER_ROOT/config"
else
    CFG="${XDG_CONFIG_HOME:-$HOME/.config}/agent-container"
fi
mkdir -p "$CFG"

if [ -f "$CFG/delivery_key" ]; then
    printf 'delivery identity already present: %s\n' "$CFG/delivery_key"
else
    ssh-keygen -q -t ed25519 -N '' -C 'agent-container-samples' -f "$CFG/delivery_key"
    printf 'created %s\n' "$CFG/delivery_key"
fi

# Merge rather than clobber: this file may already hold otlp_endpoint, claude_auth
# or a runtime choice, and a sample has no business discarding them.
if [ -f "$CFG/settings.yaml" ] && grep -q '^delivery_identity:' "$CFG/settings.yaml"; then
    printf 'settings.yaml already declares delivery_identity — left alone\n'
else
    printf 'delivery_identity: %s\n' "$CFG/delivery_key" >> "$CFG/settings.yaml"
    printf 'declared delivery_identity in %s\n' "$CFG/settings.yaml"
fi

# The key collection: the container REPLACES its managed region every boot, so
# removing a key here withdraws the access on the next deploy.
if [ -f "$CFG/authorized_keys" ] && grep -qF "$(cat "$CFG/delivery_key.pub")" "$CFG/authorized_keys"; then
    printf 'authorized_keys already admits it\n'
else
    cat "$CFG/delivery_key.pub" >> "$CFG/authorized_keys"
    printf 'admitted the public half in %s\n' "$CFG/authorized_keys"
fi

printf '\nDone. Now: export your keys, cd into a sample, and run `agent-container plan`.\n'
