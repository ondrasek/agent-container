"""Feature 007 (guided wizard) unit tests — hermetic, no runtime, no TTY.

The recommendation engine is a PURE function of an injected EnvSnapshot, so every
load-bearing rule (exactly one recommendation; never an unmet-hard-prereq action;
broken-state precedence; soft credentials; escape hatch + always-quit; secret-free
equivalent commands) is asserted without a container daemon or a terminal.
"""

from __future__ import annotations

LOCAL = {"driver": "docker", "context": "", "address": "localhost"}


def _target(wiz, name="dev", host="local", ambiguous=False):
    return wiz.ActiveTarget(host, dict(LOCAL), name, ambiguous)


def _snap(
    wiz,
    *,
    runtime="satisfied",
    host="satisfied",
    image="satisfied",
    credentials="satisfied",
    container="satisfied",
    running="satisfied",
    target=None,
    orphan=None,
    problems=None,
    details=None,
):
    """Build an EnvSnapshot directly from stage statuses (bypassing the probes)."""
    d = details or {}
    stages = [
        wiz.SetupStage("runtime", runtime, d.get("runtime", "")),
        wiz.SetupStage("host", host, d.get("host", "")),
        wiz.SetupStage("image", image),
        wiz.SetupStage("credentials", credentials),
        wiz.SetupStage("container", container, d.get("container", "")),
        wiz.SetupStage("running", running, d.get("running", "")),
    ]
    return wiz.EnvSnapshot(target or _target(wiz), stages, [], orphan or [], problems or [])


# --- Foundational: assess_stages tri-state + soft classification (T002) ------


def test_assess_stages_ordered_and_soft(wiz):
    stages = wiz.assess_stages(
        {
            "runtime_present": True,
            "runtime_usable": True,
            "host_present": True,
            "host_usable": True,
            "image_present": True,
            "credentials_present": False,
            "container_present": True,
            "running": True,
        }
    )
    assert [s.key for s in stages] == list(wiz.STAGE_KEYS)
    creds = next(s for s in stages if s.key == "credentials")
    assert creds.hard is False and creds.status == wiz.STAGE_UNSATISFIED  # soft, absent
    assert all(s.hard for s in stages if s.key != "credentials")


def test_assess_stages_unusable_vs_absent(wiz):
    # host registered but unreachable → unusable (present-but-broken), not absent
    host = next(
        s
        for s in wiz.assess_stages(
            {"host_present": True, "host_usable": False, "host_detail": "down"}
        )
        if s.key == "host"
    )
    assert host.status == wiz.STAGE_UNUSABLE and "down" in host.detail
    # container present but not running → unusable, carrying the status detail
    c = next(
        s
        for s in wiz.assess_stages(
            {"container_present": True, "running": False, "container_detail": "Exited (1)"}
        )
        if s.key == "container"
    )
    assert c.status == wiz.STAGE_UNUSABLE and "Exited" in c.detail
    # absent container → unsatisfied
    c2 = next(s for s in wiz.assess_stages({"container_present": False}) if s.key == "container")
    assert c2.status == wiz.STAGE_UNSATISFIED


def test_resolve_active_target_local_default_and_ambiguous(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL)))
    monkeypatch.setattr(wiz, "implicit_local_host", lambda rt=None: dict(LOCAL))
    monkeypatch.setattr(wiz, "load_registry", lambda: {"hosts": {}, "default": None})
    t = wiz.resolve_active_target("docker")
    assert t.host_name == "local" and t.ambiguous_host is False
    # >1 host and no default → ambiguous (the shell must prompt)
    monkeypatch.setattr(
        wiz, "load_registry", lambda: {"hosts": {"a": {}, "b": {}}, "default": None}
    )
    assert wiz.resolve_active_target("docker").ambiguous_host is True


def test_build_snapshot_reuses_sole_container(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "probe_host_runtime", lambda hr: None)
    monkeypatch.setattr(wiz, "image_exists", lambda rt, tag: True)
    monkeypatch.setattr(
        wiz,
        "host_ps_rows",
        lambda hr, include_stopped=False: [("agent-container-only", "img", "Up 2m", "2m")],
    )
    monkeypatch.setattr(wiz, "load_registry", lambda: {"hosts": {}, "default": None})
    monkeypatch.setattr(wiz, "_volume_names", lambda rt: [])
    monkeypatch.setattr(wiz, "resolve_env_file", lambda n: None)
    t = wiz.ActiveTarget("local", dict(LOCAL), None, False)
    snap = wiz.build_snapshot("docker", t)
    assert t.container_name == "only"  # FR-019: reuse the sole existing container
    assert snap.stage("running").satisfied


# --- US1: forward journey (T007) ---------------------------------------------


def test_recommend_empty_state_builds_image(wiz):
    rec = wiz.recommend_next_step(
        _snap(
            wiz,
            image="unsatisfied",
            credentials="unsatisfied",
            container="unsatisfied",
            running="unsatisfied",
        )
    )
    assert (
        rec.kind == "build_image" and rec.reason and rec.equivalent_cmd == "agent-container build"
    )


def test_recommend_never_returns_unmet_hard_prereq_action(wiz):
    # image absent ⇒ must recommend build, NOT start/attach (SC-002/SC-003)
    rec = wiz.recommend_next_step(
        _snap(wiz, image="unsatisfied", container="unsatisfied", running="unsatisfied")
    )
    assert rec.kind == "build_image"


def test_soft_credentials_does_not_gate_start(wiz):
    s = _snap(wiz, credentials="unsatisfied", container="unsatisfied", running="unsatisfied")
    assert wiz.recommend_next_step(s).kind == "start"  # FR-018: not blocked
    kinds = {a.kind for a in wiz.valid_actions(s)}
    assert "start" in kinds and "supply_credentials" in kinds  # start stays valid


def test_recommend_running_is_attach(wiz):
    assert wiz.recommend_next_step(_snap(wiz)).kind == "attach"


def test_recommend_always_has_reason_and_secret_free_cmd(wiz):
    for kw in (
        {},
        {"image": "unsatisfied"},
        {"container": "unsatisfied", "running": "unsatisfied"},
    ):
        rec = wiz.recommend_next_step(_snap(wiz, **kw))
        assert rec.reason  # FR-003
        assert "sk-" not in rec.equivalent_cmd  # never a resolved secret (III)


# --- US2: healthy environment → day-to-day (T011) ----------------------------


def test_healthy_recommends_daytoday_not_setup(wiz):
    rec = wiz.recommend_next_step(_snap(wiz))  # all satisfied incl running
    assert rec.kind == "attach"  # not a setup step


def test_valid_actions_healthy_includes_daytoday(wiz):
    kinds = {a.kind for a in wiz.valid_actions(_snap(wiz))}
    assert {"attach", "view_logs", "remove"} <= kinds


# --- US3: broken states + corrective precedence (T013) -----------------------


def test_broken_runtime_precedes_everything(wiz):
    rec = wiz.recommend_next_step(
        _snap(
            wiz,
            runtime="unusable",
            image="unsatisfied",
            container="unsatisfied",
            running="unsatisfied",
            details={"runtime": "daemon down"},
        )
    )
    assert rec.kind == "fix_runtime" and "daemon down" in rec.reason


def test_unreachable_host_recommends_fix(wiz):
    rec = wiz.recommend_next_step(_snap(wiz, host="unusable", details={"host": "no route"}))
    assert rec.kind == "fix_runtime" and "unreachable" in rec.reason


def test_missing_host_recommends_setup(wiz):
    assert wiz.recommend_next_step(_snap(wiz, host="unsatisfied")).kind == "setup_host"


def test_broken_container_recommends_logs(wiz):
    rec = wiz.recommend_next_step(
        _snap(wiz, container="unusable", running="unsatisfied", details={"container": "Exited (1)"})
    )
    assert rec.kind == "view_logs" and "logs" in rec.equivalent_cmd


def test_orphan_volumes_recommend_cleanup(wiz):
    rec = wiz.recommend_next_step(
        _snap(
            wiz,
            container="unsatisfied",
            running="unsatisfied",
            orphan=["agent-container-old-workspace"],
        )
    )
    assert rec.kind == "clean_volumes" and rec.destructive


# --- US4: escape hatch, always-quit, withheld, secret-free (T015) ------------


def test_valid_actions_always_includes_quit(wiz):
    for kw in ({}, {"runtime": "unusable"}, {"host": "unsatisfied"}, {"image": "unsatisfied"}):
        assert "quit" in {a.kind for a in wiz.valid_actions(_snap(wiz, **kw))}  # FR-015


def test_valid_actions_withholds_hard_unmet(wiz):
    # image absent → start/attach withheld (FR-004), build offered
    kinds = {
        a.kind
        for a in wiz.valid_actions(
            _snap(wiz, image="unsatisfied", container="unsatisfied", running="unsatisfied")
        )
    }
    assert "start" not in kinds and "attach" not in kinds and "build_image" in kinds
    # runtime broken → no container-y action offered at all
    broken = {a.kind for a in wiz.valid_actions(_snap(wiz, runtime="unusable"))}
    assert not ({"start", "attach", "build_image", "view_logs"} & broken)


def test_equivalent_cmd_secret_free_even_with_env_secret(wiz, monkeypatch):
    monkeypatch.setenv("SECRETVAL", "sk-supersecret")
    s = _snap(wiz, credentials="unsatisfied", container="unsatisfied", running="unsatisfied")
    for a in wiz.valid_actions(s):
        assert "sk-supersecret" not in a.equivalent_cmd
    creds = next(a for a in wiz.valid_actions(s) if a.kind == "supply_credentials")
    assert "--env-file" in creds.equivalent_cmd  # names a path/flag, never a value


def test_destructive_actions_flagged(wiz):
    acts = {a.kind: a for a in wiz.valid_actions(_snap(wiz))}
    assert acts["remove"].destructive


def test_recommendation_is_a_valid_action_kind(wiz):
    # the marked recommendation is always among the currently-valid actions
    for kw in (
        {},
        {"image": "unsatisfied"},
        {"container": "unsatisfied", "running": "unsatisfied"},
    ):
        s = _snap(wiz, **kw)
        rec_kind = wiz.recommend_next_step(s).kind
        assert rec_kind in {a.kind for a in wiz.valid_actions(s)}


# --- FR-013: no-TTY guard -----------------------------------------------------


def test_wizard_loop_no_tty_declines(wiz, monkeypatch, capsys):
    monkeypatch.setattr(wiz, "is_tty", lambda: False)
    rc = wiz.wizard_loop()
    assert rc == 2 and "interactive terminal" in capsys.readouterr().err


def test_wizard_no_tty_real_invocation():
    """T010: a real end-to-end invocation of the wizard entry with no TTY declines
    cleanly (FR-013). The interactive zero-to-attached journey itself is covered by the
    pure-engine unit tests above + the existing per-action acceptance (build/up/attach)."""
    import subprocess

    from conftest import SCRIPT_PATH

    r = subprocess.run(
        ["uv", "run", "--no-project", "--script", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=180,
    )
    assert r.returncode == 2, f"expected the no-TTY guard (exit 2), got {r.returncode}: {r.stderr}"
    assert "interactive terminal" in r.stderr
