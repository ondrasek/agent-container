"""Feature 016 US2 — the repository effect, and the two questions it answers.

Three groups, all hermetic (no runtime, no network):

  * **T028** — the git exit codes research R4 MEASURED, re-measured here **unpiped**
    against real repositories. R4's table is what the container's classification is
    built on, so a git that changed one of them would silently turn a state into a
    wrong state rather than into an error.
  * **T029/T030** — `pushed` is null and never false without an upstream (C8), and
    commit-without-push is loud in BOTH renderings (FR-005, SC-003).
  * **T053/T054** — `runs list --changed <path>` (C16) answered from stored records
    only, with a candidate it cannot rule out reported as uncertain rather than
    dropped.

Requirement anchors are named in the bodies.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}

# --- T028: R4's exit codes, re-measured UNPIPED -------------------------------
#
# R4 recorded that its first probe read `$?` after piping git through `head` and
# so reported exit 0 for every failing case — `$?` is the last element of the
# pipeline. It is the same defect CLAUDE.md records for `quality-gate.sh | tail`,
# and it would have produced a research entry that was confidently wrong.
#
# So every assertion below reads `.returncode` from an UNPIPED subprocess.run,
# and one test pipes on purpose to show what the wrong method reports.

# Git's own environment is neutralised: a developer's global config (a
# commit.gpgsign, an init.defaultBranch, an includeIf) must not decide what these
# exit codes are, or the suite measures the machine rather than git.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """One git call, UNPIPED, with output captured and the exit code preserved.

    `GIT_CEILING_DIRECTORIES` stops discovery from walking out of the temporary
    tree: without it the "not a repository" case would find whatever repository
    happens to contain the temp directory, and the 128 this file pins would
    quietly become a 0 on someone else's machine.
    """
    env = {**GIT_ENV, "GIT_CEILING_DIRECTORIES": str(cwd.parent)}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)


@pytest.fixture(scope="module")
def repo_states(tmp_path_factory) -> dict[str, Path]:
    """The four situations R4 measured, as real repositories on disk.

    Built rather than mocked: the point of this group is that git still behaves
    the way the research says it does, and a mock would only assert what the test
    author remembered.

    Module-scoped because every case below only READS these repositories, and
    rebuilding four of them per parametrised case put ten seconds into a tier the
    Stop hook runs on every change.
    """
    root = tmp_path_factory.mktemp("r4")

    origin = root / "origin.git"
    origin.mkdir()
    assert git(origin, "init", "--bare", "--initial-branch=main").returncode == 0

    with_upstream = root / "with-upstream"
    with_upstream.mkdir()
    assert git(with_upstream, "init", "--initial-branch=main").returncode == 0
    (with_upstream / "a.txt").write_text("a\n")
    assert git(with_upstream, "add", "a.txt").returncode == 0
    assert git(with_upstream, "commit", "-m", "first").returncode == 0
    assert git(with_upstream, "remote", "add", "origin", str(origin)).returncode == 0
    assert git(with_upstream, "push", "-u", "origin", "main").returncode == 0

    no_upstream = root / "no-upstream"
    no_upstream.mkdir()
    assert git(no_upstream, "init", "--initial-branch=main").returncode == 0
    (no_upstream / "a.txt").write_text("a\n")
    assert git(no_upstream, "add", "a.txt").returncode == 0
    assert git(no_upstream, "commit", "-m", "first").returncode == 0

    detached = root / "detached"
    detached.mkdir()
    assert git(detached, "init", "--initial-branch=main").returncode == 0
    (detached / "a.txt").write_text("a\n")
    assert git(detached, "add", "a.txt").returncode == 0
    assert git(detached, "commit", "-m", "first").returncode == 0
    assert git(detached, "checkout", "--detach", "HEAD").returncode == 0

    no_repo = root / "no-repo"
    no_repo.mkdir()

    return {
        "with_upstream": with_upstream,
        "no_upstream": no_upstream,
        "detached": detached,
        "no_repo": no_repo,
    }


@pytest.mark.parametrize(
    ("situation", "argv", "expected"),
    [
        # R4's table, verbatim.
        ("no_upstream", ("rev-parse", "@{u}"), 128),
        ("with_upstream", ("rev-parse", "HEAD"), 0),
        ("detached", ("symbolic-ref", "-q", "HEAD"), 1),
        ("detached", ("rev-parse", "HEAD"), 0),
        ("no_repo", ("rev-parse", "HEAD"), 128),
        # The other half of each discriminator. Without these, a git whose
        # `symbolic-ref -q` failed on EVERY head, or whose `@{u}` failed
        # everywhere, would satisfy the rows above while making every state
        # `detached` or `no-upstream` — a check that passes while the thing it
        # names is broken.
        ("with_upstream", ("symbolic-ref", "-q", "HEAD"), 0),
        ("with_upstream", ("rev-parse", "@{u}"), 0),
    ],
)
def test_r4_exit_codes_still_hold(repo_states, situation, argv, expected):
    """The measured facts the container's state classification rests on (R4, C7).

    Each is an ORDINARY situation with a word of its own — `no-upstream`,
    `detached`, `no-repository` — so each has to be told apart by an exit code
    rather than by an error. If git changes one of these, the classification does
    not fail loudly: it reports the wrong state, and this is the test that notices.
    """
    assert git(repo_states[situation], *argv).returncode == expected


def test_reading_the_exit_code_through_a_PIPE_reports_the_wrong_thing(repo_states):
    """Proof the measurement METHOD matters, not only the numbers.

    `$?` after a pipeline is the last element's status, so the same failing call
    reads as success when it is piped. R4 hit exactly this and nearly recorded
    "exit 0" for every failing case; CLAUDE.md records the same defect for
    `quality-gate.sh | tail`. Both halves are asserted here so the file cannot be
    read as superstition.
    """
    cwd = repo_states["no_upstream"]
    assert git(cwd, "rev-parse", "@{u}").returncode == 128
    piped = subprocess.run(
        ["sh", "-c", "git rev-parse @{u} | head -1"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**GIT_ENV, "GIT_CEILING_DIRECTORIES": str(cwd.parent)},
    )
    assert piped.returncode == 0, "the pipe no longer hides the failure; the warning can be dropped"


# --- T028 (cont.): each state is a RECORD, not an error ----------------------


def _repo(**over) -> dict:
    """A repository effect in the shape of data-model §3."""
    effect = {
        "start_head": "a" * 40,
        "end_head": "a" * 40,
        "branch": "main",
        "upstream": "origin/main",
        "commits": [],
        "paths": [],
        "paths_truncated": False,
        "pushed": True,
        "state": "ok",
    }
    effect.update(over)
    return effect


def _record(wiz, **over):
    kw = dict(
        run_id="20260809T101010Z-ab12",
        environment="demo",
        agent="claude",
        kind="headless",
        outcome="finished",
        started_at="2026-08-09T10:10:10Z",
    )
    kw.update(over)
    return wiz.build_run_record(**kw)


@pytest.mark.parametrize("state", ["ok", "no-repository", "no-upstream", "detached", "unreadable"])
def test_every_measured_state_is_representable(wiz, state):
    """C7: `state` is not an error channel. An `ephemeral` workspace with no clone
    is the common case for a throwaway run, and a construction that refused it
    would push the most common situation out of the record entirely."""
    # Only `ok` has an upstream to compare against; the rest carry `pushed: null`
    # for the reason C8 gives, which the next group tests directly.
    effect = _repo(state=state) if state == "ok" else _repo(state=state, upstream=None, pushed=None)
    assert _record(wiz, repository=effect)["repository"]["state"] == state


def test_a_state_outside_the_closed_set_is_refused(wiz):
    """An invented state would render as itself and look authoritative — the
    reader has no way to tell `dirty` from a state the tool actually defines."""
    with pytest.raises(wiz.Fatal, match="unknown repository state"):
        _record(wiz, repository=_repo(state="dirty"))


def test_a_record_with_no_repository_effect_at_all_is_still_a_record(wiz):
    """`repository: null` is legal (data-model §1) — the never-started record uses
    it. It means "no effect captured", which is not the same claim as
    `state: no-repository`, and neither is an error."""
    assert _record(wiz, repository=None)["repository"] is None


# --- T029: `pushed` is null, never false, without an upstream (C8) -----------


def _assert_pushed_needs_an_upstream(wiz):
    """The guard under test, factored out so the proof-it-can-fail case below can
    run the SAME assertions against a neutered guard."""
    for pushed in (False, True):
        with pytest.raises(wiz.Fatal, match="pushed must be null"):
            _record(wiz, repository=_repo(state="no-upstream", upstream=None, pushed=pushed))


def test_pushed_must_be_null_when_there_is_no_upstream(wiz):
    """C8, and the reason it is a refusal rather than a warning: `false` means
    "committed and did not push", the failure Constitution I exists to prevent and
    the loudest signal this feature has. Spent once on "could not tell", every
    future one is unreliable. `true` is refused on the same footing — without an
    upstream it would be a verification that never happened."""
    _assert_pushed_needs_an_upstream(wiz)


def test_the_pushed_guard_can_actually_fail(wiz, monkeypatch):
    """Proof-it-can-fail. Neuter the check — which is what "the writer will get it
    right" looks like in code — and the assertions above must break. Without this
    they would keep passing for a build that accepted `pushed: false` with no
    upstream, and C8 would be measured by a check that cannot notice."""
    monkeypatch.setattr(wiz, "validate_repository_effect", lambda repo: None)
    with pytest.raises(pytest.fail.Exception):
        _assert_pushed_needs_an_upstream(wiz)


def test_the_shape_C8_requires_is_accepted(wiz):
    """The other direction, and the one that keeps the test above honest: a guard
    that refused every no-upstream effect would make the `no-upstream` state
    unrecordable, which is C7's failure instead of C8's."""
    rec = _record(wiz, repository=_repo(state="no-upstream", upstream=None, pushed=None))
    assert rec["repository"]["pushed"] is None


def test_a_real_commit_without_push_is_recordable(wiz):
    """`pushed: false` WITH an upstream is the fact FR-005 exists to surface. A
    guard that refused it would have deleted the alarm rather than protected it."""
    rec = _record(wiz, repository=_repo(commits=["abc123"], pushed=False))
    assert rec["repository"]["pushed"] is False


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        ({"commits": ["abc"], "pushed": False, "upstream": "origin/main"}, "unpushed"),
        ({"commits": ["abc"], "pushed": True, "upstream": "origin/main"}, "pushed"),
        ({"commits": ["abc"], "pushed": None, "upstream": None}, "unknown"),
        # WAS "nothing", and that was the defect adversarial review found. `pushed:
        # false` means the exit head is provably NOT on the upstream, so something
        # is outstanding by definition — while the writer emits `commits: []` for an
        # UNKNOWN list as well as an empty one (a rev-list failure, unattributable
        # history, or the exit-capture deadline under SIGTERM). Classifying on
        # `commits` turned that into "nothing to push" for a run whose work existed
        # only in the container: SC-003's clean-looking failure, produced by the
        # check written to prevent it.
        ({"commits": [], "pushed": False, "upstream": "origin/main"}, "unpushed"),
        # C8's contradiction, from a writer this tool does not control: `false`
        # with no upstream. Read as the alarm, not as silence — see push_status.
        ({"commits": ["abc"], "pushed": False, "upstream": None}, "unpushed"),
    ],
)
def test_push_status_classifies_each_case(wiz, effect, expected):
    """One classifier for both renderings (C8): two sites deciding separately what
    counts as commit-without-push is how `--json` ends up quiet about a run the
    table shouts about."""
    assert wiz.push_status(_repo(**effect)) == expected


def test_could_not_tell_is_never_rendered_as_did_not_push(wiz):
    """The human half of C8. Conflating the two would make the loudest signal in
    the feature unreliable in the exact direction that matters."""
    rows = dict(wiz.render_repository(_repo(commits=["abc"], upstream=None, pushed=None)))
    assert "could not tell" in rows["push"]
    assert "!! push" not in rows


# --- T030: commit-without-push is LOUD in both renderings --------------------


@pytest.fixture
def store(wiz, monkeypatch):
    """A durable store the read commands work against, with no drain: these are
    being tested as READERS of records that already exist."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])

    def _add(
        run_id: str, *, environment: str = "acme", started: str = "2026-08-09T10:00:00Z", **over
    ):
        rec = _record(
            wiz, run_id=run_id, environment=environment, started_at=started, exit_code=0, **over
        )
        rec["host"] = "local"
        wiz.atomic_write_json(wiz.runs_store_dir("local", environment), f"{run_id}.json", rec)
        return rec

    return _add


def test_json_names_the_unpushed_runs(store, wiz, capsys):
    """T030/C8 in `--json`. Each record is served verbatim (C2), so without this
    key an agent has to re-derive the alarm from `repository.pushed` — and an
    agent that forgets to is exactly SC-003's run that "looks like a clean
    success"."""
    store("r-clean", repository=_repo(commits=["abc"], pushed=True))
    store("r-dirty", repository=_repo(commits=["def"], pushed=False))
    store("r-unknown", repository=_repo(commits=["ghi"], upstream=None, pushed=None))
    wiz.set_json_mode(True)
    wiz.do_runs_list("acme", None, True)
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["unpushed"] == ["r-dirty"]
    assert len(data["runs"]) == 3


def test_json_reports_the_key_even_when_nothing_is_unpushed(store, wiz, capsys):
    """Always present, even empty: a key that appeared only when non-empty would
    leave a consumer unable to tell "no run committed without pushing" from "this
    build does not report it"."""
    store("r-clean", repository=_repo(commits=["abc"], pushed=True))
    wiz.set_json_mode(True)
    wiz.do_runs_list("acme", None, True)
    assert json.loads(capsys.readouterr().out)["data"]["unpushed"] == []


def test_the_human_listing_names_the_unpushed_run(store, wiz, capsys):
    """The listing's columns are what the run WAS, not what it left behind, so
    without this line a commit-without-push is present in the store and invisible
    on screen. The id is spelled out, not counted: a count announces a problem and
    leaves the operator to find it."""
    store("r-clean", repository=_repo(commits=["abc"], pushed=True))
    store("r-dirty", repository=_repo(commits=["def"], pushed=False))
    wiz.set_json_mode(False)
    wiz.do_runs_list("acme", None, False)
    out = capsys.readouterr().out
    assert "COMMITTED WITHOUT PUSHING" in out
    assert "r-dirty" in out


def test_a_run_that_could_not_tell_is_not_flagged_as_unpushed(store, wiz, capsys):
    """The false-alarm direction. An alarm that fires for every run with no
    upstream is one an operator learns to ignore, and then SC-003 is measured on a
    signal nobody reads."""
    store("r-unknown", repository=_repo(commits=["abc"], upstream=None, pushed=None))
    wiz.set_json_mode(False)
    wiz.do_runs_list("acme", None, False)
    out = capsys.readouterr().out
    assert "COMMITTED WITHOUT PUSHING" not in out
    assert (
        wiz.unpushed_run_ids([{"run_id": "x", "repository": _repo(upstream=None, pushed=None)}])
        == []
    )


def test_show_states_commit_without_push_in_words(store, wiz, capsys):
    """`runs show` is where an operator lands after the listing flags the run, so
    the same fact has to be stated there in words rather than as `pushed: false`
    among nine other fields."""
    store("r-dirty", repository=_repo(commits=["def456"], pushed=False))
    wiz.set_json_mode(False)
    wiz.do_runs_show("r-dirty", None, False)
    assert "COMMITTED WITHOUT PUSHING" in capsys.readouterr().out


# --- T053: `runs list --changed <path>` (C16, SC-007) ------------------------


def test_changed_returns_exactly_the_runs_that_touched_the_file(store, wiz, capsys):
    """SC-007 with five runs present, which is the N the criterion names."""
    store("r-1", started="2026-08-09T10:01:00Z", repository=_repo(paths=["src/auth/session.py"]))
    store("r-2", started="2026-08-09T10:02:00Z", repository=_repo(paths=["README.md"]))
    store("r-3", started="2026-08-09T10:03:00Z", repository=_repo(paths=["src/auth/session.py"]))
    store("r-4", started="2026-08-09T10:04:00Z", repository=_repo(paths=[]))
    store("r-5", started="2026-08-09T10:05:00Z", repository=_repo(paths=["src/authz/policy.py"]))
    wiz.set_json_mode(True)
    wiz.do_runs_list("acme", None, True, "src/auth/session.py")
    data = json.loads(capsys.readouterr().out)["data"]
    # Newest-first is preserved by the filter rather than re-derived.
    assert [r["run_id"] for r in data["runs"]] == ["r-3", "r-1"]
    assert data["uncertain"] == []


def test_changed_opens_no_repository_and_spawns_no_process(store, wiz, capsys):
    """R11/C16: the paths were captured when the run ended, so the query is a
    lookup over stored records. Asserted by making any subprocess fatal — a build
    that resolved SHAs at query time would need one, and would then answer nothing
    at all on a machine that no longer has the clone."""

    def boom(*a, **k):
        raise AssertionError("--changed spawned a process; it must read stored records only")

    store("r-1", repository=_repo(paths=["src/auth/session.py"]))
    wiz.set_json_mode(True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiz.subprocess, "run", boom)
        wiz.do_runs_list("acme", None, True, "src/auth/session.py")
    assert [r["run_id"] for r in json.loads(capsys.readouterr().out)["data"]["runs"]] == ["r-1"]


def test_the_command_actually_passes_changed_through(wiz, monkeypatch):
    """The WIRING, which nothing else in this file touches: every case above calls
    `do_runs_list` directly, so a `runs list` that accepted `--changed` and then
    dropped it would satisfy all of them while listing the whole store — a command
    that answers a different question than the one asked."""
    seen: dict = {}
    monkeypatch.setattr(wiz, "do_runs_list", lambda *a: seen.update(args=a))
    result = CliRunner().invoke(wiz.app, ["runs", "list", "acme", "--changed", "src/a.py"])
    assert result.exit_code == 0, result.output
    assert seen["args"] == ("acme", None, False, "src/a.py")


@pytest.mark.parametrize(
    ("recorded", "wanted", "covered"),
    [
        ("src/auth/session.py", "src/auth/session.py", True),
        ("src/auth/session.py", "src/auth", True),
        ("src/authz/policy.py", "src/auth", False),
        ("src/auth/session.py", "session.py", False),
    ],
)
def test_path_matching_is_exact_or_a_directory(wiz, recorded, wanted, covered):
    """A directory answers for the files under it — an operator asking about
    `src/auth` means the directory, and matching the file alone would report "no
    run touched it" for a run that rewrote all of it. A bare suffix does NOT
    match: `session.py` would otherwise collect every session.py in the tree and
    the answer would name runs that touched a different file."""
    assert wiz.path_is_covered(recorded, wanted) is covered


@pytest.mark.parametrize("given", ["/abs/src/a.py", "../a.py", "src/../../a.py", "", "   "])
def test_a_path_that_cannot_be_repo_relative_is_refused(wiz, given):
    """Records hold repo-relative paths and this command reads nothing else, so
    there is no repository root here to resolve an absolute or `..` path against.
    Searching for one would match nothing — and a confident empty answer is
    exactly what C16 forbids. Refusing says which question cannot be answered."""
    with pytest.raises(wiz.Fatal, match="not a repository-relative path"):
        wiz.normalise_changed_path(given)


def test_leading_dot_slash_and_trailing_slash_are_the_same_question(wiz):
    """`./src/auth/` is how a shell completes a directory. Three spellings that
    silently answered differently would make the empty result a property of the
    typing rather than of the runs."""
    assert wiz.normalise_changed_path("./src/auth/") == "src/auth"
    assert wiz.normalise_changed_path("src/auth") == "src/auth"


def test_no_match_says_so_rather_than_printing_nothing(store, wiz, monkeypatch, capsys):
    """C1's rule applied to `--changed`: an empty screen and "no run touched it"
    look identical, and only one of them is an answer."""
    said: list[str] = []
    monkeypatch.setattr(wiz, "log", said.append)
    store("r-1", repository=_repo(paths=["README.md"]))
    wiz.set_json_mode(False)
    wiz.do_runs_list("acme", None, False, "src/auth/session.py")
    assert any("no stored record shows a change to src/auth/session.py" in m for m in said)


# --- T054: a candidate that cannot be ruled out is UNCERTAIN, not dropped ----


def _assert_a_truncated_non_match_is_uncertain(wiz):
    """The rule under test, factored out so the proof-it-can-fail case can run the
    SAME assertions against a build that drops uncertainty."""
    rec = {
        "run_id": "r-cut",
        "environment": "acme",
        "repository": _repo(paths=["README.md"], paths_truncated=True),
    }
    verdict, reason = wiz.changed_path_verdict(rec, "src/auth/session.py")
    assert verdict == wiz.CHANGED_UNCERTAIN
    assert "truncated" in reason
    matched, uncertain = wiz.select_changed([rec], "src/auth/session.py")
    assert matched == []
    assert [u["run_id"] for u in uncertain] == ["r-cut"]


def test_a_truncated_list_that_does_not_match_is_uncertain(wiz):
    """C16's headline. The path may have been in the part that was cut, so a
    confident "no run changed that file" from a truncated list is the failure the
    contract exists to prevent — the same shape as a check that passes while the
    thing it names is broken."""
    _assert_a_truncated_non_match_is_uncertain(wiz)


def test_the_uncertainty_rule_can_actually_fail(wiz, monkeypatch):
    """Proof-it-can-fail. Make every non-match a confident `no` — which is what
    "just filter the records" looks like in code — and the assertions above must
    break. Without this they would keep passing for a build that silently omitted
    every truncated candidate."""
    monkeypatch.setattr(
        wiz,
        "changed_path_verdict",
        lambda rec, wanted: (
            (wiz.CHANGED_MATCH, "")
            if any(wiz.path_is_covered(str(p), wanted) for p in rec["repository"]["paths"])
            else (wiz.CHANGED_NO, "")
        ),
    )
    # Both exception types: the helper's plain asserts raise AssertionError, while
    # a `pytest.raises` that saw nothing raises Failed. Naming only one would make
    # the proof depend on which assertion in the helper happens to break first.
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _assert_a_truncated_non_match_is_uncertain(wiz)


def test_a_truncated_list_that_DOES_match_is_a_match(wiz):
    """The other half, and the one that keeps the rule from degenerating: a match
    inside a truncated list is still a fact. Reporting it as uncertain would make
    every truncated run permanently unanswerable."""
    rec = {"run_id": "r-cut", "repository": _repo(paths=["src/a.py"], paths_truncated=True)}
    assert wiz.changed_path_verdict(rec, "src/a.py") == (wiz.CHANGED_MATCH, "")


def test_a_record_with_no_path_list_cannot_be_ruled_out(wiz):
    """Silence about the paths is not evidence they were untouched — a record from
    before the paths were captured, or one whose capture failed, knows nothing
    either way. Same reasoning as truncation, one step earlier."""
    verdict, reason = wiz.changed_path_verdict({"run_id": "r-old", "repository": None}, "a.py")
    assert verdict == wiz.CHANGED_UNCERTAIN
    assert "no path list" in reason


@pytest.mark.parametrize(
    "rec",
    [
        {"run_id": "r-never", "outcome": "never-started", "repository": None},
        {"run_id": "r-bare", "repository": {"state": "no-repository"}},
    ],
)
def test_the_two_runs_that_CAN_be_ruled_out_without_a_path_list(wiz, rec):
    """A container that never started and a workspace that held no repository
    could not have changed a file. Calling them uncertain would fill every answer
    with runs that provably touched nothing, and an uncertainty list nobody can
    finish reading is one nobody reads."""
    assert wiz.changed_path_verdict(rec, "a.py") == (wiz.CHANGED_NO, "")


def test_json_carries_the_uncertain_runs_beside_the_matches(store, wiz, capsys):
    """Uncertain entries are DELIBERATELY not records: they are not answers, and
    putting them in `runs` would let a consumer read that list as "the runs that
    changed this file" and be wrong."""
    store("r-hit", started="2026-08-09T10:02:00Z", repository=_repo(paths=["src/a.py"]))
    store(
        "r-cut",
        started="2026-08-09T10:01:00Z",
        repository=_repo(paths=["README.md"], paths_truncated=True),
    )
    wiz.set_json_mode(True)
    wiz.do_runs_list("acme", None, True, "src/a.py")
    data = json.loads(capsys.readouterr().out)["data"]
    assert [r["run_id"] for r in data["runs"]] == ["r-hit"]
    assert [u["run_id"] for u in data["uncertain"]] == ["r-cut"]
    assert "truncated" in data["uncertain"][0]["reason"]


def test_the_human_answer_says_it_is_incomplete(store, wiz, monkeypatch, capsys):
    """The case S13 calls "a wrong answer that looks right": zero matches and a
    truncated candidate. The operator must not read that as "no run changed it"."""
    said: list[str] = []
    monkeypatch.setattr(wiz, "log", said.append)
    store("r-cut", repository=_repo(paths=["README.md"], paths_truncated=True))
    wiz.set_json_mode(False)
    wiz.do_runs_list("acme", None, False, "src/a.py")
    out = capsys.readouterr().out + "\n".join(said)
    assert "cannot be ruled out" in out
    assert "NOT complete" in out
    assert "r-cut" in out


def test_uncertainty_is_reported_alongside_matches_too(store, wiz, capsys):
    """A match does not make the rest of the answer certain. Suppressing the
    uncertain list whenever something matched would hide it exactly when the
    operator has a reason to believe the answer is complete."""
    store("r-hit", started="2026-08-09T10:02:00Z", repository=_repo(paths=["src/a.py"]))
    store(
        "r-cut",
        started="2026-08-09T10:01:00Z",
        repository=_repo(paths=["README.md"], paths_truncated=True),
    )
    wiz.set_json_mode(False)
    wiz.do_runs_list("acme", None, False, "src/a.py")
    out = capsys.readouterr().out
    assert "r-hit" in out
    assert "cannot be ruled out" in out


# --- the truncation flag is never silent in `runs show` either ---------------


def test_show_states_the_capture_cap_in_the_same_words_as_the_count(wiz):
    """C16/R11: `paths_truncated` rendered as a footnote — or not at all — is what
    makes a partial list look complete. It travels in the same line as the count."""
    rows = dict(wiz.render_repository(_repo(paths=["a.py", "b.py"], paths_truncated=True)))
    assert "TRUNCATED" in rows["files"]
    rows = dict(wiz.render_repository(_repo(paths=["a.py", "b.py"])))
    assert "TRUNCATED" not in rows["files"]
    assert "2 changed" in rows["files"]
