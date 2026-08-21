"""Feature 016 (run observability) foundational unit tests — hermetic, no runtime.

Covers the machinery every later phase is built on: where the durable store lives
(R1), the atomic write and directory listing that Feature 014 will share (R3 /
FR-011a), the closed outcome vocabulary enforced at construction (C5), and the
tenth-volume migration in BOTH directions (T010, and the T129d lesson that the
reverse path is the one that gets forgotten).

Requirement anchors are named in the bodies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}
_ROOT = Path(__file__).resolve().parents[2]


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


# --- T001: the mount point exists in the image, dev-owned --------------------


def test_the_runs_mount_point_is_created_dev_owned_before_the_user_switch(wiz):
    """CLAUDE.md's invariant, and the one the runtime enforces: a named volume
    whose mount point does not exist in the image is created root:root, and a
    rootless container cannot write it — not even under a dev-owned parent. After
    `USER dev` the build can no longer chown anything, so ordering is the property.

    This verifies the DECLARATION, not the effect — a Dockerfile cannot be executed
    in a hermetic test. Only the acceptance tier proves the built image is writable.
    """
    body = (_ROOT / "image" / "Dockerfile").read_text()
    mount = wiz.RUNS_MOUNT_PATH
    assert f"mkdir -p {mount}" in body, f"{mount} is never created in the image"
    chown = "chown -R dev:dev /var/lib/agent-container"
    assert chown in body, f"{mount} is created but never handed to dev"
    assert body.index(chown) < body.index("\nUSER dev"), (
        "the chown runs after the USER switch, where the build is no longer root"
    )


# --- T005: where the durable store lives (R1) --------------------------------


def test_store_dir_is_under_xdg_data_home(wiz, tmp_path):
    p = wiz.runs_store_dir("vps", "demo")
    assert p == tmp_path / "xdg-data" / "agent-container" / "runs" / "vps" / "demo"


def test_store_dir_falls_back_to_local_share(load_wiz, tmp_path):
    """R1: XDG_DATA_HOME unset must resolve to ~/.local/share, not to the state
    dir — which docs/layout.md documents as 'computed; safe to delete'. A durable
    record kept somewhere safe to delete is the contradiction R1 exists to avoid."""
    home = tmp_path / "h"
    wiz = load_wiz(home=home, xdg_data=None)
    assert wiz.runs_store_dir("local", "demo") == (
        home / ".local/share" / "agent-container" / "runs" / "local" / "demo"
    )


def test_store_dir_separates_hosts_and_environments(wiz):
    """The same environment name can be deployed to several hosts; two runs must
    not land in one directory where neither could say which host it came from."""
    assert wiz.runs_store_dir("a", "demo") != wiz.runs_store_dir("b", "demo")
    assert wiz.runs_store_dir("a", "demo") != wiz.runs_store_dir("a", "other")


# --- T006: the atomic write (R3), shared with Feature 014 (FR-011a) ----------


def test_atomic_write_creates_the_directory_and_round_trips(wiz, tmp_path):
    d = tmp_path / "store" / "nested"
    p = wiz.atomic_write_json(d, "r1.json", {"a": 1})
    assert p == d / "r1.json"
    assert json.loads(p.read_text()) == {"a": 1}
    assert p.read_text().endswith("\n")


def test_atomic_write_stages_inside_the_target_directory(wiz, tmp_path, monkeypatch):
    """os.replace is atomic only WITHIN a filesystem. A temp file in $TMPDIR can
    land on a different one, where the rename degrades to a copy a reader can catch
    half-done — the exact failure the helper exists to prevent (R3)."""
    d = tmp_path / "store"
    seen: dict[str, str] = {}
    real = os.replace
    monkeypatch.setattr(wiz.os, "replace", lambda a, b: seen.update(src=str(a)) or real(a, b))
    wiz.atomic_write_json(d, "r1.json", {"a": 1})
    assert os.path.dirname(seen["src"]) == str(d)


def test_a_failed_write_leaves_no_file_at_the_final_name_and_no_debris(wiz, tmp_path):
    """FR-009: a partially written record must never be visible. Nothing may
    appear at the final name, and a failed write must not accumulate temp files in
    a directory whose whole retention story is 'delete files'."""
    d = tmp_path / "store"
    d.mkdir()
    with pytest.raises(TypeError):
        wiz.atomic_write_json(d, "r1.json", {"bad": object()})
    assert not (d / "r1.json").exists()
    assert list(d.iterdir()) == []


def test_atomic_write_knows_nothing_about_run_records(wiz, tmp_path):
    """FR-011a: Feature 014 adopts this machinery for a DIFFERENT schema. A helper
    that reached for a run record's fields could not be shared, and 014 would grow
    a second, subtly different atomic write."""
    p = wiz.atomic_write_json(tmp_path / "inv", "host-a.json", ["not", "a", "record"])
    assert json.loads(p.read_text()) == ["not", "a", "record"]


# --- T007: the listing helper -------------------------------------------------


def test_listing_is_newest_first(wiz, tmp_path):
    d = tmp_path / "store"
    for i, name in enumerate(("old.json", "mid.json", "new.json")):
        wiz.atomic_write_json(d, name, {"i": i})
        os.utime(d / name, (1000 + i * 100, 1000 + i * 100))
    assert [p.name for p in wiz.list_stored_records(d)] == ["new.json", "mid.json", "old.json"]


def test_listing_a_missing_directory_is_empty_not_an_error(wiz, tmp_path):
    """An environment that has never run is not an error state."""
    assert wiz.list_stored_records(tmp_path / "never") == []


def test_listing_hides_an_in_flight_write(wiz, tmp_path):
    """The suffix filter is load-bearing, not cosmetic: atomic_write_json stages
    under a dot-prefixed .tmp name, and a half-written record listed as a finished
    one would be read as a corrupt record rather than as no record at all."""
    d = tmp_path / "store"
    wiz.atomic_write_json(d, "r1.json", {"a": 1})
    (d / ".r1.json.abcd.tmp").write_text("{partial")
    assert [p.name for p in wiz.list_stored_records(d)] == ["r1.json"]


def test_equal_mtimes_still_order_deterministically(wiz, tmp_path):
    """Two records written in the same second must not reorder between listings —
    the name breaks the tie rather than the filesystem's arbitrary order."""
    d = tmp_path / "store"
    for name in ("a.json", "b.json", "c.json"):
        wiz.atomic_write_json(d, name, {})
        os.utime(d / name, (500, 500))
    assert [p.name for p in wiz.list_stored_records(d)] == ["c.json", "b.json", "a.json"]


# --- T008/T009: the closed outcome vocabulary (C5, FR-003, SC-002) -----------


def test_every_legal_kind_outcome_pair_is_accepted(wiz):
    for kind, outcomes in wiz.RUN_OUTCOMES.items():
        for outcome in outcomes:
            # exit_code is headless-only and never applies to never-started.
            exit_code = 0 if (kind == "headless" and outcome != "never-started") else None
            # Feature 017: a management action has NO AGENT. Passing one is
            # refused rather than ignored — naming an agent that did not run would
            # be an invented fact, the same reason an interactive record may not
            # carry a task.
            agent = None if kind == wiz.RUN_KIND_MANAGEMENT else "claude"
            r = _record(
                wiz, kind=kind, outcome=outcome, exit_code=exit_code, task=None, agent=agent
            )
            assert (r["kind"], r["outcome"]) == (kind, outcome)


def test_a_management_record_REFUSES_an_agent(wiz):
    """FR-009a: no agent ran. A placeholder here would be a fact nobody
    established, and `runs list` would then attribute a management action to an
    agent that was never involved."""
    with pytest.raises(wiz.Fatal, match="management action has no agent"):
        _record(wiz, kind="management", outcome="performed", task=None, agent="claude")


def _assert_interactive_completion_outcomes_are_refused(wiz):
    """The guard under test, factored out so the proof-it-can-fail case below can
    run the SAME assertions against a neutered vocabulary."""
    for outcome in ("finished", "failed"):
        with pytest.raises(wiz.Fatal, match="not legal for kind 'interactive'"):
            _record(wiz, kind="interactive", outcome=outcome)


def test_interactive_can_never_be_finished_or_failed(wiz):
    """C5/FR-003: a session has no completion semantics, so the two completion
    outcomes are UNREPRESENTABLE for it — refused where the record is constructed,
    which is the only place the rule can be made structural rather than prose."""
    _assert_interactive_completion_outcomes_are_refused(wiz)


def test_the_vocabulary_guard_can_actually_fail(wiz, monkeypatch):
    """Proof-it-can-fail. Neuter the closed set — add the completion outcomes to
    the interactive vocabulary, i.e. exactly what "enforced by convention" would
    look like — and the guard above must break. Without this, the test would keep
    passing for a build where construction accepted anything, and SC-002 ('zero
    ambiguous endings') would be measured by a check that cannot notice."""
    monkeypatch.setitem(wiz.RUN_OUTCOMES, "interactive", ("ended", "stopped", "finished", "failed"))
    with pytest.raises(pytest.fail.Exception):
        _assert_interactive_completion_outcomes_are_refused(wiz)


def test_an_unknown_kind_is_refused(wiz):
    with pytest.raises(wiz.Fatal, match="unknown kind"):
        _record(wiz, kind="batch", outcome="finished")


def test_an_unknown_agent_is_refused(wiz):
    """SC-005 rests on the field set being CLOSED and every non-task field being
    tool-generated. An agent name outside AGENTS means the caller invented one."""
    with pytest.raises(wiz.Fatal, match="unknown agent"):
        _record(wiz, agent="gpt")


def test_an_interactive_session_carries_no_task(wiz):
    """FR-002: a session was never given a task, so a task on a session record
    would be an invented fact rather than a recorded one."""
    with pytest.raises(wiz.Fatal, match="no task"):
        _record(wiz, kind="interactive", outcome="ended", task="do the thing")


def test_exit_code_is_headless_only_and_absent_for_never_started(wiz):
    """A `0` on a session or on a container that never ran would read as a clean
    run that never happened."""
    with pytest.raises(wiz.Fatal, match="exit_code"):
        _record(wiz, kind="interactive", outcome="ended", task=None, exit_code=0)
    with pytest.raises(wiz.Fatal, match="exit_code"):
        _record(wiz, outcome="never-started", exit_code=0)
    assert _record(wiz, outcome="never-started")["exit_code"] is None


def test_record_shape_matches_the_data_model(wiz):
    r = _record(wiz, ended_at="2026-08-09T10:12:00Z", exit_code=0, task="tidy the imports")
    assert set(r) == {
        "schema",
        "run_id",
        "environment",
        "host",
        "agent",
        "kind",
        "task",
        "started_at",
        "ended_at",
        "outcome",
        "exit_code",
        "repository",
        "usage",
        # Feature 017, data-model §6. Spelled out rather than derived from
        # RECORD_FIELD_PROVENANCE on purpose: this literal is a SECOND encoding of
        # the data model, so a field added to the table alone fails here instead
        # of silently agreeing with itself.
        "attribution",
        "egress_decision",
        "export_state",
        "notes",
    }
    assert r["schema"] == wiz.RUN_SCHEMA == 1
    # FR-009h: `pending` at birth on every record — written, not yet resolved
    # with the endpoint. Never absent: an absent state cannot distinguish a record
    # that was never sent from one whose outcome was lost.
    assert r["export_state"] == wiz.EXPORT_PENDING
    # host is stamped at INGESTION — the container does not reliably know what the
    # operator calls its host (data-model §1).
    assert r["host"] is None


def test_unreported_usage_is_a_value_and_never_zero(wiz):
    """FR-006/SC-004: a false zero silently understates every total it enters, and
    omitting the key would be indistinguishable from a schema change — a consumer
    would read the absence as zero (R6)."""
    r = _record(wiz)
    assert r["usage"] == {"reported": False}
    assert r["usage"].get("units") is None


def test_the_task_text_is_recorded_verbatim(wiz):
    """R9/C13: no pattern-based redaction. A redactor that misses one value turns
    an operator's caution into misplaced confidence; the rule is stated, not
    filtered. The one field that could carry a credential is the one field a human
    wrote, and that boundedness is the whole claim."""
    task = "deploy to $STAGING with token ghp_notARealToken"
    assert _record(wiz, task=task)["task"] == task


# --- T010/T011: the tenth-volume migration, BOTH directions ------------------


def _deploy_model(wiz, host, name, volumes):
    """Write the generated compose model the tool left behind for a deployment."""
    return wiz.write_compose_file(host, name, {"volumes": {v: {"name": v} for v in volumes}})


def _nine(wiz, name):
    """The pre-016 volume set: everything except the runs volume."""
    return [v for v in wiz.per_container_volumes(name) if v != wiz.runs_volume_name(name)]


def test_adopting_the_tenth_volume(wiz):
    """The forward direction. Container name, port and all nine existing volume
    names are unchanged, so every identity check passes while the deployed shape
    differs — and an environment left alone writes its records into the container's
    own layer, where teardown destroys them."""
    _deploy_model(wiz, "local", "acme", _nine(wiz, "acme"))
    adopt, release = wiz.volume_set_migration("local", "acme", wiz.per_container_volumes("acme"))
    assert adopt == [wiz.runs_volume_name("acme")]
    assert release == []


def test_rolling_back_to_nine(wiz):
    """The reverse direction — T129d's lesson: only the adopt side was handled
    last time, and the drop side broke redeploy. Nothing here is special-cased to
    'runs': the same set difference populates both lists."""
    _deploy_model(wiz, "local", "acme", wiz.per_container_volumes("acme"))
    adopt, release = wiz.volume_set_migration("local", "acme", _nine(wiz, "acme"))
    assert adopt == []
    assert release == [wiz.runs_volume_name("acme")]


def test_a_current_deployment_needs_no_migration(wiz):
    """The case that must NOT fire. A detector that reported drift here would
    recreate every healthy environment on every deploy."""
    _deploy_model(wiz, "local", "acme", wiz.per_container_volumes("acme"))
    assert wiz.volume_set_migration("local", "acme", wiz.per_container_volumes("acme")) == ([], [])


def test_no_model_and_an_unreadable_model_both_mean_no_migration(wiz):
    """A failed read is not evidence of a stale shape. Inventing one would recreate
    a healthy environment on every deploy — worse than the migration it chases."""
    assert wiz.volume_set_migration("local", "never-deployed", ["x"]) == ([], [])
    wiz.compose_file_path("local", "acme").parent.mkdir(parents=True, exist_ok=True)
    wiz.compose_file_path("local", "acme").write_text("{not json")
    assert wiz.volume_set_migration("local", "acme", ["x"]) == ([], [])
    wiz.compose_file_path("local", "acme").write_text(json.dumps({"services": {}}))
    assert wiz.volume_set_migration("local", "acme", ["x"]) == ([], [])


def test_the_workspace_mode_change_is_the_same_migration(wiz):
    """Not a special case for 016: dropping the workspace volume (persistent →
    ephemeral) travels the SAME code path as adopting the runs volume, which is why
    the reverse direction cannot rot untested."""
    _deploy_model(wiz, "local", "acme", wiz.per_container_volumes("acme"))
    adopt, release = wiz.volume_set_migration("local", "acme", wiz.other_container_volumes("acme"))
    assert adopt == []
    assert release == [wiz.volume_name("acme")]


def test_both_directions_are_announced(wiz, monkeypatch):
    """Announced, not silent (T010). On the release side the operator also has to
    hear that the volume is left on the host and is no longer removed by --purge —
    otherwise the tool silently orphans storage the operator still pays for."""
    warned: list[str] = []
    monkeypatch.setattr(wiz, "warn", warned.append)

    _deploy_model(wiz, "local", "acme", _nine(wiz, "acme"))
    assert wiz.announce_volume_set_migration("local", "acme", wiz.per_container_volumes("acme"))
    assert any(wiz.runs_volume_name("acme") in m for m in warned)

    warned.clear()
    _deploy_model(wiz, "local", "acme", wiz.per_container_volumes("acme"))
    assert wiz.announce_volume_set_migration("local", "acme", _nine(wiz, "acme"))
    assert any("NOT deleted" in m for m in warned)

    warned.clear()
    assert not wiz.announce_volume_set_migration("local", "acme", wiz.per_container_volumes("acme"))
    assert warned == []


# --- T010 wiring: the identity check must stop reporting 'matching' ----------


@pytest.fixture
def running_and_config_clean(wiz, monkeypatch):
    """A running container whose agent-config matches the spec — i.e. every signal
    `apply` compared before Feature 016 says 'matching'."""
    cname = wiz.container_name("acme")
    monkeypatch.setattr(wiz, "host_container_names", lambda host, include_stopped=False: {cname})
    monkeypatch.setattr(
        wiz,
        "env_live_config",
        lambda hr, n: {"mode": "interactive", "agent": "claude", "repo": None, "egress": None},
    )
    return wiz.ExecSpec(mode="interactive", agent="claude", workspace="persistent")


def test_a_nine_volume_deployment_is_drifted_not_matching(wiz, running_and_config_clean):
    """The headline of T010. Before this, `apply` reported 'matching' forever for
    an environment deployed before the runs volume existed: nothing it compared
    could see the difference, and the records it dropped were silent by nature."""
    _deploy_model(wiz, "local", "acme", _nine(wiz, "acme"))
    state, detail = wiz.env_reconcile(
        LOCAL_HOST, "acme", running_and_config_clean, host_name="local"
    )
    assert state == "drifted"
    assert wiz.runs_volume_name("acme") in detail


def test_a_ten_volume_deployment_still_reports_matching(wiz, running_and_config_clean):
    """The other half, and the one that keeps the test above honest: an assertion
    that only ever sees 'drifted' would pass for an implementation that reports
    drift unconditionally — and `apply` would recreate every environment forever."""
    _deploy_model(wiz, "local", "acme", wiz.per_container_volumes("acme"))
    assert wiz.env_reconcile(LOCAL_HOST, "acme", running_and_config_clean, host_name="local") == (
        "matching",
        "",
    )


def test_reconcile_needs_the_host_KEY_not_the_host_record(wiz, running_and_config_clean):
    """The trap _previous_model_had_egress documents, one feature later: a host
    record does not carry its own key, so a wrong/blank host name resolves to a
    path that never exists and EVERY environment reports a matching volume set.
    Keyword-only and required, so the mistake cannot be made silently."""
    _deploy_model(wiz, "local", "acme", _nine(wiz, "acme"))
    with pytest.raises(TypeError):
        wiz.env_reconcile(LOCAL_HOST, "acme", running_and_config_clean)
    # And the failure it prevents: the wrong host key finds no model, so the stale
    # nine-volume deployment reads as matching.
    assert wiz.env_reconcile(
        LOCAL_HOST, "acme", running_and_config_clean, host_name="not-this-host"
    ) == ("matching", "")
