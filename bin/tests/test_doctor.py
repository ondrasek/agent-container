"""Feature 013: `doctor` — preflight validation.

Two properties carry this feature and both are easy to fake. **Read-only** is an
absence, which working output never demonstrates. **`unknown`** is a third state that
collapses into `pass` the moment anyone treats a check as a boolean — and a diagnostic
that reports healthy is what stops an operator looking further.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

HOST = {"driver": "docker", "context": ""}


# --- the model refuses to be built wrong -------------------------------------


def test_a_finding_CANNOT_exist_without_a_remedy(wiz):
    """SC-003 wants zero findings that state only a symptom. A field that is merely
    usually filled in produces exactly the finding that is not, so the constructor
    refuses — a check unable to name a remedy has not finished being designed."""
    with pytest.raises(ValueError, match="has no remedy"):
        wiz.Finding(check_id="x", severity="blocking", observed="something", remedy="")
    with pytest.raises(ValueError, match="has no remedy"):
        wiz.Finding(check_id="x", severity="blocking", observed="something", remedy="   ")


def test_a_check_pairs_its_finding_with_its_status(wiz):
    """A `fail` with no finding is a problem nobody can act on; a `pass` carrying one
    is a contradiction a consumer would have to guess about."""
    with pytest.raises(ValueError, match="finding is present exactly when"):
        wiz.Check(id="x", title="x", scope="project", severity="blocking", status="fail")
    f = wiz.Finding(check_id="x", severity="blocking", observed="o", remedy="r")
    with pytest.raises(ValueError, match="finding is present exactly when"):
        wiz.Check(id="x", title="x", scope="project", severity="blocking", status="pass", finding=f)


def test_three_statuses_exist_and_unknown_is_one_of_them(wiz):
    assert set(wiz.DOCTOR_STATUSES) == {"pass", "fail", "unknown"}


# --- the exit mapping, including the case the spec originally left undefined --


@pytest.mark.parametrize(
    ("status", "severity", "blocks"),
    [
        ("fail", "blocking", True),
        ("fail", "advisory", False),
        ("unknown", "blocking", False),  # FR-011a — the one that matters
        ("unknown", "advisory", False),
        ("pass", "blocking", False),
    ],
)
def test_only_a_FAILED_blocking_check_blocks(wiz, status, severity, blocks):
    """FR-011/FR-011a. Exit 1 asserts that a deploy would not work, and `unknown` is
    precisely the state in which that assertion cannot be made — so an unknown never
    yields 1 however severe the check. Failing on one would break `doctor && up` for
    anyone whose secondary host happened to be slow."""
    finding = (
        None
        if status == "pass"
        else wiz.Finding(check_id="c", severity=severity, observed="o", remedy="r")
    )
    c = wiz.Check(
        id="c", title="c", scope="project", severity=severity, status=status, finding=finding
    )
    assert c.blocks_deploy is blocks


def test_an_advisory_only_run_exits_ZERO(wiz):
    """SC-004: `doctor && up` must stay viable, or the command stops being run."""
    adv = wiz.doctor_fail("stale", "advisory", "old image", "rebuild it")
    assert wiz.doctor_exit_code([adv]) == wiz.EXIT_OK


def test_an_unknown_only_run_exits_ZERO(wiz):
    """SC-004a. The spec originally defined the exit status in terms of pass and fail
    only, leaving the third state undefined at the boundary a program consumes."""
    unk = wiz.doctor_unknown("host-reachability", "blocking", "timed out", remedy="retry")
    assert wiz.doctor_exit_code([unk]) == wiz.EXIT_OK


def test_a_blocking_failure_exits_ONE(wiz):
    bad = wiz.doctor_fail("layout", "blocking", "pre-011 layout", "move the files")
    assert wiz.doctor_exit_code([bad]) == wiz.EXIT_FAILURE


def test_NOTHING_produces_an_exit_above_two(wiz):
    """`3` is *pending registration* tool-wide, documented in --help and pinned by a
    test. A `doctor` returning it would tell an automated caller something false about
    an SSH key."""
    every = (
        [wiz.doctor_ok("a", sev) for sev in wiz.DOCTOR_SEVERITIES]
        + [wiz.doctor_fail("b", sev, "o", "r") for sev in wiz.DOCTOR_SEVERITIES]
        + [wiz.doctor_unknown("c", sev, "o", remedy="r") for sev in wiz.DOCTOR_SEVERITIES]
    )
    for n in range(len(every) + 1):
        assert wiz.doctor_exit_code(every[:n]) in (wiz.EXIT_OK, wiz.EXIT_FAILURE)


def test_doctor_defines_no_parallel_exit_namespace(wiz):
    """The values live in the tool-wide table 019 made the single source and pinned
    `--help` to. A `DOCTOR_EXIT_*` set with the same three numbers is how doctor's 2
    and the global 2 drift apart in meaning."""
    src = Path(wiz.__file__).read_text()
    assert "DOCTOR_EXIT_OK" not in src
    assert "DOCTOR_EXIT_CANNOT_RUN" not in src


# --- read-only, structurally ------------------------------------------------


def _reachable_names(wiz, root_func) -> set[str]:
    """Every global name reachable from `root_func`, transitively.

    Delimits "the doctor code path" mechanically, because a 14k-line single file has
    no natural boundary and a grep over the whole thing would pass or fail for reasons
    unrelated to `doctor`.
    """
    seen: set[str] = set()
    stack = [root_func]
    while stack:
        fn = stack.pop()
        code = getattr(fn, "__code__", None)
        if code is None:
            continue
        for n in code.co_names:
            if n in seen:
                continue
            seen.add(n)
            nxt = getattr(wiz, n, None)
            if callable(nxt) and getattr(nxt, "__module__", None) == wiz.__name__:
                stack.append(nxt)
    return seen


def test_the_doctor_PATH_never_reaches_a_mutating_helper(wiz):
    """R1, and the reason this feature is hard. The helpers a deploy calls FIRST are
    the ones that mutate, and `migrate_flat_state()` is the trap: it opens do_up,
    do_redeploy and do_list, it relocates files on disk, it is idempotent, and it
    documents itself as "safe to call repeatedly". It reads as harmless and is exactly
    what SC-002 measures.

    Structural rather than behavioural, and that is the point: an acceptance snapshot
    catches a mutation only when the test project happens to trigger it, so a
    reachable-but-not-yet-triggered call passes the gate and fails only here.
    """
    reachable = _reachable_names(wiz, wiz.do_doctor)
    for forbidden in (
        "migrate_flat_state",
        "drain_host_records",
        "record_inventory_creation",
        "pin_host_key",
        "record_agent_ssh_pubkey",
        "down_container",
        "compose_up_exec",
    ):
        assert forbidden not in reachable, f"doctor can reach {forbidden}"


def test_the_reachability_guard_CAN_fail(wiz):
    """A guard that cannot fire is decoration. `do_up` really does reach the helper
    the previous test forbids, so the walker is looking at something real."""
    assert "migrate_flat_state" in _reachable_names(wiz, wiz.do_up)


def test_doctor_never_resolves_a_credential(wiz):
    """FR-009/FR-010, C8/C9. For a manager source, resolving IS the prompt: `op read`
    against an approval-gated item raises a system dialog. Not retrieving the value at
    all is stronger than not printing it — a value never read cannot leak through a
    log, a traceback, or a `--json` field somebody adds later."""
    reachable = _reachable_names(wiz, wiz.do_doctor)
    assert "resolve_credential_value" not in reachable
    assert "_run_resolver" not in reachable
    assert "_keychain_lookup" not in reachable


# --- the credential check's classification table -----------------------------


def test_an_env_credential_is_checked_by_PRESENCE(wiz, monkeypatch):
    monkeypatch.setenv("DOCTOR_PRESENT", "x")
    c = wiz.doctor_check_credential({"name": "k", "source": "env", "var": "DOCTOR_PRESENT"}, "e")
    assert c.status == "pass"
    monkeypatch.delenv("DOCTOR_PRESENT")
    c = wiz.doctor_check_credential({"name": "k", "source": "env", "var": "DOCTOR_PRESENT"}, "e")
    assert c.status == "fail" and "is not set" in c.finding.observed


def test_a_file_credential_is_checked_by_EXISTENCE(wiz, tmp_path):
    p = tmp_path / "key"
    c = wiz.doctor_check_credential({"name": "k", "source": "file", "path": str(p)}, "e")
    assert c.status == "fail"
    p.write_text("secret-value-nobody-should-see\n")
    c = wiz.doctor_check_credential({"name": "k", "source": "file", "path": str(p)}, "e")
    assert c.status == "pass"


def test_a_manager_credential_reports_UNKNOWN_when_its_binary_exists(wiz, monkeypatch):
    """The honest answer: the resolver is installed, and whether the item resolves
    cannot be established without prompting. Never `pass` — that would assert
    something unverified."""
    monkeypatch.setattr(wiz.shutil, "which", lambda _b: "/usr/local/bin/op")
    c = wiz.doctor_check_credential(
        {"name": "k", "source": "onepassword", "vault": "V", "item": "I", "field": "F"}, "e"
    )
    assert c.status == "unknown"
    assert "NOT verified" in c.finding.observed


def test_a_manager_credential_FAILS_when_its_binary_is_absent(wiz, monkeypatch):
    """The most common real failure on a new machine — US3's scenario — and free to
    detect."""
    monkeypatch.setattr(wiz.shutil, "which", lambda _b: None)
    c = wiz.doctor_check_credential(
        {"name": "k", "source": "onepassword", "vault": "V", "item": "I", "field": "F"}, "e"
    )
    assert c.status == "fail"
    assert "not on PATH" in c.finding.observed
    assert "install op" in c.finding.remedy


def test_no_credential_check_leaks_a_VALUE(wiz, tmp_path):
    """FR-010/SC-006, asserted against a real file's contents."""
    secret = "sk-ant-DOCTOR-MUST-NEVER-PRINT-THIS"
    p = tmp_path / "k"
    p.write_text(secret + "\n")
    c = wiz.doctor_check_credential({"name": "k", "source": "file", "path": str(p)}, "e")
    assert secret not in repr(c)


# --- unknown is never a shrug ------------------------------------------------


def test_every_unknown_names_an_ACTION(wiz, monkeypatch):
    """FR-004 admits no exception for `unknown`. "Check by hand" tells the operator
    nothing they did not already know, which turns the unknown into a dead end."""
    monkeypatch.setattr(wiz.shutil, "which", lambda _b: "/usr/local/bin/op")
    unknowns = [
        wiz.doctor_check_credential(
            {"name": "k", "source": "onepassword", "vault": "V", "item": "I", "field": "F"}, "e"
        ),
        wiz.doctor_check_host("attachonly", {"driver": "existing-ssh"}),
    ]
    for c in unknowns:
        assert c.status == "unknown"
        assert c.finding.remedy.strip()
        assert "check by hand: " not in c.finding.remedy


def test_an_unreachable_host_is_never_reported_as_PASS(wiz, monkeypatch):
    """SC-005/C5. The scenario the feature exists to get right."""

    def boom(*_a, **_kw):
        raise OSError("no route to host")

    monkeypatch.setattr(wiz, "probe_host_runtime", boom)
    c = wiz.doctor_check_host("dead", HOST)
    assert c.status == "unknown"


def test_a_host_that_answers_with_an_error_FAILS_as_unreachable(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "probe_host_runtime", lambda _h: "connection refused")
    c = wiz.doctor_check_host("dead", HOST)
    assert c.status == "fail" and "UNREACHABLE" in c.finding.observed


# --- the port check must not cry wolf on a healthy environment ---------------


def test_a_RUNNING_environments_own_port_is_a_pass(wiz, monkeypatch):
    """R10/C14. The port derives from the name (Constitution IV), so a running
    environment always holds "its" port — reporting that as a conflict would fail
    `doctor` on every healthy deployment, and a diagnostic that cries wolf on the
    normal case is one nobody runs."""
    monkeypatch.setattr(wiz, "host_container_names", lambda *_a, **_k: {wiz.container_name("acme")})
    monkeypatch.setattr(wiz, "port_free", lambda _p: False)  # occupied — by itself
    assert wiz.doctor_check_port("local", HOST, "acme").status == "pass"


def test_a_port_held_by_a_STRANGER_blocks(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "host_container_names", lambda *_a, **_k: set())
    monkeypatch.setattr(wiz, "port_free", lambda _p: False)
    c = wiz.doctor_check_port("local", HOST, "acme")
    assert c.status == "fail" and c.severity == "blocking"


# --- image freshness ---------------------------------------------------------


def test_an_unstamped_image_is_unknown_not_stale(wiz, monkeypatch):
    """FR-012b. Reporting it stale nags every operator into a rebuild they may not
    need; reporting it fresh asserts something unknown."""
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 0, "\n", ""))
    c = wiz.doctor_check_image_freshness(HOST, "t")
    assert c.status == "unknown" and "no version stamp" in c.finding.observed


def test_a_matching_stamp_passes_and_a_mismatch_is_ADVISORY(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "_resolve_version", lambda: "1.2.3")
    monkeypatch.setattr(
        wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 0, "1.2.3\n", "")
    )
    assert wiz.doctor_check_image_freshness(HOST, "t").status == "pass"
    monkeypatch.setattr(
        wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 0, "1.0.0\n", "")
    )
    c = wiz.doctor_check_image_freshness(HOST, "t")
    # Advisory, not blocking: a stale image still RUNS. That is the whole reason this
    # check exists — it reports something with no failure at all today.
    assert c.status == "fail" and c.severity == "advisory"


def test_the_freshness_check_never_touches_a_registry(wiz, monkeypatch):
    """FR-012a: local comparison only. A label rather than an ENV, read with
    `image inspect`, so nothing pulls and nothing starts."""
    seen: list[list[str]] = []
    monkeypatch.setattr(
        wiz,
        "query",
        lambda argv, **k: (seen.append(argv), subprocess.CompletedProcess([], 0, "x\n", ""))[1],
    )
    wiz.doctor_check_image_freshness(HOST, "t")
    argv = seen[0]
    assert argv[1:3] == ["image", "inspect"]
    assert "pull" not in argv and "run" not in argv
    assert wiz.IMAGE_VERSION_LABEL in " ".join(argv)


def _func_body(src: str, name: str) -> str:
    """A function's source, sliced to the next top-level `def` rather than a fixed
    character count.

    This replaced a 900-character window anchored on one statement. Feature 017
    moved the version resolution ABOVE that anchor so `build` could stamp two
    images from one resolved value, and the window then excluded the very clause
    it was asserting — a false failure, and the fourth time a magic window has
    cost this suite one.
    """
    i = src.index(f"\ndef {name}(")
    j = src.index("\ndef ", i + 1)
    return src[i:j]


def test_build_OMITS_the_stamp_when_the_version_is_unknown(wiz):
    """R5. `_resolve_version()` returns "0.0.0+unknown" when it cannot tell, and
    stamping that would be worse than not stamping — a meaningless value that looks
    like an answer, where absence is honestly *unknown* (FR-012b)."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_build")
    assert 'not version.endswith("+unknown")' in body
    assert "--build-arg" in body


def test_build_resolves_the_version_ONCE_for_every_image(wiz):
    """Feature 017 T004: `build` now produces two images, and FR-016 compares the
    control plane's version against an environment's.

    Two resolutions could return different values — the git describe underlying
    `_resolve_version` is not a constant — and FR-016 would then report a drift
    between two images built by the same command. So the value is resolved OUTSIDE
    the per-image loop, and this asserts that ordering rather than trusting it.
    """
    body = _func_body(Path(wiz.__file__).read_text(), "do_build")
    resolve_at = body.index("version = _resolve_version()")
    loop_at = body.index("for image_tag, subdir in targets:")
    assert resolve_at < loop_at, (
        "_resolve_version() is called inside the per-image loop, so two images "
        "from one `build` could carry different versions"
    )
    # Comment lines excluded: the block DOCUMENTS `_resolve_version()` as well as
    # calling it, and counting prose would make this assert the wrong thing —
    # failing on a clarifying comment and passing on a second real call the day
    # someone deleted the comment.
    calls = [
        ln
        for ln in body.splitlines()
        if "_resolve_version()" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(calls) == 1, f"expected one _resolve_version() call, found: {calls}"


@pytest.mark.parametrize("image_dir", ["image", "image-control-plane"])
def test_the_dockerfile_defaults_the_stamp_to_EMPTY(wiz, image_dir):
    """An unset build arg must produce an image with no usable stamp, not one carrying
    a literal placeholder that would read as a version.

    Parameterised over BOTH images (Feature 017): the control-plane image is the
    one FR-016's semver rule reads, so an unstamped-but-placeholder-carrying
    control plane would make the comparison assert a version nobody has.
    """
    df = (Path(wiz.__file__).parents[1] / image_dir / "Dockerfile").read_text()
    assert "ARG AGENT_CONTAINER_VERSION=\n" in df
    assert f'LABEL {wiz.IMAGE_VERSION_LABEL}="${{AGENT_CONTAINER_VERSION}}"' in df


# --- scope, ordering, brevity ------------------------------------------------


@pytest.mark.parametrize(
    ("name", "has_root", "expect"),
    [
        ("acme", True, "environment"),
        ("acme", False, "environment"),
        (None, True, "project"),
        (None, False, "machine"),
    ],
)
def test_scope_resolution(wiz, name, has_root, expect):
    assert wiz.doctor_scope(name, Path("/p") if has_root else None) == expect


def test_no_project_is_a_SUCCESS_state(wiz):
    """FR-007/C11. US3's whole scenario is a new machine, before any project exists —
    failing there would make the command useless in the case it exists for."""
    assert wiz.doctor_scope(None, None) == "machine"
    assert wiz.doctor_exit_code([]) == wiz.EXIT_OK


def test_findings_are_ordered_blocking_first_and_STABLY(wiz):
    """A report whose order changes between runs cannot be diffed, and diffing two
    runs is how an operator confirms they fixed something."""
    checks = [
        wiz.doctor_ok("z-pass", "blocking"),
        wiz.doctor_unknown("m-unknown", "advisory", "o", remedy="r"),
        wiz.doctor_fail("b-advisory", "advisory", "o", "r"),
        wiz.doctor_fail("a-blocking", "blocking", "o", "r"),
    ]
    ids = [c.id for c in wiz.doctor_order(checks)]
    assert ids == ["a-blocking", "b-advisory", "m-unknown", "z-pass"]
    assert [c.id for c in wiz.doctor_order(list(reversed(checks)))] == ids


def test_the_brief_threshold_is_pinned(wiz):
    """SC-007 is a number, not "one screen": screen height is not a property of the
    tool, and a criterion nothing can fail is not a criterion."""
    assert wiz.DOCTOR_BRIEF_LINES == 24


# --- reuse the deploy's wording, discard its control flow --------------------


def test_a_validators_FATAL_becomes_a_finding_and_the_run_continues(wiz):
    """R9. Every validator dies on the first problem — right for a deploy, fatal for
    "report all of them in one pass"."""

    def dies() -> None:
        wiz.die("the exact words a deploy would use")

    c = wiz.doctor_finding_from_fatal("layout", "blocking", dies)
    assert c.status == "fail"
    # The remedy is the validator's OWN string. SC-008 measures divergence at zero,
    # and two strings that agree today drift the moment one is edited.
    assert c.finding.remedy == "the exact words a deploy would use"


def test_an_UNEXPECTED_exception_becomes_unknown_not_a_crash(wiz):
    """C10: the registry must survive a check author's mistake, or one bad check
    silences every other."""

    def broken() -> None:
        raise KeyError("a typo in the check itself")

    c = wiz.doctor_finding_from_fatal("x", "blocking", broken)
    assert c.status == "unknown" and "the check itself failed" in c.finding.observed


def test_a_clean_validator_passes(wiz):
    assert wiz.doctor_finding_from_fatal("x", "blocking", lambda: None).status == "pass"


def test_the_layout_check_reuses_the_deploys_producer(wiz):
    """SC-008: the same producer, so divergence is impossible rather than unlikely."""
    block = _func_src(wiz, "doctor_check_layout")
    assert "refuse_superseded_layout" in block


def test_doctor_is_in_the_json_set(wiz):
    """FR-011's machine-readable half, enforced by machinery that already exists."""
    assert "doctor" not in wiz.NO_JSON_COMMANDS
    assert wiz.NO_JSON_COMMANDS == frozenset({"host env", "completions", "attach", "menu"})


# --- machine-level checks ----------------------------------------------------


def _func_src(wiz, name: str) -> str:
    """A function's source, sliced to the next top-level `def`.

    Not a fixed character count: a magic window silently shrinks the assertion every
    time the code grows, and that has already produced three false failures across
    this project. The boundary is the next definition, so it cannot rot.
    """
    src = Path(wiz.__file__).read_text()
    i = src.index(f"\ndef {name}(")
    j = src.index("\ndef ", i + 1)
    return src[i:j]


def test_a_missing_runtime_BLOCKS(wiz, monkeypatch):
    """Nothing deploys without one, so this is the one machine-level check that is
    blocking rather than advisory."""
    monkeypatch.setattr(wiz.shutil, "which", lambda _b: None)
    c = wiz.doctor_check_runtime()
    assert c.status == "fail" and c.severity == "blocking"


def test_an_unresolvable_tool_version_is_unknown_and_EXPLAINS_the_knock_on(wiz, monkeypatch):
    """Running from a checkout without readable metadata is legitimate, so not a
    failure — but it is why freshness reports unknown, and saying so here saves the
    operator correlating two findings."""
    monkeypatch.setattr(wiz, "_resolve_version", lambda: "0.0.0+unknown")
    c = wiz.doctor_check_tool()
    assert c.status == "unknown"
    assert "freshness" in c.finding.remedy


def test_an_ABSENT_user_config_is_a_pass_not_a_finding(wiz, monkeypatch, tmp_path):
    """A fresh machine has none and nothing is wrong with that. Reporting it would put
    a permanent item on the checklist of every operator who never needed one, and a
    checklist with a permanent entry is one people learn to skip."""
    monkeypatch.setattr(wiz, "CONFIG_DIR", tmp_path / "nope")
    assert wiz.doctor_check_user_config().status == "pass"


def test_machine_checks_run_in_EVERY_scope(wiz):
    """A project reported clean while the runtime is missing would be a lie of
    omission — the deploy depends on both."""
    block = _func_src(wiz, "doctor_collect")
    assert "doctor_check_runtime()" in block
    # ...and before the early return for a project-less run.
    assert block.index("doctor_check_runtime()") < block.index("if root is None:")


def test_the_report_says_what_it_CHECKED(wiz):
    """T040. A narrow run that reads as a clean one is how an operator concludes more
    was checked than was."""
    block = _func_src(wiz, "do_doctor")
    assert '"checks_run": covered' in block
    assert 'log(f"checked: ' in block


def test_the_non_invocation_guard_CAN_fail(wiz, tmp_path, monkeypatch):
    """The other half of T053a: prove the sentinel would notice.

    `resolve_credential_value` on the same declaration DOES run the script, so a
    marker-based assertion is looking at something real rather than at a script that
    never runs for an unrelated reason.
    """
    marker = tmp_path / "ran"
    script = tmp_path / "r.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\necho v\n")
    script.chmod(0o755)
    cred = {"name": "c", "source": "command", "argv": [str(script)]}

    wiz.doctor_check_credential(cred, "e")
    assert not marker.exists(), "the doctor check invoked the resolver"

    wiz.resolve_credential_value(cred, tmp_path)
    assert marker.exists(), "the sentinel never fires — the guard proves nothing"
