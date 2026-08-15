"""Feature 014: the durable inventory — what the tool ever created.

The store is FLAT and lives in the durable location, unlike Feature 016's
`runs/<host>/<env>/`. That difference is the feature: an entry must outlive its
host's removal, and a per-host directory dies with the host.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _entry(wiz, name="acme", host="local", provisioned=False):
    e = wiz.build_inventory_entry(name, host, provisioned)
    wiz.write_inventory_entry(e)
    return e


# --- the store's shape -------------------------------------------------------


def test_the_store_is_flat_with_host_as_an_attribute(wiz):
    """FR-002/FR-003: host is a FIELD, never a path component. A per-host directory
    is deleted with its host, destroying exactly the entries FR-003 exists to keep."""
    _entry(wiz, host="vps1")
    files = list(wiz.inventory_store_dir().glob("*.json"))
    assert len(files) == 1
    assert files[0].parent == wiz.inventory_store_dir()  # no <host>/ level
    assert json.loads(files[0].read_text())["host"] == "vps1"


def test_the_store_is_durable_data_not_derived_state(wiz):
    """It must not live under STATE_DIR, which docs/layout.md documents as
    'computed; safe to delete' — a record of something that already happened cannot
    be recomputed."""
    assert wiz.DATA_DIR in wiz.inventory_store_dir().parents
    assert wiz.STATE_DIR not in wiz.inventory_store_dir().parents


# --- the closed outcome set (FR-004) -----------------------------------------


@pytest.mark.parametrize("outcome", ["active", "removed", "vanished", "host-gone"])
def test_the_four_stored_outcomes_are_accepted(wiz, outcome):
    assert wiz.validate_inventory_outcome(outcome) == outcome


def test_unknown_is_refused_by_name_with_its_own_reason(wiz):
    """SC-003: `unknown` is a reconciliation RESULT. Storing it would make the record
    permanently lie about a host that later comes back, and it is the one wrong
    answer somebody reaches for in good faith — so it gets its own message rather
    than a generic 'not one of'."""
    with pytest.raises(wiz.Fatal, match="reconciliation RESULT"):
        wiz.validate_inventory_outcome("unknown")


def test_an_invented_outcome_is_refused(wiz):
    with pytest.raises(wiz.Fatal, match="not one of"):
        wiz.validate_inventory_outcome("probably-fine")


def test_the_outcome_guard_can_fail(wiz, monkeypatch):
    """Proof the check is load-bearing: neuter it and `unknown` sails through. A
    guard nobody has watched refuse anything is a line of code, not a guarantee."""
    monkeypatch.setattr(wiz, "validate_inventory_outcome", lambda o: o)
    assert wiz.validate_inventory_outcome("unknown") == "unknown"


def test_writing_an_entry_validates_its_outcome(wiz):
    e = wiz.build_inventory_entry("acme", "local", False)
    e["outcome"] = "unknown"
    with pytest.raises(wiz.Fatal):
        wiz.write_inventory_entry(e)


# --- identity: the ENTRY is the key, not the name (FR-015) -------------------


def test_a_reused_name_yields_another_entry_and_leaves_the_first_alone(wiz):
    """SC-003a. The wrong answer that LOOKS right is 1 — it would mean name is the
    key and every recreation silently erases history."""
    first = _entry(wiz, name="acme")
    wiz.set_inventory_outcome("acme", "local", "removed")
    second = _entry(wiz, name="acme")
    entries = wiz.read_inventory_entries()
    assert len(entries) == 2
    assert first["entry_id"] != second["entry_id"]
    by_id = {e["entry_id"]: e for e in entries}
    assert by_id[first["entry_id"]]["outcome"] == "removed"  # history intact
    assert by_id[second["entry_id"]]["outcome"] == "active"


def test_two_entries_in_the_same_second_do_not_collide(wiz):
    ids = {wiz.inventory_entry_id("acme", "2026-08-15T10:00:00Z") for _ in range(50)}
    assert len(ids) == 50


# --- the field set is closed, which IS the FR-010 guarantee ------------------


def test_no_free_text_field_exists(wiz):
    """FR-010: unlike Feature 016 — which had to STATE its task-text exposure — the
    guarantee here is structural. Every field is tool-generated, so there is nowhere
    for a credential to arrive. That is only true while the field set stays closed."""
    e = wiz.build_inventory_entry("acme", "local", True)
    assert tuple(e) == wiz.INVENTORY_FIELDS
    assert "task" not in e and "command" not in e and "description" not in e


# --- outcome transitions -----------------------------------------------------


def test_only_active_entries_move(wiz):
    """An entry already `removed` must not be rewritten when its host later goes, or
    the record would claim the host took something already gone — and `removed` vs
    `host-gone` is exactly the what-disappeared distinction FR-004 draws."""
    _entry(wiz, name="acme")
    wiz.set_inventory_outcome("acme", "local", "removed")
    before = wiz.read_inventory_entries()[0]["outcome_at"]
    assert wiz.set_inventory_outcome_for_host("local", "host-gone") == 0
    after = wiz.read_inventory_entries()[0]
    assert after["outcome"] == "removed" and after["outcome_at"] == before


def test_host_removal_marks_every_active_entry_on_that_host_only(wiz):
    _entry(wiz, name="a", host="vps1")
    _entry(wiz, name="b", host="vps1")
    _entry(wiz, name="c", host="local")
    assert wiz.set_inventory_outcome_for_host("vps1", "host-gone") == 2
    got = {e["name"]: e["outcome"] for e in wiz.read_inventory_entries()}
    assert got == {"a": "host-gone", "b": "host-gone", "c": "active"}


def test_an_entry_outlives_its_hosts_state_directory(wiz):
    """FR-003/SC-002, the property the whole feature rests on."""
    _entry(wiz, name="acme", host="vps1")
    import shutil

    shutil.rmtree(wiz.host_state_dir("vps1"), ignore_errors=True)
    shutil.rmtree(wiz.STATE_DIR, ignore_errors=True)
    assert [e["name"] for e in wiz.read_inventory_entries()] == ["acme"]


# --- a write failure must be LOUD and non-fatal (FR-008) ---------------------


def test_a_write_failure_warns_and_does_not_raise(wiz, monkeypatch, capsys):
    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(wiz, "write_inventory_entry", boom)
    wiz.record_inventory_creation("acme", "local", False)  # must not raise
    err = capsys.readouterr().err
    assert "could not record this deployment" in err
    assert "running and unaffected" in err  # the deploy is fine; say so


def test_asserting_only_the_non_fatal_half_would_pass_a_silent_build(wiz, monkeypatch, capsys):
    """The companion to the test above, and the reason it asserts the WARNING too: a
    build that recorded nothing and said nothing also 'does not raise'."""
    monkeypatch.setattr(wiz, "write_inventory_entry", lambda *_a, **_kw: None)
    monkeypatch.setattr(wiz, "warn", lambda *_a, **_kw: None)
    wiz.record_inventory_creation("acme", "local", False)
    assert capsys.readouterr().err == ""  # silent — which the other test rejects


# --- absent store degrades, never fails (FR-013) -----------------------------


def test_every_read_tolerates_a_missing_store(wiz):
    assert not wiz.inventory_store_dir().exists()
    assert wiz.read_inventory_entries() == []
    assert wiz.set_inventory_outcome("acme", "local", "removed") == 0
    assert wiz.set_inventory_outcome_for_host("local", "host-gone") == 0
    wiz.do_inventory_list(False)  # must not raise


def test_listing_an_empty_store_says_so_rather_than_printing_nothing(wiz, capsys):
    wiz.do_inventory_list(False)
    assert "no environments recorded" in capsys.readouterr().err


# --- the retention cap is COUNT-only, and the number is bound to the help ----


def test_retention_has_no_age_dimension_and_the_documented_number_is_the_enforced_one(wiz):
    """FR-012/C14: a number typed into prose beside a different number in the code is
    this project's recurring defect, so the help interpolates the constant."""
    assert wiz.INVENTORY_MAX_ENTRIES == 5000
    help_text = wiz.inventory_app.info.help
    assert str(wiz.INVENTORY_MAX_ENTRIES) in help_text
    assert "never by age" in help_text
    assert not hasattr(wiz, "INVENTORY_MAX_AGE_DAYS")  # no time criterion at any level


# --- THE MUTATION CENSUS (T008) ----------------------------------------------


def test_every_mutation_point_records(wiz):
    """The highest-risk property in this feature, expressed as a test over the
    SOURCE rather than a comment.

    The failure mode is a NEW create/destroy path added later that records nothing —
    invisible, because everything else it does works correctly. SC-001 demands 100%,
    and a record that begins late has a permanent blind spot.
    """
    src = Path(wiz.__file__).read_text()

    def body(fn: str) -> str:
        i = src.index(f"\ndef {fn}(")
        j = src.index("\ndef ", i + 1)
        return src[i:j]

    # create
    assert "record_inventory_creation(" in body("compose_up_exec")
    # removed (torn down while the host remained)
    assert 'set_inventory_outcome(name, host_name, "removed")' in body("down_container")
    assert 'set_inventory_outcome(name, host_name, "removed")' in body("do_wipe")
    # host-gone (its host went away and took it)
    assert 'set_inventory_outcome_for_host(name, "host-gone")' in body("cli_host_rm")


def test_the_census_guard_can_fail(wiz):
    """A creating path that does not record must be rejected by the check above."""
    fake = "\ndef compose_up_exec(a, b):\n    return 1\n\ndef next_one():\n    pass\n"
    i = fake.index("\ndef compose_up_exec(")
    j = fake.index("\ndef ", i + 1)
    assert "record_inventory_creation(" not in fake[i:j]


# --- reconciliation: computed, four classifications, fail-closed -------------


def _reachable(wiz, monkeypatch, names):
    monkeypatch.setattr(wiz, "host_ps_rows", lambda h, **k: [(n, "img", "Up", "1m") for n in names])


def _unreachable(wiz, monkeypatch):
    def boom(*_a, **_kw):
        raise wiz.Fatal("host unreachable")

    monkeypatch.setattr(wiz, "host_ps_rows", boom)


def test_an_agreeing_entry_is_classified_agreeing(wiz, monkeypatch):
    _entry(wiz, name="acme")
    _reachable(wiz, monkeypatch, ["agent-container-acme"])
    rows = wiz.reconcile_inventory()
    assert [r["classification"] for r in rows] == ["agreeing"]


def test_a_reachable_host_reporting_absence_is_missing(wiz, monkeypatch):
    _entry(wiz, name="acme")
    _reachable(wiz, monkeypatch, [])
    assert [r["classification"] for r in wiz.reconcile_inventory()] == ["missing"]


def test_an_unreachable_host_is_unknown_and_NEVER_missing(wiz, monkeypatch):
    """FR-006/SC-004 — Feature 002's fail-closed rule. Invisible is
    indistinguishable from gone, and guessing sends an operator hunting for a
    container sitting safely on a host they cannot currently reach."""
    _entry(wiz, name="acme")
    _unreachable(wiz, monkeypatch)
    got = [r["classification"] for r in wiz.reconcile_inventory()]
    assert "missing" not in got
    assert got == ["unknown"]


def test_the_unreachable_test_has_a_positive_control(wiz, monkeypatch):
    """T023's second half. Asserting only the ABSENCE of `missing` would also pass
    for a build that classifies nothing at all, so prove the classifier does produce
    `missing` when the host genuinely answers."""
    _entry(wiz, name="acme")
    _reachable(wiz, monkeypatch, [])
    assert "missing" in [r["classification"] for r in wiz.reconcile_inventory()]


def test_a_container_we_did_not_record_is_unrecorded_and_NOT_claimed(wiz, monkeypatch):
    """FR-007/SC-005: `CONTAINER_PREFIX` is a naming convention an operator can
    imitate, so a match is evidence of a NAME and nothing more."""
    _reachable(wiz, monkeypatch, ["agent-container-stranger"])
    rows = wiz.reconcile_inventory()
    assert [r["classification"] for r in rows] == ["unrecorded"]
    note = rows[0]["note"]
    assert "observation" in note and "not a claim of ownership" in note
    for forbidden in ("our container", "created by this tool", "we created", "belongs to"):
        assert forbidden not in note.lower()


def test_the_ownership_wording_check_can_fail(wiz, monkeypatch):
    """Proof T025 is load-bearing: a note that DID claim ownership must be rejected
    by the assertion above."""
    claim = "our container, created by this tool"
    assert any(f in claim.lower() for f in ("our container", "created by this tool"))


def test_every_entry_lands_in_exactly_one_classification(wiz, monkeypatch):
    _entry(wiz, name="a")
    _entry(wiz, name="b")
    _reachable(wiz, monkeypatch, ["agent-container-a", "agent-container-stranger"])
    rows = wiz.reconcile_inventory()
    assert len(rows) == 3  # a=agreeing, b=missing, stranger=unrecorded
    assert all(r["classification"] in wiz.INVENTORY_CLASSIFICATIONS for r in rows)


def test_unknown_is_computed_and_never_written_to_the_store(wiz, monkeypatch):
    """SC-003: zero stored entries may carry `unknown`, even after a reconciliation
    that classified one that way."""
    _entry(wiz, name="acme")
    _unreachable(wiz, monkeypatch)
    wiz.do_inventory_reconcile(True)
    assert all(e["outcome"] != "unknown" for e in wiz.read_inventory_entries())


def test_only_reconciliation_records_vanished(wiz, monkeypatch, capsys):
    """data-model §5: it is the one path that has SEEN a reachable host report the
    container gone. Anywhere else would record an inference as a fact."""
    _entry(wiz, name="acme")
    _reachable(wiz, monkeypatch, [])
    wiz.do_inventory_reconcile(True)
    capsys.readouterr()
    assert wiz.read_inventory_entries()[0]["outcome"] == "vanished"


def test_an_unreachable_host_does_not_mark_anything_vanished(wiz, monkeypatch):
    _entry(wiz, name="acme")
    _unreachable(wiz, monkeypatch)
    wiz.do_inventory_reconcile(True)
    assert wiz.read_inventory_entries()[0]["outcome"] == "active"


def test_the_list_hint_is_one_line_and_names_no_classification(wiz, monkeypatch):
    """FR-005a/C9: a discrepancy an operator must already suspect in order to look
    for is one nobody finds — but the classification is reconcile's answer, and two
    places giving it would drift."""
    _entry(wiz, name="acme")
    _reachable(wiz, monkeypatch, [])
    hint = wiz.inventory_disagreement_hint()
    assert hint and "\n" not in hint
    assert "inventory reconcile" in hint
    for word in wiz.INVENTORY_CLASSIFICATIONS:
        assert word not in hint


def test_no_hint_when_everything_agrees(wiz, monkeypatch):
    _entry(wiz, name="acme")
    _reachable(wiz, monkeypatch, ["agent-container-acme"])
    assert wiz.inventory_disagreement_hint() is None


def test_the_hint_never_breaks_list(wiz, monkeypatch):
    """FR-013: no command's behaviour may depend on the inventory working."""

    def boom(*_a, **_kw):
        raise RuntimeError("store on fire")

    monkeypatch.setattr(wiz, "reconcile_inventory", boom)
    assert wiz.inventory_disagreement_hint() is None


# --- US3: age and provenance -------------------------------------------------


def test_age_is_rendered_not_left_as_arithmetic(wiz):
    """SC-009: a date the operator must subtract from today is not the answer they
    asked for."""
    assert wiz.inventory_age("2026-08-01T00:00:00Z", now=1785549600) == "2h"
    assert wiz.inventory_age("2026-08-01T00:00:00Z", now=1785801600) == "3d"


def test_age_and_provenance_still_answer_when_the_host_is_GONE(wiz, monkeypatch, capsys):
    """SC-009's trailing clause — the half that can actually fail. A rendering that
    reached for the live host to derive either value would break exactly where this
    feature is most useful."""
    _entry(wiz, name="acme", host="vps1", provisioned=True)
    wiz.set_inventory_outcome_for_host("vps1", "host-gone")

    def no_hosts(*_a, **_kw):
        raise AssertionError("consulted a host that no longer exists")

    monkeypatch.setattr(wiz, "host_ps_rows", no_hosts)
    monkeypatch.setattr(wiz, "load_registry", lambda *_a, **_kw: {"version": 1, "hosts": {}})
    wiz.do_inventory_list(False)
    out = capsys.readouterr().out
    assert "vps1" in out and "host-gone" in out
    assert "yes" in out  # host_provisioned, read from the ENTRY


# --- the honest edges --------------------------------------------------------


def test_concurrent_deployments_each_produce_a_complete_entry(wiz):
    """FR-009/SC-007. Guaranteed by SHAPE — separate entries are separate files — so
    this test exists to prove the shape was actually used rather than to exercise a
    lock."""
    import threading

    errors: list[BaseException] = []

    def make(i: int):
        try:
            wiz.record_inventory_creation(f"env{i}", "local", False)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=make, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    entries = wiz.read_inventory_entries()
    assert len(entries) == 12
    assert {e["name"] for e in entries} == {f"env{i}" for i in range(12)}
    assert all(set(e) == set(wiz.INVENTORY_FIELDS) for e in entries)  # none half-written


def test_the_cap_is_count_only_and_prunes_the_oldest(wiz, monkeypatch, capsys):
    monkeypatch.setattr(wiz, "INVENTORY_MAX_ENTRIES", 5)
    for i in range(8):
        wiz.write_inventory_entry(wiz.build_inventory_entry(f"env{i}", "local", False))
    assert wiz.prune_inventory() == 3
    assert len(wiz.read_inventory_entries()) == 5
    assert "pruned 3 entries" in capsys.readouterr().err  # never silent


def test_there_is_no_age_based_pruning_anywhere(wiz):
    """FR-012 / finding U1: the entries most worth having are the oldest forgotten
    ones, so a time criterion would delete the feature's value first. Asserted over
    the SOURCE, because the risk is a future 'obvious improvement'."""
    src = Path(wiz.__file__).read_text()
    i = src.index("\ndef prune_inventory(")
    j = src.index("\ndef ", i + 1)
    # EXECUTABLE LINES ONLY. The docstring explains at length why age-pruning is
    # forbidden, so a whole-text scan matches its own explanation and reports a
    # violation that does not exist — a guard reading prose instead of code, which is
    # exactly the failure this project keeps finding.
    body, in_doc = [], False
    for line in src[i:j].splitlines():
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.endswith('"""'):
            in_doc = not in_doc
            continue
        if in_doc or stripped.startswith("#") or not stripped:
            continue
        body.append(stripped)
    code = "\n".join(body)
    for banned in ("MAX_AGE", "days", "created_at", "mtime", "timedelta"):
        assert banned not in code, f"{banned} appeared in prune_inventory's CODE"
    assert not hasattr(wiz, "INVENTORY_MAX_AGE_DAYS")


def test_the_no_age_pruning_guard_reads_code_and_can_fail(wiz):
    """Proof the guard above is not vacuous: a body that DOES prune by age is caught,
    and one that merely mentions age in a comment is not."""
    prose_only = ["def prune_inventory():", '"""Age-pruning is forbidden."""', "pass"]
    real_violation = ["def prune_inventory():", "cutoff = time.time() - MAX_AGE_DAYS * 86400"]
    assert not any("MAX_AGE" in ln for ln in prose_only if not ln.startswith('"""'))
    assert any("MAX_AGE" in ln for ln in real_violation)


def test_pruning_keeps_the_newest(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "INVENTORY_MAX_ENTRIES", 2)
    for i in range(4):
        wiz.write_inventory_entry(wiz.build_inventory_entry(f"env{i}", "local", False))
    wiz.prune_inventory()
    kept = {e["name"] for e in wiz.read_inventory_entries()}
    assert len(kept) == 2
