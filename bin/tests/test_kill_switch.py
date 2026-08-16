"""Feature 015: the kill switch (`panic`).

The hard part is not stopping things. It is being HONEST about failure: an
operator reaching for this is already having a bad day, and a report that
overstates success is worse than an error because it ends the investigation.

Every test below exists because its absence would be invisible in a green run.
"""

from __future__ import annotations

import json

import pytest

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample0000000000000000000000000000000="


@pytest.fixture
def seeded(wiz):
    """Two recorded environments on one host, both active."""
    for n in ("alpha", "beta"):
        wiz.write_inventory_entry(wiz.build_inventory_entry(n, "local", False))
    return wiz


def _reachable(wiz, monkeypatch, present: dict[str, set[str]]):
    """A host that answers, reporting `present` per project."""

    def fake(host_rec, project, include_stopped):
        return set(present.get(project, ()))

    monkeypatch.setattr(wiz, "project_containers", fake)


def _unreachable(wiz, monkeypatch):
    def boom(*_a, **_kw):
        raise wiz.Fatal("host did not answer")

    monkeypatch.setattr(wiz, "project_containers", boom)


def _no_act(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "run_child", lambda *a, **k: type("R", (), {"returncode": 0})())


# --- the constants carry their own reasons -----------------------------------


def test_the_timeout_has_a_floor_not_a_taste(wiz):
    """It must exceed the 20s bound host_ps_rows applies to its own query, or the
    budget expires BEFORE the call it is meant to bound and a healthy-but-loaded
    host is reported undetermined while its ps is still legitimately running."""
    assert wiz.KILL_HOST_TIMEOUT > 20.0
    assert wiz.KILL_HOST_TIMEOUT > wiz.RUNS_PROBE_TIMEOUT  # 10s would inherit the bug


def test_the_outcome_set_is_closed_and_ok_is_a_strict_subset(wiz):
    assert wiz.KILL_OUTCOMES == ("stopped", "already-stopped", "failed", "undetermined")
    assert set(wiz.KILL_OK_OUTCOMES) < set(wiz.KILL_OUTCOMES)
    # undetermined is NOT ok — the requirement the whole feature turns on.
    assert "undetermined" not in wiz.KILL_OK_OUTCOMES
    assert "failed" not in wiz.KILL_OK_OUTCOMES


# --- enumeration comes from the RECORD ---------------------------------------


def test_only_active_entries_are_candidates(seeded):
    seeded.set_inventory_outcome("beta", "local", "removed")
    assert [e["name"] for e in seeded.kill_candidates(None, None)] == ["alpha"]


def test_scope_resolves_from_stored_fields_without_contacting_a_host(seeded, monkeypatch):
    """FR-011: scoping that needed a daemon would depend on the very reachability
    this feature cannot assume."""

    def explode(*_a, **_kw):
        raise AssertionError("contacted a host to resolve a scope")

    monkeypatch.setattr(seeded, "project_containers", explode)
    monkeypatch.setattr(seeded, "query", explode)
    assert [e["name"] for e in seeded.kill_candidates(["local"], ["alpha"])] == ["alpha"]
    assert seeded.kill_candidates(["nosuch"], None) == []


# --- unreadable refuses; absent succeeds -------------------------------------


def test_an_unreadable_store_refuses_and_does_not_enumerate_live(wiz, monkeypatch):
    """FR-013/SC-009. The mischief is SILENT FALLBACK — so the refusal must also not
    reach for a daemon on the way out."""
    d = wiz.inventory_store_dir()
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(wiz.os, "access", lambda *a, **k: False)
    monkeypatch.setattr(
        wiz, "project_containers", lambda *a, **k: pytest.fail("fell back to live enumeration")
    )
    with pytest.raises(wiz.Fatal, match="refusing to fall back"):
        wiz.kill_read_inventory()


def test_an_absent_store_succeeds_and_does_not_claim_nothing_exists(wiz, capsys):
    assert not wiz.inventory_store_dir().exists()
    wiz.do_panic(None, None, False, False, False, 1.0, False)
    err = capsys.readouterr().err
    assert "nothing was RECORDED" in err
    assert "not that nothing exists" in err  # the tool cannot make that claim


# --- THE GATE: an unreachable host is undetermined, never stopped ------------


def test_an_unreachable_host_is_undetermined_and_NEVER_stopped(seeded, monkeypatch):
    """T014 — C3/SC-002. THE test for this feature.

    A build that reports success for a host it never reached passes every other test
    in this file.
    """
    _unreachable(seeded, monkeypatch)
    _no_act(seeded, monkeypatch)
    with pytest.raises(seeded.Fatal, match="did NOT succeed"):
        seeded.do_panic(None, None, False, False, False, 5.0, False)
    # And nothing was durably recorded as gone.
    assert all(e["outcome"] == "active" for e in seeded.read_inventory_entries())


def test_the_unreachable_assertion_has_a_positive_control(seeded, monkeypatch, capsys):
    """T015: asserting only the ABSENCE of `stopped` would pass for a build that
    classifies nothing at all. Prove the classifier does produce `stopped`."""
    _reachable(seeded, monkeypatch, {"agent-container-alpha": {"agent-container-alpha"}})
    _no_act(seeded, monkeypatch)
    monkeypatch.setattr(seeded, "kill_verify", lambda *a, **k: {"alpha": set(), "beta": set()})
    seeded.do_panic(None, ["alpha"], False, False, False, 5.0, True)
    out = json.loads(capsys.readouterr().out)["data"]
    assert [r["outcome"] for r in out["results"]] == ["stopped"]


def test_a_single_undetermined_among_many_stopped_still_fails_the_run(seeded, monkeypatch):
    """FR-005/SC-003: 'we do not know' is not success."""
    _no_act(seeded, monkeypatch)
    monkeypatch.setattr(seeded, "kill_snapshot", lambda h, e, f: {x["name"]: {"c"} for x in e})
    monkeypatch.setattr(seeded, "kill_verify", lambda h, e, f: {x["name"]: set() for x in e})
    real = seeded._kill_one_host

    def one_bad(host_name, rec, entries, form, preview):
        rows = real(host_name, rec, entries, form, preview)
        rows[0]["outcome"] = "undetermined"
        return rows

    monkeypatch.setattr(seeded, "_kill_one_host", one_bad)
    with pytest.raises(seeded.Fatal, match="not stopped or not confirmed"):
        seeded.do_panic(None, None, False, False, False, 5.0, False)


def test_one_hosts_failure_does_not_abort_the_others(wiz, monkeypatch, capsys):
    """FR-003: a run that aborts on first failure leaves an operator worse off than
    doing it by hand."""
    wiz.write_inventory_entry(wiz.build_inventory_entry("alpha", "local", False))
    wiz.write_inventory_entry(wiz.build_inventory_entry("beta", "gone", False))
    _no_act(wiz, monkeypatch)
    monkeypatch.setattr(wiz, "kill_snapshot", lambda h, e, f: {x["name"]: {"c"} for x in e})
    monkeypatch.setattr(wiz, "kill_verify", lambda h, e, f: {x["name"]: set() for x in e})
    # JSON mode signals failure by exit code on a SINGLE envelope, not by a second
    # error envelope — see test_json_mode_emits_exactly_ONE_envelope...
    with pytest.raises(wiz.typer.Exit):
        wiz.do_panic(None, None, False, False, False, 5.0, True)
    out = json.loads(capsys.readouterr().out)["data"]
    got = {r["name"]: r["outcome"] for r in out["results"]}
    assert got["alpha"] == "stopped"  # the reachable one still completed
    assert got["beta"] == "undetermined"  # host is not in the registry


# --- verification: two forms, two queries ------------------------------------


def test_classify_needs_the_BEFORE_state_to_tell_stopped_from_already_stopped(wiz):
    """I1: once a container is not running, nothing distinguishes 'we stopped it'
    from 'it was already stopped'. The pre-snapshot is the only difference."""
    assert wiz.classify_kill("a", before={"c"}, after=set()) == "stopped"
    assert wiz.classify_kill("a", before=set(), after=set()) == "already-stopped"
    assert wiz.classify_kill("a", before={"c"}, after={"c"}) == "failed"


def test_the_two_forms_query_differently(wiz, monkeypatch):
    """R2: a stopped container still EXISTS, so verifying a stop against `ps -a`
    would report every stop as failed."""
    seen = []
    monkeypatch.setattr(
        wiz,
        "project_containers",
        lambda h, p, include_stopped: seen.append(include_stopped) or set(),
    )
    e = [{"name": "alpha"}]
    wiz.kill_verify({}, e, "stop")
    wiz.kill_verify({}, e, "destroy")
    assert seen == [False, True]  # running set for stop; ps -a for destroy


def test_project_containers_uses_the_label_and_never_the_compose_file(wiz, monkeypatch):
    """R1: the compose file lives in derived host state that dies with its host,
    while the inventory outlives it — so a compose-file path refuses exactly the
    forgotten environments this feature exists to reach."""
    captured = {}

    def fake_query(argv, **kw):
        captured["argv"] = argv
        return type("R", (), {"returncode": 0, "stdout": "agent-container-alpha\n"})()

    monkeypatch.setattr(wiz, "query", fake_query)
    monkeypatch.setattr(
        wiz, "compose_file_path", lambda *a, **k: pytest.fail("reached for the compose file")
    )
    got = wiz.project_containers(
        {"driver": "docker", "context": ""}, "agent-container-alpha", False
    )
    assert got == {"agent-container-alpha"}
    assert "label=com.docker.compose.project=agent-container-alpha" in captured["argv"]


# --- the write-back, and the lie it must not tell ----------------------------


def test_a_verified_destroy_marks_removed(wiz):
    e = wiz.build_inventory_entry("alpha", "local", False)
    wiz.write_inventory_entry(e)
    wiz.kill_note(e, "destroy", "stopped")
    assert wiz.read_inventory_entries()[0]["outcome"] == "removed"


@pytest.mark.parametrize("outcome", ["undetermined", "failed"])
def test_an_UNVERIFIED_destroy_writes_no_outcome(wiz, outcome):
    """I2. Recording a removal that may not have happened puts a lie in the one
    store a later audit AND a later run both read — the same lie Feature 014 refuses
    when it makes `unknown` unstorable, smuggled in under an accepted value.

    The happy path passes without this test; the bug only shows in a store nobody
    reads until it matters.
    """
    e = wiz.build_inventory_entry("alpha", "local", False)
    wiz.write_inventory_entry(e)
    wiz.kill_note(e, "destroy", outcome)
    stored = wiz.read_inventory_entries()[0]
    assert stored["outcome"] == "active"
    assert any(outcome in n for n in stored["notes"])  # recorded, just not as removal


def test_a_stop_records_without_changing_the_outcome(wiz):
    """014's outcome set describes EXISTENCE, not runstate: a stopped environment is
    still `active`."""
    e = wiz.build_inventory_entry("alpha", "local", False)
    wiz.write_inventory_entry(e)
    wiz.kill_note(e, "stop", "stopped")
    stored = wiz.read_inventory_entries()[0]
    assert stored["outcome"] == "active"
    assert "panic/stop -> stopped" in stored["notes"][0]


def test_notes_are_capped_so_an_entry_cannot_grow_forever(wiz):
    """U1: Feature 014 caps the store by ENTRY COUNT only — nothing bounds an entry's
    size, and this feature writes on every run to a file re-read by every listing."""
    e = wiz.build_inventory_entry("alpha", "local", False)
    wiz.write_inventory_entry(e)
    for i in range(8):
        wiz.kill_note(e, "stop", f"stopped{i}")
    notes = wiz.read_inventory_entries()[0]["notes"]
    assert len(notes) == wiz.KILL_NOTES_KEPT == 5
    assert "stopped7" in notes[-1]  # newest kept
    assert not any("stopped0" in n for n in notes)  # oldest dropped


# --- preview looks, but never touches ----------------------------------------


def test_preview_acts_on_nothing(seeded, monkeypatch, capsys):
    _reachable(seeded, monkeypatch, {"agent-container-alpha": {"agent-container-alpha"}})
    monkeypatch.setattr(
        seeded, "run_child", lambda *a, **k: pytest.fail("a preview acted on something")
    )
    seeded.do_panic(None, None, False, False, True, 5.0, True)
    out = json.loads(capsys.readouterr().out)["data"]
    assert out["preview"] is True
    assert {r["outcome"] for r in out["results"]} <= {"would-act", "already-stopped"}


def test_preview_exits_zero_even_when_a_host_is_unreachable(seeded, monkeypatch, capsys):
    """T031a: a preview is a QUERY. An unreachable host during a preview is
    information, not an error — unlike the action, which must fail."""
    _unreachable(seeded, monkeypatch)
    seeded.do_panic(None, None, False, False, True, 5.0, True)  # must not raise
    out = json.loads(capsys.readouterr().out)["data"]
    assert out["ok"] is True
    assert all(r["outcome"] == "undetermined" for r in out["results"])


# --- scope -------------------------------------------------------------------


def test_a_scope_reports_what_it_excluded(seeded, monkeypatch, capsys):
    _reachable(seeded, monkeypatch, {})
    seeded.do_panic(None, ["alpha"], False, False, True, 5.0, True)
    assert json.loads(capsys.readouterr().out)["data"]["excluded"] == 1


def test_a_scope_matching_nothing_says_so(seeded, capsys):
    seeded.do_panic(["nosuchhost"], None, False, False, False, 5.0, False)
    assert "matched none" in capsys.readouterr().err


def test_the_store_message_wins_over_the_scope_message(wiz, capsys):
    """A2: when both are true, 'nothing recorded' is the more surprising condition
    and the one an operator most needs to hear."""
    wiz.do_panic(["nosuchhost"], None, False, False, False, 5.0, False)
    err = capsys.readouterr().err
    assert "nothing was RECORDED" in err
    assert "matched none" not in err


# --- destroy confirms; stop does not -----------------------------------------


def test_destroy_without_confirmation_on_a_non_tty_refuses(seeded, monkeypatch):
    monkeypatch.setattr(seeded, "is_tty", lambda: False)
    monkeypatch.setattr(
        seeded, "run_child", lambda *a, **k: pytest.fail("destroyed without confirmation")
    )
    with pytest.raises(seeded.Fatal, match="refusing to destroy"):
        seeded.do_panic(None, None, True, False, False, 5.0, False)


def test_stop_never_prompts(seeded, monkeypatch):
    """FR-007: stopping is recoverable, and a prompt is friction on the action whose
    entire value is speed."""
    _reachable(seeded, monkeypatch, {})
    monkeypatch.setattr(
        seeded.questionary, "confirm", lambda *a, **k: pytest.fail("stop asked for confirmation")
    )
    seeded.do_panic(None, None, False, False, False, 5.0, False)


def test_json_mode_emits_exactly_ONE_envelope_even_when_the_run_fails(seeded, monkeypatch, capsys):
    """Feature 009 promises one envelope per invocation. The first implementation
    emitted the results and THEN let `die` emit an error envelope — two JSON
    documents on stdout, unparseable by the agents `--json` exists for.

    Caught by an acceptance test; pinned here so it cannot regress cheaply.
    """
    _unreachable(seeded, monkeypatch)
    with pytest.raises(seeded.typer.Exit):
        seeded.do_panic(None, None, False, False, False, 5.0, True)
    out = capsys.readouterr().out
    parsed = json.loads(out)  # raises if a second document follows
    assert parsed["ok"] is True  # the ENVELOPE parsed fine...
    assert parsed["data"]["ok"] is False  # ...and the payload carries the verdict
    assert parsed["data"]["unresolved"] == 2
    assert all(r["outcome"] == "undetermined" for r in parsed["data"]["results"])
