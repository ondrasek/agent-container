"""Pytest fixtures for the bin/agent-env suite.

agent-env is a PEP 723 single-file script without a .py extension, so the
suite loads it via SourceFileLoader. Run it with uv; --no-project keeps the run
hermetic (the root pyproject.toml otherwise puts uv in project mode) and the
--with pins mirror the script's own inline metadata:

    uv run --no-project --with pytest \
           --with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' --with 'rich>=13,<15' \
           pytest bin/tests

Every loaded module instance is isolated: HOME and the XDG dirs point into
tmp_path BEFORE exec, because STATE_DIR / CONFIG_DIR / HOSTS_CONF are computed
at import time (part of the on-disk contract). Tests never touch the real
~/.local/state or ~/.config, and never require docker/podman/ssh.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "agent-env"

_counter = itertools.count()


@pytest.fixture
def load_wiz(monkeypatch, tmp_path):
    """Factory that loads a fresh, env-isolated instance of the script.

    Keyword args override where HOME / XDG_STATE_HOME / XDG_CONFIG_HOME point;
    None for an XDG var means "unset" (exercises the $HOME fallback paths).
    """
    created: list[str] = []

    def _load(*, home: Path | None = None,
              xdg_state: Path | None = None,
              xdg_config: Path | None = None):
        if home is None:
            home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        for var, val in (("XDG_STATE_HOME", xdg_state), ("XDG_CONFIG_HOME", xdg_config)):
            if val is None:
                monkeypatch.delenv(var, raising=False)
            else:
                Path(val).mkdir(parents=True, exist_ok=True)
                monkeypatch.setenv(var, str(val))
        # A leaked operator env var must never steer a test.
        for var in ("AGENT_ENV_RUNTIME", "AGENT_ENV_HOST", "AGENT_ENV_USER", "TMUX"):
            monkeypatch.delenv(var, raising=False)

        mod_name = f"_agent_env_under_test_{next(_counter)}"
        loader = SourceFileLoader(mod_name, str(SCRIPT_PATH))
        spec = importlib.util.spec_from_loader(mod_name, loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        loader.exec_module(module)
        created.append(mod_name)
        return module

    yield _load
    for mod_name in created:
        sys.modules.pop(mod_name, None)


@pytest.fixture
def wiz(load_wiz, tmp_path):
    """Default isolated module: XDG state/config under tmp_path."""
    return load_wiz(xdg_state=tmp_path / "xdg-state", xdg_config=tmp_path / "xdg-config")


@pytest.fixture
def fake_bin(tmp_path):
    """Factory for a PATH dir holding fake executables (runtime detection)."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)

    def _add(*names: str) -> Path:
        for name in names:
            exe = bin_dir / name
            exe.write_text("#!/bin/sh\nexit 0\n")
            exe.chmod(0o755)
        return bin_dir

    return _add
