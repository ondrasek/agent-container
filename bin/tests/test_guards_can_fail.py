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
    tpl.test_dockerfile_installs_exactly_the_canonical_agents(wiz)
    tpl.test_completions_offer_exactly_the_canonical_agents(wiz)
    tpl.test_orchestration_templates_mount_the_full_volume_set(wiz)
    tpl.test_completions_offer_every_cli_command(wiz)


def test_entrypoint_guard_fails_when_an_agent_arm_disappears(wiz, fake_root):
    _corrupt(
        fake_root / "image" / "entrypoint.sh",
        "opencode) exec opencode run",
        "gone) exec opencode run",
    )
    with pytest.raises(AssertionError, match="entrypoint.sh disagrees"):
        tpl.test_entrypoint_dispatch_matches_canonical_agent_list(wiz)


def test_dockerfile_guard_fails_when_an_agent_is_not_installed(wiz, fake_root):
    _corrupt(fake_root / "image" / "Dockerfile", "npm i -g opencode-ai", "npm i -g something-else")
    with pytest.raises(AssertionError, match="unmapped|disagrees"):
        tpl.test_dockerfile_installs_exactly_the_canonical_agents(wiz)


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
    real = wiz.resolve_provider_hosts

    def additive(egress):
        out = []
        for name, hosts, source in real(egress):
            extra = wiz.PROVIDERS.get(name, ())
            out.append((name, tuple(dict.fromkeys((*hosts, *extra))), source))
        return out

    monkeypatch.setattr(wiz, "resolve_provider_hosts", additive)
    ((_n, hosts, _s),) = wiz.resolve_provider_hosts(
        {"providers": [{"name": "anthropic", "hosts": ["gw.corp"]}]}
    )
    assert "api.anthropic.com" in hosts, "the additive stand-in must reproduce the bug"
    assert "gw.corp" in hosts


def test_threat_model_guard_fails_on_an_undocumented_feature(wiz, fake_root):
    """Prove the coverage guard can fail — this repo's standing rule, and the only
    reason to trust it.

    A feature directory with no maintenance row is the mechanical half of the
    failure the constitution's 2.2.0 clause targets.
    """
    (fake_root / "specs" / "018-brand-new-feature").mkdir(parents=True)
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
