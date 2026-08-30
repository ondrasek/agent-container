#!/bin/sh
# Sample 02 — the same real work, done from BEHIND a declared egress boundary.
# Usage:  ./run.sh [claude|pi]
. "$(dirname -- "$0")/../_common/lib.sh"

sample_agent "${1:-claude}"
sample_repo
NAME="sample02$AGENT"
sample_root "$NAME"

# The model API differs per agent. `provider: anthropic` is a NAMED provider the
# tool expands; ollama.com is declared as a plain host.
case "$AGENT" in
claude) ALLOW='        - provider: anthropic
        - host: github.com' ;;
pi) ALLOW='        - host: ollama.com
        - host: github.com' ;;
esac

# A project directory: `.agent-container/` beside the code, which is what makes
# this a declarative deployment rather than a pile of flags.
PROJ="$AGENT_CONTAINER_ROOT/project"
mkdir -p "$PROJ/.agent-container"
# The allow-list is spliced in with `sed … r`, not passed as an awk variable:
# awk -v cannot carry an embedded newline, and a multi-line value makes it fail
# with "newline in string" — which it does BEFORE writing anything, so the
# deployment then reads a file that was never created.
ALLOWFILE="$AGENT_CONTAINER_ROOT/allow.yaml"
printf '%s\n' "$ALLOW" > "$ALLOWFILE"
sed -e "s|@NAME@|$NAME|g" -e "s|@AGENT@|$AGENT|g" \
    -e "/@ALLOW@/r $ALLOWFILE" -e "/@ALLOW@/d" \
    "$(dirname -- "$0")/environments.yaml.template" \
    > "$PROJ/.agent-container/environments.yaml"

umask 077
{
    printf 'GH_TOKEN=%s\n' "$SAMPLE_GH_TOKEN"
    printf 'GIT_USER_NAME=%s\n' "${SAMPLE_GIT_NAME:-agent-container sample}"
    printf 'GIT_USER_EMAIL=%s\n' "${SAMPLE_GIT_EMAIL:-sample@example.invalid}"
} > "$PROJ/.agent-container/$NAME.env"

TOKEN=$(sample_token)
BRANCH="sample/egress-$AGENT-$TOKEN"
DIR="data/egress-$AGENT-$TOKEN"
TASKFILE=$(sample_task_file "$(dirname -- "$0")/../03-clone-commit-push/task.txt" \
    "$TOKEN" "$BRANCH" "$DIR")

say "project: $PROJ"
say "declared egress:"
sed 's/^/    /' "$PROJ/.agent-container/environments.yaml" | tail -n +2

cd "$PROJ"
"$CLI" up "$NAME" \
    --mode headless \
    --agent "$AGENT" \
    --workspace persistent \
    --repo "$SAMPLE_REPO" \
    --foreground \
    --task "@$TASKFILE"

say "proving the boundary was actually there (not a run that merely passed):"
RUNTIME="${AGENT_CONTAINER_RUNTIME:-podman}"
if "$RUNTIME" ps -a --filter "name=agent-egress-$NAME" --format '{{.Names}}' | grep -q .; then
    say "PASS — sidecar agent-egress-$NAME exists; the work crossed a real boundary"
else
    die "no egress sidecar: the run passed WITHOUT a boundary, so it proves nothing about egress"
fi

# `egress <name>` is the DURABLE record of what the boundary refused, and of
# anything it permitted that the declaration does not name. Silence here means
# nothing was refused — which is the result you want, and the command says so
# rather than answering with nothing.
say "what the boundary recorded (silence = nothing was refused):"
"$CLI" egress "$NAME" || true
sample_cleanup_hint "$NAME"
