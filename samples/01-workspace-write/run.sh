#!/bin/sh
# Sample 01 — a real agent runs headless and writes to the workspace.
# Usage:  ./run.sh [claude|pi]
. "$(dirname -- "$0")/../_common/lib.sh"

sample_agent "${1:-claude}"
NAME="sample01$AGENT"
sample_root "$NAME"

TOKEN=$(sample_token)
TASKFILE=$(sample_task_file "$(dirname -- "$0")/task.txt" "$TOKEN")

say "running $AGENT headless; token $TOKEN"
"$CLI" up "$NAME" \
    --mode headless \
    --agent "$AGENT" \
    --workspace persistent \
    --foreground \
    --task "@$TASKFILE"

say "checking the workspace VOLUME for $TOKEN"
RUNTIME="${AGENT_CONTAINER_RUNTIME:-podman}"
if "$RUNTIME" run --rm -v "agent-container-$NAME-workspace:/w:ro" alpine:3 \
        sh -c "grep -rl '$TOKEN' /w 2>/dev/null | head -1" | grep -q .; then
    say "PASS — the agent used its tools and the file is on the volume"
else
    die "the run reported success but nothing on the volume contains $TOKEN"
fi

say "the run record:"
"$CLI" runs list "$NAME" || true
sample_cleanup_hint "$NAME"
