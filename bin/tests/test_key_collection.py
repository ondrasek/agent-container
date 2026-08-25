"""Feature 020 — the public-key collection, PYTHON side only.

The region parser is shell and is tested by the harness that EXECUTES shell
(`test_entrypoint.sh` sections 7e/7f). Nothing in this file may stand in for
entrypoint behaviour: a Python test that reads `entrypoint.sh` as text and asserts
on its source cannot fail when the shell logic is wrong, and grep-the-source
coverage for the mechanism this whole feature rests on is exactly the defect shape
020 exists to remove.

Compose-model assertions live in `test_compose.py`, which already owns them.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def _keygen(tmp_path: Path, comment: str) -> tuple[str, str]:
    """A real ed25519 keypair. Returns (public line, private key text).

    Real keys, not fixtures shaped like keys: validation runs `ssh-keygen -l`, so a
    hand-written string would test the error path only.
    """
    priv = tmp_path / f"id_{comment}"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(priv)],
        check=True,
    )
    return priv.with_suffix(".pub").read_text().strip(), priv.read_text()


# --- C1/C2/C3/C4: resolution and the three states ----------------------------


def test_undeclared_collection_resolves_to_none(wiz, tmp_path):
    """C3: absent at both levels is UNDECLARED — not empty (Constitution VIII)."""
    assert wiz.resolve_key_collection(tmp_path / "not-a-project") is None


def test_user_level_collection_resolves(wiz, tmp_path):
    """C1: with only a user-level file, that file wins."""
    pub, _ = _keygen(tmp_path, "laptop")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    src, keys = wiz.resolve_key_collection(tmp_path / "elsewhere")
    assert src == wiz.CONFIG_DIR / "authorized_keys"
    assert keys == [pub]


def test_declared_empty_is_distinguishable_from_undeclared(wiz, tmp_path):
    """C4 vs C3 — the distinction Constitution VIII exists to protect.

    `len(keys) == 0` cannot tell these apart, which is why the resolver returns
    None for one and an empty list for the other.
    """
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text("# only a comment\n\n")
    declared = wiz.resolve_key_collection(tmp_path / "elsewhere")
    assert declared is not None
    assert declared[1] == []
    (wiz.CONFIG_DIR / "authorized_keys").unlink()
    assert wiz.resolve_key_collection(tmp_path / "elsewhere") is None


def test_project_replaces_user_entirely(wiz, tmp_path):
    """C2/FR-002: the winning FILE wins — not a per-key merge.

    Merging would let a project only WIDEN the admit set, never narrow it, and
    narrowing is the entire point of the project override: a client repository must
    not inherit an operator's personal phone.
    """
    user_pub, _ = _keygen(tmp_path, "phone")
    proj_pub, _ = _keygen(tmp_path, "workstation")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(user_pub + "\n")
    proj = tmp_path / "proj"
    (proj / ".agent-container").mkdir(parents=True)
    (proj / ".agent-container" / "authorized_keys").write_text(proj_pub + "\n")
    src, keys = wiz.resolve_key_collection(proj)
    assert keys == [proj_pub]
    assert user_pub not in keys  # NOT merged — the project narrowed the set
    assert src == proj / ".agent-container" / "authorized_keys"


def test_options_prefix_survives_verbatim(wiz, tmp_path):
    """`from=`/`restrict` are legal authorized_keys syntax and none of our business."""
    pub, _ = _keygen(tmp_path, "restricted")
    line = f'restrict,from="10.0.0.0/8" {pub}'
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(line + "\n")
    _, keys = wiz.resolve_key_collection(tmp_path / "elsewhere")
    assert keys == [line]


# --- C6/C7/C9: validation refuses before anything is created -----------------


def test_malformed_entry_refuses_naming_file_and_line(wiz, tmp_path):
    """C6/SC-004: the message must name the file AND the line number."""
    bad = tmp_path / "collection"
    bad.write_text("ssh-ed25519 NOT-VALID-BASE64 broken\n")
    with pytest.raises(wiz.Fatal) as e:
        wiz.validate_public_key_line("ssh-ed25519 NOT-VALID-BASE64 broken", str(bad), 1)
    assert str(bad) in str(e.value)
    assert ":1" in str(e.value)


def test_private_key_is_refused_as_private(wiz, tmp_path):
    """C7/SC-005: refused, and the message SAYS it is private.

    `id_ed25519` and `id_ed25519.pub` differ by four characters and the mistake is
    one `cat` away. It is also the only error here whose cost is not recoverable by
    editing a file, so a generic "invalid key" would be the wrong message.
    """
    _, priv = _keygen(tmp_path, "oops")
    first = priv.splitlines()[0]
    with pytest.raises(wiz.Fatal) as e:
        wiz.validate_public_key_line(first, "collection", 3)
    assert "PRIVATE" in str(e.value).upper()
    assert "collection:3" in str(e.value)


def test_a_real_public_key_validates_to_a_fingerprint(wiz, tmp_path):
    """The guard above must not be passing because everything fails."""
    pub, _ = _keygen(tmp_path, "good")
    fp = wiz.validate_public_key_line(pub, "collection", 1)
    assert fp.startswith("SHA256:")


# --- C10/C11: the admit set and its attribution ------------------------------


def test_flag_is_additive_and_each_entry_is_attributed(wiz, tmp_path):
    """C11/FR-008: --authorized-key widens the collection; neither wins silently."""
    coll_pub, _ = _keygen(tmp_path, "laptop")
    flag_pub, _ = _keygen(tmp_path, "iphone")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(coll_pub + "\n")
    flag = tmp_path / "iphone.pub"
    flag.write_text(flag_pub + "\n")
    entries, src, declared = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    assert declared is True
    assert [e.line for e in entries] == [coll_pub, flag_pub]
    assert str(src) in entries[0].source
    assert "--authorized-key" in entries[1].source
    assert {e.comment for e in entries} == {"laptop", "iphone"}


def test_a_duplicate_across_sources_is_admitted_once(wiz, tmp_path):
    """A duplicate is deduped on key MATERIAL, and is not an error."""
    pub, _ = _keygen(tmp_path, "same")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    flag = tmp_path / "same.pub"
    flag.write_text(pub + "\n")
    entries, _, _ = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    assert len(entries) == 1


def test_undeclared_plus_flag_admits_exactly_the_flag(wiz, tmp_path):
    """SC-007: the undeclared path behaves exactly as it does today."""
    flag_pub, _ = _keygen(tmp_path, "only")
    flag = tmp_path / "only.pub"
    flag.write_text(flag_pub + "\n")
    entries, src, declared = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    assert declared is False
    assert src is None
    assert [e.line for e in entries] == [flag_pub]


def test_a_missing_flag_file_refuses(wiz, tmp_path):
    """FR-012/C8: refuse before any runtime call, naming the path."""
    with pytest.raises(wiz.Fatal) as e:
        wiz.resolved_admit_set([tmp_path / "nope.pub"], cwd=tmp_path)
    assert "nope.pub" in str(e.value)


# --- C4/C3 at the reporting surface -----------------------------------------


def test_declared_empty_warns_and_undeclared_stays_silent(wiz, tmp_path, capsys):
    """SC-011: the two runs must differ in OUTPUT, not merely in behaviour.

    The asymmetry is deliberate. A hand-edited file can be truncated by accident;
    where there is no file there is nothing to truncate, and FR-009 requires the
    undeclared path keep behaving exactly as it does today — which is silently.
    """
    wiz.report_admit_set([], Path("/cfg/authorized_keys"), declared=True)
    declared_out = capsys.readouterr()
    combined = declared_out.out + declared_out.err
    assert "EMPTY" in combined
    assert "/cfg/authorized_keys" in combined

    wiz.report_admit_set([], None, declared=False)
    undeclared = capsys.readouterr()
    assert (undeclared.out + undeclared.err).strip() == ""


def test_the_statement_names_fingerprints_never_blobs(wiz, tmp_path, capsys):
    """C10: a fingerprint identifies a device; the full blob is noise."""
    pub, _ = _keygen(tmp_path, "macbook")
    flag = tmp_path / "macbook.pub"
    flag.write_text(pub + "\n")
    entries, src, declared = wiz.resolved_admit_set([flag], cwd=tmp_path / "elsewhere")
    wiz.report_admit_set(entries, src, declared)
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "macbook" in combined
    assert entries[0].fingerprint in combined
    assert pub.split()[1] not in combined  # the base64 body must not be printed


# --- C23/C24/C31/C32: resume drift, and observe-vs-project -------------------


def test_created_with_set_is_read_from_the_compose_file(wiz, tmp_path):
    """C24 groundwork: the created-with set needs NO new state (data-model §5).

    It is the inlined `content:` in the deployment's own compose file — which is
    already the deployment's existence record. This is also why `content:` is
    load-bearing twice: under `file:` this would hold a PATH to a staged file the
    next deploy overwrites, so "what was this created with" would answer with the
    CURRENT resolution — a comparison against itself.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    m = wiz.build_compose_model("acme", "/repo", authorized_keys_file=None)
    m.setdefault("configs", {})["ssh_authorized_keys"] = {"content": pub + "\n"}
    wiz.write_compose_file("local", "acme", m)
    assert wiz.created_with_admit_set("local", "acme") == [pub]


def test_created_with_is_none_when_there_is_no_deployment(wiz):
    """Absent compose file means "no such deployment" — a THIRD distinct absence.

    Not undeclared, not undetermined. Collapsing any pair of the three is the
    Constitution VIII failure this feature keeps meeting.
    """
    assert wiz.created_with_admit_set("local", "never-deployed") is None


def test_resume_warns_when_the_collection_has_drifted(wiz, tmp_path, capsys):
    """C23/SC-008: `start` must SAY the admit set is stale, and not re-apply it.

    The container rewrites its managed region on boot, so the set staged at `up`
    time comes back looking freshly authoritative. Without this warning an operator
    who removed a key, stopped and started would be told nothing and would still be
    admitting it — FR-006 failing one command over.
    """
    gone_pub, _ = _keygen(tmp_path, "ipad")
    kept_pub, _ = _keygen(tmp_path, "laptop")
    m = wiz.build_compose_model("acme", "/repo")
    m.setdefault("configs", {})["ssh_authorized_keys"] = {"content": f"{kept_pub}\n{gone_pub}\n"}
    wiz.write_compose_file("local", "acme", m)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(kept_pub + "\n")

    wiz.warn_on_collection_drift("local", "acme")
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "ipad" in combined  # names WHICH key differs
    assert "redeploy" in combined  # and the remedy
    assert "still admits" in combined


def test_resume_is_silent_when_the_collection_matches(wiz, tmp_path, capsys):
    """The warning above must not be firing unconditionally."""
    pub, _ = _keygen(tmp_path, "laptop")
    m = wiz.build_compose_model("acme", "/repo")
    m.setdefault("configs", {})["ssh_authorized_keys"] = {"content": pub + "\n"}
    wiz.write_compose_file("local", "acme", m)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    wiz.warn_on_collection_drift("local", "acme")
    out = capsys.readouterr()
    assert "has changed" not in (out.out + out.err)


def test_an_unreachable_environment_is_undetermined_never_empty(wiz, monkeypatch, capsys):
    """C31/FR-019/SC-013: unexamined and empty are different claims.

    Reporting a stopped environment as admitting nobody would tell an operator they
    are locked out on the strength of never having looked. The projection must also
    never be quietly substituted for the observed reading.

    RETARGETED (T056): this test used to omit the compose file, so it reached
    `undetermined` by way of an environment that had never been DEPLOYED — proving
    the conflated behaviour rather than the contract it names. A deployment is
    recorded here and only the CONTAINER is unreachable, which is the case FR-019
    is about. Retargeted rather than deleted: dropped, nobody would be watching
    C31 at all.
    """
    m = wiz.build_compose_model("acme", "/repo")
    wiz.write_compose_file("local", "acme", m)  # the deployment EXISTS...
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *_a, **_k: False)
    assert wiz.observed_admit_set({}, "acme") is None  # ...its container does not
    wiz.report_projected_vs_observed("local", {}, "acme")
    combined = "".join(capsys.readouterr())
    assert wiz.UNDETERMINED in combined
    assert "agree:" not in combined  # no verdict may be claimed without a reading


def test_a_missing_deployment_says_so_instead_of_undetermined(wiz, monkeypatch, capsys):
    """T056/FR-014/Constitution VIII: the THIRD absence gets its own answer.

    "There is nothing to look at" and "we did not look" are different facts about
    an environment, and only one of them is fixed by starting it. Reporting a name
    that was never deployed as `undetermined` sent an operator to check a container
    that does not exist. The two cases must render differently — this asserts the
    difference, not merely the wording of either one.
    """
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *_a, **_k: False)
    wiz.report_projected_vs_observed("local", {}, "never-deployed")
    absent = "".join(capsys.readouterr())
    assert "NONE recorded" in absent
    assert wiz.UNDETERMINED not in absent, "a name that was never deployed read as unreachable"

    wiz.write_compose_file("local", "deployed", wiz.build_compose_model("deployed", "/repo"))
    wiz.report_projected_vs_observed("local", {}, "deployed")
    unreachable = "".join(capsys.readouterr())
    assert wiz.UNDETERMINED in unreachable
    assert "NONE recorded" not in unreachable
    assert absent != unreachable  # distinguishable in OUTPUT, not merely in state


def test_created_with_distinguishes_no_deployment_from_admitting_nobody(wiz):
    """T056: `None` is the absent RECORD; `[]` is a record that names no keys.

    `build_compose_model` omits the config entirely when the admit set is empty, so
    an environment deployed with no collection and no `--authorized-key` produced
    the same `None` as one that was never deployed. That silenced
    `warn_on_collection_drift` for precisely the operator who declared a collection
    AFTER deploying — the drift FR-013 most needs to report.
    """
    assert wiz.created_with_admit_set("local", "never-deployed") is None
    wiz.write_compose_file("local", "nokeys", wiz.build_compose_model("nokeys", "/repo"))
    assert wiz.created_with_admit_set("local", "nokeys") == []


def test_drift_warns_when_a_collection_is_declared_after_deploying(wiz, tmp_path, capsys):
    """FR-013, the case the `None` collapse above hid.

    Deploy admitting nobody, then declare a collection: the resumed environment
    admits nobody while the operator believes it admits their laptop. That is the
    FR-006 failure one command over, which is the whole reason FR-013 exists.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    wiz.write_compose_file("local", "acme", wiz.build_compose_model("acme", "/repo"))
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    wiz.warn_on_collection_drift("local", "acme")
    combined = "".join(capsys.readouterr())
    assert "has changed" in combined
    assert "laptop" in combined


def test_observed_marks_keys_outside_the_region_as_unmanaged(wiz, monkeypatch, tmp_path):
    """A key outside the region IS admitted but is not revocable by the collection.

    It must be visible as such rather than blending in — otherwise the report
    implies the collection controls access it does not control.
    """
    managed, _ = _keygen(tmp_path, "managed")
    hand, _ = _keygen(tmp_path, "handadded")
    body = (
        f"{hand}\n"
        f"{wiz.KEY_REGION_BEGIN_ID} — replaced on every boot\n"
        f"{managed}\n"
        f"{wiz.KEY_REGION_END_ID}\n"
    )
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        wiz,
        "query",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, body, ""),
    )
    observed = wiz.observed_admit_set({}, "acme")
    assert any(ln.startswith(managed) and "unmanaged" not in ln for ln in observed)
    assert any(ln.startswith(hand) and "unmanaged" in ln for ln in observed)


# --- T057: `--json` must ANSWER, not fall silent ------------------------------


def test_keys_show_json_emits_an_envelope_rather_than_nothing(wiz, monkeypatch, capsys, tmp_path):
    """T057/FR-007: a declared `--json` that prints nothing is worse than no flag.

    Both query verbs accepted `--json`, set JSON mode, and then reported entirely
    through `log()` — which is stderr. Stdout stayed EMPTY and the exit status
    stayed 0, so an agent could not distinguish "this environment admits nobody"
    from "this command told me nothing". `keys add` was never affected: it routes
    through `emit_action`.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    wiz.write_compose_file("local", "acme", wiz.build_compose_model("acme", "/repo"))
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *_a, **_k: False)

    wiz.keys_show("acme", host=None, as_json=True)
    env = json.loads(capsys.readouterr().out)
    assert env["schema"] == wiz.SCHEMA_VERSION and env["ok"] is True
    d = env["data"]
    assert d["environment"] == "acme" and d["deployment"] == "recorded"
    assert d["projected"]["state"] == "declared"
    assert d["projected"]["keys"][0]["comment"] == "laptop"
    assert d["observed"]["state"] == wiz.UNDETERMINED
    assert d["observed"]["keys"] is None, "an unread environment must not render as []"
    # `null`, never `false`: a verdict was not reached, and reporting one it never
    # checked is the defect SC-006 was rewritten to forbid.
    assert d["agree"] is None


def test_keys_show_json_names_the_three_absences_apart(wiz, monkeypatch, capsys):
    """Constitution VIII across the machine surface too (FR-014, data-model §5)."""
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *_a, **_k: False)
    wiz.keys_show("never-deployed", host=None, as_json=True)
    d = json.loads(capsys.readouterr().out)["data"]
    assert d["projected"]["state"] == "undeclared"  # no collection anywhere
    assert d["deployment"] == "absent"  # nothing was ever created
    assert d["observed"]["state"] == wiz.UNDETERMINED  # and nothing was reached
    assert d["created_with"] is None
    # Three absences, three words. Any two sharing one is the collapse.
    assert len({d["projected"]["state"], d["deployment"], d["observed"]["state"]}) == 3


def test_declared_empty_is_its_own_state_in_the_payload(wiz, monkeypatch, capsys):
    """C4/FR-017 on the machine surface: declared-empty is not undeclared."""
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *_a, **_k: False)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text("# every device retired\n")
    wiz.keys_show("acme", host=None, as_json=True)
    d = json.loads(capsys.readouterr().out)["data"]
    assert d["projected"]["state"] == "declared-empty"
    assert d["projected"]["keys"] == []
    assert d["projected"]["source"] is not None, "the file that admits nobody must be named"


# --- T059/C32/FR-020/SC-014: the listing must not sink on one bad row --------


def _deploy(wiz, *names):
    for n in names:
        wiz.write_compose_file("local", n, wiz.build_compose_model(n, "/repo"))


def test_keys_ls_reports_every_row_and_refuses_to_claim_success(wiz, monkeypatch, capsys, tmp_path):
    """C32/FR-020/SC-014: four environments, one unreachable — four rows.

    The listing must not abort at the failure, and must not exit 0 for a set it
    only partly examined. Both halves are asserted: a listing that reported every
    row and then exited 0 would satisfy the first and quietly break the second,
    which is how an incomplete answer passes as a complete one.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    _deploy(wiz, "alpha", "bravo", "charlie", "gone")
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "observed_admit_set", lambda _h, n: None if n == "gone" else [pub])
    with pytest.raises(wiz.typer.Exit) as e:
        wiz.keys_ls(host=None, as_json=True)
    assert e.value.exit_code == 1, "exit 0 would claim success for a row never examined"
    d = json.loads(capsys.readouterr().out)["data"]
    assert [row["environment"] for row in d["environments"]] == [
        "alpha",
        "bravo",
        "charlie",
        "gone",
    ], "a listing aborted at the unreachable row"
    assert d["undetermined"] == ["gone"]  # named, so the gap is actionable
    unreached = next(r for r in d["environments"] if r["environment"] == "gone")
    assert unreached["observed"]["state"] == wiz.UNDETERMINED and unreached["agree"] is None
    reached = next(r for r in d["environments"] if r["environment"] == "alpha")
    assert reached["observed"]["state"] == "read"


def test_keys_ls_human_path_reports_every_row_too(wiz, monkeypatch, capsys, tmp_path):
    """The same contract without `--json` — the flag must not be the only way in."""
    pub, _ = _keygen(tmp_path, "laptop")
    _deploy(wiz, "alpha", "gone")
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "observed_admit_set", lambda _h, n: None if n == "gone" else [pub])
    with pytest.raises(wiz.typer.Exit) as e:
        wiz.keys_ls(host=None, as_json=False)
    assert e.value.exit_code == 1
    combined = "".join(capsys.readouterr())
    assert "alpha:" in combined and "gone:" in combined
    assert wiz.UNDETERMINED in combined
    assert "gone" in combined.split("could not be observed")[1]  # the warning NAMES it


def test_keys_ls_all_reachable_exits_zero(wiz, monkeypatch, capsys, tmp_path):
    """The non-zero exit above must not be firing unconditionally."""
    pub, _ = _keygen(tmp_path, "laptop")
    _deploy(wiz, "alpha", "bravo")
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "observed_admit_set", lambda _h, _n: [pub])
    wiz.keys_ls(host=None, as_json=True)  # no Exit raised
    d = json.loads(capsys.readouterr().out)["data"]
    assert d["undetermined"] == [] and len(d["environments"]) == 2


def test_keys_ls_observes_each_environment_exactly_once(wiz, monkeypatch, capsys, tmp_path):
    """T062: the exit status must describe the rows that were PRINTED.

    `keys ls` used to render each row and then observe the environment a SECOND
    time to decide the exit status — two independent execs against the same
    container. A row printed with an admit set could be counted `undetermined` (or
    the reverse) whenever the container's state moved between them, so the status
    described a listing nobody was shown.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    _deploy(wiz, "alpha", "bravo")
    seen: list[str] = []

    def counting_observe(_h, n):
        seen.append(n)
        return [pub]

    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "observed_admit_set", counting_observe)
    wiz.keys_ls(host=None, as_json=False)
    assert sorted(seen) == ["alpha", "bravo"], f"each environment observed once, got {seen}"


# --- T058/C27: the region has TWO writers, and both must respect it ----------


def _execute_injection(wiz, monkeypatch, tmp_path, pubs, initial=""):
    """Run `inject_keys`' OWN shell snippet against a real file, and return it.

    EXECUTED, not asserted on as text. The snippet is shell, and a test that
    matched its source could not fail when the shell is wrong — the grep-the-source
    defect shape 020 exists to remove. The container paths are rewritten onto
    tmp_path so the real script runs unmodified in every other respect.
    """
    ak = tmp_path / "authorized_keys"
    ak.write_text(initial)
    captured: list[tuple[list[str], bytes]] = []
    # BOUND BEFORE PATCHING. `wiz.subprocess` IS the stdlib module object, so the
    # patch below is process-wide — reaching it through the module again would hand
    # this helper its own stub, the snippet would never run, and its `cat` would
    # block on a stdin nobody wrote to.
    real_run = subprocess.run

    def fake_run(argv, **kw):
        captured.append((list(argv), kw.get("input")))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    wiz.inject_keys("podman", "acme", pubs)
    for argv, stdin in captured:
        # CONTAINER_AUTHKEYS first: it is prefixed by the .ssh dir, so rewriting
        # the directory first would corrupt the file path too.
        script = (
            argv[-1]
            .replace(wiz.CONTAINER_AUTHKEYS, str(ak))
            .replace("/home/dev/.ssh", str(tmp_path))
        )
        real_run(["bash", "-c", script], input=stdin, check=True, timeout=30)
    return ak.read_text()


def _region_of(text, wiz):
    inside, out = False, []
    for ln in text.splitlines():
        if ln.startswith(wiz.KEY_REGION_BEGIN_ID):
            inside = True
            continue
        if ln.startswith(wiz.KEY_REGION_END_ID):
            inside = False
            continue
        if inside and ln.strip():
            out.append(ln)
    return out


def test_an_injection_leaves_exactly_one_marker_pair(wiz, monkeypatch, tmp_path):
    """C27: an injection that appended past `END` would satisfy C25's first half.

    "Admitted immediately" would pass and "gone after a recreate" would silently
    fail, because the entrypoint only rewrites what lies BETWEEN the markers — and
    a second pair makes the region's extent ambiguous, which the entrypoint refuses
    to boot over. plan.md names this the likeliest place for the feature to go
    wrong; it had no test until now.
    """
    pub, _ = _keygen(tmp_path, "guest")
    p = tmp_path / "guest.pub"
    p.write_text(pub + "\n")
    existing = (
        f"{wiz.KEY_REGION_BEGIN_ID} — replaced on every boot; edit outside this region\n"
        f"ssh-ed25519 AAAAOLD deployed\n"
        f"{wiz.KEY_REGION_END_ID}\n"
    )
    body = _execute_injection(wiz, monkeypatch, tmp_path, [p], initial=existing)
    assert sum(ln.startswith(wiz.KEY_REGION_BEGIN_ID) for ln in body.splitlines()) == 1
    assert sum(ln.startswith(wiz.KEY_REGION_END_ID) for ln in body.splitlines()) == 1
    assert pub in _region_of(body, wiz), "the grant landed OUTSIDE the region — unrevocable"


def test_an_injection_into_a_file_with_no_region_creates_exactly_one(wiz, monkeypatch, tmp_path):
    """The other branch of the same snippet, and the one no test reached.

    A first `keys add` against a container whose file has no region yet takes the
    else-branch, which writes the markers itself. If it wrote them wrongly the
    entrypoint would refuse to boot at the next recreate — a lockout produced by a
    grant.
    """
    pub, _ = _keygen(tmp_path, "guest")
    p = tmp_path / "guest.pub"
    p.write_text(pub + "\n")
    hand = "ssh-ed25519 AAAAHAND operator\n"
    body = _execute_injection(wiz, monkeypatch, tmp_path, [p], initial=hand)
    assert sum(ln.startswith(wiz.KEY_REGION_BEGIN_ID) for ln in body.splitlines()) == 1
    assert sum(ln.startswith(wiz.KEY_REGION_END_ID) for ln in body.splitlines()) == 1
    assert pub in _region_of(body, wiz)
    # FR-016: what the tool did not write is not the tool's to move.
    assert hand.strip() in body and hand.strip() not in _region_of(body, wiz)


def test_repeated_injection_of_the_same_key_does_not_grow_the_file(wiz, monkeypatch, tmp_path):
    """A duplicate is admitted once and is not an error (data-model §2)."""
    pub, _ = _keygen(tmp_path, "guest")
    p = tmp_path / "guest.pub"
    p.write_text(pub + "\n")
    once = _execute_injection(wiz, monkeypatch, tmp_path, [p])
    twice = _execute_injection(wiz, monkeypatch, tmp_path, [p], initial=once)
    assert once == twice
    assert twice.count(pub) == 1


# --- T060/C29 + T061/C30: the command NAMES must not eat an environment name --


def _invoke(wiz, argv):
    """Drive the real CLI parser. C29 and C30 are both about ARGUMENT ROUTING, so
    calling the command functions directly would bypass the only thing under test."""
    from typer.testing import CliRunner

    return CliRunner().invoke(wiz.app, argv)


def test_an_environment_named_show_is_queryable_and_grantable(wiz, monkeypatch, tmp_path):
    """C29/SC-012/FR-018: `show`, `ls` and `add` all satisfy `validate_name`.

    That is the entire reason `keys` is a group rather than a bare positional: with
    `keys <name>`, an environment called `show` would be permanently unreachable
    through the command that manages it. The spec asks for this exact name to be
    pinned rather than reasoned about, because reasoning is what produced the
    collision in the first place.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    wiz.write_compose_file("local", "show", wiz.build_compose_model("show", "/repo"))
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "observed_admit_set", lambda _h, _n: [pub])

    r = _invoke(wiz, ["keys", "show", "show", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["data"]["environment"] == "show"

    # ...and it can be GRANTED to, which is the half a query-only fix would miss.
    granted: list[str] = []
    monkeypatch.setattr(wiz, "container_running", lambda *_a, **_k: True)
    monkeypatch.setattr(wiz, "detect_runtime", lambda *_a, **_k: "podman")
    monkeypatch.setattr(wiz, "inject_keys", lambda _rt, name, _k: granted.append(name))
    key = tmp_path / "laptop.pub"
    key.write_text(pub + "\n")
    r = _invoke(wiz, ["keys", "add", "show", "--authorized-key", str(key)])
    assert r.exit_code == 0, r.output
    assert granted == ["show"], "an environment named `show` could not be granted to"


def test_environments_named_ls_and_add_are_reachable_too(wiz, monkeypatch):
    """The collision is not special to `show` — every verb in the group is a legal
    environment name, so pinning one of the three would leave the others to rot."""
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda _h: ["docker"])
    monkeypatch.setattr(wiz, "observed_admit_set", lambda _h, _n: [])
    for name in ("ls", "add"):
        wiz.write_compose_file("local", name, wiz.build_compose_model(name, "/repo"))
        r = _invoke(wiz, ["keys", "show", name, "--json"])
        assert r.exit_code == 0, f"{name}: {r.output}"
        assert json.loads(r.stdout)["data"]["environment"] == name


def test_the_old_bare_grant_form_no_longer_grants(wiz, monkeypatch, tmp_path):
    """C30/FR-018: `keys <name> --authorized-key` was the shipped spelling.

    A breaking rename that leaves the old form quietly working is how the break
    goes unnoticed until something depends on both — so the contract is not merely
    that `keys add` works, it is that the OLD form does not grant. Asserted by
    watching `inject_keys`, not by the exit code: a non-zero exit for some
    unrelated reason would pass a test that only read the status.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    key = tmp_path / "laptop.pub"
    key.write_text(pub + "\n")
    granted: list[str] = []
    monkeypatch.setattr(wiz, "container_running", lambda *_a, **_k: True)
    monkeypatch.setattr(wiz, "detect_runtime", lambda *_a, **_k: "podman")
    monkeypatch.setattr(wiz, "inject_keys", lambda _rt, name, _k: granted.append(name))

    r = _invoke(wiz, ["keys", "acme", "--authorized-key", str(key)])
    assert r.exit_code != 0, "the pre-020 spelling still parsed"
    assert granted == [], "the OLD bare form still granted access"

    # And the replacement does, so the assertion above is about the spelling and
    # not about a `keys` group that grants nothing at all.
    r = _invoke(wiz, ["keys", "add", "acme", "--authorized-key", str(key)])
    assert r.exit_code == 0, r.output
    assert granted == ["acme"]


# --- T066/C28/FR-018: inbound and outbound are opposite directions -----------


def test_ssh_key_show_reports_no_admit_set(wiz, monkeypatch, tmp_path, capsys):
    """FR-018: `ssh-key show` reports the agent's OUTBOUND identity and nothing else.

    A do-not-do requirement is satisfied by omission, so nothing notices the
    omission being undone — which is the only reason this test exists. The command
    itself is owned by `test_agent_ssh_key.py`; the CONTRACT is 020's, and this is
    where a reader chasing FR-018 will look.

    Merging "who may log in" into "who this agent logs in AS" is the direction
    confusion the spec avoids everywhere else: one is revoked by editing the
    collection, the other by rotating a key pair, and an operator who conflates
    them rotates the wrong thing during an incident.
    """
    pub, _ = _keygen(tmp_path, "laptop")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "authorized_keys").write_text(pub + "\n")
    wiz.record_agent_ssh_pubkey("local", "acme", "ssh-ed25519 AAAAAGENT agent@acme")

    wiz.do_ssh_key_show("acme", as_json=True)
    payload = json.loads(capsys.readouterr().out)["data"]
    assert payload["agent_ssh_public_key"] == "ssh-ed25519 AAAAAGENT agent@acme"
    assert set(payload) == {"name", "host", "agent_ssh_public_key"}, (
        "ssh-key show grew a field; if it is an admit set, FR-018 forbids it here"
    )

    wiz.do_ssh_key_show("acme", as_json=False)
    human = "".join(capsys.readouterr())
    assert "laptop" not in human, "the ADMIT set leaked into the outbound-identity command"
    for word in ("projected", "observed", "admitting", "agree:"):
        assert word not in human
