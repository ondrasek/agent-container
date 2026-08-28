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
import time
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
        # `--permission-mode bypassPermissions` was added because headless has no
        # tty and nobody to approve a tool call, so the default asked for
        # permission it could never receive and the agent silently did nothing.
        # It changes WHAT THE AGENT MAY DO, not what it REPORTS: `-p` still emits
        # prose, nothing here requests a machine-readable usage summary, and the
        # record still honestly says unknown. That is the question this test makes
        # someone answer when an invocation changes, and this is the answer.
        'cmd=(claude --permission-mode bypassPermissions -p "${t}")',
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
    doc = _DOC.read_text()
    assert (
        f"{wiz.RETENTION_MAX_AGE_DAYS} days, or {wiz.RETENTION_MAX_RECORDS} records per environment"
        in doc
    )
    # HOW the count is allocated is on this list too, because it decides which records
    # a burst costs the operator — and there is no third number for it to drift by, so
    # what has to agree is the RULE. Both surfaces must name the axis; that the axis is
    # actually enforced is proved behaviourally further down, not by this string.
    assert "spent on distinct UTC days first" in help_text
    assert "spent on distinct UTC days first" in doc
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


def test_the_documented_ALLOCATION_rule_is_the_enforced_one(wiz, tmp_path, monkeypatch):
    """Proof-it-can-fail for the axis claim, and it has to be behavioural: there is no
    constant to bump, so the way the documented rule and the code can part company is
    that the prose keeps promising distinct days while the code stops bucketing by
    them. Collapsing every record into one bucket IS a plain newest-first rule.

    Both halves are asserted together — the words on both surfaces, and the behaviour
    those words describe — because either alone is the recurring defect: a string
    match that passes over a rule nobody enforces, or a behaviour nothing tells the
    operator about."""
    _assert_the_documented_numbers_are_the_enforced_ones(wiz)
    d = tmp_path / "store"
    history = _history(wiz, d, range(2, 32))
    _burst(d, "2026-04-01", 600)
    monkeypatch.setattr(wiz, "_utc_day", lambda epoch: "one-bucket")
    removed = set(wiz.prune_run_store(d, now=_now(1) + 90 * 86400))
    assert set(history) <= removed, (
        "with the day axis collapsed the burst must evict the history — otherwise "
        "the documented rule is not what keeps it"
    )


def test_the_enforced_bound_is_the_constant_and_not_a_second_copy(wiz, tmp_path, monkeypatch):
    """The other direction: the constant must be what `prune_run_store` actually
    reads. A rule that hard-coded 90 beside a constant saying 90 would satisfy the
    text-binding above and ignore any future change."""
    monkeypatch.setattr(wiz, "RETENTION_MAX_AGE_DAYS", 1)
    d = tmp_path / "store"
    _write_record(wiz, d, "two-days-old", _at(1))
    assert wiz.prune_run_store(d, now=_now(3)) == ["two-days-old.json"]


def test_the_count_is_spent_on_distinct_DAYS_before_any_day_gets_a_second_record(
    wiz, tmp_path, monkeypatch
):
    """The allocation, at a size small enough to state exactly. Four slots, a burst of
    three on one day and ten older days holding one run each: the burst may have ONE
    of the four, because the other three are the newest three days that also have a
    record. A newest-first rule would give the burst three of the four."""
    monkeypatch.setattr(wiz, "RETENTION_MAX_RECORDS", 4)
    d = tmp_path / "store"
    burst = set(_burst(d, "2026-04-01", 3))
    _history(wiz, d, range(2, 12))
    wiz.prune_run_store(d, now=_now(1) + 90 * 86400)
    kept = {p.name for p in d.iterdir()}
    assert len(kept) == wiz.RETENTION_MAX_RECORDS
    assert len(kept & burst) == 1, f"the burst took more than its round: {sorted(kept)}"


def test_the_bound_the_round_robin_fills_is_the_CONSTANT_and_not_a_second_copy(
    wiz, tmp_path, monkeypatch
):
    """The other direction for the count bound: lower it and the same store must lose
    more. A rule that read a hard-coded 500 would satisfy the text binding above and
    ignore every future change to it."""
    monkeypatch.setattr(wiz, "RETENTION_MAX_RECORDS", 3)
    d = tmp_path / "store"
    _history(wiz, d, range(2, 12))  # ten days, one record each
    wiz.prune_run_store(d, now=_now(1) + 90 * 86400)
    assert len(list(d.iterdir())) == 3


def test_both_stores_share_ONE_count_rule_with_different_axes(wiz, tmp_path, monkeypatch):
    """The run store buckets by UTC day and the egress store by destination, and both
    go through `_round_robin_keeps`. Asserted because a second copy of the rule is how
    a fix to one store silently misses the other — this repository has done exactly
    that twice (T118/T129d), and the rule was reimplemented per store before this."""
    axes: list[str] = []
    real = wiz._round_robin_keeps
    monkeypatch.setattr(
        wiz,
        "_round_robin_keeps",
        lambda rows, limit: axes.extend(b for _w, b, _p in rows) or real(rows, limit),
    )
    runs = tmp_path / "runs"
    _write_record(wiz, runs, "20260401T000000Z-aaaa", _at(1))
    wiz.prune_run_store(runs, now=_now(2))
    assert axes == ["2026-01-01"], f"the run store's axis is not the UTC day: {axes}"

    axes.clear()
    egress = tmp_path / "egress"
    wiz.atomic_write_json(
        egress, "e.json", {"timestamp": _at(1), "host": "api.openai.com", "decision": "refused"}
    )
    wiz.prune_egress_store(egress, now=_now(2))
    assert axes == ["api.openai.com"], f"the egress store's axis is not the destination: {axes}"


# --- T040: a crash-loop burst must not evict the records that explain it ------
#
# The tool deploys a headless run with `restart: on-failure` and NO retry limit, so
# an agent that cannot start is restarted for as long as it is left alone and every
# restart writes a record — measured at ~9 records in ~40s, i.e. thousands in a
# night. Under a plain newest-first count bound that one burst evicts every older
# record of the environment: the store stays bounded and stops being worth reading,
# which is the letter of FR-011 with none of its point.


def _burst(directory: Path, day: str, count: int, start_hour: int = 0) -> list[str]:
    """`count` records stamped on `day` from `start_hour`, as a restart loop writes them.

    Written directly rather than through the atomic helper: this is about which
    records survive, and a few thousand fsyncs would make it slow enough to skip.
    """
    directory.mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(count):
        h, m, sec = start_hour + i // 3600, i // 60 % 60, i % 60
        assert h < 24, "a burst that ran past midnight needs a second _burst call, by day"
        name = f"{day.replace('-', '')}T{h:02d}{m:02d}{sec:02d}Z-b{i:05d}"
        (directory / f"{name}.json").write_text(
            json.dumps({"started_at": f"{day}T{h:02d}:{m:02d}:{sec:02d}Z"})
        )
        names.append(f"{name}.json")
    return names


def _history(wiz, directory: Path, days: range) -> list[str]:
    """One record per day across `days` of January — the runs a crash loop in April
    must not cost the operator. January only, so every stamp is a REAL date: an
    invalid one would fall back to the file's mtime and rank as today's, which would
    quietly make this fixture the burst rather than the history."""
    return [_write_record(wiz, directory, f"jan{d:02d}", _at(d)).name for d in days]


def test_a_crash_loop_burst_does_not_evict_the_history_that_explains_it(wiz, tmp_path):
    """The property, stated as an operator would: after a night of restart records,
    the runs from BEFORE the loop are all still there. Under a plain newest-first rule
    every one of them is gone, and the store contains 500 copies of the same failure
    and nothing that shows what changed."""
    d = tmp_path / "store"
    history = _history(wiz, d, range(2, 32))  # 30 runs, one a day, all within 90 days
    burst = _burst(d, "2026-04-01", 600)
    now = _now(1) + 90 * 86400  # 2026-04-01, so January 2nd is still inside the age bound
    removed = set(wiz.prune_run_store(d, now=now))
    assert removed.isdisjoint(history), "the burst evicted the runs that explain it"
    assert set(history) <= {p.name for p in d.iterdir()}
    # The store is still bounded: the history takes one slot per day in the first pass
    # and the burst takes every slot no other day wanted.
    assert len(list(d.iterdir())) == wiz.RETENTION_MAX_RECORDS
    assert len(removed & set(burst)) == len(burst) - (wiz.RETENTION_MAX_RECORDS - len(history))


def test_a_burst_that_CROSSES_UTC_MIDNIGHT_still_does_not_evict_the_history(wiz, tmp_path):
    """The scenario the rule is documented for is an OVERNIGHT loop, which crosses UTC
    midnight by construction — so the protection has to hold when the burst occupies
    more than one day.

    The per-day SHARE this replaces failed here and only here, which is why it stood
    for a while: with a share of half the bound, two days of burst at their share
    consumed all 500 slots before any older day was examined. Measured on that rule —
    600 records on ONE day left all 30 history runs intact, and 500 split across two
    days deleted every one of them. Fewer records, total loss.
    """
    d = tmp_path / "store"
    history = _history(wiz, d, range(2, 32))
    # 22:00 on the 31st into the 1st and 2nd: one loop, three UTC days.
    burst = set(_burst(d, "2026-03-31", 250, start_hour=22))
    burst |= set(_burst(d, "2026-04-01", 250))
    burst |= set(_burst(d, "2026-04-02", 500))
    removed = set(wiz.prune_run_store(d, now=_now(1) + 91 * 86400))
    assert removed.isdisjoint(history), (
        "a burst spanning three UTC days evicted the history — the day axis only "
        "protects a burst that happens to stay inside one day"
    )
    assert len(list(d.iterdir())) == wiz.RETENTION_MAX_RECORDS
    assert removed <= burst


def test_the_newest_record_survives_a_burst_that_blew_the_cap(wiz, tmp_path):
    """FR-011 bounds the store; it does not license losing the run an operator is
    most likely to be asking about. The newest record is first in the order the count
    bound fills and its bucket is the first one walked, so it cannot be the record
    that pays for the burst."""
    d = tmp_path / "store"
    _burst(d, "2026-04-01", wiz.RETENTION_MAX_RECORDS + 50)
    newest = max(p.name for p in d.iterdir())
    wiz.prune_run_store(d, now=_now(1) + 90 * 86400)
    assert (d / newest).exists()


def test_the_round_robin_is_a_priority_and_never_deletes_below_the_count_bound(wiz, tmp_path):
    """The allocation must not become a third bound. An environment that legitimately
    ran 450 times today, in a store holding only those 450, must lose none of them —
    deleting the 251st would be data loss for no space at all."""
    d = tmp_path / "store"
    _burst(d, "2026-04-01", wiz.RETENTION_MAX_RECORDS - 50)
    assert wiz.prune_run_store(d, now=_now(1) + 90 * 86400) == []


def test_the_allocation_needs_no_number_of_its_own(wiz):
    """PARAMETER-FREE is the property, not an implementation note. The share constant
    this replaces had to be chosen without knowing how many days there would be, and
    any share S is defeated by bound/S buckets at S apiece — which is the midnight
    case above. A store rule with no third number cannot drift from its prose, so the
    absence is asserted rather than left to be reintroduced by the next reader."""
    assert not hasattr(wiz, "RETENTION_MAX_RECORDS_PER_DAY")
    assert "no number of its own" in _DOC.read_text()


def test_a_time_no_clock_can_render_does_not_break_the_prune(wiz, tmp_path, monkeypatch):
    """`_record_epoch` returns infinity for a record that vanished mid-prune, and the
    round-robin rule has to bucket it. One missing file must not fail the whole prune —
    retention is an errand on the way to the operator's real command."""
    assert wiz._utc_day(float("inf")) == ""
    d = tmp_path / "store"
    _write_record(wiz, d, "gone", _at(1))
    monkeypatch.setattr(wiz, "_record_epoch", lambda p: float("inf"))
    assert wiz.prune_run_store(d, now=_now(20)) == []


def test_a_FUTURE_dated_record_is_not_IMMORTAL_under_the_age_bound(wiz, tmp_path):
    """`started_at` comes from inside a container, so it is the one time value in a
    record that a broken clock can put in the future — and unclamped it is `>= cutoff`
    for every cutoff the age rule can compute, so the age bound can NEVER take it. A
    store can then be permanently full of records dated 2098 that no passage of time
    removes.

    The count bound is a separate story and the round-robin rule already handles it:
    600 bogus records spread over two bogus days are two buckets, so 30 real days still
    take a slot each in the first pass. Both halves are asserted, but only the SECOND
    one fails without the clamp — stated so nobody reads the first as its proof.

    `_record_epoch` clamps to the moment this store wrote the record down, because no
    run can have started after the tool recorded it. That is a reading a real clock
    produced, so the record ages, buckets and eventually goes."""
    d = tmp_path / "store"
    history = _history(wiz, d, range(2, 32))
    bogus = set(_burst(d, "2098-01-01", 300)) | set(_burst(d, "2098-01-02", 300))
    removed = set(wiz.prune_run_store(d, now=_now(1) + 91 * 86400))
    assert removed.isdisjoint(history), "future-dated records evicted the real ones"
    # THE CLAMP'S OWN ASSERTION. `now` here is a decade past the real clock that set
    # every one of these files' mtimes, so a store that ages from a believable time is
    # empty and one that trusts `started_at` still holds 500 records dated 2098.
    survivors = bogus - removed
    assert survivors, "the fixture proved nothing: no bogus record survived the count bound"
    assert set(wiz.prune_run_store(d, now=time.time() + 10 * 365 * 86400)) >= survivors


def test_a_record_RESCUED_from_a_long_dead_host_is_not_destroyed_by_the_same_drain(
    wiz, tmp_path, monkeypatch
):
    """An ordinary host switched off for four months. The drain stores its records,
    removes the volume copy, and then prunes — so without the exemption the tool
    destroys, inside ONE command, the records that command existed to rescue, and the
    operator's listing is empty. No clock skew is needed.

    The exemption is for the AGE bound only: `protect` is not a way past the count."""
    d = tmp_path / "store"
    rescued = _write_record(wiz, d, "four-months-old", _at(1)).name
    now = _now(1) + (wiz.RETENTION_MAX_AGE_DAYS * 86400) + 60
    assert wiz.prune_run_store(d, now=now, protect=frozenset([rescued])) == []
    assert (d / rescued).exists(), "the drain deleted the record it had just rescued"
    # Pruned on a LATER contact, once it has been readable at least once.
    assert wiz.prune_run_store(d, now=now) == [rescued]


def test_the_drain_RESCUES_a_record_past_the_age_bound_instead_of_destroying_it(
    wiz, drain, monkeypatch
):
    """End to end, and this is the wiring rather than the rule. `prune_run_store` could
    be provably correct about `protect` while `ingest_records` never fills it — an
    argument nothing passes is this repository's recurring defect — so the assertion is
    on the STORE after a real drain of a four-month-old record.

    The record is `finished`, so the drain clears it from the volume: its only other
    copy is gone by the time the prune runs, which is what makes this loss permanent
    rather than a re-ingestion away."""
    import io
    import tarfile

    rec = _record(wiz, run_id="ancient", started_at=_at(1), ended_at=_at(1), exit_code=0)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        body = json.dumps(rec).encode()
        info = tarfile.TarInfo("./ancient.json")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    payload = buf.getvalue()
    monkeypatch.setattr(
        wiz.subprocess,
        "run",
        lambda argv, capture_output=False, timeout=None, **kw: subprocess.CompletedProcess(
            argv, 0, payload, b""
        ),
    )
    # `now` is real, so the January record is far past the 90-day bound.
    ingested = wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert ingested == ["ancient"]
    stored = [p.name for p in wiz.runs_store_dir("local", "acme").iterdir()]
    assert stored == ["ancient.json"], (
        "the drain stored the record, cleared the volume copy and then deleted the "
        f"stored copy — all in one command, so nothing was rescued: {stored}"
    )


# --- T040: what pruning must never touch, and never do quietly ---------------


def test_retention_makes_no_call_to_a_HOST_and_so_cannot_reach_a_pending_record(
    wiz, tmp_path, monkeypatch
):
    """The one deletion that could never be noticed. A record still pending on a
    container volume has left nothing behind: prune it and the store is simply short
    of runs, with nothing anywhere looking wrong. Pruning therefore reads the durable
    store and nothing else — asserted as "issues no command at all", because that is
    the property that keeps it true after a refactor."""

    def forbidden(*a, **kw):
        raise AssertionError("retention reached the container runtime")

    monkeypatch.setattr(wiz, "query", forbidden)
    monkeypatch.setattr(wiz.subprocess, "run", forbidden)
    d = tmp_path / "store"
    _write_record(wiz, d, "ancient", _at(1))
    assert wiz.prune_run_store(d, now=_now(1) + (wiz.RETENTION_MAX_AGE_DAYS * 86400) + 60) == [
        "ancient.json"
    ]


def test_retention_runs_even_when_the_drain_RAISES(wiz, drain, monkeypatch):
    """The hole this closes, and the reason `ingest_records` uses `finally`: the drain
    raises on a large backlog (the clear step's argv exceeded ARG_MAX), the exception
    left through `ingest_records` to `drain_host_records`'s handler, and the prune
    never ran. Retention became unreachable on exactly the crash-looping environment
    that needed it — on every contact, forever, while the store grew without bound."""
    _write_record(wiz, wiz.runs_store_dir("local", "acme"), "ancient", _at(1))
    monkeypatch.setattr(
        wiz, "_ingest_from_volume", lambda *a, **k: (_ for _ in ()).throw(OSError("E2BIG"))
    )
    with pytest.raises(OSError):
        wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert list(wiz.runs_store_dir("local", "acme").iterdir()) == []
    assert any("pruned 1 run record(s)" in m for m in drain.logs)


def test_a_prune_that_itself_fails_does_not_MASK_the_drains_own_failure(wiz, drain, monkeypatch):
    """The hazard `finally` introduces, and the reason retention swallows OSError
    here. Bookkeeping raising inside a `finally` would replace the drain's exception
    with a complaint about the store — so the operator is told retention is unhappy
    and never told why the drain failed, which is C11's masking failure exactly."""
    monkeypatch.setattr(
        wiz, "_ingest_from_volume", lambda *a, **k: (_ for _ in ()).throw(OSError("the real one"))
    )
    monkeypatch.setattr(
        wiz, "prune_run_store", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only store"))
    )
    with pytest.raises(OSError, match="the real one"):
        wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    assert any("could not apply run-record retention" in m for m in drain.warnings)


def test_the_announcement_names_WHICH_records_were_taken(wiz, drain):
    """ "pruned 4000 records" answers a question no operator has. The range of run ids
    is what lets them tell whether the run they came looking for is among them."""
    d = wiz.runs_store_dir("local", "acme")
    _write_record(wiz, d, "20260101T000000Z-aaaa", _at(1))
    _write_record(wiz, d, "20260101T000001Z-bbbb", _at(1))
    wiz.ingest_records("local", dict(LOCAL_HOST), "acme", "img")
    said = " ".join(drain.logs)
    assert "20260101T000000Z-aaaa .. 20260101T000001Z-bbbb" in said


# --- T040: the clear step's argv is bounded (the backlog that broke retention) --


def _clear_argv_bytes(wiz, batch: list[str]) -> int:
    argv = wiz.driver_ingest_clear_argv(LOCAL_HOST, "v", "img", batch)
    return sum(len(a.encode()) + 1 for a in argv)


def test_a_backlog_is_cleared_in_batches_that_cannot_exceed_ARG_MAX(wiz):
    """Measured on this project's own machine (ARG_MAX 1 MiB): `subprocess.run`
    raises OSError(E2BIG) between 10k and 20k record paths, which one crash-looping
    environment reaches in about a day. Bounded in BYTES rather than in files because
    a run id may be 128 characters (RUN_ID_RE), and a file count that was safe for
    short ids would not be for long ones."""
    names = [f"20260401T{i:06d}Z-{'c' * 100}.json" for i in range(20000)]
    batches = wiz._clear_batches(names)
    assert len(batches) > 1, "20k records went out as one argv"
    assert [n for b in batches for n in b] == names, "batching lost or reordered a record"
    for b in batches:
        assert _clear_argv_bytes(wiz, b) < wiz.MAX_CLEAR_ARGV_BYTES * 2


def test_one_over_long_name_still_gets_its_own_batch_rather_than_being_dropped(wiz):
    """A record dropped here would sit on the volume with nothing saying why. The
    runtime is entitled to refuse it loudly instead."""
    assert wiz._clear_batches(["x" * (wiz.MAX_CLEAR_ARGV_BYTES * 2)]) == [
        ["x" * (wiz.MAX_CLEAR_ARGV_BYTES * 2)]
    ]
    assert wiz._clear_batches([]) == []


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
