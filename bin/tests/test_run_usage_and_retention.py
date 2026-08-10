"""Feature 016 US3 + the honest edges — usage, retention, and what must be visible.

Hermetic: no docker, no podman, no network, no clock dependence (every retention
test passes its own `now`).

  * **T033/T034** — `usage` in the shape of data-model §4, and the reason nothing is
    extracted per agent today: the tool invokes no agent in a form that reports.
  * **T035** — unknown renders as THE WORD and serialises as `reported: false`,
    never `0` (C9, SC-004). A genuinely reported `0` is a different fact and must
    survive as a number.
  * **T036** — an aggregate STATES its unknown components rather than excluding them
    (FR-007).
  * **T037** — usage is never normalised across agents (FR-015, C10): no cross-agent
    total exists, and two agents' identically-named units are never added.
  * **T038** — a record write that fails surfaces without failing the run (C11).
  * **T040/T041** — retention prunes by age and count at ingestion, and the
    DOCUMENTED default is the ENFORCED one.
  * **T057** — records lost to an out-of-band volume removal are VISIBLE.
  * **T058** — the record's field set is CLOSED, which is the whole of SC-005's
    100%-no-credentials claim.

Requirement anchors are named in the bodies. Several tests exist only to prove
another test can fail, because this project's recurring defect is a check that
passes while the thing it names is broken.
"""

from __future__ import annotations

import json
import re
import subprocess
import types
from pathlib import Path

import pytest

# Rich colourises the figures it prints, so a captured line carries escapes between
# a number and the word next to it. Stripped in the test rather than turned off in
# the product: the assertion is about what an operator reads, not about how the
# console was configured for a test run.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}
_ROOT = Path(__file__).resolve().parents[2]
_ENTRYPOINT = _ROOT / "image" / "entrypoint.sh"
_PLAN = _ROOT / "specs" / "016-run-observability" / "plan.md"
_DOC = _ROOT / "docs" / "observability.md"


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


def _reported(agent="claude", **units):
    return {"reported": True, "agent": agent, "units": units}


# --- T033: the usage block's shape (data-model §4) ---------------------------


def test_the_default_is_unreported_and_carries_no_figure(wiz):
    """FR-006/SC-004: `unknown` is a VALUE, not an absence and not a zero. Omitting
    the key would be indistinguishable from a schema change and a consumer would
    read the absence as zero (research R6)."""
    assert _record(wiz)["usage"] == {"reported": False}
    assert wiz.usage_unreported() == {"reported": False}


def test_reported_usage_keeps_the_agents_own_keys_and_names_the_agent(wiz):
    """C10/FR-015: `units` is the agent's vocabulary, untouched. Naming the agent
    beside it is what stops a consumer adding two agents' figures together."""
    usage = _reported("codex", cached_input_tokens=7, output_tokens=3)
    stored = _record(wiz, usage=usage)["usage"]
    assert stored == usage
    assert sorted(stored["units"]) == ["cached_input_tokens", "output_tokens"]


def _assert_misleading_usage_is_refused(wiz):
    """The guard under test, factored out so the proof-it-can-fail case can run the
    SAME assertions against a neutered validator."""
    for usage in (
        {"reported": False, "units": {"t": 1}},  # says both at once
        {"units": {"t": 1}},  # no `reported` at all
        {"reported": "yes"},  # truthy, but not the field's vocabulary
        _reported("gpt", t=1),  # an agent this tool does not run
        {"reported": True, "units": {"t": 1}},  # units belonging to nobody
        _reported("claude"),  # a report with nothing in it
        _reported("claude", t="lots"),  # a figure that is prose
        _reported("claude", t=True),  # a flag that would sum as 1
        _reported("claude", **{"ghp_secret-ish": 1}),  # a key that is not a name
    ):
        with pytest.raises(wiz.Fatal):
            _record(wiz, usage=usage)


def test_a_usage_that_would_misstate_what_the_agent_said_is_refused(wiz):
    """Each refusal is a record that would MISLEAD rather than one that is merely
    incomplete: a figure beside `reported: false` states both at once, an unnamed
    agent makes units uncomparable, and a string value opens a second free-text
    field in a record whose closure SC-005 rests on."""
    _assert_misleading_usage_is_refused(wiz)


def test_the_usage_guard_can_actually_fail(wiz, monkeypatch):
    """Proof-it-can-fail. Neuter the validator — exactly what "the shape is a
    convention" looks like — and every refusal above must stop happening. Without
    this the suite would keep passing for a build that accepted anything, and
    SC-004/SC-005 would be measured by a check that cannot notice."""
    monkeypatch.setattr(wiz, "validate_usage", lambda usage: None)
    with pytest.raises(pytest.fail.Exception):
        _assert_misleading_usage_is_refused(wiz)


@pytest.mark.parametrize(
    "usage,message",
    [
        ({"reported": False, "units": {"t": 1}}, "carries nothing but"),
        ({"reported": None}, "must be true or false"),
        (_reported("gpt", t=1), "must name one of"),
        (_reported("claude", t="lots"), "must be a number"),
        (_reported("claude", **{"9lives": 1}), "not an identifier"),
        ({"reported": True, "agent": "claude", "units": {"t": 1}, "cost": 2}, "unknown usage keys"),
    ],
)
def test_each_refusal_says_which_rule_it_broke(wiz, usage, message):
    """A refusal an operator cannot act on is a crash with extra steps."""
    with pytest.raises(wiz.Fatal, match=message):
        _record(wiz, usage=usage)


# --- T034: nothing is invented for agents that report nothing ----------------


def _entrypoint_text() -> str:
    return _ENTRYPOINT.read_text()


def test_the_container_writes_the_unreported_shape_and_never_a_figure(wiz):
    """The container is the writer for every real run, so this is where a false
    zero would actually appear (SC-004). It writes the literal unreported shape.

    Anchored to `usage_unreported()` and not to a copy of the JSON, so the two
    writers — this file and the entrypoint — cannot drift into a Python record that
    says `unknown` and a shell record that says something else.
    """
    assert json.dumps(wiz.usage_unreported()) == '{"reported": false}'
    assert '"usage": { "reported": false }' in _entrypoint_text()


@pytest.mark.parametrize(
    "invocation",
    [
        'cmd=(claude -p "${t}")',
        'cmd=(codex exec "${t}")',
        'cmd=(pi -p "${t}")',
        'cmd=(opencode run "${t}")',
    ],
)
def test_no_agent_is_invoked_in_a_form_that_reports_usage(invocation):
    """T034's "invent nothing" rests on a FACT about how the tool invokes agents,
    and a fact left unpinned is an assumption.

    `run_headless_agent` runs the prose forms. Nothing asks for a machine-readable
    report, so there is nothing to parse and every record honestly says unknown.
    The day one of these invocations changes, this test fails — and the extraction
    has to be written, rather than the tool quietly filing a figure the agent DID
    report as `reported: false`, which is the FR-006 half of SC-004.
    """
    assert invocation in _entrypoint_text()


# --- T035: unknown is the WORD, never a zero (C9, SC-004) --------------------


def test_unknown_usage_renders_as_a_word_with_no_digit_in_it(wiz):
    """ "never `0`" is the requirement, so the assertion is over the CHARACTERS: a
    rendering that said "0 tokens" would satisfy any test looking only for the word
    "unknown" beside it."""
    rendered = wiz.render_usage({"reported": False})
    assert "unknown" in rendered
    assert not any(c.isdigit() for c in rendered)


@pytest.mark.parametrize("usage", [None, {}, {"reported": False}, {"reported": "no"}, "junk"])
def test_every_shape_that_is_not_a_report_renders_as_unknown(wiz, usage):
    """The read side is defensive on purpose: a container-written record never
    passes `validate_usage`, so the renderer meets shapes the constructor refuses.
    Unknown is the only answer that cannot silently understate a total."""
    assert wiz.render_usage(usage).startswith("unknown")


def test_a_reported_zero_stays_a_zero_and_is_not_collapsed_into_unknown(wiz):
    """The other direction, and the one a `if not value` would break: an agent that
    reported zero tokens SAID something. Turning that into `unknown` would be the
    mirror of SC-004's false zero — a known figure filed as a gap."""
    usage = _reported("claude", input_tokens=0)
    assert wiz.render_usage(usage) == "claude: input_tokens=0"
    assert wiz.usage_units(usage, "claude") == {"input_tokens": 0}


def test_the_json_record_serialises_unknown_as_reported_false(wiz):
    """C9's machine-readable half. A consumer must be able to tell "nothing was
    reported" from "nothing was consumed" without reading prose."""
    assert json.loads(json.dumps(_record(wiz)))["usage"] == {"reported": False}


# --- T036: an aggregate STATES its unknown components (FR-007) ---------------


def _runs(*usages):
    return [{"agent": u.get("agent", "claude") if u else "claude", "usage": u} for u in usages]


def test_the_aggregate_counts_unknown_components_rather_than_dropping_them(wiz):
    """FR-007. A sum with three unreported runs quietly missing from it is
    indistinguishable from a sum of everything, and a total that is quietly wrong
    is worse than one that admits a gap."""
    agg = wiz.aggregate_usage(
        _runs(_reported("claude", t=10), {"reported": False}, {"reported": False})
    )
    assert agg["runs"] == 3
    assert agg["unknown_components"] == 2
    assert agg["by_agent"]["claude"] == {
        "runs": 3,
        "reported": 1,
        "unknown_components": 2,
        "units": {"t": 10},
    }


def test_the_unknown_count_is_present_even_when_it_is_zero(wiz):
    """A key that appeared only when non-empty would make "nothing was unknown" and
    "this build does not report unknowns" identical to a consumer — the same trap
    `unpushed` is always-present for (T030)."""
    agg = wiz.aggregate_usage(_runs(_reported("claude", t=1)))
    assert agg["unknown_components"] == 0
    assert agg["by_agent"]["claude"]["unknown_components"] == 0


def test_a_malformed_usage_is_an_unknown_component_and_never_a_partial_total(wiz):
    """All-or-nothing on purpose. A half-counted record produces a figure that
    looks complete; unknown is the answer that admits what it does not know."""
    for broken in ({"reported": True, "agent": "claude"}, {"reported": True}, None, {"x": 1}):
        agg = wiz.aggregate_usage(_runs(broken))
        assert agg["unknown_components"] == 1, broken
        assert agg["by_agent"]["claude"]["units"] == {}, broken


def _assert_the_summary_states_the_gap(wiz):
    """The guard under test, factored out for the proof-it-can-fail case below."""
    lines = wiz.render_usage_totals(
        wiz.aggregate_usage(_runs(_reported("claude", t=10), {"reported": False}))
    )
    assert "1 with no usage reported" in lines[0]
    assert "never counted as zero" in lines[0]


def test_the_human_summary_leads_with_the_gap_before_the_figures(wiz):
    """FR-007 is about what a reader takes away, and a summary is read in the order
    it is printed: the gap has to arrive before the numbers it qualifies."""
    _assert_the_summary_states_the_gap(wiz)
    lines = wiz.render_usage_totals(
        wiz.aggregate_usage(_runs(_reported("claude", t=10), {"reported": False}))
    )
    assert lines[1].strip().startswith("claude:")


def test_the_gap_report_can_actually_fail(wiz, monkeypatch):
    """Proof-it-can-fail: an aggregate that silently EXCLUDES its unknown
    components — precisely what FR-007 forbids — must break the assertion above."""
    real = wiz.aggregate_usage
    monkeypatch.setattr(
        wiz,
        "aggregate_usage",
        lambda recs: real([r for r in recs if r["usage"] != {"reported": False}]),
    )
    with pytest.raises(AssertionError):
        _assert_the_summary_states_the_gap(wiz)


def test_a_listing_with_nothing_reported_still_says_so(wiz):
    """The common case today, and the one an operator must not read as "no cost"."""
    lines = wiz.render_usage_totals(wiz.aggregate_usage(_runs({"reported": False}, None)))
    assert lines == [
        "usage: unknown for all 2 run(s) — no agent reported any (never counted as zero)"
    ]


# --- T037: usage is NEVER normalised across agents (FR-015, C10) -------------


def _assert_no_cross_agent_total(agg):
    """The guard under test. Named keys rather than "no key called total", because
    the failure is any single figure spanning agents, whatever it is called."""
    assert set(agg) == {"runs", "unknown_components", "by_agent"}
    assert not isinstance(agg.get("units"), dict)


def test_the_aggregate_offers_no_cross_agent_total(wiz):
    """C10. Two agents' `input_tokens` are not the same quantity; a combined figure
    would be the one number a reader quotes, and it would mean nothing."""
    _assert_no_cross_agent_total(
        wiz.aggregate_usage(
            _runs(_reported("claude", input_tokens=1), _reported("codex", input_tokens=2))
        )
    )


def test_the_no_total_assertion_can_actually_fail(wiz, monkeypatch):
    """Proof-it-can-fail: add the convenience total FR-015 forbids and the check
    above must notice. Without this it would pass for any dict shape at all."""
    real = wiz.aggregate_usage

    def with_total(records):
        agg = real(records)
        agg["units"] = {"input_tokens": 3}
        return agg

    monkeypatch.setattr(wiz, "aggregate_usage", with_total)
    with pytest.raises(AssertionError):
        _assert_no_cross_agent_total(
            wiz.aggregate_usage(_runs(_reported("claude", input_tokens=1)))
        )


def test_two_agents_identical_unit_names_are_never_added_together(wiz):
    """The concrete equivalence C10 forbids: the same key name from two agents is
    two different quantities that happen to share a spelling."""
    agg = wiz.aggregate_usage(
        _runs(_reported("claude", input_tokens=10), _reported("codex", input_tokens=5))
    )
    assert agg["by_agent"]["claude"]["units"] == {"input_tokens": 10}
    assert agg["by_agent"]["codex"]["units"] == {"input_tokens": 5}


def test_usage_naming_a_different_agent_from_the_one_that_ran_is_unknown(wiz):
    """Two names for one run means nobody can say whose units these are, and
    putting them in either bucket would invent the equivalence C10 forbids."""
    agg = wiz.aggregate_usage([{"agent": "claude", "usage": _reported("codex", t=9)}])
    assert agg["unknown_components"] == 1
    assert agg["by_agent"]["claude"]["units"] == {}


def test_the_summary_warns_a_reader_looking_at_two_agents(wiz):
    """The reader with two rows in front of them is exactly the reader about to add
    them, so the line that says not to appears precisely then."""
    two = wiz.render_usage_totals(
        wiz.aggregate_usage(_runs(_reported("claude", t=1), _reported("codex", t=1)))
    )
    assert any("not comparable" in line for line in two)
    one = wiz.render_usage_totals(wiz.aggregate_usage(_runs(_reported("claude", t=1))))
    assert not any("not comparable" in line for line in one)


# --- T035/T036 wiring: the listing actually carries all of this --------------


@pytest.fixture
def store(wiz, monkeypatch):
    """A durable store the read commands work against, with no drain: these are
    being tested as READERS of records that already exist."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])

    def _add(run_id: str, *, environment: str = "acme", **over):
        rec = _record(wiz, run_id=run_id, environment=environment, exit_code=0, **over)
        rec["host"] = "local"
        wiz.atomic_write_json(wiz.runs_store_dir("local", environment), f"{run_id}.json", rec)
        return rec

    return _add


def test_the_json_listing_always_carries_the_usage_aggregate(store, wiz, capsys):
    """An agent reading `runs list --json` must not have to re-derive the totals —
    an agent that can forget to is an agent that reports a run's cost as nothing."""
    store("r-1", usage=_reported("claude", input_tokens=4))
    store("r-2")
    wiz.set_json_mode(True)
    wiz.do_runs_list("acme", None, True)
    usage = json.loads(capsys.readouterr().out)["data"]["usage"]
    assert usage["unknown_components"] == 1
    assert usage["by_agent"]["claude"]["units"] == {"input_tokens": 4}


def test_the_key_is_there_even_for_an_empty_listing(wiz, monkeypatch, capsys):
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])
    wiz.set_json_mode(True)
    wiz.do_runs_list("acme", None, True)
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["usage"] == {"runs": 0, "unknown_components": 0, "by_agent": {}}


def test_the_human_listing_prints_the_gap_under_the_table(store, wiz, capsys):
    store("r-1", usage=_reported("claude", input_tokens=4))
    store("r-2")
    wiz.set_json_mode(False)
    wiz.do_runs_list("acme", None, False)
    out = _plain(capsys.readouterr().out)
    assert "1 with no usage reported" in out
    assert "input_tokens=4" in out


def test_human_show_renders_unknown_usage_as_the_word(store, wiz, capsys):
    """C2's explicit clause: `runs show` MUST render unknown usage as the word."""
    store("r-2")
    wiz.set_json_mode(False)
    wiz.do_runs_show("r-2", None, False)
    assert "unknown" in _plain(capsys.readouterr().out)


# --- T040: retention prunes by age AND by count (FR-011, C14) ----------------


def _write_record(wiz, directory: Path, run_id: str, started: str) -> Path:
    return wiz.atomic_write_json(
        directory,
        f"{run_id}.json",
        _record(wiz, run_id=run_id, started_at=started, ended_at=started, exit_code=0),
    )


def _at(day: int) -> str:
    """An RFC 3339 stamp on 2026-01-<day>, so an age can be computed exactly."""
    return f"2026-01-{day:02d}T00:00:00Z"


def _now(day: int) -> float:
    import calendar
    import time as _time

    return float(calendar.timegm(_time.strptime(_at(day), "%Y-%m-%dT%H:%M:%SZ")))


def test_a_record_past_the_age_bound_is_pruned_and_one_inside_it_is_kept(wiz, tmp_path):
    """The boundary is read from the constant, so the test cannot drift away from
    the rule it is checking (T041's other half)."""
    d = tmp_path / "store"
    _write_record(wiz, d, "old", _at(1))
    _write_record(wiz, d, "new", _at(1))
    just_inside = _now(1) + (wiz.RETENTION_MAX_AGE_DAYS * 86400) - 60
    assert wiz.prune_run_store(d, now=just_inside) == []
    just_past = _now(1) + (wiz.RETENTION_MAX_AGE_DAYS * 86400) + 60
    assert sorted(wiz.prune_run_store(d, now=just_past)) == ["new.json", "old.json"]
    assert list(d.iterdir()) == []


def test_the_count_bound_keeps_the_newest_and_deletes_the_rest(wiz, tmp_path):
    d = tmp_path / "store"
    d.mkdir(parents=True)
    total = wiz.RETENTION_MAX_RECORDS + 3
    for i in range(total):
        # Written directly rather than through the atomic helper: this test is about
        # the bound, and 503 fsyncs would make it slow enough to be skipped.
        (d / f"r{i:04d}.json").write_text(
            json.dumps({"started_at": f"2026-01-01T00:00:{i % 60:02d}Z"})
        )
    removed = wiz.prune_run_store(d, now=_now(1) + 3600)
    assert len(removed) == 3
    assert len(list(d.iterdir())) == wiz.RETENTION_MAX_RECORDS


def test_the_two_bounds_are_independent_whichever_prunes_first(wiz, tmp_path):
    """Neither bound subsumes the other: an environment that runs every ten minutes
    blows the count long before anything is 90 days old, and one that ran twice a
    year ago keeps two records forever under the count rule alone."""
    d = tmp_path / "store"
    _write_record(wiz, d, "ancient", _at(1))
    _write_record(wiz, d, "recent", _at(20))
    removed = wiz.prune_run_store(d, now=_now(20) + (wiz.RETENTION_MAX_AGE_DAYS * 86400) - 3600)
    assert removed == ["ancient.json"]
    assert [p.name for p in d.iterdir()] == ["recent.json"]


def test_age_comes_from_the_RUN_and_not_from_the_files_mtime(wiz, tmp_path):
    """mtime is when the record was INGESTED — for a detached run, whenever the
    operator next ran a command; for a re-ingested one, today. An age rule built on
    it would keep a year-old run alive because the tool touched its file this
    morning, which is the opposite of what FR-011 asks for."""
    import os

    d = tmp_path / "store"
    p = _write_record(wiz, d, "ancient", _at(1))
    os.utime(p, (_now(20), _now(20)))  # freshly ingested, long-finished run
    assert wiz.prune_run_store(d, now=_now(1) + (wiz.RETENTION_MAX_AGE_DAYS * 86400) + 60) == [
        "ancient.json"
    ]


def test_an_unreadable_timestamp_errs_toward_KEEPING_the_record(wiz, tmp_path):
    """Pruning is the one operation here that cannot be undone, so ambiguity must
    resolve toward keeping. The mtime fallback is always LATER than the run it
    describes, which is what makes the fallback conservative rather than arbitrary."""
    import os

    d = tmp_path / "store"
    d.mkdir(parents=True)
    (d / "broken.json").write_text("{not json")
    os.utime(d / "broken.json", (_now(20), _now(20)))
    assert wiz.prune_run_store(d, now=_now(20) + 3600) == []
    assert (d / "broken.json").exists()


def test_pruning_an_empty_or_missing_store_does_nothing(wiz, tmp_path):
    assert wiz.prune_run_store(tmp_path / "never") == []


def test_a_file_that_cannot_be_deleted_warns_and_does_not_raise(wiz, tmp_path, monkeypatch):
    """Retention is bookkeeping done on the way to the operator's real command; a
    store it cannot prune must not become a reason `runs list` stops working."""
    d = tmp_path / "store"
    _write_record(wiz, d, "old", _at(1))
    warnings: list[str] = []
    monkeypatch.setattr(wiz, "warn", warnings.append)
    monkeypatch.setattr(
        wiz.Path, "unlink", lambda self, **kw: (_ for _ in ()).throw(OSError("nope"))
    )
    assert wiz.prune_run_store(d, now=_now(1) + (wiz.RETENTION_MAX_AGE_DAYS * 86400) + 60) == []
    assert any("could not prune" in m for m in warnings)


# --- T040: pruning happens AT INGESTION (C14), and is announced --------------


@pytest.fixture
def drain(wiz, monkeypatch):
    """A runtime whose runs volume exists and drains an empty tarball, so ingestion
    reaches its end without storing anything — which is where retention runs."""
    state = types.SimpleNamespace(
        logs=[], warnings=[], volumes={wiz.runs_volume_name("acme")}, reachable=True
    )

    def fake_query(argv, timeout=None):
        # `volume ls` and `volume inspect` are answered SEPARATELY on purpose: they
        # fail together on an unreachable host and differently on a reachable one,
        # which is the whole distinction T057's detector turns on.
        if "volume" in argv and "ls" in argv:
            return subprocess.CompletedProcess(argv, 0 if state.reachable else 1, b"", b"")
        rc = 0 if ("volume" not in argv or argv[-1] in state.volumes) else 1
        return subprocess.CompletedProcess(argv, rc, b"", b"")

    def fake_run(argv, capture_output=False, timeout=None, **kw):
        import io
        import tarfile

        buf = io.BytesIO()
        tarfile.open(fileobj=buf, mode="w").close()
        return subprocess.CompletedProcess(argv, 0, buf.getvalue(), b"")

    monkeypatch.setattr(wiz, "query", fake_query)
    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    monkeypatch.setattr(wiz, "log", state.logs.append)
    monkeypatch.setattr(wiz, "warn", state.warnings.append)
    return state


def test_ingestion_prunes_the_store_it_just_wrote_to(wiz, drain):
    """C14 puts retention at ingestion rather than in a background process — a CLI
    that runs on demand has no home for one (research R8)."""
    d = wiz.runs_store_dir("local", "acme")
    _write_record(wiz, d, "ancient", _at(1))
    _write_record(wiz, d, "recent", wiz.utc_now())
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert [p.name for p in d.iterdir()] == ["recent.json"]


def test_a_prune_is_announced_rather_than_silent(wiz, drain):
    """The whole feature is that the account of a run outlives its container, so the
    tool deleting one is the last thing that may happen quietly — and the message
    names the rule, so an operator knows which bound took it."""
    _write_record(wiz, wiz.runs_store_dir("local", "acme"), "ancient", _at(1))
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    said = " ".join(drain.logs)
    assert "pruned 1 run record(s)" in said
    assert f"{wiz.RETENTION_MAX_AGE_DAYS} days" in said
    assert f"{wiz.RETENTION_MAX_RECORDS} records" in said


def test_retention_runs_even_when_the_volume_is_gone(wiz, drain):
    """An environment whose volume vanished still has a store, and a store that can
    only be pruned by a successful drain is a store that never prunes again."""
    drain.volumes.clear()
    _write_record(wiz, wiz.runs_store_dir("local", "acme"), "ancient", _at(1))
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert list(wiz.runs_store_dir("local", "acme").iterdir()) == []


# --- T041: the DOCUMENTED default is the ENFORCED one ------------------------


def _assert_the_documented_numbers_are_the_enforced_ones(wiz):
    """The guard under test. EVERY surface an operator can read is bound to the
    constants that do the deleting: the help text they get at the point of use, the
    prose doc that explains retention, and the plan that decided the numbers.

    `docs/observability.md` is in this list because it is where an operator goes to
    ask how long a record lives. A figure written only there is the recurring
    defect in its purest form — the code changes, the suite stays green, and the
    document keeps confidently stating a number that no longer deletes anything.
    """
    help_text = wiz.runs_app.info.help
    assert f"{wiz.RETENTION_MAX_AGE_DAYS} days" in help_text
    assert f"{wiz.RETENTION_MAX_RECORDS} records" in help_text
    assert (
        f"{wiz.RETENTION_MAX_AGE_DAYS} days, or {wiz.RETENTION_MAX_RECORDS} records per environment"
        in _DOC.read_text()
    )
    assert (
        f"{wiz.RETENTION_MAX_AGE_DAYS} days and {wiz.RETENTION_MAX_RECORDS} records"
        in _PLAN.read_text()
    )


def test_the_documented_default_is_the_enforced_one(wiz):
    """T041, and the reason it exists: a documented number the code does not use is
    this repository's recurring defect. The retention rule is only a rule while the
    figure that is written down is the figure that deletes."""
    _assert_the_documented_numbers_are_the_enforced_ones(wiz)


def test_a_default_that_drifted_from_its_documentation_is_caught(wiz, monkeypatch):
    """Proof-it-can-fail. Change the enforced number without touching the prose —
    exactly how the defect happens — and the check must break. `help` is composed at
    import time, so after this the code says 30 and both documents say 90."""
    monkeypatch.setattr(wiz, "RETENTION_MAX_AGE_DAYS", 30)
    with pytest.raises(AssertionError):
        _assert_the_documented_numbers_are_the_enforced_ones(wiz)


def test_the_enforced_bound_is_the_constant_and_not_a_second_copy(wiz, tmp_path, monkeypatch):
    """The other direction: the constant must be what `prune_run_store` actually
    reads. A rule that hard-coded 90 beside a constant saying 90 would satisfy the
    text-binding above and ignore any future change."""
    monkeypatch.setattr(wiz, "RETENTION_MAX_AGE_DAYS", 1)
    d = tmp_path / "store"
    _write_record(wiz, d, "two-days-old", _at(1))
    assert wiz.prune_run_store(d, now=_now(3)) == ["two-days-old.json"]


# --- T038: a record write that fails surfaces, and never fails the run -------


def test_a_never_started_record_that_cannot_be_written_warns_instead_of_raising(wiz, monkeypatch):
    """C11: the run is already failing on its own terms; the record must not become
    a second failure. The warning is the other half — a missing record must never be
    mistaken for a run that never happened."""
    warnings: list[str] = []
    monkeypatch.setattr(wiz, "warn", warnings.append)
    monkeypatch.setattr(
        wiz, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only store"))
    )
    spec = wiz.ExecSpec(mode="headless", agent="claude", task="t")
    assert wiz.record_never_started("local", "acme", spec, "image missing") is None
    assert any("could not be written" in m and "read-only store" in m for m in warnings)


def test_a_record_that_cannot_be_BUILT_does_not_mask_the_real_failure(wiz, monkeypatch):
    """The subtler half, and the reason the guard wraps the CONSTRUCTION too:
    `build_run_record` refuses an illegal record by calling `die`, and this function
    is called from an `except Fatal:` block that is about to re-raise the failure the
    operator is waiting to read. A Fatal escaping here would replace "the image is
    not built here" with a complaint about bookkeeping."""
    warnings: list[str] = []
    monkeypatch.setattr(wiz, "warn", warnings.append)
    monkeypatch.setattr(
        wiz, "build_run_record", lambda **kw: wiz.die("run record: unknown agent 'gpt'")
    )
    spec = wiz.ExecSpec(mode="headless", agent="claude", task="t")
    assert wiz.record_never_started("local", "acme", spec, "image missing") is None
    assert any("unknown agent" in m for m in warnings)


def test_a_failing_up_still_reports_ITS_OWN_failure_when_the_record_write_fails(wiz, monkeypatch):
    """The wiring, not just the helper. Without the guard the operator would be told
    the record could not be written and never told why the deploy failed."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda h, **k: None)
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])
    monkeypatch.setattr(wiz, "host_container_names", lambda h, include_stopped=False: set())
    monkeypatch.setattr(wiz, "log", lambda _m: None)
    monkeypatch.setattr(wiz, "warn", lambda _m: None)
    monkeypatch.setattr(
        wiz, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only store"))
    )
    monkeypatch.setattr(
        wiz, "refuse_superseded_layout", lambda n, root=None: wiz.die("the image is not built here")
    )
    with pytest.raises(wiz.Fatal, match="the image is not built here"):
        wiz.do_up("acme", spec=wiz.ExecSpec(mode="headless", agent="claude", task="print ok"))


def test_a_drain_that_cannot_reach_the_host_never_fails_the_command(wiz, monkeypatch):
    """A drain is an errand on the way to the operator's real command (research R7).
    The case that matters is `runs list` against a host that has gone away: the
    durable store is the whole point of the feature and is read from local disk, so
    dying here would deny an operator the records that survived in order to be read
    now (C3, SC-001)."""
    warnings: list[str] = []
    monkeypatch.setattr(wiz, "warn", warnings.append)
    monkeypatch.setattr(wiz, "host_environments", lambda h: ["acme"])
    monkeypatch.setattr(
        wiz, "ensure_tunnel", lambda h, **k: (_ for _ in ()).throw(OSError("ssh: not found"))
    )
    assert wiz.real_drain_host_records("local", dict(LOCAL_HOST)) == []
    assert any("could not reach local" in m for m in warnings)


# --- T057: records lost with the volume are VISIBLE (spec edge case G2) ------


def _deploy_model(wiz, name, volumes):
    return wiz.write_compose_file("local", name, {"volumes": {v: {"name": v} for v in volumes}})


def test_a_declared_runs_volume_that_has_vanished_is_reported(wiz, drain):
    """T017 drains on the tool's own teardown; this is the case that goes AROUND the
    tool. An un-ingested record leaves nothing behind, so the store simply has fewer
    runs in it than the operator ran and nothing anywhere looks wrong."""
    drain.volumes.clear()
    _deploy_model(wiz, "acme", wiz.per_container_volumes("acme"))
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    said = " ".join(drain.warnings)
    assert wiz.runs_volume_name("acme") in said
    assert "removed outside the tool" in said
    assert "GONE" in said


def test_a_purged_or_never_deployed_environment_is_silent(wiz, drain):
    """The condition is the MODEL and not the absence. `down --purge` drains first
    and then removes the volume together with the generated model, so it leaves
    nothing behind to ask about — and a warning that cried wolf on every clean host
    is one an operator learns to scroll past, costing exactly the case above."""
    drain.volumes.clear()
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert drain.warnings == []


def test_a_pre_016_deployment_is_not_reported_as_a_LOSS(wiz, drain):
    """A nine-volume deployment never had a runs volume, so nothing was lost with
    it. That environment IS dropping its records — into the container's own layer —
    and the migration announcement (T010) is what says so, in the words that name
    the actual remedy."""
    drain.volumes.clear()
    nine = [v for v in wiz.per_container_volumes("acme") if v != wiz.runs_volume_name("acme")]
    _deploy_model(wiz, "acme", nine)
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert drain.warnings == []


def test_a_host_that_cannot_be_ASKED_is_never_reported_as_a_loss(wiz, drain):
    """`volume inspect` fails identically for "no such volume" and for a daemon that
    cannot be reached, so the model alone is not enough evidence. Without the second
    probe this would announce records permanently lost every time a VPS was asleep —
    and a warning that cries wolf on a reachable-tomorrow host is one an operator
    learns to scroll past, costing exactly the case the warning exists for."""
    drain.volumes.clear()
    drain.reachable = False
    _deploy_model(wiz, "acme", wiz.per_container_volumes("acme"))
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert drain.warnings == []


def test_a_present_volume_is_never_reported_as_lost(wiz, drain):
    """The half that keeps the test above honest: an assertion that only ever sees a
    warning would pass for a build that warned unconditionally."""
    _deploy_model(wiz, "acme", wiz.per_container_volumes("acme"))
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert drain.warnings == []


# --- T058: the record's field set is CLOSED (finding U1, SC-005) -------------


def _full_record(wiz):
    return _record(
        wiz,
        ended_at="2026-08-09T10:12:00Z",
        exit_code=0,
        task="tidy the imports",
        host="local",
        repository={
            "start_head": "a" * 40,
            "end_head": "b" * 40,
            "branch": "main",
            "upstream": "origin/main",
            "commits": ["b" * 40],
            "paths": ["src/a.py"],
            "paths_truncated": False,
            "pushed": True,
            "state": "ok",
        },
        usage=_reported("claude", input_tokens=12),
        notes=["a diagnostic"],
    )


def _assert_the_field_set_is_closed(wiz):
    """The guard under test.

    SC-005 claims no credential value appears in any record, 100% of runs. That is
    not the property of a filter — research R9 rejected pattern redaction — it is
    the property of the field set having exactly one operator-authored field. Add a
    second and SC-005 becomes false while every other test in this suite still
    passes, which is precisely what this asserts against.
    """
    assert set(_full_record(wiz)) == set(wiz.RECORD_FIELD_PROVENANCE)
    operator_fields = {f for f, p in wiz.RECORD_FIELD_PROVENANCE.items() if p == "operator"}
    assert operator_fields == {"task"}


def test_every_field_is_tool_git_or_agent_derived_except_the_task(wiz):
    _assert_the_field_set_is_closed(wiz)


def test_the_closure_check_notices_a_new_free_text_field(wiz, monkeypatch):
    """Proof-it-can-fail, in both directions the defect can arrive from: a field
    added to the record without a provenance, and a second field declared
    operator-authored."""
    monkeypatch.setitem(wiz.RECORD_FIELD_PROVENANCE, "comment", "operator")
    with pytest.raises(AssertionError):
        _assert_the_field_set_is_closed(wiz)


def test_the_declared_provenances_are_a_closed_vocabulary(wiz):
    """A provenance nobody defined would let a new field be waved through with a
    word that sounds safe."""
    assert set(wiz.RECORD_FIELD_PROVENANCE.values()) == {"tool", "git", "agent", "operator"}


def test_the_one_agent_authored_field_is_bounded_to_numbers(wiz):
    """`usage` is the only field an AGENT fills, so the closure holds only while its
    values cannot be prose. This is why validate_usage refuses a string rather than
    storing it (see the usage group above)."""
    assert wiz.RECORD_FIELD_PROVENANCE["usage"] == "agent"
    with pytest.raises(wiz.Fatal, match="must be a number"):
        _record(wiz, usage=_reported("claude", note="ghp_notARealToken"))


def test_the_container_writes_the_same_field_set_and_no_more(wiz):
    """The record for a REAL run is composed in shell, so a free-text field could be
    added there without touching a line of Python and SC-005 would still "pass".

    The template is read as TEXT rather than parsed: it is not JSON until the
    entrypoint has expanded it. Extraction that missed a key would make the two sets
    differ and fail loudly, so this cannot pass by finding nothing.
    """
    body = _entrypoint_text().split("body=$(cat <<EOF", 1)[1].split("\nEOF\n", 1)[0]
    keys = {
        line.strip().split('"')[1]
        for line in body.splitlines()
        if line.strip().startswith('"') and '":' in line
    }
    assert keys == set(wiz.RECORD_FIELD_PROVENANCE)


def test_a_record_arriving_with_an_undeclared_field_is_named_and_still_stored(wiz, drain):
    """The closure is a claim about the records IN THE STORE, and ingestion is the
    only door records enter by that the tool did not compose itself. The field is
    not dropped — that would lose an operator's data to silence a warning, and C2
    says `runs show --json` is verbatim — so the claim is narrowed out loud instead.
    """
    rec = _full_record(wiz)
    rec["operator_comment"] = "ghp_notARealToken"
    assert wiz._decode_record("r.json", json.dumps(rec).encode()) is not None
    assert any("operator_comment" in m and "undeclared" in m for m in drain.warnings)


def test_a_record_with_exactly_the_declared_fields_is_silent(wiz, drain):
    """The half that keeps the test above honest: an assertion that only ever sees a
    warning would pass for a build that warned on every record it ingested."""
    assert wiz._decode_record("r.json", json.dumps(_full_record(wiz)).encode()) is not None
    assert drain.warnings == []


def test_ingestion_stamps_two_fields_and_widens_the_set_by_none(wiz, monkeypatch):
    """Ingestion is the other writer into the durable store. It fills `host` and
    `environment`, both already declared — a record arriving from a volume must not
    be able to grow the store's schema on the way in."""
    import io
    import tarfile

    rec = _full_record(wiz)
    rec["host"] = None
    rec["environment"] = None
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        blob = json.dumps(rec).encode()
        info = tarfile.TarInfo("./20260809T101010Z-ab12.json")
        info.size = len(blob)
        tf.addfile(info, io.BytesIO(blob))
    payload = buf.getvalue()

    def fake_query(argv, timeout=None):
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(wiz, "query", fake_query)
    monkeypatch.setattr(
        wiz.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, payload, b""),
    )
    monkeypatch.setattr(wiz, "log", lambda _m: None)
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    stored = json.loads(
        (wiz.runs_store_dir("local", "acme") / "20260809T101010Z-ab12.json").read_text()
    )
    assert set(stored) == set(wiz.RECORD_FIELD_PROVENANCE)
    assert (stored["host"], stored["environment"]) == ("local", "acme")
