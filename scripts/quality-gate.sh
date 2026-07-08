#!/usr/bin/env bash
# Quality gate — the single set of fast, hermetic checks that gate a change.
# Used two ways from ONE source of truth (constitution: verify before trust):
#   - Claude Code Stop hook (local): a non-zero exit (2) feeds the failure to
#     Claude as a fix prompt — the fail-fast loop. Register it per-clone in
#     .claude/settings.json (that dir is gitignored), e.g.:
#       "hooks": { "Stop": [ { "hooks": [ { "type": "command",
#         "command": "${CLAUDE_PROJECT_DIR}/scripts/quality-gate.sh",
#         "timeout": 180 } ] } ] }
#   - CI (`quality-gate` job): runs this same script; any non-zero exit hard-
#     fails the job, and because release.yml gates on `ci` success, a failing
#     gate blocks the release (Principle VII).
#
# Fail-fast: stop at the first failing check and emit its full output. The
# real-container acceptance suite is intentionally NOT here — it is the slow,
# authoritative CI-only layer (bin/tests/test_acceptance.py, `pytest -m acceptance`).
set -o pipefail
cd "$(dirname "$0")/.." || exit 1  # repo root

HOOK_LOG="${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/quality-gate.log"
debuglog() {
    mkdir -p "$(dirname "$HOOK_LOG")" 2>/dev/null
    echo "[quality-gate] $(date '+%Y-%m-%d %H:%M:%S') $1" >> "$HOOK_LOG" 2>/dev/null || true
}
debuglog "=== started (pid=$$) ==="

# Per-check diagnostic hints — specific, tell Claude what to read and how to re-check.
declare -A TOOL_HINTS
TOOL_HINTS=(
    [ruff-check]="Run 'uv run --no-project --with ruff ruff check --output-format=full' for details. Most issues auto-fix with '... ruff check --fix'. Read the reported file before editing."
    [ruff-format]="Run 'uv run --no-project --with ruff ruff format' to auto-fix formatting."
    [self-test]="'./bin/agent-container --self-test' failed — a doctest or the port-hash/key-derivation corpus regressed. Read the failing doctest in bin/agent-container; fix the code, or the doctest if the on-disk contract intentionally changed."
    [pytest]="Read the failing test and the code it exercises. Re-run one test: 'uv run --no-project --with pytest --with typer --with questionary --with rich pytest bin/tests/test_FILE.py::test_NAME -x --tb=long'. Fix the source, not the test, unless the test is wrong."
    [shell-entrypoint]="bin/tests/test_entrypoint.sh failed — entrypoint tmux-layout / git-credential / host-key logic. Read entrypoint.sh and the failing assertion label."
    [shell-completions]="bin/tests/test_completions.sh failed — bash/zsh completion parity or an injection guard. Read completions/agent-container.{bash,zsh}."
    [shell-tmux-layout]="bin/tests/test_entrypoint_tmux_layout.sh failed — real-tmux window layout. Read the tmux section of entrypoint.sh."
)

fail() {
    local name="$1" cmd="$2" output="$3" hint="${TOOL_HINTS[$name]:-}"
    {
        echo ""
        echo "QUALITY GATE FAILED [$name]:"
        echo "Command: $cmd"
        echo ""
        echo "$output"
        echo ""
        [ -n "$hint" ] && { echo "Hint: $hint"; echo ""; }
        echo "ACTION REQUIRED: You MUST fix the issue above. Do NOT stop or explain — read the failing file, edit the source, and the gate re-runs automatically."
    } >&2
    debuglog "=== FAILED: $name ==="
    exit 2
}

run_check() {
    local name="$1"; shift
    local cmd="$*" out
    debuglog "running $name..."
    out=$("$@" 2>&1) || fail "$name" "$cmd" "$out"
}

RUFF=(uv run --no-project --with ruff ruff)
PYT=(uv run --no-project --with pytest --with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' --with 'rich>=13,<15' pytest)

# Ordered fastest / most-likely-to-fail first.
run_check "ruff-check"        "${RUFF[@]}" check
run_check "ruff-format"       "${RUFF[@]}" format --check
run_check "self-test"         ./bin/agent-container --self-test
run_check "pytest"            "${PYT[@]}" bin/tests -x -q
run_check "shell-entrypoint"      bash bin/tests/test_entrypoint.sh
run_check "shell-completions"     bash bin/tests/test_completions.sh
run_check "shell-tmux-layout"     bash bin/tests/test_entrypoint_tmux_layout.sh

debuglog "=== ALL CHECKS PASSED ==="
exit 0
