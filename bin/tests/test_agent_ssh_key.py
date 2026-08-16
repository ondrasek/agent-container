"""Feature 019: the agent's own SSH key pair.

The headline is an ABSENCE — no private key on the operator's disk — and an
absence is the one thing a passing `git push` never demonstrates. Most of what
follows guards removals rather than behaviour.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOST = {"driver": "docker", "context": ""}


def _entrypoint(wiz) -> str:
    return (Path(wiz.__file__).parents[1] / "image" / "entrypoint.sh").read_text()


# --- the conventional path is the design ------------------------------------


def test_the_key_lives_at_the_conventional_identity_path(wiz):
    """Not a tool-specific filename: being conventional is what makes git, ssh, scp
    and rsync all use it with no wiring — which is why core.sshCommand and its
    scaffolding are deleted rather than rewired."""
    assert wiz.CONTAINER_AGENT_SSH_KEY == "/home/dev/.ssh/id_ed25519"


def test_the_scaffolding_is_DELETED_not_rewired(wiz):
    """T008. Read over EXECUTABLE lines only: the entrypoint still names the removed
    channels in a comment explaining why they went, and an unexplained removal is how
    a channel gets quietly reinstated by someone who never learns what it cost."""
    code = [
        ln for ln in _entrypoint(wiz).splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    ]
    for gone in ("PUSH_RUNTIME", "core.sshCommand", "SSH_PUSH_KEY_B64", "push_ed25519_key"):
        assert not any(gone in ln for ln in code), gone
    assert any('AGENT_KEY="${SSH_DIR}/id_ed25519"' in ln for ln in code)
    assert any("ssh-keygen" in ln and "${AGENT_KEY}" in ln for ln in code)


def test_the_entrypoint_generates_only_when_absent(wiz):
    """T004. Regenerating each boot would silently invalidate the operator's
    registration while every other symptom looked healthy — surfacing days later as a
    push that stopped working."""
    entry = _entrypoint(wiz)
    block = entry[entry.index('AGENT_KEY="${SSH_DIR}/id_ed25519"') :][:1200]
    assert "! -" + 'f "${AGENT_KEY}"' in block  # generate only when the file is absent
    assert "already present, keeping it" in block


def test_generation_failure_is_fatal_and_loud(wiz):
    """T010a/FR-008. `ssh-keygen` can fail on a full or read-only volume, and a
    container that starts, cannot authenticate anywhere, and says nothing is the worst
    outcome: the agent meets it hours later as an inexplicable permission denied."""
    entry = _entrypoint(wiz)
    block = entry[entry.index('log "generating the agent SSH key') :][:600]
    assert "die " in block
    assert "unable to authenticate anywhere" in block


# --- the ssh_config block: appended if the BLOCK is absent -------------------


def test_the_config_block_is_explicit(wiz):
    """The operator's call: state the settings rather than lean on ssh's defaults, so
    the config documents what the identity IS and survives a change in ssh's search
    order. IdentitiesOnly earns its keep the moment a second key exists."""
    entry = _entrypoint(wiz)
    block = entry[entry.index("# BEGIN agent-container (managed") :][:400]
    for line in (
        "IdentityFile",
        "IdentitiesOnly yes",
        "UserKnownHostsFile",
        "StrictHostKeyChecking accept-new",
    ):
        assert line in block, line


def test_the_block_is_keyed_on_the_BLOCK_not_the_file(wiz):
    """T010, the case that matters. "Write the file only if absent" would leave a
    config the agent created first — for a jump host — without StrictHostKeyChecking,
    so every ssh it attempted would hang on a prompt it cannot answer."""
    entry = _entrypoint(wiz)
    block = entry[entry.index('SSH_CONFIG="${SSH_DIR}/config"') :][:300]
    assert "'^# BEGIN agent-container'" in block  # the BLOCK, not the file
    assert ">>" in block  # appended, never truncating


# --- every supplying channel is gone ----------------------------------------


def test_no_private_key_channel_survives(wiz):
    """T012, the census. The failure mode is ONE channel surviving, which is
    indistinguishable from a complete removal by every other test here."""
    src = Path(wiz.__file__).read_text()
    assert "INJECT_PUSH_KEY_PATH" not in src
    assert "clone_credential_precheck" not in src
    assert "push_key" not in wiz.CRED_SSH_TARGETS
    # stage_push_injection survives, but only for known_hosts — the FORGE direction.
    assert wiz.stage_push_injection("local", "acme", None) == []


def test_the_census_guard_can_fail(wiz):
    reintroduced = 'INJECT_PUSH_KEY_PATH = "/run/agent-container/push_key"'
    assert "INJECT_PUSH_KEY_PATH" in reintroduced  # the guard's predicate does fire


@pytest.mark.parametrize("source", ["up --push-key", "redeploy --push-key"])
def test_each_removed_flag_explains_itself(wiz, source):
    """A bare "no such option" would be a regression rather than a removal: the
    operator who used the flag had a reason, and it is now served without a private
    key on their disk."""
    with pytest.raises(wiz.Fatal) as e:
        wiz.refuse_removed_push_key(source)
    msg = str(e.value)
    assert "generated INSIDE the container" in msg
    assert "ssh-key show" in msg  # names the replacement, not just the removal


def test_a_declared_push_key_is_refused_not_ignored(wiz):
    with pytest.raises(wiz.Fatal, match="generated INSIDE the container"):
        wiz.validate_credential(
            {"name": "K", "source": "file", "path": "/k", "target": "push_key"}, "spec.yaml"
        )


def test_a_stale_staged_key_is_removed_and_reported(wiz, capsys):
    """FR-009: `--purge` never removed this file, so merely ceasing to write it would
    leave the exposure on every machine that used the flag."""
    stale = wiz.host_state_dir("local") / "acme.push_key"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    wiz.remove_stale_staged_push_key("local", "acme")
    assert not stale.exists()
    err = capsys.readouterr().err
    assert "removed a PRIVATE SSH key" in err
    assert "treat it as exposed" in err  # copies may exist elsewhere


# --- exposure of the public half --------------------------------------------


def test_show_reads_local_state_and_never_the_daemon(wiz, monkeypatch):
    """FR-005: a stopped environment or an unreachable host is exactly when an
    operator needs the key, so a lookup requiring reachability fails in the one case
    it exists for."""
    wiz.record_agent_ssh_pubkey("local", "acme", "ssh-ed25519 AAAA agent")

    def explode(*_a, **_kw):
        raise AssertionError("consulted the runtime for a value held locally")

    monkeypatch.setattr(wiz, "query", explode)
    assert wiz.read_agent_ssh_pubkey("local", "acme") == "ssh-ed25519 AAAA agent"


def test_the_list_row_carries_the_public_key(wiz):
    """FR-004. The task for this was marked done while the row builder never gained
    the field — `ssh-key show` worked, so every hand-check passed and only a consumer
    of `list --json` would have found the hole."""
    wiz.record_agent_ssh_pubkey("local", "acme", "ssh-ed25519 AAAA agent")
    row = {"name": f"{wiz.CONTAINER_PREFIX}acme", "host": "local"}
    assert wiz.row_agent_ssh_public_key(row) == "ssh-ed25519 AAAA agent"


def test_an_uncaptured_list_row_is_null_not_empty(wiz):
    """`None`, never `""` — a consumer must be able to tell *never captured* from a
    captured value, and an empty string reads as a key that happens to be blank."""
    row = {"name": f"{wiz.CONTAINER_PREFIX}never", "host": "local"}
    assert wiz.row_agent_ssh_public_key(row) is None
    assert wiz.row_agent_ssh_public_key({"name": "not-ours", "host": "local"}) is None


def test_show_is_explicit_when_nothing_was_captured(wiz):
    """Never a silent empty result — "no key" and "not captured" are different, and
    only one of them is fixed by deploying."""
    with pytest.raises(wiz.Fatal, match="no agent SSH key captured"):
        wiz.do_ssh_key_show("acme", False)


def test_show_json_carries_null_rather_than_an_empty_string(wiz, capsys):
    wiz.do_ssh_key_show("acme", True)
    assert json.loads(capsys.readouterr().out)["data"]["agent_ssh_public_key"] is None


# --- the probe: in-container, --repo only, fails soft ------------------------


def test_the_probe_targets_only_the_repo_host(wiz, monkeypatch):
    """R8: defaulting to github.com would invent a fact — an agent whose only SSH use
    is a self-hosted forge would be told "not registered" about a host it never
    contacts — and would manufacture an egress requirement."""
    monkeypatch.setattr(wiz, "query", lambda *a, **k: pytest.fail("probed with no repo"))
    assert wiz.ssh_probe_registration(HOST, "acme", None) == "unknown"
    assert wiz.ssh_probe_registration(HOST, "acme", "https://github.com/x/y.git") == "unknown"


def test_the_probe_fails_SOFT(wiz, monkeypatch):
    """FR-011: denied egress (Feature 012), offline, or a forge outage is `unknown` —
    never `not-registered`, and never a reason to fail a deploy."""

    def boom(*_a, **_kw):
        raise OSError("no route to host")

    monkeypatch.setattr(wiz, "query", boom)
    assert wiz.ssh_probe_registration(HOST, "acme", "git@github.com:x/y.git") == "unknown"


@pytest.mark.parametrize(
    ("blob", "expect"),
    [
        ("Hi you! You've successfully authenticated", "registered"),
        ("does not provide shell access", "registered"),
        ("git@github.com: Permission denied (publickey).", "not-registered"),
        ("something else entirely", "unknown"),
    ],
)
def test_the_probe_classifies_the_forge_reply(wiz, monkeypatch, blob, expect):
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 1, "", blob))
    assert wiz.ssh_probe_registration(HOST, "acme", "git@github.com:x/y.git") == expect


def test_the_probe_is_bounded(wiz):
    """Unbounded, "fails soft" would be meaningless because it would never return."""
    assert wiz.PROBE_TIMEOUT == 10.0


def test_an_unreachable_forge_still_ANNOUNCES(wiz, monkeypatch, capsys):
    """T037. Asserting only that the deploy survived would pass for a build that says
    nothing at all — which is the failure this requirement exists to prevent, since the
    operator then never learns there is a key to register."""

    def boom(*_a, **_kw):
        raise OSError("no route to host")

    monkeypatch.setattr(wiz, "query", boom)
    wiz.announce_agent_ssh_key(HOST, "acme", "ssh-ed25519 AAAA agent", "git@github.com:x/y.git")
    err = capsys.readouterr().err
    assert "could NOT be confirmed" in err  # unknown, stated — not silence
    assert "ssh-ed25519 AAAA agent" in err  # and the line to register


def test_a_registered_key_stops_the_nagging(wiz, monkeypatch, capsys):
    """FR-011: a warning that never stops is a warning nobody reads, and the operator
    who did register would learn to ignore the one that matters."""
    monkeypatch.setattr(
        wiz,
        "query",
        lambda *a, **k: subprocess.CompletedProcess([], 1, "", "successfully authenticated"),
    )
    wiz.announce_agent_ssh_key(HOST, "acme", "ssh-ed25519 AAAA agent", "git@github.com:x/y.git")
    assert capsys.readouterr().err == ""


# --- the destructive reactions, forbidden in words ---------------------------


def test_the_pending_report_forbids_the_teardown(wiz):
    """T045, on the WORDING. The exit code is the thing that *causes* the wrong
    reaction — a caller reading only the status tears the environment down, destroying
    the key it was about to register — so it cannot also be the thing that prevents it."""
    src = Path(wiz.__file__).read_text()
    block = src[src.index("the workspace was NOT cloned") :][:700]
    assert "DO NOT tear this environment down" in block
    assert "redeploy" in block  # names the recovery, not only the hazard
    assert "ssh-key show" in block


def test_purge_says_the_registration_is_dead(wiz):
    """T049/FR-007. The key rides the `ssh` volume, so a purge rotates it; nothing else
    in that output says so, and the operator would otherwise learn it from a push that
    stopped working against a forge entry naming a key that no longer exists."""
    src = Path(wiz.__file__).read_text()
    block = src[src.index("purged volumes: ") :][:800]
    assert "generates a NEW one" in block
    assert "now dead" in block
    assert "ssh-key show" in block


# --- exit codes --------------------------------------------------------------


def test_the_pending_code_is_distinct(wiz):
    assert wiz.EXIT_PENDING_REGISTRATION == 3
    assert (
        len({wiz.EXIT_OK, wiz.EXIT_FAILURE, wiz.EXIT_REFUSED, wiz.EXIT_PENDING_REGISTRATION}) == 4
    )


def test_the_documented_codes_ARE_the_enforced_ones(wiz):
    """T054b. A number in prose drifting from the number in code is this project's
    recurring defect, and an automated caller branching on a stale value fails
    silently — so --help is BUILT from the constants rather than restating them."""
    epilog = wiz.app.info.epilog
    for code, _desc in wiz.EXIT_CODES:
        assert str(code) in epilog
    assert "shared" in epilog.lower()  # the 2-is-ambiguous caveat
    assert "--foreground" in epilog  # the headless caveat


def test_pending_clone_url_tolerates_a_runtime_with_no_stdout(wiz, monkeypatch):
    """The bug the suite caught: this runs on EVERY deploy, and a runtime returning no
    stdout must not crash a deployment that otherwise succeeded."""
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 0, None, ""))
    assert wiz.clone_pending_url(HOST, "acme") is None
