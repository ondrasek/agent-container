#!/bin/sh
# Shared setup for the sample runs. SOURCED by each sample's run.sh, never run.
#
# Everything here goes through a DOCUMENTED SURFACE. Nothing writes into a
# container by hand, nothing edits a compose file, nothing sets an undocumented
# variable. That is deliberate: these samples double as a check that the
# documented conventions actually work, so if a convention breaks, the sample
# breaks with it rather than papering over it.

set -eu

SAMPLES_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SAMPLES_DIR/.." && pwd)
CLI="${AGENT_CONTAINER_CLI:-$REPO_ROOT/bin/agent-container}"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mnote:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31msamples:\033[0m %s\n' "$*" >&2; exit 2; }

# --- the agent and its credential -------------------------------------------
#
# Provider keys ride the `<name>.<provider>.key` convention: one file per
# provider, user level only, discovered by `up` with no flag. The value reaches
# the container over the container's OWN sshd (Constitution IX) and lands on a
# per-credential volume. It is never on argv, never in the compose file, and
# never in the environment file.
sample_agent() {
    AGENT="${SAMPLE_AGENT:-${1:-claude}}"
    CLAUDE_AUTH=""
    case "$AGENT" in
    claude)
        # Prefer a subscription token when present — it is the cheaper path for
        # anyone who has one, and it exercises the oauth arm.
        if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
            PROVIDER="claude-oauth"; KEY_ENV="CLAUDE_CODE_OAUTH_TOKEN"; CLAUDE_AUTH="oauth"
        else
            PROVIDER="anthropic";    KEY_ENV="ANTHROPIC_API_KEY";      CLAUDE_AUTH="api-key"
        fi
        ;;
    pi)
        PROVIDER="ollama"; KEY_ENV="OLLAMA_API_KEY"
        ;;
    *)
        die "unknown agent '$AGENT' — these samples support: claude, pi"
        ;;
    esac

    eval "KEY_VALUE=\${$KEY_ENV:-}"
    [ -n "$KEY_VALUE" ] || die "\$$KEY_ENV is not set.

  This sample makes a REAL, BILLABLE call to a model provider. Export the key
  for the agent you want to run:

    export ANTHROPIC_API_KEY=sk-ant-...       # claude, API key
    export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-... # claude, subscription (preferred)
    export OLLAMA_API_KEY=...                 # pi, via Ollama Cloud

  Then re-run:  ./run.sh $AGENT"
}

# --- an isolated, disposable configuration root ------------------------------
#
# AGENT_CONTAINER_ROOT relocates config, state AND data together. Using it here
# means a sample cannot disturb your real setup, and cleaning up is `rm -rf` on
# one directory. Never point this at $HOME.
sample_root() {
    NAME="$1"
    AGENT_CONTAINER_ROOT="${AGENT_CONTAINER_ROOT:-$HOME/.cache/agent-container-samples/$NAME}"
    export AGENT_CONTAINER_ROOT
    CFG="$AGENT_CONTAINER_ROOT/config"
    mkdir -p "$CFG"
    say "config root: $AGENT_CONTAINER_ROOT"

    # 1. The provider key, on its own volume by convention.
    printf '%s\n' "$KEY_VALUE" > "$CFG/$NAME.$PROVIDER.key"
    chmod 0600 "$CFG/$NAME.$PROVIDER.key"

    # 2. The delivery identity. Constitution IX: secrets travel to the container
    #    over its own sshd, authenticated by an operator-DECLARED identity. The
    #    tool never mints one — an undeclared identity is a refusal, not a
    #    fallback to a weaker channel — so the sample declares one here.
    if [ ! -f "$CFG/delivery_key" ]; then
        ssh-keygen -q -t ed25519 -N '' -C 'agent-container-sample' -f "$CFG/delivery_key"
    fi
    {
        printf 'delivery_identity: %s\n' "$CFG/delivery_key"
        [ -n "$CLAUDE_AUTH" ] && printf 'claude_auth: %s\n' "$CLAUDE_AUTH"
    } > "$CFG/settings.yaml"

    # 3. The key collection (Feature 020): the public half, so the container
    #    admits the identity above. The container REPLACES its managed region
    #    every boot, so removing a key here withdraws the access.
    cp "$CFG/delivery_key.pub" "$CFG/authorized_keys"

    # 4. Canonical config, where the agent needs any. Only the manifest's own file
    #    types are copied, and the directory is created ONLY if there is something
    #    to put in it — claude needs no delivered config, and an empty
    #    `<name>.config/claude/` would claim otherwise to anyone reading the tree.
    for f in "$SAMPLES_DIR/_common/agents/$AGENT"/*.json; do
        [ -e "$f" ] || continue
        mkdir -p "$CFG/$NAME.config/$AGENT"
        cp "$f" "$CFG/$NAME.config/$AGENT/"
    done
}

# --- the repository these samples push to ------------------------------------
#
# Samples 02-04 push real commits, so they need a repository YOU can write to.
# There is no default: pushing to somebody else's repository is not a sensible
# fallback, and a public one would let a dummy token appear to work.
sample_repo() {
    [ -n "${SAMPLE_REPO:-}" ] || die "\$SAMPLE_REPO is not set.

  This sample has the agent CLONE a repository, commit to it, and PUSH. That
  needs a repository you can write to — set it to your own:

    export SAMPLE_REPO=https://github.com/<you>/<a-scratch-repo>
    export SAMPLE_GH_TOKEN=ghp_...   # a PAT with 'repo' scope

  A throwaway repository is the right choice: every run pushes a new branch."
    [ -n "${SAMPLE_GH_TOKEN:-}" ] || die "\$SAMPLE_GH_TOKEN is not set (a PAT with 'repo' scope)."
}

# A token unique to this run, so a result can never be a leftover from the last
# one — the workspace volume persists, which is exactly how that would happen.
sample_token() {
    printf 'SAMPLE-%s' "$(od -An -tx1 -N6 /dev/urandom | tr -d ' \n')"
}

# Render a task template: @TOKEN@, @BRANCH@ and @DIR@ are substituted.
sample_task() {
    sed -e "s|@TOKEN@|$2|g" -e "s|@BRANCH@|${3:-}|g" -e "s|@DIR@|${4:-}|g" "$1"
}

sample_cleanup_hint() {
    cat <<EOF

--- done ----------------------------------------------------------------------
Inspect:   AGENT_CONTAINER_ROOT=$AGENT_CONTAINER_ROOT $CLI logs $1
Attach:    AGENT_CONTAINER_ROOT=$AGENT_CONTAINER_ROOT $CLI attach $1
Remove:    AGENT_CONTAINER_ROOT=$AGENT_CONTAINER_ROOT $CLI purge $1 --yes
Remove all state for this sample:  rm -rf $AGENT_CONTAINER_ROOT
EOF
}

# Render a task template to a file inside the disposable root and echo the path.
# `--task @FILE` is a documented surface, and it keeps a multi-line task off argv.
sample_task_file() {
    _out="$AGENT_CONTAINER_ROOT/task.txt"
    sample_task "$@" > "$_out"
    printf '%s' "$_out"
}

# The env file carries GH_TOKEN. It lives in the disposable root at 0600, never
# in the repository — which is why these samples read the PAT from your
# environment instead of shipping a file for you to fill in.
sample_env_file() {
    _out="$AGENT_CONTAINER_ROOT/env"
    umask 077
    {
        printf 'GH_TOKEN=%s\n' "$SAMPLE_GH_TOKEN"
        printf 'GIT_USER_NAME=%s\n' "${SAMPLE_GIT_NAME:-agent-container sample}"
        printf 'GIT_USER_EMAIL=%s\n' "${SAMPLE_GIT_EMAIL:-sample@example.invalid}"
    } > "$_out"
    printf '%s' "$_out"
}
