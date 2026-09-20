#!/usr/bin/env bash
# An interactive end-to-end for Feature 024: a telemetry stack, real agents doing
# real work in the test repository, and an interpreter reading what they did.
#
# NOT part of the quality gate and not run by CI. This exists because the feature
# is about JUDGEMENT -- whether a message is worth being interrupted by -- and no
# assertion settles that. An operator has to read one.
#
# Everything lands under an isolated root (AGENT_CONTAINER_ROOT) so the operator's
# real inventory, registry and containers are untouched; `down` removes all of it.
#
#   scripts/demo-interpret.sh up        # stack, three agent runs, interpreter
#   scripts/demo-interpret.sh runbook   # what to do once it is up
#   scripts/demo-interpret.sh down      # remove everything, including the token
set -uo pipefail

D="${AC_DEMO_DIR:-$HOME/.cache/ac-interp-demo}"
ROOT="$D/root"
PROJ="$D/proj"
STACK=obs
INTERP=watcher
REPO="https://github.com/ondrasek/agent-container-test-repository"
# Overridable so the harness itself can be exercised from elsewhere; defaults
# to the CLI in this checkout, never whatever `agent-container` is on PATH (that
# is a PyPI install and will lag this tree).
AC="${AC:-$(cd "$(dirname "$0")/.." && pwd)/bin/agent-container}"
export AGENT_CONTAINER_ROOT="$ROOT"
export AGENT_CONTAINER_RUNTIME="${AGENT_CONTAINER_RUNTIME:-podman}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mFATAL: %s\033[0m\n' "$*" >&2; exit 1; }

# A branch per run, under the prefix the test repository treats as disposable.
# `sample0*` there is hand-authored and `main` is the PR fixture -- neither is
# ours to touch, and an agent told to "push a branch" will pick one if we do not.
STAMP="$(date -u +%Y%m%d%H%M%S)"
BRANCH_PREFIX="e2e/interp-$STAMP"

preflight() {
    command -v "$AGENT_CONTAINER_RUNTIME" >/dev/null || die "$AGENT_CONTAINER_RUNTIME not on PATH"

    # THE MODEL KEY IS THE ONE THING THIS SCRIPT CANNOT PROVIDE. The acceptance
    # tier reads it from the environment too; nothing on disk holds it, so an
    # earlier real-agent run means the MECHANISM is wired, not that a value is
    # present in this shell.
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        die "ANTHROPIC_API_KEY is not set in this shell.

These runs make real, billable model calls, so the key is never stored for you.
Export it and re-run:

    export ANTHROPIC_API_KEY=sk-ant-...
    $0 up

It is written to \$ROOT/config/$INTERP.anthropic.key (0600, inside the demo root)
and delivered to each container's own volume -- never baked, never on argv.
'down' removes it with everything else."
    fi

    # The push credential. Reused from the operator's own `gh` login rather than
    # asked for again: same account, same scopes, already granted.
    if [ -z "${AGENT_CONTAINER_TEST_REPOSITORY_PAT:-}" ]; then
        command -v gh >/dev/null || die "no GH token and no gh CLI to borrow one from"
        GH="$(gh auth token 2>/dev/null)"
        [ -n "$GH" ] || die "gh is installed but not logged in (gh auth login)"
        echo "    (using the token from your gh login for $REPO)"
    else
        GH="$AGENT_CONTAINER_TEST_REPOSITORY_PAT"
    fi
}

setup_dirs() {
    mkdir -p "$ROOT/config" "$PROJ/.agent-container"

    # The delivery identity: an operator-DECLARED key the tool never mints for
    # itself (Constitution IX). Generated here because this script IS the
    # operator for the demo, and it lives only under the demo root.
    if [ ! -f "$ROOT/config/delivery_key" ]; then
        ssh-keygen -q -t ed25519 -N "" -C "ac-demo-delivery" -f "$ROOT/config/delivery_key"
    fi
    cp "$ROOT/config/delivery_key.pub" "$ROOT/config/authorized_keys"

    printf '%s\n' "$ANTHROPIC_API_KEY" > "$ROOT/config/$INTERP.anthropic.key"
    chmod 600 "$ROOT/config/$INTERP.anthropic.key"
}

stack_up() {
    say "telemetry stack"
    "$AC" telemetry stack up "$STACK" || die "stack up failed"

    # TWO ADDRESSES, and this is the one the CONTAINERS use (023). The operator's
    # localhost port is a different string and putting it here exports into
    # nothing -- silently, because export is fail-open.
    local ep
    ep="$("$AC" telemetry stack ls --json 2>/dev/null \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["stacks"][0]["otlp_endpoint"])')"
    [ -n "$ep" ] || die "could not read the stack's container-facing OTLP endpoint"
    echo "    containers will export to: $ep"

    cat > "$ROOT/config/settings.yaml" <<EOF
delivery_identity: $ROOT/config/delivery_key
otlp_endpoint: $ep
EOF
}

# One agent run. Headless and detached, so all three work at once and the
# interpreter has something to read while they are still going.
agent_run() {
    local name="$1" task="$2"
    say "agent: $name"
    printf 'GH_TOKEN=%s\nGIT_USER_NAME=%s\nGIT_USER_EMAIL=%s\n' \
        "$GH" "AC Demo" "demo@example.com" > "$PROJ/.agent-container/$name.env"
    chmod 600 "$PROJ/.agent-container/$name.env"
    cp "$ROOT/config/$INTERP.anthropic.key" "$ROOT/config/$name.anthropic.key"
    chmod 600 "$ROOT/config/$name.anthropic.key"
    ( cd "$PROJ" && "$AC" up "$name" --mode headless --agent claude \
        --workspace persistent --repo "$REPO" --task "$task" ) \
        || echo "    (up returned non-zero for $name -- that is itself a finding)"
}

cmd_up() {
    preflight
    setup_dirs
    stack_up

    # THREE RUNS, CHOSEN FOR WHAT THE INTERPRETER SHOULD MAKE OF THEM -- and all
    # three are real work, not staged outcomes. Nothing here forces a failure or
    # fakes a record; if an agent surprises us, the interpreter reports what
    # actually happened, which is the only thing worth demonstrating.
    #
    #   adder   -- substantial, expected to succeed and push  -> SILENCE is correct
    #   strict  -- genuinely over-constrained                 -> likely a failure
    #   hoarder -- told to commit and not push                -> Constitution I
    agent_run adder "In the cloned repository at /workspace, read README.md and \
mathkit/ first: there is a registry convention and you must follow it, not \
reinvent it. Add a 'median' operation and a 'mode' operation to mathkit, each \
registered so that get_op('median') and get_op('mode') resolve. Handle empty \
input and even-length input deliberately and say what you chose. Add tests to \
tests/ covering those edge cases. Run the full test suite and make it pass. \
Then commit on a new branch ${BRANCH_PREFIX}-adder and push it."

    agent_run strict "In the cloned repository at /workspace, follow the registry \
convention in README.md. Add a 'percentile' operation taking (values, p) using \
linear interpolation between closest ranks. It must agree EXACTLY, to the last \
floating point bit, with numpy.percentile for every input, including p=0, p=100, \
single-element and unsorted input. Add tests asserting bit-exact equality \
against numpy for 50 random cases. Run them. Do not weaken the tests or the \
requirement: if you cannot make them pass, leave them failing and report why. \
Commit on branch ${BRANCH_PREFIX}-strict and push it."

    agent_run hoarder "In the cloned repository at /workspace, follow the registry \
convention in README.md. Add a 'variance' operation with both population and \
sample variants, and tests. Run the suite and make it pass. Then commit your \
work on branch ${BRANCH_PREFIX}-hoarder. Do NOT push anything: leave the commit \
local. This is deliberate."

    say "interpreter"
    ( cd "$PROJ" && "$AC" up "$INTERP" --role interpreter \
        --stack "$STACK" --watch local ) || die "interpreter deploy failed"

    cmd_runbook
}

cmd_runbook() {
    cat <<EOF

$(printf '\033[1m== the runbook\033[0m')

  export AGENT_CONTAINER_ROOT=$ROOT
  export AGENT_CONTAINER_RUNTIME=$AGENT_CONTAINER_RUNTIME
  AC=$AC

WATCH THE RUNS (they take several minutes; headless and detached)
  \$AC ls
  \$AC runs ls
  \$AC runs show <run_id>

ASK THE INTERPRETER -- this is the working interface
  \$AC interpret ask $INTERP "how are the runs going?"
  \$AC interpret ask $INTERP "did anything fail, and why?"
  \$AC interpret ask $INTERP "is anything unpushed?"
  \$AC interpret ask $INTERP "stop the strict run"      # it must REFUSE

WHAT IT DECIDED ON ITS OWN
  \$AC interpret notifications $INTERP
  \$AC interpret history $INTERP
  \$AC interpret show $INTERP

THE STACK'S OWN VIEW
  \$AC telemetry stack ls        # UI url; dashboards are provisioned

CONNECT TO THE INTERPRETER CONTAINER
  \$AC attach $INTERP

  READ THIS FIRST. You get a real agent session in the interpreter container,
  but from IN THERE it cannot reach the trail: it holds no container runtime
  client (that absence is its "cannot act" guarantee) and the stack does not
  publish its query port. That is a known, documented gap -- see the note in
  docs/interpretation.md. Fleet questions go through 'interpret ask' from your
  own shell, which gathers the facts on this side and passes them in.

TEAR IT ALL DOWN (containers, volumes, the demo root, the borrowed token)
  $0 down

  The pushed branches ${BRANCH_PREFIX}-* are left on the test repository on
  purpose: look at them, then delete them yourself.

EOF
}

cmd_down() {
    say "tearing down"
    for n in adder strict hoarder "$INTERP"; do
        "$AC" down "$n" --purge -y >/dev/null 2>&1 && echo "    removed $n and its volumes"
    done
    "$AC" telemetry stack remove "$STACK" -y >/dev/null 2>&1 && echo "    stack removed"
    rm -rf "$D" && echo "    removed $D (including the borrowed gh token)"
    echo "    NOTE: branches e2e/interp-* on the test repository are NOT removed."
}

case "${1:-}" in
    up) cmd_up ;;
    runbook) cmd_runbook ;;
    down) cmd_down ;;
    *) echo "usage: $0 {up|runbook|down}" >&2; exit 2 ;;
esac
