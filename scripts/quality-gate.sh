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
    [shell-execution]="bin/tests/test_entrypoint_execution.sh failed — Feature 004 entrypoint mode branch (interactive agent launch / headless workload+exit code / clone-on-start). Read the mode-branch + clone-on-start sections of entrypoint.sh and the failing assertion label."
    [shell-completions]="bin/tests/test_completions.sh failed — bash/zsh completion parity or an injection guard. Read completions/agent-container.{bash,zsh}."
    [shell-tmux-layout]="bin/tests/test_entrypoint_tmux_layout.sh failed — real-tmux window layout. Read the tmux section of entrypoint.sh."
    [shell-repository]="bin/tests/test_entrypoint_repository.sh failed — Feature 016 repository-effect capture in entrypoint.sh (section 1r/3e): the five C7 states, pushed-by-ancestry, the changed-path list and its cap. Read the runs_repo_* helpers and the failing assertion label."
    [vulture]="Dead code in bin/agent-container flagged by vulture (>=80% confidence). Read the reported line; if truly unused, delete it. If it is used dynamically (a Typer command, a doctest-only helper, a dynamic attribute) it is a false positive — raise the confidence or add a vulture whitelist entry with a rationale."
    [xenon]="A function in bin/agent-container exceeds cyclomatic-complexity rank B (CC>10). Read the reported function and extract helpers to cut branching (each if/elif/for/while/and/or/except/ternary/comprehension-if is +1). Target rank B or better."
    [refurb]="A modernization refurb suggests for bin/agent-container. Run 'uv run --no-project --with refurb refurb --explain FURBxxx' to see it, then apply the one-line change. If it is a false positive, add the code to [tool.refurb] ignore in pyproject.toml with a rationale (see FURB143)."
)

fail() {
    local name="$1" cmd="$2" output="$3"
    # `hint` MUST be assigned on its own line. `local a=$1 b=${T[$a]}` expands every
    # argument BEFORE the builtin binds any of them, so the subscript was empty on
    # every call: bash printed "bad array subscript" and the hint came out blank —
    # the whole TOOL_HINTS table above was dead text for every failure it names.
    local hint="${TOOL_HINTS[$name]:-}"
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

# --- parallel execution ------------------------------------------------------
#
# The checks are INDEPENDENT — different tools reading the same files, and five
# shell suites that each mktemp their own workspace (no fixed container or
# directory names, verified). Run serially they took ~184s on a 16-core machine,
# of which pytest is 59s and the shell suites 114s. Nothing was waiting on
# anything; the wall-clock was just the sum.
#
# This matters more than a normal test suite because the gate is a STOP HOOK: it
# runs after every turn, so its cost is paid constantly rather than once.
#
# ORDER IS PRESERVED FOR REPORTING even though execution is not. The serial
# version was deliberately ordered "fastest / most-likely-to-fail first" so an
# operator saw the most probable failure first; that intent survives by REPORTING
# the earliest-declared failure, not the earliest-finishing one. Otherwise which
# error you saw would depend on a race.
PAR_DIR=""
par_names=(); par_cmds=(); par_pids=()

spawn_check() {  # spawn_check <check|nonempty> <name> <cmd...>
    local mode="$1" name="$2"; shift 2
    [ -n "$PAR_DIR" ] || PAR_DIR=$(mktemp -d)
    local i=${#par_names[@]}
    par_names+=("$name"); par_cmds+=("$*")
    (
        if [ "$mode" = "nonempty" ]; then
            # Same stdout-only rule as run_check_nonempty: uv's install progress
            # goes to stderr and must not read as a finding.
            out=$("$@" 2>/dev/null); rc=$?
            if [ -n "$out" ]; then printf '%s' "$out" >"$PAR_DIR/$i.out"; echo 1 >"$PAR_DIR/$i.rc"
            elif [ "$rc" -ne 0 ]; then "$@" >"$PAR_DIR/$i.out" 2>&1; echo 1 >"$PAR_DIR/$i.rc"
            else : >"$PAR_DIR/$i.out"; echo 0 >"$PAR_DIR/$i.rc"; fi
        else
            out=$("$@" 2>&1); rc=$?
            printf '%s' "$out" >"$PAR_DIR/$i.out"; echo "$rc" >"$PAR_DIR/$i.rc"
        fi
    ) &
    par_pids+=($!)
}

await_checks() {
    local pid; for pid in "${par_pids[@]}"; do wait "$pid" || true; done
    local i rc
    for i in "${!par_names[@]}"; do
        rc=$(cat "$PAR_DIR/$i.rc" 2>/dev/null || echo 1)
        if [ "$rc" -ne 0 ]; then
            fail "${par_names[$i]}" "${par_cmds[$i]}" "$(cat "$PAR_DIR/$i.out" 2>/dev/null)"
        fi
    done
    rm -rf "$PAR_DIR"; PAR_DIR=""
    par_names=(); par_cmds=(); par_pids=()
}

# Like run_check, but for tools whose "clean" is EMPTY output (they may exit 0
# even when reporting findings — e.g. vulture, refurb). Their findings go to
# STDOUT; uv's "Installed N packages" progress (emitted on a fresh runner, e.g.
# CI) and any tool crash go to STDERR. So test STDOUT ONLY for findings — else a
# first-run uv install line reads as a phantom finding — while still failing on a
# nonzero exit (a real tool error), re-running to surface stderr for the message.
run_check_nonempty() {
    local name="$1"; shift
    local cmd="$*" out rc
    debuglog "running $name..."
    out=$("$@" 2>/dev/null); rc=$?
    if [ -n "$out" ]; then
        fail "$name" "$cmd" "$out"
    elif [ "$rc" -ne 0 ]; then
        fail "$name" "$cmd" "$("$@" 2>&1)"  # empty stdout but errored — capture stderr
    fi
}

# App runtime deps (mirrors the PEP 723 block); pytest runs inside this uv env.
DEPS=(--with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' --with 'rich>=13,<15' --with 'pyyaml>=6,<7')
RUFF=(uv run --no-project --with ruff ruff)
BANDIT=(uv run --no-project --with bandit bandit)
# Universal static checks adopted from the canonical quality hook, adapted to the
# single-file --no-project layout: vulture (dead code), xenon (cyclomatic
# complexity), refurb (modernizations; reads [tool.refurb] ignores from pyproject).
# PIN the versions (like the runtime DEPS above): an unpinned `--with <tool>`
# resolves the NEWEST release, so a stale local cache and a fresh CI runner can
# land on different versions and disagree — a newer refurb/vulture adds a rule and
# only CI fails. Bump these deliberately, in lockstep, when adopting new rules.
VULTURE=(uv run --no-project --with 'vulture>=2.16,<2.17' vulture)
XENON=(uv run --no-project --with 'xenon>=0.9.3,<0.10' xenon)
REFURB=(uv run --no-project --with 'refurb>=2.3,<2.4' refurb)
# pytest-github-actions-annotate-failures turns failures into inline GitHub
# annotations (file:line) under Actions; it auto-detects GITHUB_ACTIONS and is a
# no-op locally, so it rides in the one shared pytest env without changing local
# behavior. It's a test-only plugin — never a runtime dep of the CLI.
# pytest-xdist: 1588 hermetic tests in ~17s across workers vs ~59s in one
# process, and the suite was already parallel-safe (measured — every test passed
# unchanged under -n 8). PINNED like every other tool here: an unpinned `--with`
# takes the newest release, so a stale local cache and a fresh CI runner can
# disagree and only CI fails.
#
# `-n auto` rather than a fixed count: this runs CONCURRENTLY with the other
# checks, and a CI runner has far fewer cores than a workstation, so a hardcoded
# width would oversubscribe there and under-use here.
PYT=(uv run --no-project "${DEPS[@]}" --with pytest
     --with 'pytest-xdist>=3.6,<4'
     --with 'pytest-github-actions-annotate-failures>=0.2,<1' pytest)

# ty resolves third-party imports against a Python environment. Left to its own
# discovery it picks the system interpreter (on CI that is /usr/lib/python3.12,
# which lacks typer/questionary) — NOT uv's `--with` overlay and NOT ty's own
# install venv. So build a 3.14 venv holding the runtime deps and point ty at it
# EXPLICITLY with `--python` below; without that flag ty ignores this venv and
# reports unresolved-import on a clean checkout. Cache it in a temp dir: first
# build ~3s, cached runs instant; CI's temp dir is fresh each run so it builds
# once.
TY_DEPS="typer>=0.12,<1 questionary>=2.0,<3 rich>=13,<15 pyyaml>=6,<7 ty"
TYVENV="${TMPDIR:-/tmp}/agent-container-tyvenv"
build_ty_env() {
    rm -rf "$TYVENV"
    # shellcheck disable=SC2086 # deliberate word-splitting of the pin list
    uv venv "$TYVENV" --python "$UV_PYTHON" -q \
        && uv pip install --python "$TYVENV" -q $TY_DEPS \
        && echo "$TY_DEPS" >"$TYVENV/.deps"
}
# STRUCTURAL (re)build only: when the venv is absent or its pinned deps changed.
# CORRUPTION of an existing venv is NOT detected here — the cache lives in a
# VOLATILE temp dir, so its packages can vanish (TMPDIR reaping, a partial clean)
# while the .deps marker still matches, yielding phantom `unresolved-import` on
# unchanged code. That is caught at CHECK time by the phantom-import signature
# (see the ty check below), which self-heals with one rebuild+retry. A prior
# probe type-checked a one-line file OUTSIDE the repo — a different first-party
# root than bin/agent-container — so it could pass while the real in-repo check
# failed; the check below IS the real target, so the probe can no longer diverge.
if [ "$(cat "$TYVENV/.deps" 2>/dev/null || true)" != "$TY_DEPS" ] || [ ! -x "$TYVENV/bin/ty" ]; then
    debuglog "ty env missing/stale — building $TYVENV"
    build_ty_env || { echo "quality-gate: failed to build the ty environment" >&2; exit 1; }
fi

# Ordered fastest / most-likely-to-fail first: static checks (lint, types,
# security) before the behavioural ones (self-test, pytest, shell suites).
# bandit `-ll` = MEDIUM+ only; the CLI's legitimate subprocess calls are all LOW.
spawn_check check    "ruff-check"        "${RUFF[@]}" check
spawn_check check    "ruff-format"       "${RUFF[@]}" format --check

# ty (inline, with phantom-import self-heal). A corrupted volatile-TMPDIR venv
# yields PHANTOM `unresolved-import` on the third-party deps (typer/questionary/
# rich) rather than a real type error; detect exactly that signature against the
# REAL target's output and rebuild+retry once. Any other failure is genuine.
debuglog "running ty..."
_ty_cmd="$TYVENV/bin/ty check --python $TYVENV bin/agent-container"
ty_out=$("$TYVENV/bin/ty" check --python "$TYVENV" bin/agent-container 2>&1) && ty_rc=0 || ty_rc=$?
if [ "$ty_rc" -ne 0 ] \
    && grep -q 'unresolved-import' <<<"$ty_out" \
    && grep -qE '\b(typer|questionary|rich)\b' <<<"$ty_out"; then
    debuglog "ty phantom unresolved-import — rebuilding $TYVENV and retrying"
    build_ty_env || { echo "quality-gate: failed to rebuild the ty environment" >&2; exit 1; }
    ty_out=$("$TYVENV/bin/ty" check --python "$TYVENV" bin/agent-container 2>&1) && ty_rc=0 || ty_rc=$?
fi
[ "$ty_rc" -eq 0 ] || fail "ty" "$_ty_cmd" "$ty_out"

spawn_check check    "bandit"            "${BANDIT[@]}" -q -ll bin/agent-container
spawn_check nonempty "vulture"  "${VULTURE[@]}" bin/agent-container --min-confidence 80
spawn_check check    "xenon"             "${XENON[@]}" --max-absolute B --max-modules A --max-average A bin/agent-container
spawn_check nonempty "refurb"   "${REFURB[@]}" bin/agent-container --quiet
spawn_check check    "self-test"         ./bin/agent-container --self-test
spawn_check check    "pytest"            "${PYT[@]}" bin/tests -x -q -n auto
spawn_check check    "shell-entrypoint"      bash bin/tests/test_entrypoint.sh
spawn_check check    "shell-execution"       bash bin/tests/test_entrypoint_execution.sh
spawn_check check    "shell-completions"     bash bin/tests/test_completions.sh
spawn_check check    "shell-tmux-layout"     bash bin/tests/test_entrypoint_tmux_layout.sh
# Every shell suite is enumerated by hand here, so a new file under bin/tests/ is
# a suite NOBODY runs until this list names it — the pytest line above globs a
# directory, this one does not, and the difference is invisible in a green gate.
spawn_check check    "shell-repository"      bash bin/tests/test_entrypoint_repository.sh

# One barrier, at the end: every check above runs concurrently and the earliest
# DECLARED failure is the one reported.
await_checks

debuglog "=== ALL CHECKS PASSED ==="
exit 0
