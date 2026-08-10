#!/usr/bin/env bash
# Feature 016 US2: the repository effect the ENTRYPOINT records (T026, T027,
# T051, T052), exercised against REAL git repositories — no container, nothing
# privileged, and deliberately NO git stub.
#
# Run:  bin/tests/test_entrypoint_repository.sh
#
# Why real git rather than the stub the sibling suite uses: every branch under
# test is a classification of a git EXIT CODE that research R4 measured
# (`rev-parse @{u}` → 128 with no upstream, `symbolic-ref -q HEAD` → 1 when
# detached, 128 outside a repository). A stub returning codes this suite chose
# would be asserting that the entrypoint agrees with the stub, which is a check
# that passes while the thing it names is broken. So the repositories here are
# built with git and the codes come from git.
#
# Covers:
#   T027  each of the five states of C7 is a RECORD, not an error:
#         ok · no-repository · no-upstream · detached · unreadable.
#   T026  start/exit capture with NO agent involvement — including a run whose
#         agent killed itself, which is the case FR-004a exists for — and
#         `pushed` as null-not-false wherever there is nothing to compare
#         against (C8: `false` means "committed and did not push", the failure
#         Constitution I exists to prevent).
#   T051  changed paths captured at exit, byte-for-byte, including the awkward
#         names git would otherwise C-quote.
#   T052  the cap is enforced AND announced — never a silent cap.
#
# Two attribution guards get their own cases because they are the loudest wrong
# answers this record can give: a workspace that GAINED a repository during the
# run (an agent that cloned into it) must not have that history attributed to
# it, and one that LOST its repository must not report "changed nothing".
#
# The last case is a PROOF IT CAN FAIL: it runs a deliberately broken copy of
# the entrypoint and asserts this suite notices. Four further mutations were
# applied by hand during development and each was caught by the case named:
#   silent cap (drop the note+flag)          -> "the cap is announced"
#   pushed defaults to false, not null       -> "pushed is NULL, never false"
#   attribute unattributable history         -> "nothing attributed"
#   remove the exit capture entirely         -> every state assertion

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRY="${REPO_ROOT}/image/entrypoint.sh"

pass=0
fail=0
note() { printf '%s\n' "$*" >&2; }
check_eq() {
    if [[ "$2" == "$3" ]]; then pass=$((pass + 1)); else
        fail=$((fail + 1)); note "FAIL: $1"; note "  expected: [$2]"; note "  actual:   [$3]"
    fi
}
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); note "FAIL: $1"; }

SB="$(mktemp -d)"
trap 'rm -rf "${SB}"' EXIT
STUB="${SB}/stub"; mkdir -p "${STUB}"

printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/tail";  chmod +x "${STUB}/tail"
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/sshd";  chmod +x "${STUB}/sshd"
# tmux: `has-session` must FAIL so the interactive path builds its session, and
# everything else is a no-op. The layout is the sibling suite's subject, not this
# one's.
printf '#!/usr/bin/env bash\ncase "$1" in has-session) exit 1;; esac\nexit 0\n' > "${STUB}/tmux"
chmod +x "${STUB}/tmux"

# The agent stub runs a per-case script inside the workspace, so the commits the
# record accounts for are made by the same process the entrypoint supervises —
# on the far side of the fork, exactly as a real agent's would be.
for a in claude codex pi opencode; do
cat > "${STUB}/${a}" <<'EOF'
#!/usr/bin/env bash
if [[ -n "${AGENT_SCRIPT:-}" && -f "${AGENT_SCRIPT}" ]]; then
    bash "${AGENT_SCRIPT}" >/dev/null 2>&1
fi
exit 0
EOF
chmod +x "${STUB}/${a}"
done

CASE=""; RUNS=""; WORKSPACE=""; ENTRY_UNDER_TEST="${ENTRY}"

# Each case gets its own runs dir and workspace. A record left by an earlier case
# would let a case that captured NOTHING still find a plausible-looking one.
fresh_case() {
    CASE="$1"
    RUNS="${SB}/${CASE}/runs"; WORKSPACE="${SB}/${CASE}/workspace"
    rm -rf "${SB}/${CASE:?}" "${SB}/home" "${SB}/inject"
    mkdir -p "${RUNS}" "${WORKSPACE}" "${SB}/home" "${SB}/inject"
    printf 'do the thing\n' > "${SB}/inject/task"
    unset AGENT_SCRIPT
    ENTRY_UNDER_TEST="${ENTRY}"
}

agent_script() {
    AGENT_SCRIPT="${SB}/${CASE}/agent.sh"
    printf '%s\n' "$1" > "${AGENT_SCRIPT}"
    export AGENT_SCRIPT
}

# A bare "remote" plus a clone of it, so `@{u}` resolves and a push is a real
# push rather than a simulated one.
make_cloned_repo() {
    local bare="${SB}/${CASE}/remote.git" seed="${SB}/${CASE}/seed"
    git init -q --bare "${bare}"
    git init -q -b main "${seed}"
    printf 'seed\n' > "${seed}/README"
    git -C "${seed}" add README
    git -C "${seed}" -c user.name=S -c user.email=s@e commit -qm seed
    git -C "${seed}" remote add origin "${bare}"
    git -C "${seed}" push -q origin main
    rm -rf "${WORKSPACE:?}"
    git clone -q "${bare}" "${WORKSPACE}"
    git -C "${WORKSPACE}" config user.name S
    git -C "${WORKSPACE}" config user.email s@e
}

make_local_repo() {
    git init -q -b main "${WORKSPACE}"
    git -C "${WORKSPACE}" config user.name S
    git -C "${WORKSPACE}" config user.email s@e
}

run_entry() {
    (
        cd "${SB}" || exit 99
        export GH_TOKEN=x GIT_USER_NAME='Test User' GIT_USER_EMAIL='t@example.com'
        export HOME="${SB}/home" AGENT_CONTAINER_HOME="${SB}/home"
        export AGENT_CONTAINER_SSHD="${STUB}/sshd"
        export AGENT_CONTAINER_INJECT_DIR="${SB}/inject"
        export AGENT_CONTAINER_WORKSPACE="${WORKSPACE}"
        export AGENT_CONTAINER_RUNS_DIR="${RUNS}"
        export PATH="${STUB}:${PATH}"
        unset ANTHROPIC_API_KEY OPENAI_API_KEY
        unset AGENT_CONTAINER_MODE AGENT_CONTAINER_AGENT AGENT_CONTAINER_CLONE_URL
        for kv in "$@"; do export "${kv?}"; done
        bash "${ENTRY_UNDER_TEST}" >/dev/null 2>"${SB}/log"
    )
}

record_path() { /bin/ls -1 "${RUNS}"/*.json 2>/dev/null | head -1; }

# PARSED, never grepped. A regex over the record would report the field this
# suite expects while the JSON around it was malformed — and malformed is exactly
# what the entrypoint's escaping exists to prevent, so a reader that could not
# notice it would be the defect shape this feature keeps finding.
#
# `<field>[.<field>...]`; a list prints as JSON, a null as `null`, and a missing
# record as `<<none>>` so "no record at all" can never read as a value.
field() {
    local f; f="$(record_path)"
    if [[ -z "${f}" ]]; then printf '<<none>>'; return 0; fi
    python3 - "${f}" "$1" <<'PY'
import json, sys
cur = json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    cur = cur.get(key) if isinstance(cur, dict) else None
if isinstance(cur, list):
    print(json.dumps(cur, ensure_ascii=False), end="")
elif cur is None:
    print("null", end="")
elif cur is True:
    print("true", end="")
elif cur is False:
    print("false", end="")
else:
    print(cur, end="")
PY
}
# Length of a list field, so a count assertion never depends on SHA text.
count() {
    local f; f="$(record_path)"
    if [[ -z "${f}" ]]; then printf '<<none>>'; return 0; fi
    python3 - "${f}" "$1" <<'PY'
import json, sys
cur = json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    cur = cur.get(key) if isinstance(cur, dict) else None
print(0 if cur is None else len(cur), end="")
PY
}
notes_contain() { [[ "$(field notes)" == *"$1"* ]]; }

# --- C7: no-repository — the ORDINARY case, not an error ---------------------
# An `ephemeral` workspace with no clone is the common shape for a throwaway
# run (research R4). It must produce a record that says so, and it must not
# manufacture a diagnostic: an honest empty is different from an unknown, and
# only the latter earns a note.
fresh_case norepo
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "no-repository: state" "no-repository" "$(field repository.state)"
check_eq "no-repository: start_head null" "null" "$(field repository.start_head)"
check_eq "no-repository: end_head null" "null" "$(field repository.end_head)"
check_eq "no-repository: pushed null, never false" "null" "$(field repository.pushed)"
check_eq "no-repository: no commits" "0" "$(count repository.commits)"
check_eq "no-repository: an HONEST empty is not truncated" "false" "$(field repository.paths_truncated)"
check_eq "no-repository: no diagnostic invented" "0" "$(count notes)"

# --- C8: committed WITHOUT pushing — the failure Constitution I prevents ------
fresh_case commitnopush
make_cloned_repo
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; echo hi > a.txt; git add a.txt; git commit -qm work'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "ok: state" "ok" "$(field repository.state)"
check_eq "ok: branch" "main" "$(field repository.branch)"
check_eq "ok: upstream" "origin/main" "$(field repository.upstream)"
check_eq "commit-without-push: pushed FALSE, and it means it" "false" "$(field repository.pushed)"
check_eq "commit-without-push: exactly this run's commit" "1" "$(count repository.commits)"
check_eq "commit-without-push: the changed path" '["a.txt"]' "$(field repository.paths)"
check_eq "commit-without-push: a complete list is not truncated" "false" "$(field repository.paths_truncated)"
# The baseline must be a real, DIFFERENT commit. Equal heads would mean the
# start capture ran after the agent, and the run's work would be invisible.
_sh="$(field repository.start_head)"; _eh="$(field repository.end_head)"
if [[ "${_sh}" != "null" && -n "${_sh}" && "${_sh}" != "${_eh}" ]]; then ok
else bad "the baseline must be a real commit distinct from the exit head (start=${_sh} end=${_eh})"; fi

# --- pushed: true is reserved for work that actually reached the remote -------
fresh_case commitpush
make_cloned_repo
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; echo hi > b.txt; git add b.txt; git commit -qm work; git push -q origin main'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "pushed: true" "true" "$(field repository.pushed)"
check_eq "pushed: the commit is still recorded" "1" "$(count repository.commits)"
check_eq "pushed: the path is still recorded" '["b.txt"]' "$(field repository.paths)"

# --- a run that changed nothing says nothing, loudly or otherwise ------------
fresh_case nochange
make_cloned_repo
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "no-op: state ok" "ok" "$(field repository.state)"
check_eq "no-op: no commits" "0" "$(count repository.commits)"
check_eq "no-op: no paths" "0" "$(count repository.paths)"
check_eq "no-op: nothing outstanding" "true" "$(field repository.pushed)"
check_eq "no-op: and that answer is CERTAIN" "false" "$(field repository.paths_truncated)"

# --- C7: no-upstream (`git rev-parse @{u}` → 128) ----------------------------
# `pushed` MUST be null here. Reporting false would say "committed and did not
# push" about a branch that has nowhere to push to, making the loudest signal in
# the feature unreliable in the one direction that matters.
fresh_case noupstream
make_local_repo
printf 'x\n' > "${WORKSPACE}/f"; git -C "${WORKSPACE}" add f; git -C "${WORKSPACE}" commit -qm base
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; echo y > g; git add g; git commit -qm work'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "no-upstream: state" "no-upstream" "$(field repository.state)"
check_eq "no-upstream: pushed is NULL, never false (C8)" "null" "$(field repository.pushed)"
check_eq "no-upstream: the effect is still attributed" "1" "$(count repository.commits)"
check_eq "no-upstream: and the paths still captured" '["g"]' "$(field repository.paths)"

# --- C7: detached HEAD (`symbolic-ref -q HEAD` → 1) --------------------------
fresh_case detached
make_local_repo
printf 'x\n' > "${WORKSPACE}/f"; git -C "${WORKSPACE}" add f; git -C "${WORKSPACE}" commit -qm base
git -C "${WORKSPACE}" checkout -q --detach
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; echo y > h; git add h; git commit -qm work'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "detached: state" "detached" "$(field repository.state)"
check_eq "detached: no branch to name" "null" "$(field repository.branch)"
check_eq "detached: pushed null" "null" "$(field repository.pushed)"
check_eq "detached: the effect is measured anyway" '["h"]' "$(field repository.paths)"

# --- an UNBORN branch is a repository, not the absence of one ----------------
# `git init` with no commit yet: `rev-parse HEAD` fails exactly as it does
# outside a repository, so a capture that read only that code would call this
# `no-repository` and lose the run's first commit.
fresh_case unborn
make_local_repo
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; echo y > first; git add first; git commit -qm first'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "unborn: state is no-upstream, NOT no-repository" "no-upstream" "$(field repository.state)"
check_eq "unborn: no baseline commit exists to name" "null" "$(field repository.start_head)"
check_eq "unborn: the first commit is this run's" "1" "$(count repository.commits)"
check_eq "unborn: paths come off the empty-tree baseline" '["first"]' "$(field repository.paths)"

# --- the repository APPEARED during the run: attribute NOTHING ---------------
# An agent that clones into an empty workspace leaves a full history at exit,
# and none of it is this run's work. Attributing it would be the loudest wrong
# answer the record can give — so the run reports no commits AND says the answer
# is incomplete, rather than a confident "changed nothing".
fresh_case appeared
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; git init -q -b main .; git config user.name S; git config user.email s@e; echo y > z; git add z; git commit -qm work'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "appeared: the end state is read honestly" "no-upstream" "$(field repository.state)"
check_eq "appeared: nothing attributed" "0" "$(count repository.commits)"
check_eq "appeared: flagged uncertain, not a confident empty" "true" "$(field repository.paths_truncated)"
if notes_contain "not this run's work"; then ok
else bad "appeared: unattributable history must be STATED (notes: $(field notes))"; fi

# --- the repository VANISHED during the run ----------------------------------
fresh_case vanished
make_cloned_repo
agent_script 'rm -rf "$AGENT_CONTAINER_WORKSPACE/.git"'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "vanished: state no-repository" "no-repository" "$(field repository.state)"
check_eq "vanished: an unknown effect is NOT an empty one" "true" "$(field repository.paths_truncated)"
if notes_contain "INCOMPLETE, not empty"; then ok
else bad "vanished: the lost effect must be stated (notes: $(field notes))"; fi

# --- T052: the cap is enforced AND announced ---------------------------------
# 250 changed paths against a cap of 200. A truncated list that looked complete
# would answer "no run changed that file" with confidence when one did, so the
# flag and the real total are both part of the contract.
fresh_case cap
make_cloned_repo
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; for i in $(seq 1 250); do echo x > "f$i"; done; git add -A; git commit -qm many'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "cap: the list is capped" "200" "$(count repository.paths)"
check_eq "cap: paths_truncated is set" "true" "$(field repository.paths_truncated)"
if notes_contain "capped at 200 of 250 paths"; then ok
else bad "cap: the cap must NAME the real total (notes: $(field notes))"; fi

# --- T051: awkward path names survive verbatim -------------------------------
# Without `-z`, git C-quotes any path holding a space, a quote or a non-ASCII
# byte, and the record would carry a name that matches nothing when
# `runs list --changed` is later asked about the real one (C16).
fresh_case oddpaths
make_cloned_repo
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; mkdir -p src; echo x > "src/a b.txt"; echo x > "src/qu\"ote.txt"; echo x > "src/é.py"; git add -A; git commit -qm odd'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "odd paths: recorded verbatim, never C-quoted" \
    '["src/a b.txt", "src/qu\"ote.txt", "src/é.py"]' "$(field repository.paths)"

# --- FR-004a: NO agent involvement — the crashed agent is the point ----------
# The agent kills itself outright. The run that most needs a record is exactly
# this one, so the effect must be captured by the entrypoint regardless.
fresh_case crashed
make_cloned_repo
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; echo hi > c.txt; git add c.txt; git commit -qm work; kill -9 $$'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "crashed agent: its effect is still recorded" '["c.txt"]' "$(field repository.paths)"
check_eq "crashed agent: and still loudly unpushed" "false" "$(field repository.pushed)"

# --- FR-013: an interactive session gets the same capture --------------------
fresh_case interactive
make_cloned_repo
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude
check_eq "interactive: kind" "interactive" "$(field kind)"
check_eq "interactive: the repository is captured for a session too" "ok" "$(field repository.state)"

# --- C11: git failing wholesale must not fail the RUN ------------------------
# A copy of the entrypoint whose exit-capture deadline has already passed, so
# every git call reports "did not finish in time" — the shape of a hung or
# missing git. The run's own status must be untouched, the record must still be
# written, and the gap must be stated rather than rendered as "changed nothing".
fresh_case gitgone
make_cloned_repo
python3 - "${ENTRY}" "${SB}/gitgone/entrypoint.sh" <<'PY'
import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
old = "    RUNS_GIT_DEADLINE=$(( $(date +%s) + 5 ))"
assert src.count(old) == 1, "the exit-capture deadline moved; update this mutation"
pathlib.Path(sys.argv[2]).write_text(src.replace(old, "    RUNS_GIT_DEADLINE=$(( $(date +%s) - 1 ))"))
PY
ENTRY_UNDER_TEST="${SB}/gitgone/entrypoint.sh"
printf '#!/usr/bin/env bash\nexit 7\n' > "${STUB}/claude"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "git gone: the run's own exit status is untouched (C11)" "7" "$?"
check_eq "git gone: the record is still written" "failed" "$(field outcome)"
check_eq "git gone: state degrades to unreadable, not to a wrong answer" "unreadable" "$(field repository.state)"
check_eq "git gone: and the gap is flagged uncertain" "true" "$(field repository.paths_truncated)"
if notes_contain "INCOMPLETE, not empty"; then ok
else bad "git gone: an unreadable repository must not be silent (FR-008)"; fi
# Restore the agent stub the other cases share.
cat > "${STUB}/claude" <<'EOF'
#!/usr/bin/env bash
if [[ -n "${AGENT_SCRIPT:-}" && -f "${AGENT_SCRIPT}" ]]; then
    bash "${AGENT_SCRIPT}" >/dev/null 2>&1
fi
exit 0
EOF
chmod +x "${STUB}/claude"

# --- PROOF IT CAN FAIL -------------------------------------------------------
# Every assertion above would keep passing for a build that recorded nothing if
# the reader were broken instead of the entrypoint. So: run a copy with the `-z`
# removed from the path diff — the one-character change that reintroduces git's
# C-quoting — and assert THIS SUITE NOTICES. If the check below stops failing,
# the odd-paths assertion above has stopped meaning anything.
fresh_case proof
make_cloned_repo
python3 - "${ENTRY}" "${SB}/proof/entrypoint.sh" <<'PY'
import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
old = 'git_bounded diff --name-only -z "${base}" "${head}"'
assert src.count(old) == 1, "the path diff moved; update this mutation"
pathlib.Path(sys.argv[2]).write_text(src.replace(old, 'git_bounded diff --name-only "${base}" "${head}"'))
PY
ENTRY_UNDER_TEST="${SB}/proof/entrypoint.sh"
agent_script 'cd "$AGENT_CONTAINER_WORKSPACE"; mkdir -p src; echo x > "src/a b.txt"; git add -A; git commit -qm odd'
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
if [[ "$(field repository.paths)" == '["src/a b.txt"]' ]]; then
    bad "proof-it-can-fail: a build WITHOUT -z produced the correct paths, so the odd-paths check proves nothing"
else ok; fi

# --- summary -----------------------------------------------------------------
note ""
note "test_entrypoint_repository.sh: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
