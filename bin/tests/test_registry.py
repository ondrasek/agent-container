"""Host registry (Feature 001) tests: hosts.json is the single source of truth
for WHERE containers run. These pin its read/write/round-trip behavior, the
atomic write, the malformed-file failure, and the read-only legacy hosts.conf
synthesis. The registry content is data, never executed.
"""

from __future__ import annotations

import json

import pytest


def test_absent_registry_and_absent_hostsconf_is_empty(wiz):
    reg = wiz.load_registry()
    assert wiz.registry_hosts(reg) == {}
    assert wiz.default_host_name(reg) is None


def test_save_then_load_round_trip(wiz):
    reg = {
        "version": 1,
        "default": "local",
        "hosts": {
            "local": {
                "driver": "docker",
                "context": "lima",
                "address": "localhost",
                "provisioning": None,
                "created_by_tool": False,
            }
        },
    }
    wiz.save_registry(reg)
    assert wiz.HOSTS_JSON.is_file()
    loaded = wiz.load_registry()
    assert loaded == reg
    assert wiz.get_host(loaded, "local")["context"] == "lima"
    assert wiz.default_host_name(loaded) == "local"


def test_save_is_atomic_leaves_no_tmp(wiz):
    wiz.save_registry({"version": 1, "default": None, "hosts": {}})
    leftovers = list(wiz.CONFIG_DIR.glob("hosts.json*.tmp")) + list(wiz.CONFIG_DIR.glob("*.tmp"))
    assert leftovers == []


def test_save_trailing_newline(wiz):
    wiz.save_registry({"version": 1, "default": None, "hosts": {}})
    assert wiz.HOSTS_JSON.read_text().endswith("\n")


def test_malformed_registry_dies(wiz):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_JSON.write_text("{ not json ")
    with pytest.raises(wiz.Fatal):
        wiz.load_registry()


def test_registry_missing_hosts_key_dies(wiz):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_JSON.write_text(json.dumps({"version": 1}))
    with pytest.raises(wiz.Fatal):
        wiz.load_registry()


def test_registry_defaults_are_filled(wiz):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_JSON.write_text(json.dumps({"hosts": {}}))
    reg = wiz.load_registry()
    assert reg["version"] == wiz.REGISTRY_VERSION
    assert reg["default"] is None


def test_legacy_hostsconf_synthesized_when_no_json(wiz):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_CONF.write_text("MY_BOX_HOST=vps.example.com\nMY_BOX_PORT=2222\n")
    reg = wiz.load_registry()
    host = wiz.get_host(reg, "my_box")
    assert host is not None
    assert host["driver"] == "existing-ssh"
    assert host["address"] == "vps.example.com"
    assert host["port"] == "2222"
    assert host["created_by_tool"] is False


def test_legacy_incomplete_pair_skipped(wiz):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_CONF.write_text("SOLO_HOST=only-host-no-port\n")
    reg = wiz.load_registry()
    assert wiz.registry_hosts(reg) == {}


def test_json_wins_over_legacy_hostsconf(wiz):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    wiz.HOSTS_CONF.write_text("OLD_HOST=legacy\nOLD_PORT=2222\n")
    wiz.save_registry({"version": 1, "default": "local", "hosts": {"local": {"driver": "docker"}}})
    reg = wiz.load_registry()
    assert "old" not in wiz.registry_hosts(reg)
    assert "local" in wiz.registry_hosts(reg)


@pytest.mark.parametrize("using_fixture", [True])
def test_make_registry_fixture(make_registry, using_fixture):
    mod = make_registry({"default": "hz1", "hosts": {"hz1": {"driver": "docker"}}})
    reg = mod.load_registry()
    assert mod.default_host_name(reg) == "hz1"
