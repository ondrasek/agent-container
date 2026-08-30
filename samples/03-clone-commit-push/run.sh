#!/bin/sh
# Sample 03 — clone on start, generate data, transform it, report, PUSH.
# Usage:  ./run.sh [claude|pi]
. "$(dirname -- "$0")/../_common/lib.sh"

sample_agent "${1:-claude}"
sample_repo
NAME="sample03$AGENT"
sample_root "$NAME"

TOKEN=$(sample_token)
BRANCH="sample/pipeline-$AGENT-$TOKEN"
DIR="data/$AGENT-$TOKEN"
TASKFILE=$(sample_task_file "$(dirname -- "$0")/task.txt" "$TOKEN" "$BRANCH" "$DIR")
ENVFILE=$(sample_env_file)

say "cloning $SAMPLE_REPO; the agent will push branch $BRANCH"
"$CLI" up "$NAME" \
    --mode headless \
    --agent "$AGENT" \
    --workspace persistent \
    --repo "$SAMPLE_REPO" \
    --env-file "$ENVFILE" \
    --foreground \
    --task "@$TASKFILE"

cat <<EOF

--- verify on the forge -------------------------------------------------------
Three commits should be on branch $BRANCH, and summary.md must AGREE with
input.csv. Recompute it yourself — that is the part a fabricated answer fails:

  git clone --branch $BRANCH $SAMPLE_REPO /tmp/check-$TOKEN
  cd /tmp/check-$TOKEN
  cat $DIR/summary.md
  awk -F, 'NR>1 {n++; s+=\$3} END {print "ROWS="n; print "TOTAL="s}' $DIR/input.csv
EOF
sample_cleanup_hint "$NAME"
