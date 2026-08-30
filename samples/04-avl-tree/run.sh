#!/bin/sh
# Sample 04 — the agent writes real software: an AVL tree, unit tests and a TUI.
# Usage:  ./run.sh [claude|pi]
. "$(dirname -- "$0")/../_common/lib.sh"

sample_agent "${1:-claude}"
sample_repo
NAME="sample04$AGENT"
sample_root "$NAME"

TOKEN=$(sample_token)
BRANCH="sample/avl-$AGENT-$TOKEN"
DIR="avl/$AGENT-$TOKEN"
TASKFILE=$(sample_task_file "$(dirname -- "$0")/task.txt" "$TOKEN" "$BRANCH" "$DIR")
ENVFILE=$(sample_env_file)

say "$AGENT will implement an AVL tree and push branch $BRANCH"
"$CLI" up "$NAME" \
    --mode headless \
    --agent "$AGENT" \
    --workspace persistent \
    --repo "$SAMPLE_REPO" \
    --env-file "$ENVFILE" \
    --foreground \
    --task "@$TASKFILE"

# --- verify by RUNNING it, in a throwaway container with no network ----------
say "fetching what the agent pushed"
WORK="$AGENT_CONTAINER_ROOT/verify"
rm -rf "$WORK"
git clone --quiet --depth 1 --branch "$BRANCH" "$SAMPLE_REPO" "$WORK" \
    || die "branch $BRANCH is not on the forge — nothing was pushed"
[ -f "$WORK/$DIR/avl.py" ] || die "$DIR/avl.py is missing from the pushed branch"

if grep -riqE '^\s*(import|from)\s+(avltree|bintrees|sortedcontainers)' "$WORK/$DIR/avl.py"; then
    die "avl.py IMPORTS a third-party tree instead of implementing one"
fi

cp "$(dirname -- "$0")/verify.py" "$WORK/$DIR/verify.py"
RUNTIME="${AGENT_CONTAINER_RUNTIME:-podman}"
say "running the agent's own unittest suite AND the property check (no network)"
"$RUNTIME" run --rm --network none -v "$WORK/$DIR:/w:ro" -w /w python:3.13-slim \
    sh -c 'python -m unittest discover -p "test_*.py" -v && python verify.py && printf "i 5\ni 3\ni 8\np\nq\n" | python tui.py' \
    || die "the agent's code does not work: its tests, the balance property, or the TUI failed"

say "PASS — the agent wrote an AVL tree that is genuinely balanced, tested and runnable"
say "browse it:  $WORK/$DIR"
sample_cleanup_hint "$NAME"
