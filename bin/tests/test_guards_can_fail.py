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
    ):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REAL_ROOT / rel, dst)
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
