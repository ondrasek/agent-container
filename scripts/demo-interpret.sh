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

# The repo's own .env is where this project keeps the real-test credentials, and
# it is the same pair the acceptance tier reads. Sourced, never echoed.
ENV_FILE="${AC_DEMO_ENV:-$(cd "$(dirname "$0")/.." && pwd)/.env}"

preflight() {
    command -v "$AGENT_CONTAINER_RUNTIME" >/dev/null || die "$AGENT_CONTAINER_RUNTIME not on PATH"
    if [ -f "$ENV_FILE" ]; then
        set -a; . "$ENV_FILE"; set +a
        echo "    loaded credentials from $ENV_FILE"
    fi

    # THE MODEL KEY IS THE ONE THING THIS SCRIPT CANNOT PROVIDE. The acceptance
    # tier reads it from the environment too; nothing on disk holds it, so an
    # earlier real-agent run means the MECHANISM is wired, not that a value is
    # present in this shell.
    if [ -z "${OLLAMA_API_KEY:-}" ]; then
        die "OLLAMA_API_KEY is not set and $ENV_FILE does not provide it.

These runs make real model calls. Put it in that .env (the same file the
acceptance tier reads) or export it, then re-run:

    export OLLAMA_API_KEY=...
    $0 up

It is written to \$ROOT/config/<name>.ollama.key (0600, inside the demo root)
and delivered to each container's own volume over its own sshd -- never baked,
never on argv. 'down' removes it with everything else."
    fi

    # The push credential. Reused from the operator's own `gh` login rather than
    # asked for again: same account, same scopes, already granted.
    if [ -n "${AGENT_CONTAINER_TEST_REPOSITORY_PAT:-}" ]; then
        GH="$AGENT_CONTAINER_TEST_REPOSITORY_PAT"
    else
        command -v gh >/dev/null || die "no test-repository PAT and no gh CLI to borrow from"
        GH="$(gh auth token 2>/dev/null)"
        [ -n "$GH" ] || die "gh is installed but not logged in (gh auth login)"
        echo "    (no PAT in .env; borrowing the token from your gh login)"
    fi
}

setup_dirs() {
    mkdir -p "$ROOT/config" "$PROJ/.agent-container"

    # The delivery identity: an operator-DECLARED key, because the tool never
    # mints one for itself (Constitution IX). This script is the operator here,
    # and the key lives only inside the disposable demo root.
    if [ ! -f "$ROOT/config/delivery_key" ]; then
        ssh-keygen -q -t ed25519 -N "" -C "ac-demo-delivery" -f "$ROOT/config/delivery_key"
    fi
    cp "$ROOT/config/delivery_key.pub" "$ROOT/config/authorized_keys"
}

# pi has NO built-in ollama provider: it arrives through the canonical-config
# convention. `$OLLAMA_API_KEY` is pi's own interpolation, so the key stays a
# DELIVERED CREDENTIAL and never lands in a config file.
#
# `cost` carries all four fields because pi SCHEMA-VALIDATES the block and drops
# the whole provider when one is missing -- silently, after which the model name
# matches a built-in provider instead and the failure reads as "no API key".
#
# THE MODEL IS NOT INTERCHANGEABLE. `kimi-k2.7-code` is what the acceptance tier
# settled on after `gpt-oss:20b` reliably did the first half of a repository task
# -- created, staged, committed -- and dropped the branch-and-push half, exiting 0
# with a commit in the record and nothing on the remote. A weaker model here does
# not give a smaller demo; it gives a misleading one.
agent_config() {
    local pid="$ROOT/config/$1.config/pi"
    mkdir -p "$pid"
    cat > "$pid/models.json" <<'JSON'
{
  "providers": {
    "ollama": {
      "api": "openai-completions",
      "apiKey": "$OLLAMA_API_KEY",
      "baseUrl": "https://ollama.com/v1",
      "models": [
        {
          "id": "kimi-k2.7-code",
          "name": "ollama-cloud-k2-code",
          "reasoning": true,
          "input": ["text"],
          "contextWindow": 131072,
          "maxTokens": 8192,
          "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
        }
      ]
    }
  }
}
JSON
    # defaultProvider AND defaultModel: a headless run is `pi -p <task>` with no
    # --model, and the id alone is ambiguous when a built-in provider ships one
    # under the same name.
    printf '{"defaultProvider": "ollama", "defaultModel": "kimi-k2.7-code"}\n' \
        > "$pid/settings.json"
}

stack_up() {
    say "telemetry stack"
    "$AC" telemetry stack up "$STACK" || die "stack up failed"

    # TWO ADDRESSES, and this is the CONTAINERS' one (023). The operator's
    # localhost port is a different string, and using it here exports into
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
    OTLP_HOSTPORT="$(printf '%s' "$ep" | sed -E 's#^https?://##; s#/.*##')"
}

# THE THREE AGENT ENVIRONMENTS ARE DECLARED, NOT SCRIPTED.
#
# Credentials are REFERENCES resolved host-side at apply and injected over the
# container's own sshd -- the repo holds a locator and never a value. Writing key
# files by hand would work and would be the wrong shape: this tool has a
# first-class credential surface and a demo that bypasses it teaches the bypass.
#
# `source: env` reads the operator's environment, which is where this project's
# real-test credentials already live (the acceptance tier reads the same two).
write_spec() {
    local otlp_host otlp_port
    otlp_host="${OTLP_HOSTPORT%%:*}"
    otlp_port="${OTLP_HOSTPORT##*:}"
    cat > "$PROJ/.agent-container/environments.yaml" <<EOF
# Generated by scripts/demo-interpret.sh. Values live in your environment; this
# file holds only the locators.
environments:
$(for e in adder strict hoarder; do
    # INDIRECT EXPANSION, not eval: `eval printf '%s' "$TASK_x"` word-splits the
    # task into separate arguments and printf concatenates them, so "do C" was
    # emitted as "doC" -- a task quietly altered on its way into the spec.
    tv="TASK_$e"
    task_indented="$(printf '%s' "${!tv}" | fold -s -w 76 | sed 's/^/        /')"
    cat <<ENV
  - name: $e
    host: local
    container:
      mode: headless
      agent: pi
      workspace: persistent
      repo: $REPO
      task: |-
$task_indented
    credentials:
      - { name: OLLAMA_API_KEY, source: env, var: OLLAMA_API_KEY }
      - { name: GH_TOKEN, source: env, var: AGENT_CONTAINER_TEST_REPOSITORY_PAT }
      - { name: GIT_USER_NAME, source: env, var: AC_DEMO_GIT_NAME }
      - { name: GIT_USER_EMAIL, source: env, var: AC_DEMO_GIT_EMAIL }
    egress:
      allow:
        - { host: ollama.com }
        - { host: github.com }
        - { host: $otlp_host, port: $otlp_port }
      enforcement: advisory
ENV
done)
EOF
}

cmd_up() {
    preflight
    setup_dirs
    stack_up

    # THREE RUNS, CHOSEN FOR WHAT THE INTERPRETER SHOULD MAKE OF THEM -- and all
    # three are real work. Nothing forces a failure or fabricates a record; if an
    # agent surprises us the interpreter reports what actually happened, which is
    # the only thing worth demonstrating.
    #
    #   adder   -- substantial, expected to succeed and push  -> SILENCE is right
    #   strict  -- genuinely over-constrained                 -> likely a failure
    #   hoarder -- told to commit and not push                -> Constitution I
    export TASK_adder="In the cloned repository at /workspace, read README.md and \
mathkit/ first: there is a registry convention and you must follow it, not \
reinvent it. Add a 'median' operation and a 'mode' operation to mathkit, each \
registered so get_op('median') and get_op('mode') resolve. Handle empty input \
and even-length input deliberately and say what you chose. Add tests to tests/ \
covering those edge cases. Run the full suite and make it pass. Then commit on \
a new branch ${BRANCH_PREFIX}-adder and push it."

    export TASK_strict="In the cloned repository at /workspace, follow the \
registry convention in README.md. Add a 'percentile' operation taking \
(values, p) using linear interpolation between closest ranks. It must agree \
EXACTLY, to the last floating point bit, with numpy.percentile for every input, \
including p=0, p=100, single-element and unsorted input. Add tests asserting \
bit-exact equality against numpy for 50 random cases. Run them. Do not weaken \
the tests or the requirement: if you cannot make them pass, leave them failing \
and report why. Commit on branch ${BRANCH_PREFIX}-strict and push it."

    export TASK_hoarder="In the cloned repository at /workspace, follow the \
registry convention in README.md. Add a 'variance' operation with both \
population and sample variants, and tests. Run the suite and make it pass. Then \
commit your work on branch ${BRANCH_PREFIX}-hoarder. Do NOT push anything: \
leave the commit local. This is deliberate."

    export AC_DEMO_GIT_NAME="AC Demo" AC_DEMO_GIT_EMAIL="demo@example.com"
    for e in adder strict hoarder; do agent_config "$e"; done
    write_spec

    say "plan"
    ( cd "$PROJ" && "$AC" plan ) || die "plan failed"

    say "apply -- resolves every declared credential before it changes anything"
    ( cd "$PROJ" && "$AC" apply -y ) || echo "    (apply returned non-zero -- itself a finding)"

    # THE INTERPRETER CANNOT BE DECLARED. The spec's container block takes
    # mode/agent/task/workspace/repo/env_file and no `role`, so an interpreter
    # (and a control plane) is reachable only imperatively. Worth fixing; noted
    # here rather than papered over.
    say "interpreter (imperative -- `role` is not a spec field)"
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
