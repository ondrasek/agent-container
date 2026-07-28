"""Agent credentialing (Feature 003) unit tests — hermetic, no live runtime.

Covers the foundational injected-material staging + the US1 outbound push
credential: staging is ephemeral (targets under /run, never a persistent volume,
FR-012), fail-fast on a missing source (FR-016), the compose model carries the
material as `configs` with no secret value inlined (FR-011), and the outbound
push key is a DISTINCT credential from the inbound host key (SC-008). Real-
container push behavior is the acceptance tier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _key(tmp_path: Path, name: str = "push") -> Path:
    f = tmp_path / name
    f.write_bytes(
        b"-----BEGIN OPENSSH PRIVATE KEY-----\nFAKEKEYBYTES\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    return f


# --- foundational staging (T004) ---------------------------------------------


def test_stage_push_injection_stages_ephemeral_entries(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    pk = _key(tmp_path)
    kh = tmp_path / "known_hosts"
    kh.write_text("github.com ssh-ed25519 AAAA\n")
    entries = wiz.stage_push_injection("local", "acme", pk, kh)
    by_name = {e[0]: e for e in entries}
    # both present, targeting the EPHEMERAL /run paths (never a volume)
    assert (
        by_name["push_key"][2]
        == wiz.INJECT_PUSH_KEY_PATH
        == "/run/agent-container/push_ed25519_key"
    )
    assert by_name["known_hosts"][2] == wiz.INJECT_KNOWN_HOSTS_PATH
    # staged locally under the per-host state dir, byte-identical, 0644 (state dir 0700)
    staged = by_name["push_key"][1]
    assert staged == wiz.host_state_dir("local") / "acme.push_key"
    assert staged.read_bytes() == pk.read_bytes()
    assert (staged.stat().st_mode & 0o777) == 0o644
    assert (wiz.host_state_dir("local").stat().st_mode & 0o777) == 0o700


def test_stage_push_injection_none_returns_empty(wiz):
    assert wiz.stage_push_injection("local", "acme", None, None) == []


def test_stage_push_injection_missing_key_dies(wiz, tmp_path):
    with pytest.raises(wiz.Fatal, match="--push-key"):
        wiz.stage_push_injection("local", "acme", tmp_path / "nope", None)


def test_stage_push_injection_missing_known_hosts_dies(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    with pytest.raises(wiz.Fatal, match="--known-hosts"):
        wiz.stage_push_injection("local", "acme", _key(tmp_path), tmp_path / "nope")


def test_stage_push_injection_validates_key(wiz, monkeypatch, tmp_path):
    def _reject(p):
        raise wiz.Fatal("encrypted key")

    monkeypatch.setattr(wiz, "validate_private_key", _reject)
    with pytest.raises(wiz.Fatal, match="encrypted key"):
        wiz.stage_push_injection("local", "acme", _key(tmp_path), None)


# --- compose model wiring (T005 / T006) --------------------------------------


def test_build_compose_model_emits_injected_configs(wiz, tmp_path):
    push = tmp_path / "acme.push_key"
    push.write_bytes(b"KEY")
    injected = [("push_key", push, wiz.INJECT_PUSH_KEY_PATH)]
    model = wiz.build_compose_model("acme", tmp_path / "repo", injected_configs=injected)
    svc = model["services"]["agent"]
    assert {"source": "push_key", "target": wiz.INJECT_PUSH_KEY_PATH} in svc["configs"]
    assert model["configs"]["push_key"] == {"file": str(push)}


def test_push_key_distinct_from_host_key(wiz, tmp_path):
    """SC-008: the inbound host key and the outbound push key are two distinct
    credentials at two distinct targets — never conflated."""
    hk = tmp_path / "hk"
    hk.write_bytes(b"HOSTKEY")
    push = tmp_path / "acme.push_key"
    push.write_bytes(b"PUSHKEY")
    model = wiz.build_compose_model(
        "acme", tmp_path / "repo",
        host_key_file=hk,
        injected_configs=[("push_key", push, wiz.INJECT_PUSH_KEY_PATH)],
    )  # fmt: skip
    targets = {c["source"]: c["target"] for c in model["services"]["agent"]["configs"]}
    assert targets["ssh_host_key"] == wiz.INJECT_HOST_KEY_PATH
    assert targets["push_key"] == wiz.INJECT_PUSH_KEY_PATH
    assert targets["ssh_host_key"] != targets["push_key"]  # distinct
    assert model["configs"]["ssh_host_key"]["file"] != model["configs"]["push_key"]["file"]


def test_no_secret_value_inlined_in_compose_model(wiz, tmp_path):
    """FR-011: the compose model references the key by FILE path, never inlines the
    secret bytes."""
    push = tmp_path / "acme.push_key"
    push.write_bytes(b"SUPERSECRETKEYBYTES")
    model = wiz.build_compose_model(
        "acme", tmp_path / "repo",
        injected_configs=[("push_key", push, wiz.INJECT_PUSH_KEY_PATH)],
    )  # fmt: skip
    assert "SUPERSECRETKEYBYTES" not in json.dumps(model)


# --- CLI threading (T007) ----------------------------------------------------


def test_do_up_threads_push_material(wiz, monkeypatch, tmp_path):
    seen: dict = {}

    def _fake_exec(*a, **k):
        seen["push_key"] = k.get("push_key")
        seen["known_hosts"] = k.get("known_hosts")

    monkeypatch.setattr(
        wiz, "resolve_deploy_host", lambda h=None: ("local", {"driver": "docker", "context": ""})
    )
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "migrate_flat_state", lambda: None)
    monkeypatch.setattr(wiz, "host_container_names", lambda *a, **k: set())
    monkeypatch.setattr(wiz, "resolve_env_file", lambda n: tmp_path / "acme.env")
    (tmp_path / "acme.env").write_text("GH_TOKEN=x\n")
    monkeypatch.setattr(wiz, "compose_up_exec", _fake_exec)
    pk, kh = tmp_path / "pk", tmp_path / "kh"
    pk.write_bytes(b"K")
    kh.write_text("h\n")
    wiz.do_up("acme", push_key=pk, known_hosts=kh)
    assert seen == {"push_key": pk, "known_hosts": kh}


# --- US2: model/API credential FILE discovery + ephemeral staging (T011) ------


def test_plaintext_credentials_are_user_level_only(wiz, tmp_path):
    """Feature 011 FR-001f / contract C2b. Project-local plaintext keys are GONE,
    with no `.agent-container/` replacement.

    `.agent-container/` travels with the repository and Feature 008 settled that
    the repo holds a locator, never a value. Keeping keys out of it means
    `git add .agent-container/` — the natural action, since it holds the spec —
    cannot stage an API key. Neither the old project-root name nor a project
    config placement may be discovered.
    """
    (tmp_path / ".agent-container").mkdir()
    (tmp_path / "agent-container.acme.anthropic.key").write_text("OLD-LAYOUT")
    (tmp_path / ".agent-container" / "acme.anthropic.key").write_text("IN-PROJECT-CONFIG")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.anthropic.key").write_text("USERCONF")
    found = wiz.discover_apikey_files("acme", cwd=tmp_path)
    assert found == {"anthropic": wiz.CONFIG_DIR / "acme.anthropic.key"}


def test_discover_apikey_files_multiple_providers_lowercased(wiz, tmp_path):
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.anthropic.key").write_text("A")
    (wiz.CONFIG_DIR / "acme.OpenAI.key").write_text("O")  # mixed case -> lowered
    found = wiz.discover_apikey_files("acme", cwd=tmp_path)
    assert set(found) == {"anthropic", "openai"}


def test_discover_apikey_files_absent_returns_empty(wiz, tmp_path):
    assert wiz.discover_apikey_files("acme", cwd=tmp_path) == {}


def test_discover_apikey_files_ignores_other_names(wiz, tmp_path):
    """Only <name>'s keys are discovered — a sibling deployment's file is ignored,
    and non-.key files (e.g. the .env / sidecar) never match."""
    (tmp_path / "agent-container.other.anthropic.key").write_text("X")
    (tmp_path / "agent-container.acme.services.yaml").write_text("services: {}")
    (tmp_path / ".agent-container").mkdir(exist_ok=True)
    (tmp_path / ".agent-container" / ".env").write_text("GH_TOKEN=x")
    assert wiz.discover_apikey_files("acme", cwd=tmp_path) == {}


def test_stage_apikey_injection_ephemeral_target(wiz, tmp_path):
    """Each provider key is staged to the EPHEMERAL INJECT_APIKEY_DIR/<provider>
    (a /run path — never a per-agent volume, H1/FR-012), byte-identical, 0644,
    under the 0700 per-host state dir."""
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    src = wiz.CONFIG_DIR / "acme.anthropic.key"
    src.write_bytes(b"sk-ant-SECRET")
    entries = wiz.stage_apikey_injection("local", "acme", cwd=tmp_path)
    by_name = {e[0]: e for e in entries}
    name, staged, target = by_name["apikey_anthropic"]
    assert target == f"{wiz.INJECT_APIKEY_DIR}/anthropic"
    assert target.startswith("/run/")  # ephemeral, not a volume mount
    assert "/home/dev/" not in target  # never a per-agent volume path
    assert staged == wiz.host_state_dir("local") / "acme.apikey.anthropic"
    assert staged.read_bytes() == src.read_bytes()
    assert (staged.stat().st_mode & 0o777) == 0o644
    assert (wiz.host_state_dir("local").stat().st_mode & 0o777) == 0o700


def test_stage_apikey_injection_none_returns_empty(wiz, tmp_path):
    assert wiz.stage_apikey_injection("local", "acme", cwd=tmp_path) == []


def test_apikey_value_never_inlined_in_compose_model(wiz, tmp_path):
    """FR-011: the compose model references the staged key by FILE path — the secret
    bytes are never inlined, and the target stays under /run (ephemeral)."""
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    src = wiz.CONFIG_DIR / "acme.openai.key"
    src.write_bytes(b"sk-oai-SUPERSECRET")
    entries = wiz.stage_apikey_injection("local", "acme", cwd=tmp_path)
    model = wiz.build_compose_model("acme", tmp_path / "repo", injected_configs=entries)
    dumped = json.dumps(model)
    assert "sk-oai-SUPERSECRET" not in dumped  # never inlined (FR-011)
    targets = {c["source"]: c["target"] for c in model["services"]["agent"]["configs"]}
    assert targets["apikey_openai"] == f"{wiz.INJECT_APIKEY_DIR}/openai"


def test_apikey_env_delivery_unaffected(wiz, tmp_path):
    """The env/`.env` delivery remains the layered fallback: with no key FILE the
    staging is empty, and a `.env` value rides via env_file (referenced by path,
    never inlined into the compose model / argv)."""
    assert wiz.stage_apikey_injection("local", "acme", cwd=tmp_path) == []
    env_file = tmp_path / "acme.env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-ENVSECRET\n")
    model = wiz.build_compose_model("acme", tmp_path / "repo", env_file=env_file)
    assert model["services"]["agent"]["env_file"] == [str(env_file)]
    assert "sk-ant-ENVSECRET" not in json.dumps(model)  # value not inlined; only the path


def test_compose_up_exec_threads_discovered_apikeys(wiz, monkeypatch, tmp_path):
    """compose_up_exec auto-discovers + stages provider key files and threads them
    into build_compose_model's injected_configs (no new flags — discovery is
    automatic), alongside the push material."""
    captured: dict = {}

    def _fake_build(name, build_ctx, *a, **k):
        captured["injected"] = k.get("injected_configs")
        return {"name": name, "services": {"agent": {}}, "volumes": {}}

    monkeypatch.chdir(tmp_path)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.anthropic.key").write_bytes(b"K")
    monkeypatch.setattr(wiz, "build_compose_model", _fake_build)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    monkeypatch.setattr(wiz, "write_compose_file", lambda *a, **k: tmp_path / "c.yaml")
    monkeypatch.setattr(wiz, "resolve_sidecar_override", lambda n: None)
    monkeypatch.setattr(wiz, "driver_up_argv", lambda *a, **k: ["true"])
    monkeypatch.setattr(wiz, "port_free", lambda p: True)
    monkeypatch.setattr(wiz, "write_state", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda r: "localhost")
    host_rec = {"driver": "docker", "context": ""}
    wiz.compose_up_exec("local", host_rec, "acme", tmp_path / "acme.env", [], None, [])
    sources = {e[0] for e in (captured["injected"] or [])}
    assert "apikey_anthropic" in sources


# --- US3: canonical config fresh each deploy; runtime state persists (T015) ----


def _config_src(tmp_path: Path, name: str = "acme") -> Path:
    """Build a project-local canonical-config source dir with canonical files
    (settings, guidance, an MCP def — all non-secret per FR-007) plus a
    runtime-state file that is NOT in the manifest (must not be delivered)."""
    (tmp_path / ".agent-container").mkdir(exist_ok=True)
    root = tmp_path / ".agent-container" / f"{name}.config"
    claude = root / "claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text('{"theme":"dark"}\n')
    (claude / "CLAUDE.md").write_text("# guidance\n")
    (claude / "history.jsonl").write_text('{"runtime":"state"}\n')  # runtime state
    (claude / "servers.mcp.json").write_text('{"url":"MCPMARKER"}\n')  # canonical MCP def
    codex = root / "codex"
    codex.mkdir(parents=True)
    (codex / "config.toml").write_text("model = 'o1'\n")
    (codex / "auth.json").write_text('{"runtime":"auth"}\n')  # runtime state
    return root


def test_discover_canonical_config_filters_by_manifest(wiz, tmp_path):
    """Only manifest-matched CANONICAL files are discovered; runtime-state files
    (not in the manifest) are NOT delivered (FR-008)."""
    _config_src(tmp_path)
    found = wiz.discover_canonical_config("acme", cwd=tmp_path)
    targets = {t for t, _src in found}
    assert ".claude/settings.json" in targets
    assert ".claude/CLAUDE.md" in targets
    assert ".codex/config.toml" in targets
    # runtime state is NOT delivered
    assert ".claude/history.jsonl" not in targets
    assert ".codex/auth.json" not in targets


def test_discover_canonical_config_includes_mcp_defs(wiz, tmp_path):
    """MCP definitions are non-secret canonical config (FR-007) — delivered like
    any other canonical file, not shunted to an unconsumed secret channel."""
    _config_src(tmp_path)
    targets = {t for t, _src in wiz.discover_canonical_config("acme", cwd=tmp_path)}
    assert ".claude/servers.mcp.json" in targets


def test_discover_canonical_config_absent_returns_empty(wiz, tmp_path):
    assert wiz.discover_canonical_config("acme", cwd=tmp_path) == []


def test_canonical_config_dir_project_local_wins(wiz, tmp_path):
    (tmp_path / ".agent-container").mkdir(exist_ok=True)
    proj = tmp_path / ".agent-container" / "acme.config"
    (proj / "claude").mkdir(parents=True)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.config" / "claude").mkdir(parents=True)
    assert wiz.canonical_config_dir("acme", tmp_path) == proj


def test_stage_config_injection_targets(wiz, tmp_path):
    """Canonical files (incl. MCP defs) stage to INJECT_CONFIG_DIR/<home-relative>,
    all under /run (delivered fresh each boot), 0644 under the 0700 state dir."""
    _config_src(tmp_path)
    entries = wiz.stage_config_injection("local", "acme", cwd=tmp_path)
    targets = {e[0]: e[2] for e in entries}
    assert (
        targets["config_claude_settings_json"] == f"{wiz.INJECT_CONFIG_DIR}/.claude/settings.json"
    )
    assert targets["config_codex_config_toml"] == f"{wiz.INJECT_CONFIG_DIR}/.codex/config.toml"
    # MCP def is canonical config — delivered under INJECT_CONFIG_DIR, consumed by the entrypoint
    assert (
        targets["config_claude_servers_mcp_json"]
        == f"{wiz.INJECT_CONFIG_DIR}/.claude/servers.mcp.json"
    )
    for _n, staged, target in entries:
        assert target.startswith(wiz.INJECT_CONFIG_DIR + "/")
        assert (staged.stat().st_mode & 0o777) == 0o644
    assert (wiz.host_state_dir("local").stat().st_mode & 0o777) == 0o700


def test_stage_config_injection_absent_returns_empty(wiz, tmp_path):
    assert wiz.stage_config_injection("local", "acme", cwd=tmp_path) == []


def test_canonical_config_value_never_inlined(wiz, tmp_path):
    """FR-011: canonical config is referenced by FILE path — its contents are never
    inlined into the compose model."""
    _config_src(tmp_path)
    entries = wiz.stage_config_injection("local", "acme", cwd=tmp_path)
    model = wiz.build_compose_model("acme", tmp_path / "repo", injected_configs=entries)
    assert "MCPMARKER" not in json.dumps(model)


def test_compose_up_exec_threads_canonical_config(wiz, monkeypatch, tmp_path):
    """compose_up_exec auto-discovers + stages canonical config and threads it into
    build_compose_model's injected_configs (no new flags — discovery is automatic)."""
    captured: dict = {}

    def _fake_build(name, build_ctx, *a, **k):
        captured["injected"] = k.get("injected_configs")
        return {"name": name, "services": {"agent": {}}, "volumes": {}}

    monkeypatch.chdir(tmp_path)
    _config_src(tmp_path)
    monkeypatch.setattr(wiz, "build_compose_model", _fake_build)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    monkeypatch.setattr(wiz, "write_compose_file", lambda *a, **k: tmp_path / "c.yaml")
    monkeypatch.setattr(wiz, "resolve_sidecar_override", lambda n: None)
    monkeypatch.setattr(wiz, "driver_up_argv", lambda *a, **k: ["true"])
    monkeypatch.setattr(wiz, "port_free", lambda p: True)
    monkeypatch.setattr(wiz, "write_state", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda r: "localhost")
    host_rec = {"driver": "docker", "context": ""}
    wiz.compose_up_exec("local", host_rec, "acme", tmp_path / "acme.env", [], None, [])
    sources = {e[0] for e in (captured["injected"] or [])}
    assert "config_claude_settings_json" in sources
    assert "config_claude_servers_mcp_json" in sources


# --- US4: rotation, scoping, fail-fast robustness (T019) ----------------------
#
# US4 does not add new material — it VERIFIES the emergent guarantees end-to-end:
# a deploy that references ANY missing/invalid injected item (of ANY kind) dies
# BEFORE any compose call, and every kind is staged locally before `compose up`
# so a later failure leaves nothing running (FR-016/FR-017/SC-007). Scoping the
# push credential narrowly is confirmed to be just a narrower `--push-key`
# (FR-004) — no separate plumbing.


def _compose_tripwires(wiz, monkeypatch, tmp_path) -> list[str]:
    """Arm every downstream stage of compose_up_exec as a tripwire so a test can
    assert the deploy died in the LOCAL staging phase, before ANY compose call
    (build_compose_model → write_compose_file → driver_up_argv → the compose
    subprocess). Returns the ordered list of stages that were reached."""
    tripped: list[str] = []
    monkeypatch.setattr(wiz, "port_free", lambda p: True)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")

    def _build(*a, **k):
        tripped.append("build_compose_model")
        return {"name": "x", "services": {"agent": {}}, "volumes": {}}

    monkeypatch.setattr(wiz, "build_compose_model", _build)

    def _write(*a, **k):
        tripped.append("write_compose_file")
        return tmp_path / "c.yaml"

    monkeypatch.setattr(wiz, "write_compose_file", _write)
    monkeypatch.setattr(wiz, "resolve_sidecar_override", lambda n: None)

    def _up(*a, **k):
        tripped.append("driver_up_argv")
        return ["true"]

    monkeypatch.setattr(wiz, "driver_up_argv", _up)

    def _run(*a, **k):
        tripped.append("compose-subprocess")

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(wiz.subprocess, "run", _run)
    monkeypatch.setattr(wiz, "write_state", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda r: "localhost")
    return tripped


_HOST_REC = {"driver": "docker", "context": ""}


def test_missing_push_key_dies_before_any_compose_call(wiz, monkeypatch, tmp_path):
    """FR-016/SC-007: a referenced but missing --push-key aborts in staging — no
    compose model is built and no compose command is invoked."""
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    with pytest.raises(wiz.Fatal, match="--push-key"):
        wiz.compose_up_exec(
            "local", _HOST_REC, "acme", tmp_path / "acme.env", [], None, [],
            push_key=tmp_path / "nope",
        )  # fmt: skip
    assert tripped == []  # nothing downstream of staging ran


def test_missing_known_hosts_dies_before_any_compose_call(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    with pytest.raises(wiz.Fatal, match="--known-hosts"):
        wiz.compose_up_exec(
            "local", _HOST_REC, "acme", tmp_path / "acme.env", [], None, [],
            push_key=_key(tmp_path), known_hosts=tmp_path / "nope",
        )  # fmt: skip
    assert tripped == []


def test_missing_host_key_dies_before_any_compose_call(wiz, monkeypatch, tmp_path):
    """The inbound host-key material shares the same all-staging-before-compose
    guard — a missing --host-key aborts before any compose call, too."""
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    with pytest.raises(wiz.Fatal, match="--host-key"):
        wiz.compose_up_exec(
            "local", _HOST_REC, "acme", tmp_path / "acme.env", [], tmp_path / "nope", [],
        )  # fmt: skip
    assert tripped == []


def test_missing_discovered_apikey_dies_before_any_compose_call(wiz, monkeypatch, tmp_path):
    """A convention-discovered model/API key file that is referenced (discovered)
    but has vanished/become unreadable dies with a clear diagnostic BEFORE any
    compose call (FR-016) — never a raw traceback, never a partial deploy."""
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    monkeypatch.setattr(
        wiz, "discover_apikey_files", lambda name, cwd=None: {"anthropic": tmp_path / "gone.key"}
    )
    with pytest.raises(wiz.Fatal, match="anthropic"):
        wiz.compose_up_exec("local", _HOST_REC, "acme", tmp_path / "acme.env", [], None, [])
    assert tripped == []


def test_missing_discovered_canonical_config_dies_before_any_compose_call(
    wiz, monkeypatch, tmp_path
):
    """A discovered canonical-config file that has vanished before staging dies with
    a clear diagnostic BEFORE any compose call (FR-016)."""
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    monkeypatch.setattr(wiz, "discover_apikey_files", lambda name, cwd=None: {})
    monkeypatch.setattr(
        wiz,
        "discover_canonical_config",
        lambda name, cwd=None: [(".claude/settings.json", tmp_path / "gone.json")],
    )
    with pytest.raises(wiz.Fatal, match="disappeared"):
        wiz.compose_up_exec("local", _HOST_REC, "acme", tmp_path / "acme.env", [], None, [])
    assert tripped == []


def test_all_material_staged_locally_before_compose_up(wiz, monkeypatch, tmp_path):
    """FR-017: every kind of injected material (push key, known_hosts, discovered
    API key, discovered canonical config) is staged to a LOCAL file that already
    exists on disk by the time the compose model is built — so when the compose
    call itself later fails, nothing was half-provisioned into a running agent."""
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    monkeypatch.chdir(tmp_path)
    pk = _key(tmp_path)
    kh = tmp_path / "kh"
    kh.write_text("github.com ssh-ed25519 AAAA\n")
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.anthropic.key").write_bytes(b"sk-ant-SECRET")
    _config_src(tmp_path)
    captured: dict = {}

    def _build(name, build_ctx, *a, **k):
        captured["injected"] = k.get("injected_configs")
        return {"name": name, "services": {"agent": {}}, "volumes": {}}

    monkeypatch.setattr(wiz, "build_compose_model", _build)
    monkeypatch.setattr(wiz, "resolve_build_context", lambda: tmp_path / "repo")
    monkeypatch.setattr(wiz, "write_compose_file", lambda *a, **k: tmp_path / "c.yaml")
    monkeypatch.setattr(wiz, "resolve_sidecar_override", lambda n: None)
    monkeypatch.setattr(wiz, "port_free", lambda p: True)
    monkeypatch.setattr(wiz, "driver_up_argv", lambda *a, **k: ["false"])  # compose FAILS
    monkeypatch.setattr(wiz, "write_state", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda r: "localhost")
    with pytest.raises(wiz.Fatal, match="compose"):
        wiz.compose_up_exec(
            "local", _HOST_REC, "acme", tmp_path / "acme.env", [], None, [],
            push_key=pk, known_hosts=kh,
        )  # fmt: skip
    injected = captured["injected"]
    assert injected  # build_compose_model was reached with the full staged set
    sources = {e[0] for e in injected}
    assert {"push_key", "known_hosts", "apikey_anthropic"} <= sources
    assert any(s.startswith("config_") for s in sources)  # canonical config too
    for _n, staged, _t in injected:
        assert staged.is_file()  # staged to a real LOCAL file before compose ran


def test_per_repo_deploy_key_is_just_a_narrower_push_key(wiz, monkeypatch, tmp_path):
    """FR-004: a narrowly-scoped per-repository deploy key is provisioned through the
    SAME --push-key mechanism to the SAME ephemeral target — the narrower scope is a
    property of the KEY, not of the plumbing (no separate flag, no separate path)."""
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    deploy_key = _key(tmp_path, "repo_deploy_key")
    entries = wiz.stage_push_injection("local", "acme", deploy_key, None)
    by_name = {e[0]: e for e in entries}
    assert by_name["push_key"][2] == wiz.INJECT_PUSH_KEY_PATH  # identical ephemeral target
    assert by_name["push_key"][1].read_bytes() == deploy_key.read_bytes()


# --- Feature 010 US2: opencode credentials ride the EXISTING channels --------


def test_opencode_key_is_never_inlined_in_the_compose_descriptor(wiz, tmp_path):
    """FR-011 / Constitution III. The compose descriptor is exactly where an
    env-delivered secret leaks (it is written to disk and read by `inspect`), so
    the key must ride as a FILE reference, never as bytes or an `environment:`
    value."""
    key = tmp_path / "acme.anthropic.key"
    key.write_bytes(b"sk-ant-OPENCODE-SECRET-BYTES")
    model = wiz.build_compose_model(
        "acme", tmp_path / "repo",
        environment=wiz.ExecSpec(agent="opencode").compose_environment(),
        injected_configs=[("anthropic_key", key, "/run/agent-container/apikeys/anthropic")],
    )  # fmt: skip
    blob = json.dumps(model)
    assert "sk-ant-OPENCODE-SECRET-BYTES" not in blob
    env = model["services"]["agent"].get("environment", {})
    assert not any("sk-ant" in str(v) for v in env.values())
    # The agent selection itself is not a secret and SHOULD be present.
    assert env.get("AGENT_CONTAINER_AGENT") == "opencode"


def test_opencode_key_discovery_uses_the_shared_convention(wiz, tmp_path):
    """FR-010: no bespoke path for opencode — the same
    `./agent-container.<name>.<provider>.key` convention as the other agents."""
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.anthropic.key").write_text("A")
    assert set(wiz.discover_apikey_files("acme", cwd=tmp_path)) == {"anthropic"}


def test_entrypoint_gives_opencode_no_home_redirect(wiz):
    """Research R6, asserted structurally so a later 'symmetry' refactor cannot
    quietly add one. codex/pi are redirected only to keep an injected key off
    their volume; opencode never writes an env-supplied key to its auth store
    (verified against the real binary), so a redirect would add machinery and
    exposure surface, not remove it."""
    body = (Path(__file__).resolve().parents[2] / "entrypoint.sh").read_text()
    assert "CODEX_HOME" in body and "PI_CODING_AGENT_DIR" in body  # the two that DO redirect
    assert "OPENCODE_CONFIG_DIR" not in body
    assert "OPENCODE_CONFIG" not in body
    assert "XDG_DATA_HOME" not in body


# --- Feature 011 US1: the two configuration levels share one schema ----------


def test_config_and_sidecar_resolve_project_then_user(wiz, tmp_path, monkeypatch):
    """FR-001/FR-001a. Canonical config and sidecar overrides both resolve from
    the project config directory first, then user level — and the SAME filename
    means the same thing at both levels, which is what makes the two levels
    legible as one layered configuration rather than two conventions."""
    root = tmp_path / "proj"
    pcd = root / ".agent-container"
    pcd.mkdir(parents=True)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # identical basenames at both levels
    (pcd / "acme.config").mkdir()
    (wiz.CONFIG_DIR / "acme.config").mkdir()
    assert wiz.canonical_config_dir("acme", root) == pcd / "acme.config"

    got = [p.name for p in wiz.sidecar_override_candidates("acme", root)]
    assert got == ["acme.services.yaml", "acme.services.yaml"]  # same name, two scopes
    parents = [p.parent for p in wiz.sidecar_override_candidates("acme", root)]
    assert parents == [pcd, wiz.CONFIG_DIR]  # project first, user fallback


def test_user_level_is_the_fallback_when_the_project_has_none(wiz, tmp_path):
    """The layering must degrade, not fail: a project that defines nothing still
    picks up the operator's machine-wide defaults."""
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.config").mkdir()
    assert wiz.canonical_config_dir("acme", root) == wiz.CONFIG_DIR / "acme.config"


# --- Feature 011 US1: the hard cut refuses, never ignores --------------------


def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / ".agent-container").mkdir(parents=True)
    return root


def test_superseded_files_are_refused_and_name_their_destination(wiz, tmp_path):
    """FR-004/FR-005, contract C3. Deleting the old lookup is not enough: a
    deleted lookup is indistinguishable, from the operator's side, from silently
    ignoring their file. Each offender is named with where it now belongs."""
    root = _proj(tmp_path)
    (root / "agent-container.acme.env").write_text("X=1\n")
    with pytest.raises(wiz.Fatal) as ei:
        wiz.refuse_superseded_layout("acme", root)
    msg = str(ei.value)
    assert "agent-container.acme.env" in msg
    assert ".agent-container/acme.env" in msg


def test_a_superseded_key_names_user_level_not_a_project_destination(wiz, tmp_path):
    """FR-001f. There IS no project-local destination for a plaintext key, so the
    message must not invent one — it points at user level and the locator model."""
    root = _proj(tmp_path)
    (root / "agent-container.acme.anthropic.key").write_text("sk-ant-x")
    with pytest.raises(wiz.Fatal) as ei:
        wiz.refuse_superseded_layout("acme", root)
    msg = str(ei.value)
    assert "agent-container.acme.anthropic.key" in msg
    assert ".agent-container/acme.anthropic.key" not in msg  # must NOT suggest this
    assert "config/agent-container" in msg or "locator" in msg


def test_all_offenders_are_listed_in_one_message(wiz, tmp_path):
    """One message, not one per run — an operator fixing them one at a time is a
    worse experience than being told everything at once."""
    root = _proj(tmp_path)
    for f in (
        "agent-container.acme.env",
        "agent-container.acme.services.yaml",
        "agent-container.acme.anthropic.key",
    ):
        (root / f).write_text("x")
    (root / "agent-container.acme.config").mkdir()
    with pytest.raises(wiz.Fatal) as ei:
        wiz.refuse_superseded_layout("acme", root)
    msg = str(ei.value)
    for f in ("acme.env", "acme.services.yaml", "acme.anthropic.key", "acme.config"):
        assert f"agent-container.{f}" in msg, f"{f} missing from the refusal"


def test_a_clean_project_is_silent(wiz, tmp_path):
    """No migration chatter for a project that has nothing to migrate."""
    root = _proj(tmp_path)
    (root / ".agent-container" / "acme.env").write_text("X=1\n")
    wiz.refuse_superseded_layout("acme", root)  # must not raise


def test_bare_dotenv_refuses_only_when_no_agent_container_env_resolves(wiz, tmp_path, monkeypatch):
    """FR-001c. The CONDITIONAL case, and the silent half is as load-bearing as
    the loud one.

    Refusing on any `./.env` would make the tool hostile to the directory it
    shares — Compose projects legitimately have one that was never meant for us.
    Ignoring it silently when nothing else resolves would strand GH_TOKEN and
    provider keys. So: refuse only when the operator would otherwise deploy with
    no env file at all while a `.env` sits there.
    """
    monkeypatch.setattr(wiz, "CONFIG_DIR", tmp_path / "userconf")
    root = _proj(tmp_path)
    (root / ".env").write_text("GH_TOKEN=x\n")

    with pytest.raises(wiz.Fatal, match=r"\.env"):
        wiz.refuse_superseded_layout("acme", root)  # nothing else resolves -> refuse

    (root / ".agent-container" / "acme.env").write_text("GH_TOKEN=y\n")
    wiz.refuse_superseded_layout("acme", root)  # now silent: the stray .env is someone else's
