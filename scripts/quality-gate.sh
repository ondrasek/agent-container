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

# Pin every `uv run` below to the support floor (mirrors requires-python). The
# source uses 3.14-only syntax (PEP 758 parenthesis-less except); without this
# an `--no-project` run on a host/CI box whose default python is < 3.14 would
# SyntaxError. uv fetches 3.14 if absent. Bump this in lockstep with the floor.
export UV_PYTHON="${UV_PYTHON:-3.14}"

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
    [ty]="A type error in bin/agent-container (ty, targeting the requires-python floor). Read the reported line. Common fixes: annotate/narrow None (a None-guard that calls die()/raise makes ty see the branch as terminating), correct return types, fix argument types. Re-check by re-running scripts/quality-gate.sh (it reuses the cached ty venv), or directly: \"\$TYVENV/bin/ty check --python \$TYVENV bin/agent-container\"."
    [bandit]="A MEDIUM-or-higher security finding in bin/agent-container. Read the flagged line. Typical fixes: never pass shell=True (use an argv list), use the 'secrets' module (not 'random') for tokens/keys, avoid eval/exec, never hardcode credentials. NOTE: low-severity subprocess notes (B603/B607/B404/B606) are expected for this container CLI and are filtered out by -ll — do NOT try to silence them."
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

# App runtime deps (mirrors the PEP 723 block); pytest runs inside this uv env.
DEPS=(--with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' --with 'rich>=13,<15')
RUFF=(uv run --no-project --with ruff ruff)
BANDIT=(uv run --no-project --with bandit bandit)
# pytest-github-actions-annotate-failures turns failures into inline GitHub
# annotations (file:line) under Actions; it auto-detects GITHUB_ACTIONS and is a
# no-op locally, so it rides in the one shared pytest env without changing local
# behavior. It's a test-only plugin — never a runtime dep of the CLI.
PYT=(uv run --no-project "${DEPS[@]}" --with pytest
     --with 'pytest-github-actions-annotate-failures>=0.2,<1' pytest)

# ty resolves third-party imports against a Python environment. Left to its own
# discovery it picks the system interpreter (on CI that is /usr/lib/python3.12,
# which lacks typer/questionary) — NOT uv's `--with` overlay and NOT ty's own
# install venv. So build a 3.14 venv holding the runtime deps and point ty at it
# EXPLICITLY with `--python` below; without that flag ty ignores this venv and
# reports unresolved-import on a clean checkout. Cache it in a temp dir: first
# build ~3s, cached runs instant; CI's temp dir is fresh each run so it builds
# once. The cache lives in a VOLATILE temp dir, so its packages can vanish
# (TMPDIR reaping, a partial clean) while the .deps marker still matches — that
# yields phantom `unresolved-import` errors on unchanged code. So validate the
# cache is actually USABLE (pin set matches AND the deps still import) and
# rebuild if not — self-healing rather than failing the gate.
TY_DEPS="typer>=0.12,<1 questionary>=2.0,<3 rich>=13,<15 ty"
TYVENV="${TMPDIR:-/tmp}/agent-container-tyvenv"
ty_env_usable() {
    [ "$(cat "$TYVENV/.deps" 2>/dev/null || true)" = "$TY_DEPS" ] \
        && [ -x "$TYVENV/bin/ty" ] \
        && "$TYVENV/bin/python" -c "import typer, questionary, rich" 2>/dev/null
}
build_ty_env() {
    rm -rf "$TYVENV"
    # shellcheck disable=SC2086 # deliberate word-splitting of the pin list
    uv venv "$TYVENV" --python "$UV_PYTHON" -q \
        && uv pip install --python "$TYVENV" -q $TY_DEPS \
        && echo "$TY_DEPS" >"$TYVENV/.deps"
}
if ! ty_env_usable; then
    debuglog "ty env missing/stale — (re)building $TYVENV"
    build_ty_env || { echo "quality-gate: failed to build the ty environment" >&2; exit 1; }
    ty_env_usable || { echo "quality-gate: ty environment unusable after rebuild" >&2; exit 1; }
fi

# Ordered fastest / most-likely-to-fail first: static checks (lint, types,
# security) before the behavioural ones (self-test, pytest, shell suites).
# bandit `-ll` = MEDIUM+ only; the CLI's legitimate subprocess calls are all LOW.
run_check "ruff-check"        "${RUFF[@]}" check
run_check "ruff-format"       "${RUFF[@]}" format --check
run_check "ty"                "$TYVENV/bin/ty" check --python "$TYVENV" bin/agent-container
run_check "bandit"            "${BANDIT[@]}" -q -ll bin/agent-container
run_check "self-test"         ./bin/agent-container --self-test
run_check "pytest"            "${PYT[@]}" bin/tests -x -q
run_check "shell-entrypoint"      bash bin/tests/test_entrypoint.sh
run_check "shell-completions"     bash bin/tests/test_completions.sh
run_check "shell-tmux-layout"     bash bin/tests/test_entrypoint_tmux_layout.sh

debuglog "=== ALL CHECKS PASSED ==="
exit 0
