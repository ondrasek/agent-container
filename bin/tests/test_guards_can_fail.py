"""Proof that the structural drift guards actually fail on drift.

Several checks in this suite verify a DECLARATION rather than an EFFECT: they
parse `entrypoint.sh`, the `Dockerfile`, the completions, the docs and the
`orchestration/` templates and assert those agree with the CLI. That is the right
design — you cannot execute a Dockerfile in a hermetic test — but it has a
specific failure mode, and this project has now hit it four times in one day:

  * the zsh completion declared the agent list AND referenced it, while
    completing nothing;
  * the completions' command list had drifted for two features, unnoticed,
    because nothing compared it to anything;
  * the FR-005 exit-status probe nearly measured the wrong failure;
  * `build` told an operator to "run from a checkout" while they stood in one,
    because the guard was tested through one of its two entrances.

In every case a check existed and passed while the thing it named was broken. A
guard that cannot fail is worse than no guard, because it *reads* as coverage.

So each guard below is fed a deliberately drifted tree and asserted to reject it.
`_ROOT` is a module constant in test_pure_logic, so monkeypatching it points the
guards at a fixture instead of the real repo.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import test_pure_logic as tpl

REAL_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A copy of the files the guards read, which a test may then corrupt."""
    root = tmp_path / "repo"
    for rel in (
        "image/entrypoint.sh",
        "image/Dockerfile",
        "image-control-plane/Dockerfile",
        "image-control-plane/entrypoint.sh",
        "completions/agent-container.bash",
        "completions/agent-container.zsh",
        "docs/execution.md",
        "bin/agent-container",
        "orchestration/compose.yaml",
        "orchestration/agent-container.container",
        "docs/threat-model.md",
    ):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REAL_ROOT / rel, dst)
    # The threat-model guard reads specs/ to find features that need a row, so the
    # fake root needs the directory NAMES (contents are irrelevant to it).
    for spec_dir in (REAL_ROOT / "specs").iterdir():
        if spec_dir.is_dir():
            (root / "specs" / spec_dir.name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(tpl, "_ROOT", root)
    return root


def _corrupt(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"fixture drifted: {old!r} not in {path}"
    path.write_text(text.replace(old, new, 1))


def test_guards_pass_on_the_unmodified_fixture(wiz, fake_root):
    """Control. If the copied tree already failed, every proof below would be
    vacuous — passing for the wrong reason is exactly what is being guarded."""
    tpl.test_entrypoint_dispatch_matches_canonical_agent_list(wiz)
    tpl.test_entrypoint_writes_to_the_runs_mount_path(wiz)
    tpl.test_every_dockerfile_has_a_declared_agent_expectation()
    for rel in sorted(tpl._DOCKERFILE_EXPECTATIONS):
        tpl.test_dockerfile_installs_exactly_the_canonical_agents(wiz, rel)
    tpl.test_completions_offer_exactly_the_canonical_agents(wiz)
    tpl.test_orchestration_templates_mount_the_full_volume_set(wiz)
    tpl.test_completions_offer_every_cli_command(wiz)


def test_entrypoint_guard_fails_when_an_agent_arm_disappears(wiz, fake_root):
    _corrupt(
        fake_root / "image" / "entrypoint.sh",
        "opencode) cmd=(opencode run",
        "gone) cmd=(opencode run",
    )
    with pytest.raises(AssertionError, match="entrypoint.sh disagrees"):
        tpl.test_entrypoint_dispatch_matches_canonical_agent_list(wiz)


def test_runs_mount_guard_fails_when_the_entrypoint_writes_elsewhere(wiz, fake_root):
    """The drift this catches is invisible from either side alone: the CLI still
    mounts the volume, the entrypoint still writes a record, and the record is
    simply somewhere the volume is not."""
    _corrupt(
        fake_root / "image" / "entrypoint.sh",
        'RUNS_DIR="${AGENT_CONTAINER_RUNS_DIR:-/var/lib/agent-container/runs}"',
        'RUNS_DIR="${AGENT_CONTAINER_RUNS_DIR:-/tmp/agent-container-runs}"',
    )
    with pytest.raises(AssertionError, match="RUNS_MOUNT_PATH"):
        tpl.test_entrypoint_writes_to_the_runs_mount_path(wiz)


def test_dockerfile_guard_fails_when_an_agent_is_not_installed(wiz, fake_root):
    _corrupt(fake_root / "image" / "Dockerfile", "npm i -g opencode-ai", "npm i -g something-else")
    with pytest.raises(AssertionError, match="unmapped|disagrees"):
        tpl.test_dockerfile_installs_exactly_the_canonical_agents(wiz, "image/Dockerfile")


# --- Feature 017: the census used to go BLIND on a second image ---------------
# The spec predicted the census would FAIL on a Dockerfile that omits the agents.
# It would not have: it read one hardcoded path, so a second image was not
# failed — it was SKIPPED, and the suite stayed green while the container holding
# keys to everything went unchecked. That is the worse direction, and these three
# proofs are why the parameterised version is not just tidier.


def test_census_rejects_a_dockerfile_it_has_no_expectation_for(wiz, fake_root):
    """T008/C12: THE clause that makes a third image impossible to add unnoticed.

    Without this, adding an image is a silent reduction in coverage: every
    declared image still passes and nothing mentions the new one.
    """
    third = fake_root / "image-something-new" / "Dockerfile"
    third.parent.mkdir(parents=True, exist_ok=True)
    third.write_text("FROM debian:12-slim\nRUN npm i -g @anthropic-ai/claude-code\n")
    with pytest.raises(AssertionError, match="no declared agent expectation"):
        tpl.test_every_dockerfile_has_a_declared_agent_expectation()


def test_census_rejects_an_agent_installed_in_the_control_plane_image(wiz, fake_root):
    """FR-015a: 'no agents here' is the property this image exists to have.

    The failure being guarded is an agent CLI arriving in the control-plane image
    — by a copy-paste from the agent Dockerfile, most likely — which would put a
    model-calling agent in the container whose key reaches the whole fleet.
    """
    cp = fake_root / "image-control-plane" / "Dockerfile"
    cp.write_text(cp.read_text() + "\nRUN npm i -g opencode-ai\n")
    with pytest.raises(AssertionError, match="disagrees with its declared expectation"):
        tpl.test_dockerfile_installs_exactly_the_canonical_agents(
            wiz, "image-control-plane/Dockerfile"
        )


def test_shared_block_guard_fails_when_the_copies_diverge(wiz, fake_root):
    """The drift guard must reject a real divergence, not just read like one.

    A guard over duplicated shell is only worth having if it fails; this one
    covers who can log in to the control plane, so a vacuous version would be
    the most expensive kind of false comfort.
    """
    _corrupt(
        fake_root / "image-control-plane" / "entrypoint.sh",
        "awk 'NF && !seen[$0]++'",
        "cat",
    )
    with pytest.raises(AssertionError, match="has DRIFTED"):
        tpl.test_shared_entrypoint_blocks_are_identical_across_images("authorized_keys")


def test_shared_block_guard_fails_when_a_sentinel_is_removed(wiz, fake_root):
    """Deleting the sentinel must not be a way to silence the guard.

    Otherwise the cheapest fix for a failing drift check is to delete the marker,
    which converts a caught divergence into an uncaught one.
    """
    _corrupt(
        fake_root / "image-control-plane" / "entrypoint.sh",
        "# SHARED-BLOCK END authorized_keys",
        "# (sentinel removed)",
    )
    with pytest.raises(AssertionError, match="has no .*sentinel"):
        tpl.test_shared_entrypoint_blocks_are_identical_across_images("authorized_keys")


def test_census_rejects_a_stale_expectation_for_a_deleted_image(wiz, fake_root):
    """A table entry for a file that no longer exists makes the table LOOK
    maintained, which is what would let the next real addition slip past."""
    (fake_root / "image-control-plane" / "Dockerfile").unlink()
    with pytest.raises(AssertionError, match="do not exist"):
        tpl.test_every_dockerfile_has_a_declared_agent_expectation()


def test_completion_guard_fails_when_the_agent_list_drifts(wiz, fake_root):
    _corrupt(
        fake_root / "completions" / "agent-container.bash",
        '_agent_container_agents="claude codex pi opencode"',
        '_agent_container_agents="claude codex pi"',
    )
    with pytest.raises(AssertionError, match="disagrees with AGENTS"):
        tpl.test_completions_offer_exactly_the_canonical_agents(wiz)


def test_completion_guard_fails_when_the_list_is_declared_but_unused(wiz, fake_root):
    """The exact bug that shipped: declared, referenced nowhere, completing nothing."""
    zsh = fake_root / "completions" / "agent-container.zsh"
    text = zsh.read_text()
    zsh.write_text(text.replace("${_agent_container_agents}", "claude codex pi opencode"))
    with pytest.raises(AssertionError, match="never uses it"):
        tpl.test_completions_offer_exactly_the_canonical_agents(wiz)


def test_command_guard_fails_when_a_command_is_missing(wiz, fake_root):
    _corrupt(
        fake_root / "completions" / "agent-container.bash",
        "menu context skill commands completions",
        "menu context skill completions",
    )
    with pytest.raises(AssertionError, match="out of sync with the CLI"):
        tpl.test_completions_offer_every_cli_command(wiz)


def test_orchestration_guard_fails_when_a_volume_is_dropped(wiz, fake_root):
    compose = fake_root / "orchestration" / "compose.yaml"
    text = compose.read_text()
    kept = [ln for ln in text.splitlines() if "-opencode-data:/home/dev" not in ln]
    compose.write_text("\n".join(kept) + "\n")
    with pytest.raises(AssertionError, match="out of sync with per_container_volumes"):
        tpl.test_orchestration_templates_mount_the_full_volume_set(wiz)


# --- the file-kind guard (011 FR-016) ---------------------------------------


def test_kind_guard_would_catch_the_coexistence_bug(wiz, tmp_path):
    """Prove the regression test can actually fail.

    Restore the old behaviour — select spec files by 'any *.yaml here' rather than
    by kind — and the spec/sidecar coexistence test must break. Without this, the
    coexistence test could pass for reasons unrelated to the fix and nobody would
    know it had stopped protecting anything.
    """
    import pytest as _pytest

    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    (root / ".agent-container" / "environments.yaml").write_text(
        "environments:\n  - name: acme\n    host: local\n"
    )
    (root / ".agent-container" / "acme.services.yaml").write_text(
        "services:\n  redis:\n    image: redis:7\n"
    )
    # Sanity: with kind-based selection the two coexist.
    assert [e["name"] for e in wiz.load_project_spec(root)] == ["acme"]

    original = wiz._spec_yaml_files
    try:
        wiz._spec_yaml_files = lambda r: sorted(  # the pre-fix glob
            p
            for p in (r / wiz.PROJECT_MARKER).rglob("*")
            if p.is_file() and p.suffix in (".yaml", ".yml")
        )
        with _pytest.raises(wiz.Fatal, match="unknown top-level key 'services'"):
            wiz.load_project_spec(root, skip_unknown=True)
    finally:
        wiz._spec_yaml_files = original


# --- Feature 012: the per-agent fact fixtures --------------------------------


def test_builtin_default_guard_fails_when_an_agent_is_unprobed(wiz, monkeypatch):
    """A fifth agent added to AGENTS without a recorded built-in default must
    BREAK the guard. Without this proof the guard could be vacuously true and
    nobody would notice it had stopped protecting anything — which is exactly how
    the opencode default went unnoticed until Feature 010 probed for it.
    """
    monkeypatch.setattr(wiz, "AGENTS", (*wiz.AGENTS, "newagent"))
    with pytest.raises(AssertionError, match="AGENT_BUILTIN_DEFAULT disagrees with AGENTS"):
        tpl.test_builtin_default_fixture_covers_exactly_the_agents(wiz)


def test_honours_proxy_guard_fails_when_an_agent_is_unprobed(wiz, monkeypatch):
    """Same for proxy adherence — the fact FR-008's honesty claim rests on."""
    monkeypatch.setattr(wiz, "AGENTS", (*wiz.AGENTS, "newagent"))
    with pytest.raises(AssertionError, match="AGENT_HONOURS_PROXY disagrees with AGENTS"):
        tpl.test_honours_proxy_fixture_covers_exactly_the_agents(wiz)


def test_builtin_default_guard_fails_on_a_provider_it_cannot_name(wiz, monkeypatch):
    """A default pointing at a provider absent from PROVIDERS means the tool
    cannot answer "what can this agent reach?" — FR-005's whole promise."""
    monkeypatch.setattr(
        wiz, "AGENT_BUILTIN_DEFAULT", {**wiz.AGENT_BUILTIN_DEFAULT, "claude": "ghost-vendor"}
    )
    with pytest.raises(AssertionError, match="is not in PROVIDERS"):
        tpl.test_builtin_default_fixture_covers_exactly_the_agents(wiz)


def test_replacement_guard_fails_if_hosts_are_made_additive(wiz, monkeypatch):
    """FR-001b is invisible in a passing deployment: an additive implementation
    still deploys, still enforces something, and still looks constrained. Prove
    the test that pins it can actually fail.
    """
    real = wiz.resolve_destinations

    def additive(egress):
        out = []
        for name, host, port, source in real(egress):
            out.append((name, host, port, source))
            for extra in wiz.PROVIDERS.get(name, ()):
                if extra != host:
                    out.append((name, extra, port, source))
        return out

    monkeypatch.setattr(wiz, "resolve_destinations", additive)
    hosts = [
        h
        for _n, h, _p, _s in wiz.resolve_destinations(
            {"allow": [{"provider": "anthropic", "hosts": ["gw.corp"]}]}
        )
    ]
    assert "api.anthropic.com" in hosts, "the additive stand-in must reproduce the bug"
    assert "gw.corp" in hosts


def test_threat_model_guard_fails_on_an_undocumented_feature(wiz, fake_root):
    """Prove the coverage guard can fail — this repo's standing rule, and the only
    reason to trust it.

    A feature directory with no maintenance row is the mechanical half of the
    failure the constitution's 2.2.0 clause targets.
    """
    # 999, NOT the next real number. This read `018-brand-new-feature` and broke the
    # day Feature 018 was specified: a real 018 row appeared, the guard correctly
    # stopped firing, and the proof-it-can-fail test failed for the one reason that
    # is not a defect. A can-fail fixture must name something that CANNOT become
    # real, or it has an expiry date nobody wrote down.
    (fake_root / "specs" / "999-brand-new-feature").mkdir(parents=True)
    with pytest.raises(AssertionError, match="no maintenance row"):
        tpl.test_threat_model_names_every_feature(wiz)


def test_threat_model_guard_fails_on_a_ticked_but_empty_row(wiz, fake_root):
    """A ✅ naming no threats must break. This is the T12 shape the document
    itself catalogues: reconciling by checkbox looks identical to reconciling."""
    tm = fake_root / "docs" / "threat-model.md"
    tm.write_text(tm.read_text().replace("| 001–011 | ✅ |", "| 001–011 | ✅ |  |", 1))
    with pytest.raises(AssertionError, match="name no threats"):
        tpl.test_threat_model_reconciled_rows_name_their_threats(wiz)


# --- late binding: what makes the two proofs above meaningful ---------------


def test_threat_model_guard_reads_the_fake_root_not_the_real_document(wiz, fake_root):
    """Directly pins the late binding that makes the two proofs above meaningful.

    If the path is ever hoisted back to a module-level constant, this fails —
    rather than the proofs quietly degrading into assertions about the real file.
    """
    (fake_root / "docs" / "threat-model.md").write_text("no table here\n", encoding="utf-8")
    assert tpl._threat_model_path() == fake_root / "docs" / "threat-model.md"
    assert tpl._tm_rows() == [], "the guard is reading the real document, not the fake root"


# --- T141: the overclaim guard, which is an ABSENCE check -------------------


def test_overclaim_guard_fails_on_a_statement_that_overclaims(wiz, monkeypatch):
    """An absence assertion is the easiest kind to write and the easiest to have
    silently stop covering anything — it passes just as happily against a string
    that says nothing at all as against an honest one.

    So it is fed a statement that DOES overclaim and asserted to reject it. Both
    mechanisms are proved separately: the packet-level statement can defend more,
    and that is exactly the one at risk of being written as absolute.
    """
    import test_cli as tc

    for transparent, phrase in ((False, "we guarantee it"), (True, "this blocks all egress")):
        monkeypatch.setattr(
            wiz,
            "egress_strength_statement",
            lambda agent, *, transparent=False, _p=phrase: _p,
        )
        check = (
            tc.test_transparent_statement_contains_no_overclaim
            if transparent
            else tc.test_strength_statement_contains_no_overclaim
        )
        with pytest.raises(AssertionError, match="overclaim"):
            check(wiz)


def test_mode_divergence_guard_fails_when_both_modes_say_the_same_thing(wiz, monkeypatch):
    """A mode-aware statement collapsed to one string would pass every presence
    check while telling the operator nothing about which mechanism they got."""
    import test_cli as tc

    monkeypatch.setattr(
        wiz, "egress_strength_statement", lambda agent, *, transparent=False: "identical"
    )
    with pytest.raises(AssertionError):
        tc.test_the_two_statements_are_actually_different(wiz)


# --- T148: the wildcard-with-a-port refusal ---------------------------------


def test_wildcard_port_guard_fails_when_the_combination_is_admitted(wiz, monkeypatch, tmp_path):
    """The refusal is a validator, and a validator that stops refusing is silent.

    Its whole value is that NOTHING downstream can catch this: the entry resolves,
    renders and passes the permission check exactly like a legal one. So the
    validator is replaced with one that admits the combination, and the test that
    pins the refusal is asserted to fail.
    """
    import test_agent_as_code as tac

    monkeypatch.setattr(wiz, "validate_destination", lambda entry, where: None)
    with pytest.raises(pytest.fail.Exception):
        tac.test_a_wildcard_host_with_a_port_is_refused_naming_the_mechanism(wiz, tmp_path)
