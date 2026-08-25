"""Pytest fixtures for the bin/agent-container suite.

agent-container is a PEP 723 single-file script without a .py extension, so the
suite loads it via SourceFileLoader. Run it with uv; --no-project keeps the run
hermetic (the root pyproject.toml otherwise puts uv in project mode) and the
--with pins mirror the script's own inline metadata:

    uv run --no-project --with pytest \
           --with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' --with 'rich>=13,<15' \
           --with 'pyyaml>=6,<7' \
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

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "agent-container"

_counter = itertools.count()


def _no_drain(*_args, **_kwargs) -> list[str]:
    """Stand-in for Feature 016's drain_host_records — see `load_wiz`."""
    return []


def _no_capture(*_args, **_kwargs) -> None:
    """Stand-in for Feature 018's capture_host_pubkey — see `load_wiz`.

    Returns None, which the callers must already handle: "nothing captured" is a
    first-class outcome (a deploy warns and continues; an attach with nothing pinned
    refuses or asks). A fake that returned a key would make every deploy test assert
    a pin it never really made.
    """
    return None


@pytest.fixture
def load_wiz(monkeypatch, tmp_path):
    """Factory that loads a fresh, env-isolated instance of the script.

    Keyword args override where HOME / XDG_STATE_HOME / XDG_CONFIG_HOME point;
    None for an XDG var means "unset" (exercises the $HOME fallback paths).
    """
    created: list[str] = []

    def _load(
        *,
        home: Path | None = None,
        xdg_state: Path | None = None,
        xdg_config: Path | None = None,
        xdg_data: Path | None = None,
        own_config: Path | str | None = None,
    ):
        if home is None:
            home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        # XDG_DATA_HOME joined the list with Feature 016's durable run store. A
        # leaked one would point DATA_DIR at the operator's real ~/.local/share and
        # a test would write records there — the docstring's isolation promise has
        # to cover every XDG dir the script reads, not the ones it read first.
        for var, val in (
            ("XDG_STATE_HOME", xdg_state),
            ("XDG_CONFIG_HOME", xdg_config),
            ("XDG_DATA_HOME", xdg_data),
        ):
            if val is None:
                monkeypatch.delenv(var, raising=False)
            else:
                Path(val).mkdir(parents=True, exist_ok=True)
                monkeypatch.setenv(var, str(val))
        # A leaked operator env var must never steer a test.
        for var in (
            "AGENT_CONTAINER_RUNTIME",
            "HCLOUD_TOKEN",
            "AGENT_CONTAINER_HOST",
            "AGENT_CONTAINER_USER",
            # OUTRANKS the XDG vars set above, so a leaked one would point a test
            # at the operator's real config and silently void this fixture's whole
            # isolation promise — the failure mode the XDG_DATA_HOME comment
            # describes, one variable further along.
            "AGENT_CONTAINER_CONFIG_DIR",
            "TMUX",
        ):
            monkeypatch.delenv(var, raising=False)
        # ...and only THEN what a test asks for deliberately. Scrub first, set
        # second: reversing it would have the leak-guard eat the test's own intent,
        # which is a fixture that silently ignores its arguments.
        if own_config is not None:
            monkeypatch.setenv("AGENT_CONTAINER_CONFIG_DIR", str(own_config))

        mod_name = f"_agent_container_under_test_{next(_counter)}"
        loader = SourceFileLoader(mod_name, str(SCRIPT_PATH))
        spec = importlib.util.spec_from_loader(mod_name, loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        loader.exec_module(module)
        # Feature 016: every lifecycle command now drains pending run records
        # before doing its work, and draining reaches the container RUNTIME. This
        # module docstring promises the suite never requires docker or podman, and
        # a test whose `query` fake answers "success" would otherwise let the drain
        # spawn a REAL container from a hermetic test.
        #
        # So it is neutralised in every loaded instance, and the real implementation
        # is kept beside it under a second name: bin/tests/test_run_ingestion.py —
        # the file that owns the drain — puts it back explicitly. That is what stops
        # this from quietly becoming a suite-wide way of never testing it.
        module.real_drain_host_records = module.drain_host_records
        module.drain_host_records = _no_drain
        # Feature 018: the same hazard, one feature later. Capture reads the host
        # public key THROUGH THE RUNTIME on every deploy, and every attach with
        # nothing pinned tries once more — so a hermetic test would either talk to a
        # real daemon or spend the poll window waiting for one that is not there.
        #
        # Neutralised the same way, and kept beside itself under a second name so the
        # files that own capture (test_pure_logic.py, test_shell_integration.py) put
        # the real one back explicitly. Suite-wide stubbing is only safe while
        # SOMETHING still exercises the real thing.
        module.real_capture_host_pubkey = module.capture_host_pubkey
        module.capture_host_pubkey = _no_capture
        created.append(mod_name)
        return module

    yield _load
    for mod_name in created:
        sys.modules.pop(mod_name, None)


@pytest.fixture
def wiz(load_wiz, tmp_path):
    """Default isolated module: XDG state/config/data under tmp_path."""
    return load_wiz(
        xdg_state=tmp_path / "xdg-state",
        xdg_config=tmp_path / "xdg-config",
        xdg_data=tmp_path / "xdg-data",
    )


@pytest.fixture
def make_registry(wiz):
    """Write a hosts.json into the isolated config dir of the `wiz` module.

    Feature 001: gives registry/compose tests a hermetic host registry without
    touching the real ~/.config. Returns the module so callers can also reach
    wiz.load_registry() etc. Pass the registry dict; a minimal valid skeleton is
    filled in when keys are omitted.
    """
    import json as _json

    def _write(reg: dict):
        reg = {"version": 1, "default": None, "hosts": {}, **reg}
        wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        wiz.HOSTS_JSON.write_text(_json.dumps(reg))
        return wiz

    return _write


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
