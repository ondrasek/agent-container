"""Feature 019: the agent's own SSH key pair.

The headline is an ABSENCE — no private key on the operator's disk — and an
absence is the one thing a passing `git push` never demonstrates. Most of what
follows guards removals rather than behaviour.
"""

from __future__ import annotations

import contextlib
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
    with pytest.raises(wiz.Fatal) as e:
        wiz.validate_credential(
            {"name": "K", "source": "file", "path": "/k", "target": "push_key"}, "spec.yaml"
        )
    assert "generated INSIDE the container" in str(e.value)
    # Not "drop the flag": there is no flag here, and the last line of a refusal is
    # the line the operator acts on — naming something they are not looking at sends
    # them hunting through their shell history instead of their spec file.
    assert "Remove this credential from the spec." in str(e.value)
    assert "Drop the flag" not in str(e.value)


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


def test_show_ends_the_line(wiz, capsys):
    """`$(...)` strips it either way, but without it a terminal glues the prompt onto
    the end of the key the operator is about to copy."""
    wiz.record_agent_ssh_pubkey("local", "acme", "ssh-ed25519 AAAA agent")
    wiz.do_ssh_key_show("acme", False)
    assert capsys.readouterr().out == "ssh-ed25519 AAAA agent\n"


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


def test_the_recovery_COMMAND_IS_THE_ONE_THAT_WORKS(wiz, monkeypatch, capsys):
    """The defect a real container found, fixed where it belonged.

    `redeploy <name>` used to start from an empty ExecSpec, so it set no clone URL and
    this recovery did nothing — an empty workspace and silence, at the end of the one
    instruction the message exists to give. Naming `--repo` in the message papered
    over that; `redeploy` now INHERITS the URL, so the command an operator would
    naturally type is the command that works.

    Asserted on both halves, because either alone can pass while the pair is broken:
    the message names a bare redeploy, AND a bare redeploy keeps the repo.
    """
    src = Path(wiz.__file__).read_text()
    block = src[src.index("the workspace was NOT cloned") :][:900]
    assert "redeploy {name}{hflag}\\n" in block  # bare — no --repo appended
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"repo": "git@forge:o/r.git"})
    spec = wiz.ExecSpec()
    assert _redeploy_repo(wiz, monkeypatch, spec) == "git@forge:o/r.git"


def _redeploy_repo(wiz, monkeypatch, spec, drop_repo=False, inherit=None):
    """Run only do_redeploy's inheritance step and report the resulting spec.repo.

    Everything after it recreates a container, so the deploy is cut off at the lock —
    the alternative is a test that needs a runtime to assert a pure decision.
    """
    monkeypatch.setattr(wiz, "migrate_flat_state", lambda: None)
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda _h: ("local", HOST))
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda _h: None)
    monkeypatch.setattr(wiz, "drain_host_records", lambda *_a: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda *_a, **_k: [wiz.container_name("acme")])
    monkeypatch.setattr(wiz, "refuse_superseded_layout", lambda _n: None)

    class Stop(Exception):
        pass

    def stop(*_a, **_kw):
        raise Stop

    monkeypatch.setattr(wiz, "_resolve_env_files", stop)
    # Mirrors the CLI: what the operator did NOT type is what may be inherited.
    kw = {"inherit": wiz.INHERITABLE if inherit is None else inherit}
    with contextlib.suppress(Stop, wiz.Fatal):
        wiz.do_redeploy("acme", spec=spec, drop_repo=drop_repo, **kw)
    return spec.repo


def test_redeploy_KEEPS_the_repo_by_default(wiz, monkeypatch, capsys):
    """A bare redeploy reads as "the same thing, rebuilt" and now is: silently unsetting
    the clone URL was a change the invocation did not look like it was making."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"repo": "git@forge:o/r.git"})
    assert _redeploy_repo(wiz, monkeypatch, wiz.ExecSpec()) == "git@forge:o/r.git"
    # Said out loud, and the line names its own opt-out: an inherited value the
    # operator never typed is infuriating to debug when it is the wrong one.
    err = capsys.readouterr().err
    assert "keeping --repo git@forge:o/r.git" in err
    assert "--no-repo" in err


def test_an_explicit_repo_WINS_over_the_inherited_one(wiz, monkeypatch):
    """Inheritance must not defeat the flag — `redeploy --repo` is how you CHANGE it.

    A typed field is excluded from `inherit`, exactly as the CLI computes it. That the
    exclusion is the whole mechanism is why the parameter defaults to inheriting
    NOTHING: a caller that forgets would overwrite what the operator just typed."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"repo": "git@forge:old.git"})
    spec = wiz.ExecSpec(repo="git@forge:new.git")
    typed = wiz.INHERITABLE - {"repo"}
    assert _redeploy_repo(wiz, monkeypatch, spec, inherit=typed) == "git@forge:new.git"


def test_inheriting_NOTHING_is_the_default(wiz, monkeypatch):
    """The unsafe direction must be asked for: a caller that does not work out which
    fields were typed gets the old behaviour, not silent clobbering."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"repo": "git@forge:o/r.git"})
    assert _redeploy_repo(wiz, monkeypatch, wiz.ExecSpec(), inherit=frozenset()) is None


def test_no_repo_DROPS_it(wiz, monkeypatch, capsys):
    """Opting out has to be possible or inheritance becomes a trap: an operator
    clearing a workspace would have it re-cloned under them."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"repo": "git@forge:o/r.git"})
    assert _redeploy_repo(wiz, monkeypatch, wiz.ExecSpec(), drop_repo=True) is None
    assert "keeping --repo" not in capsys.readouterr().err  # and silent about it


def test_nothing_to_inherit_is_not_an_error(wiz, monkeypatch):
    """An unreachable or absent container yields None, and a redeploy that CREATES the
    environment fresh has nothing to carry over — neither is a failure."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: None)
    assert _redeploy_repo(wiz, monkeypatch, wiz.ExecSpec()) is None
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"repo": None})
    assert _redeploy_repo(wiz, monkeypatch, wiz.ExecSpec()) is None


def _func_body(src: str, name: str) -> str:
    """A function's source, sliced to the next top-level `def` rather than a fixed
    character count — a magic window silently shrinks the assertion every time the
    code grows, which has already cost this suite two false failures."""
    i = src.index(f"\ndef {name}(")
    j = src.index("\ndef ", i + 1)
    return src[i:j]


def test_repo_and_no_repo_together_are_REFUSED(wiz):
    """Contradictory rather than redundant. Resolving it by precedence gets it wrong
    half the time, and on the half where the operator wanted the repo gone, keeping it
    re-clones into the workspace they were clearing."""
    body = _func_body(Path(wiz.__file__).read_text(), "redeploy")
    assert '"--no-repo"' in body
    assert "mutually exclusive" in body


def _redeploy_spec(wiz, monkeypatch, spec, inherit=None, mounts=None):
    """As _redeploy_repo, but hands back the whole spec after the inheritance step."""
    monkeypatch.setattr(wiz, "live_workspace", lambda *_a: mounts if mounts is not None else None)
    _redeploy_repo(wiz, monkeypatch, spec, inherit=inherit)
    return spec


def test_mode_and_agent_are_inherited(wiz, monkeypatch):
    """The same silent reset as the repo, and louder in its consequences: a bare
    redeploy of a headless codex environment came back interactive claude, so a
    long-running job was replaced by an idle shell running a different agent."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"mode": "headless", "agent": "codex"})
    spec = _redeploy_spec(wiz, monkeypatch, wiz.ExecSpec())
    assert (spec.mode, spec.agent) == ("headless", "codex")


def test_the_workspace_is_read_from_the_MOUNTS(wiz, monkeypatch):
    """Not from an env marker: the mounts ARE the workspace mode, and every container
    that already exists predates any marker we could start writing now — inferring
    from one would silently reset every environment deployed before this release,
    which is the exact defect this change is fixing."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {})
    spec = _redeploy_spec(wiz, monkeypatch, wiz.ExecSpec(), mounts=("ephemeral", None))
    assert spec.workspace == "ephemeral"


def test_a_bind_workspace_carries_its_directory(wiz, monkeypatch):
    """Inheriting `bind` without the dir would die on `--workspace bind requires
    --workspace-dir` — a redeploy that refuses itself."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {})
    spec = _redeploy_spec(wiz, monkeypatch, wiz.ExecSpec(), mounts=("bind", "/src/proj"))
    assert (spec.workspace, spec.workspace_dir) == ("bind", "/src/proj")


@pytest.mark.parametrize(
    ("mounts", "expect"),
    [
        ([{"Destination": "/workspace", "Type": "volume"}], ("persistent", None)),
        ([{"Destination": "/workspace", "Type": "bind", "Source": "/s"}], ("bind", "/s")),
        ([{"Destination": "/home/dev/.ssh", "Type": "volume"}], ("ephemeral", None)),
        ([], ("ephemeral", None)),
    ],
)
def test_live_workspace_reads_the_three_modes(wiz, monkeypatch, mounts, expect):
    monkeypatch.setattr(
        wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 0, json.dumps(mounts), "")
    )
    assert wiz.live_workspace(HOST, "acme") == expect


def test_an_unreadable_container_yields_no_workspace(wiz, monkeypatch):
    """None, not a guess — and None leaves the default, which is the pre-inheritance
    behaviour rather than a wrong claim about what the environment was."""
    monkeypatch.setattr(
        wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 1, "", "no such object")
    )
    assert wiz.live_workspace(HOST, "acme") is None


def test_the_TASK_is_never_inherited(wiz):
    """A task is a one-shot INSTRUCTION, not deployment state. Re-executing a headless
    job on every rebuild is the kind of surprise that rewrites files or opens pull
    requests nobody asked for — and unlike the other fields, repeating it has EFFECTS
    rather than just a wrong setting."""
    assert "task" not in wiz.INHERITABLE


def test_FOREGROUND_is_never_inherited(wiz):
    """It describes this invocation's terminal, not the environment. Inherited, a
    detached redeploy would block on a stream nobody is watching."""
    assert "foreground" not in wiz.INHERITABLE


def test_foreground_is_validated_AFTER_inheritance(wiz, monkeypatch):
    """`--foreground` is headless-only, and the mode it must agree with may be the one
    being inherited. Validating first would reject `redeploy --foreground` on a
    headless environment — legal, and the obvious thing to type."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"mode": "headless"})
    spec = _redeploy_spec(wiz, monkeypatch, wiz.ExecSpec(foreground=True))
    assert spec.mode == "headless"
    spec.validate()  # no Fatal: the inherited mode satisfies the guard


def test_an_inherited_value_still_has_to_be_VALID(wiz, monkeypatch):
    """A container carrying a mode this build no longer supports must fail loudly
    rather than be waved through for having come from the runtime instead of a flag."""
    monkeypatch.setattr(wiz, "env_live_config", lambda *_a: {"mode": "bogus"})
    spec = _redeploy_spec(wiz, monkeypatch, wiz.ExecSpec())
    with pytest.raises(wiz.Fatal, match="--mode must be one of"):
        spec.validate()


def test_the_kept_line_lists_only_what_DIFFERS(wiz, monkeypatch, capsys):
    """Naming a field already at its default says nothing, and a line that reports
    four unchanged settings on every redeploy is one nobody reads."""
    monkeypatch.setattr(
        wiz, "env_live_config", lambda *_a: {"mode": "interactive", "agent": "codex"}
    )
    _redeploy_spec(wiz, monkeypatch, wiz.ExecSpec(), mounts=("persistent", None))
    err = capsys.readouterr().err
    assert "--agent codex" in err
    assert "--mode" not in err  # already the default
    assert "--workspace" not in err  # already the default


def test_the_declarative_path_cannot_inherit(wiz):
    """`apply` must stay authoritative: a spec that declares no repo means NO repo, and
    an inherited one would let a DELETED declaration keep taking effect. Structural,
    because the protection is that the declarative path never reaches do_redeploy at
    all — it deploys through do_up, whose spec is the file."""
    src = Path(wiz.__file__).read_text()
    assert src.count("do_redeploy(") == 2  # the definition and the ONE CLI caller
    assert "do_redeploy(" not in _func_body(src, "do_aac_apply")
    assert "do_up(" in _func_body(src, "do_aac_apply")


def test_the_pending_report_forbids_the_teardown(wiz):
    """T045, on the WORDING. The exit code is the thing that *causes* the wrong
    reaction — a caller reading only the status tears the environment down, destroying
    the key it was about to register — so it cannot also be the thing that prevents it."""
    src = Path(wiz.__file__).read_text()
    block = src[src.index("the workspace was NOT cloned") :][:1400]
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


# --- the clone must DECIDE before we report on it ----------------------------


def test_a_clone_still_running_is_not_reported_as_finished(wiz, monkeypatch):
    """The defect a full acceptance run found. We reach the container as soon as the
    public key exists, and the entrypoint generates that key well BEFORE it clones —
    so reading "no pending file" straight through reported a successful deploy over a
    clone that had not happened. Measured: exit 0 with an empty workspace, silently."""
    calls = []

    def undecided_then_pending(argv, **_kw):
        calls.append(argv)
        if len(calls) < 3:
            return subprocess.CompletedProcess(argv, 1, "", "")  # not decided yet
        return subprocess.CompletedProcess(argv, 0, "git@forge:o/r.git\n", "")

    monkeypatch.setattr(wiz, "query", undecided_then_pending)
    monkeypatch.setattr(wiz.time, "sleep", lambda _s: None)
    assert wiz.clone_pending_url(HOST, "acme") == "git@forge:o/r.git"
    assert len(calls) == 3, "gave up on the first undecided answer"


def test_a_finished_clone_returns_at_once(wiz, monkeypatch):
    """Exit 3 is the entrypoint's positive `.clone_done` signal — a decided answer, so
    there is nothing to wait for and a healthy deploy pays nothing."""
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 3, "", ""))
    monkeypatch.setattr(wiz.time, "sleep", lambda _s: pytest.fail("waited on a decided clone"))
    assert wiz.clone_pending_url(HOST, "acme") is None


def test_an_UNDECIDED_clone_says_nothing_rather_than_guessing(wiz, monkeypatch):
    """The deliberate asymmetry. This answer drives a non-zero exit whose documented
    remedy an automated caller can get catastrophically wrong — tearing the
    environment down destroys the key — so a slow-but-healthy clone must never be
    reported as pending. Declining costs a missed warning; guessing costs the key."""
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 1, "", ""))
    monkeypatch.setattr(wiz.time, "sleep", lambda _s: None)
    ticks = iter([0.0] + [wiz.CLONE_RESOLVE_TIMEOUT + 1] * 20)
    monkeypatch.setattr(wiz.time, "monotonic", lambda: next(ticks))
    assert wiz.clone_pending_url(HOST, "acme") is None


def test_the_wait_is_bounded(wiz):
    """Unbounded, a deploy against a hanging forge would never return — and the whole
    point of the pending state is that the operator gets a usable container."""
    assert wiz.CLONE_RESOLVE_TIMEOUT == 10.0


def test_pending_clone_url_tolerates_a_runtime_with_no_stdout(wiz, monkeypatch):
    """The bug the suite caught: this runs on EVERY deploy, and a runtime returning no
    stdout must not crash a deployment that otherwise succeeded."""
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess([], 0, None, ""))
    assert wiz.clone_pending_url(HOST, "acme") is None
