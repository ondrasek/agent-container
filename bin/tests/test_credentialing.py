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
import pathlib
import subprocess
from pathlib import Path

import pytest


def _key(tmp_path: Path, name: str = "push") -> Path:
    f = tmp_path / name
    f.write_bytes(
        b"-----BEGIN OPENSSH PRIVATE KEY-----\nFAKEKEYBYTES\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    return f


# --- foundational staging (T004) ---------------------------------------------


def test_stage_push_injection_stages_only_known_hosts_now(wiz, tmp_path):
    """Feature 019 removed this function's PRIVATE-KEY arm. What remains verifies the
    FORGE — the opposite direction, public data, and unaffected.

    The assertion inverts rather than disappearing: a removal with no test behind it
    is a removal nobody notices being undone, and this one wrote a plaintext private
    key to the operator's disk at 0644.
    """
    kh = tmp_path / "known_hosts"
    kh.write_text("github.com ssh-ed25519 AAAA\n")
    entries = wiz.stage_push_injection("local", "acme", kh)
    by_name = {e[0]: e for e in entries}
    assert set(by_name) == {"known_hosts"}  # no private key channel survives
    assert by_name["known_hosts"][2] == wiz.INJECT_KNOWN_HOSTS_PATH
    assert not hasattr(wiz, "INJECT_PUSH_KEY_PATH")
    # Constitution IX: no staged copy exists to stat. The value is carried inline,
    # so the 0644 file this used to assert on is gone — which is the improvement,
    # since nothing ever deleted it.
    assert by_name["known_hosts"][1] == "github.com ssh-ed25519 AAAA\n"


def test_stage_push_injection_none_returns_empty(wiz):
    assert wiz.stage_push_injection("local", "acme", None) == []


def test_the_push_key_flag_is_refused_with_an_explanation(wiz):
    """Feature 019 (FR-002): `--push-key` no longer stages anything — it REFUSES, and
    says the agent generates its own key and the operator registers the public half.

    These three tests used to cover staging a supplied private key (missing file,
    encrypted file). That whole channel is gone; what replaces them is the refusal,
    because an operator who used the flag deserves to learn where it went.
    """
    with pytest.raises(wiz.Fatal, match="generated INSIDE the container"):
        wiz.refuse_removed_push_key("up --push-key")


def test_stage_push_injection_missing_known_hosts_dies(wiz, tmp_path):
    with pytest.raises(wiz.Fatal, match="--known-hosts"):
        wiz.stage_push_injection("local", "acme", tmp_path / "nope")


# --- compose model wiring (T005 / T006) --------------------------------------


def test_build_compose_model_emits_injected_configs(wiz, tmp_path):
    push = tmp_path / "acme.known_hosts"
    push.write_bytes(b"github.com ssh-ed25519 AAAA")
    injected = [("known_hosts", push.read_text(), wiz.INJECT_KNOWN_HOSTS_PATH)]
    model = wiz.build_compose_model("acme", tmp_path / "repo", injected_configs=injected)
    svc = model["services"]["agent"]
    assert {"source": "known_hosts", "target": wiz.INJECT_KNOWN_HOSTS_PATH} in svc["configs"]
    # `content:`, never `file:` — a file: config is a bind resolved daemon-side and
    # cannot reach a daemon that does not share the operator's filesystem (measured).
    assert model["configs"]["known_hosts"] == {"content": push.read_text()}


def test_push_key_is_its_own_channel(wiz, tmp_path):
    """SC-008: the OUTBOUND push key has its own target and its own lifecycle.

    This test paired it against an inbound private host key until Feature 018 removed
    that channel. The half that survives is the half that was always true and still
    matters: known_hosts verifies the FORGE, delivered under /run,
    and nothing else shares its target. The two directions are not symmetric —
    inbound identity is now CAPTURED, not supplied.
    """
    push = tmp_path / "acme.push_key"
    push.write_bytes(b"PUSHKEY")
    model = wiz.build_compose_model(
        "acme", tmp_path / "repo",
        injected_configs=[("known_hosts", "PUSHKEY", wiz.INJECT_KNOWN_HOSTS_PATH)],
    )  # fmt: skip
    targets = {c["source"]: c["target"] for c in model["services"]["agent"]["configs"]}
    assert targets == {"known_hosts": wiz.INJECT_KNOWN_HOSTS_PATH}
    assert model["configs"]["known_hosts"] == {"content": "PUSHKEY"}


def test_secrets_never_reach_the_compose_model_at_all(wiz, tmp_path):
    """Feature 003's FR-011 required the model to reference credentials by FILE path
    rather than inline them. Feature 020 MEASURED that a `file:` config is a bind
    resolved daemon-side, so that mechanism cannot reach a daemon which does not
    share the operator's filesystem — it refuses the deploy outright. The mechanism
    and remote delivery were mutually exclusive.

    Constitution IX resolves it by removing the premise: a secret does not belong in
    the deployment description in EITHER form. `split_injected` routes public
    material to the model and secret material to `deliver_secrets`, which pushes it
    into the already-running container over SSH.

    So the assertion is stronger than FR-011's, not weaker: not "referenced rather
    than inlined", but ABSENT — no path, no value, nothing.
    """
    entries = [
        ("known_hosts", "github.com ssh-ed25519 PUBLIC", wiz.INJECT_KNOWN_HOSTS_PATH),
        ("apikey_anthropic", "sk-ant-SUPERSECRET", f"{wiz.INJECT_APIKEY_DIR}/anthropic"),
    ]
    public, secrets = wiz.split_injected(entries)
    assert [e[0] for e in public] == ["known_hosts"]
    assert secrets == [(f"{wiz.INJECT_APIKEY_DIR}/anthropic", "sk-ant-SUPERSECRET")]
    model = wiz.build_compose_model("acme", tmp_path / "repo", injected_configs=public)
    dumped = json.dumps(model)
    assert "sk-ant-SUPERSECRET" not in dumped
    assert "apikey_anthropic" not in dumped  # not even the NAME of a secret
    assert "github.com ssh-ed25519 PUBLIC" in dumped  # public material still rides


# --- CLI threading (T007) ----------------------------------------------------


def test_do_up_threads_known_hosts_material(wiz, monkeypatch, tmp_path):
    seen: dict = {}

    def _fake_exec(*a, **k):
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
    wiz.do_up("acme", known_hosts=kh)
    # Feature 019: only the FORGE-verifying material is threaded now. The agent's own
    # key is generated in the container, so there is nothing outbound to thread.
    assert seen == {"known_hosts": kh}


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
    # Delivered secrets live in a dev-owned 0700 dir created in the IMAGE, beside the
    # runtime's own root-owned config mount point rather than inside it. Still under
    # /run, so it dies with the container and is never a volume (FR-012).
    assert target.startswith("/run/")  # dies with the container, never a volume
    assert "/home/dev/" not in target  # never a per-agent volume path
    assert staged == src.read_text()  # carried as a value, not a staged path
    # THE load-bearing half: no plaintext copy is left on disk anywhere.
    leaked = [
        f
        for f in wiz.host_state_dir("local").rglob("*")
        if f.is_file() and "sk-ant-SECRET" in f.read_text(errors="ignore")
    ]
    assert leaked == [], f"plaintext key written to disk: {leaked}"


def test_stage_apikey_injection_none_returns_empty(wiz, tmp_path):
    assert wiz.stage_apikey_injection("local", "acme", cwd=tmp_path) == []


def test_apikey_value_never_inlined_in_compose_model(wiz, tmp_path):
    """Superseded by `test_secrets_never_reach_the_compose_model_at_all`.

    This asserted FR-011's mechanism — that the value be referenced by path rather
    than inlined. Both halves of that are now wrong: canonical config is PUBLIC and
    is deliberately inlined so it can reach a daemon that shares no filesystem, and
    a real secret is not in the description at all. Kept as a pointer rather than
    deleted, so the reason the old assertion vanished is discoverable.
    """
    assert hasattr(wiz, "split_injected")


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
    monkeypatch.setattr(wiz, "resolve_build_context", lambda *a, **k: tmp_path / "repo")
    monkeypatch.setattr(wiz, "write_compose_file", lambda *a, **k: tmp_path / "c.yaml")
    monkeypatch.setattr(wiz, "resolve_sidecar_override", lambda n: None)
    monkeypatch.setattr(wiz, "driver_up_argv", lambda *a, **k: ["true"])
    monkeypatch.setattr(wiz, "port_free", lambda p: True)
    monkeypatch.setattr(wiz, "write_state", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda r: "localhost")
    delivered: list = []
    monkeypatch.setattr(wiz, "deliver_secrets", lambda *a: delivered.append(a[-1]))
    # A chown on the freshly-mounted volumes; no secret crosses it, and it needs a
    # real runtime, so it is stubbed like any other runtime call.
    monkeypatch.setattr(wiz, "claim_cred_mounts", lambda *a: None)
    host_rec = {"driver": "docker", "context": ""}
    wiz.compose_up_exec("local", host_rec, "acme", tmp_path / "acme.env", [], None, [])
    # Discovery still happens automatically (no flags); the key is now DELIVERED
    # rather than described, so assert it reached the delivery path.
    assert delivered and delivered[0][0][0] == f"{wiz.INJECT_APIKEY_DIR}/anthropic"


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
    for _n, content, target in entries:
        assert target.startswith(wiz.INJECT_CONFIG_DIR + "/")
        assert isinstance(content, str)  # inline, so there is no file to stat


def test_stage_config_injection_absent_returns_empty(wiz, tmp_path):
    assert wiz.stage_config_injection("local", "acme", cwd=tmp_path) == []


def test_canonical_config_value_never_inlined(wiz, tmp_path):
    """Superseded by `test_secrets_never_reach_the_compose_model_at_all`.

    This asserted FR-011's mechanism — that the value be referenced by path rather
    than inlined. Both halves of that are now wrong: canonical config is PUBLIC and
    is deliberately inlined so it can reach a daemon that shares no filesystem, and
    a real secret is not in the description at all. Kept as a pointer rather than
    deleted, so the reason the old assertion vanished is discoverable.
    """
    assert hasattr(wiz, "split_injected")


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
    monkeypatch.setattr(wiz, "resolve_build_context", lambda *a, **k: tmp_path / "repo")
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
    monkeypatch.setattr(wiz, "resolve_build_context", lambda *a, **k: tmp_path / "repo")

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


def test_the_push_key_flag_refuses_before_any_compose_call(wiz, monkeypatch, tmp_path):
    """Feature 019: `--push-key` no longer stages anything — it REFUSES.

    This test used to prove a MISSING --push-key aborted before compose. The
    all-staging-before-compose guarantee it protected still holds for every remaining
    channel; what changed is that this one cannot be reached at all. The refusal must
    NAME the replacement, not just fail.
    """
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    with pytest.raises(wiz.Fatal, match="generated INSIDE the container"):
        wiz.refuse_removed_push_key("up --push-key")
    assert tripped == []


def test_missing_known_hosts_dies_before_any_compose_call(wiz, monkeypatch, tmp_path):
    monkeypatch.setattr(wiz, "validate_private_key", lambda p: None)
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    with pytest.raises(wiz.Fatal, match="--known-hosts"):
        wiz.compose_up_exec(
            "local", _HOST_REC, "acme", tmp_path / "acme.env", [], None, [], known_hosts=tmp_path / "nope",
        )  # fmt: skip
    assert tripped == []


def test_the_host_key_flag_is_refused_before_any_compose_call(wiz, monkeypatch, tmp_path):
    """Feature 018 (FR-002): `--host-key` no longer stages anything — it REFUSES, and
    says host identity is captured rather than supplied.

    This test used to prove a MISSING --host-key aborted before compose. The
    all-staging-before-compose guarantee it was protecting still holds for every
    remaining channel; what changed is that this particular channel cannot be reached
    at all. The refusal must name the reason, not just fail: an operator who used the
    flag had a reason, and it is now served without a private key on their disk.
    """
    tripped = _compose_tripwires(wiz, monkeypatch, tmp_path)
    with pytest.raises(wiz.Fatal, match="captures the PUBLIC key"):
        wiz.refuse_removed_host_key("up --host-key")
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


def test_public_material_is_described_and_secret_material_is_not(wiz, monkeypatch, tmp_path):
    """What compose_up_exec threads into the model, and what it withholds.

    This test used to assert that ALL material was staged locally before compose up.
    Half of that premise is gone: nothing is staged at all now (no local file for the
    daemon to open), and secrets are withheld from the model entirely.
    """
    captured: dict = {}
    monkeypatch.chdir(tmp_path)
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "acme.anthropic.key").write_bytes(b"sk-ant-SECRET")
    monkeypatch.setattr(
        wiz, "build_compose_model",
        lambda name, ctx, *a, **k: (
            captured.update(injected=k.get("injected_configs")),
            {"name": name, "services": {"agent": {}}, "volumes": {}},
        )[1],
    )  # fmt: skip
    monkeypatch.setattr(wiz, "resolve_build_context", lambda *a, **k: tmp_path / "repo")
    monkeypatch.setattr(wiz, "write_compose_file", lambda *a, **k: tmp_path / "c.yaml")
    monkeypatch.setattr(wiz, "resolve_sidecar_override", lambda n: None)
    monkeypatch.setattr(wiz, "driver_up_argv", lambda *a, **k: ["true"])
    monkeypatch.setattr(wiz, "port_free", lambda p: True)
    monkeypatch.setattr(wiz, "write_state", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda r: "localhost")
    delivered: list = []
    monkeypatch.setattr(wiz, "deliver_secrets", lambda *a: delivered.append(a[-1]))
    # A chown on the freshly-mounted volumes; no secret crosses it, and it needs a
    # real runtime, so it is stubbed like any other runtime call.
    monkeypatch.setattr(wiz, "claim_cred_mounts", lambda *a: None)
    wiz.compose_up_exec("local", {"driver": "docker", "context": ""}, "acme",
                        tmp_path / "acme.env", [], None, [])  # fmt: skip
    described = {e[0] for e in (captured["injected"] or [])}
    assert "apikey_anthropic" not in described  # withheld from the description
    assert delivered and delivered[0] == [(f"{wiz.INJECT_APIKEY_DIR}/anthropic", "sk-ant-SECRET")]


def test_a_per_repo_deploy_key_is_now_what_the_TOOL_does(wiz):
    """This test's name stated Feature 019's thesis before 019 existed: a narrowly
    scoped per-repository deploy key was *just* a push key with a smaller grant.

    It was true, and it was something an operator had to do BY HAND — nothing stopped
    them handing over their personal key instead, and most did. Now the tool does it
    by construction: the container generates its own key, so what it can reach is
    exactly what the operator registered it for.

    The intent survives and strengthens; only the mechanism it asserted is gone.
    """
    # There is no longer any channel by which a key can be supplied at all...
    assert "push_key" not in wiz.CRED_SSH_TARGETS
    assert not hasattr(wiz, "INJECT_PUSH_KEY_PATH")
    with pytest.raises(wiz.Fatal, match="register it on the remote"):
        wiz.refuse_removed_push_key("up --push-key")
    # ...and the key the container makes lives at the conventional identity path.
    assert wiz.CONTAINER_AGENT_SSH_KEY.endswith("/.ssh/id_ed25519")


# --- Feature 010 US2: opencode credentials ride the EXISTING channels --------


def test_opencode_key_is_never_inlined_in_the_compose_descriptor(wiz, tmp_path):
    """Superseded by `test_secrets_never_reach_the_compose_model_at_all`.

    This asserted FR-011's mechanism — that the value be referenced by path rather
    than inlined. Both halves of that are now wrong: canonical config is PUBLIC and
    is deliberately inlined so it can reach a daemon that shares no filesystem, and
    a real secret is not in the description at all. Kept as a pointer rather than
    deleted, so the reason the old assertion vanished is discoverable.
    """
    assert hasattr(wiz, "split_injected")


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
    body = (Path(__file__).resolve().parents[2] / "image" / "entrypoint.sh").read_text()
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


# --- FR-003b: a credential failure is never blamed on the declaration --------


def test_credential_failure_names_the_credential_never_the_declaration(wiz, tmp_path, monkeypatch):
    """FR-003b as a PROHIBITION, which is the only form it can take.

    The earlier wording assumed the tool could tell that a declared provider needs a
    particular credential. It cannot: PROVIDERS is provider->hosts, CRED_PROVIDER is
    credential->provider for delivery routing and covers two of five, and
    AGENT_BUILTIN_DEFAULT is the inverse relation. Any inference would false-positive
    on a provider reached WITHOUT a credential — the very case Feature 010 found.

    So what is testable is that the failure points at the thing that is wrong.
    Blaming the provider list sends the operator to edit the one part that is correct.
    """
    monkeypatch.delenv("MISSING_KEY_VAR", raising=False)
    cred = {"name": "ANTHROPIC_API_KEY", "source": "env", "var": "MISSING_KEY_VAR"}
    with pytest.raises(wiz.Fatal) as e:
        wiz.resolve_credential_value(cred, tmp_path, "prod")
    msg = str(e.value)
    assert "ANTHROPIC_API_KEY" in msg and "MISSING_KEY_VAR" in msg
    assert "prod" in msg, "a multi-environment apply must say WHICH environment"
    # Only ATTRIBUTION terms are forbidden. A vendor name may legitimately appear —
    # here it is part of the credential's own name (ANTHROPIC_API_KEY), which is the
    # thing the message is supposed to point at.
    for forbidden in ("egress", "allowlist", "declaration", "declared provider"):
        assert forbidden not in msg.lower(), f"credential failure blamed on {forbidden!r}"


def test_credential_failure_still_names_its_source_kind(wiz, tmp_path):
    cred = {"name": "K", "source": "file", "path": str(tmp_path / "nope")}
    with pytest.raises(wiz.Fatal) as e:
        wiz.resolve_credential_value(cred, tmp_path)
    assert "nope" in str(e.value), "must name the unresolvable source, not just the credential"


def test_no_credential_value_reaches_any_generated_artifact(wiz, tmp_path, monkeypatch):
    """SC-007 (T039a). A 100% security criterion needs a test, not a paragraph.

    The SENTINEL is the load-bearing detail. Asserting "no key-shaped string
    appears" tests the imagination of whoever wrote the pattern — a real key that
    does not match it passes cleanly. Seeding a KNOWN value through the credential
    path and asserting its absence tests the actual path, and fails loudly when a
    new surface starts carrying it.
    """
    import json as _json

    sentinel = "sk-ant-SENTINEL-must-not-appear-anywhere"
    monkeypatch.setenv("ACC_SENTINEL_VAR", sentinel)
    egress = {"allow": [{"provider": "anthropic"}, {"host": "github.com"}]}

    # Every artifact Feature 012 generates, in one place.
    artifacts = [
        _json.dumps(wiz.build_compose_model("acme", tmp_path / "image", egress_filter_body=None)),
        wiz.build_squid_acl(wiz.resolve_destinations(egress)),
        _json.dumps(wiz.egress_payload(egress, "claude")),
        wiz.egress_strength_statement("claude"),
        _json.dumps(
            wiz.plan_payload(
                [({"name": "acme", "egress": egress}, "acme", "local", None, "absent", "")]
            )
        ),  # fmt: skip
        str(wiz.egress_config_token(egress)),
    ]
    for blob in artifacts:
        assert sentinel not in blob, "a credential value reached a generated artifact"
        assert "ACC_SENTINEL_VAR" not in blob, "even the variable NAME need not travel"


# --- Feature 018: no private host key, through ANY channel -------------------
# FR-001/FR-002/SC-001. There were FIVE channels, and the failure mode is one
# surviving: a 95% removal is indistinguishable from a complete one by every other
# test in this suite, so each is named.


@pytest.mark.parametrize("source", ["up --host-key", "keys --host-key", "redeploy --host-key"])
def test_each_removed_flag_explains_itself_rather_than_erroring(wiz, source):
    """A bare 'no such option' would be a regression, not a removal: the operator
    who used this flag had a reason, and it is now served without a private key on
    their disk. The message has to say so."""
    with pytest.raises(wiz.Fatal) as e:
        wiz.refuse_removed_host_key(source)
    msg = str(e.value)
    assert "captures the PUBLIC key" in msg
    assert "no private key sits on your disk" in msg
    assert source in msg


def test_a_declared_host_key_target_is_refused_not_ignored(wiz):
    """FR-002: silently dropping a declared `host_key` would leave an operator
    believing their key is in use — the worst of the three outcomes."""
    assert "host_key" not in wiz.CRED_SSH_TARGETS
    with pytest.raises(wiz.Fatal, match="captures the PUBLIC key"):
        wiz.validate_credential(
            {"name": "HK", "source": "file", "path": "/k", "target": "host_key"},
            "environments.yaml",
        )


def test_no_private_host_key_channel_survives_anywhere(wiz):
    """The census as a test over the SOURCE (T023). Each name below was a way to put
    a private host key somewhere; a reintroduced one must fail here rather than be
    noticed by nobody."""
    src = Path(wiz.__file__).read_text()
    assert "INJECT_HOST_KEY_PATH" not in src  # the container-side inject path
    assert "SSH_HOST_ED25519_KEY_B64" not in src  # the env-file channel
    assert "ssh_host_key" not in src  # the compose config
    assert "def resolve_ssh_injection" not in src  # the dead legacy bind path
    assert ".host_key" not in wiz._FLAT_STATE_SUFFIXES  # the 011 migration
    # The entrypoint still NAMES the removed channels in a comment explaining why they
    # went, so the check reads EXECUTABLE lines only. Matching the whole file would
    # force the explanation out, and an unexplained removal is how a channel gets
    # quietly reinstated by someone who never learns what it cost.
    entry = (Path(wiz.__file__).parents[1] / "image" / "entrypoint.sh").read_text()
    code = [ln for ln in entry.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert not any("SSH_HOST_ED25519_KEY_B64" in ln for ln in code)
    assert not any("INJECT_DIR" in ln and "ssh_host_ed25519_key" in ln for ln in code)
    # No branch installs anything into the host key path — only generate-or-keep.
    assert not any("install -m 0600" in ln and "HOSTKEY" in ln for ln in code)


def test_the_census_guard_can_fail(wiz, tmp_path):
    """Proof T023's census is load-bearing: a source that reintroduces a channel is
    rejected. Without this, the assertions above are strings nobody has watched
    refuse anything."""
    fake = tmp_path / "reintroduced"
    fake.write_text('INJECT_HOST_KEY_PATH = "/run/agent-container/ssh_host_ed25519_key"\n')
    assert "INJECT_HOST_KEY_PATH" in fake.read_text()  # the guard's own predicate fires


def test_a_stale_staged_private_key_is_removed_and_reported(wiz, capsys):
    """FR-011: `--purge` never deleted this file, so merely stopping WRITING it would
    leave the exposure on every machine that ever used the flag."""
    stale = wiz.host_state_dir("local") / "acme.host_key"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    wiz.remove_stale_staged_host_key("local", "acme")
    assert not stale.exists()
    err = capsys.readouterr().err
    assert "removed a PRIVATE host key" in err  # never silent
    assert "treat it as exposed" in err  # they may have copies elsewhere


def test_removing_a_stale_key_is_silent_when_there_is_none(wiz, capsys):
    wiz.remove_stale_staged_host_key("local", "acme")
    assert capsys.readouterr().err == ""


# --- Constitution IX: delivery, not description ------------------------------


def test_split_routes_by_target_not_by_config_name(wiz):
    """The classifier keys on WHERE material lands, not what it is called.

    The target is the same string the entrypoint reads, so a new producer writing
    into the api-key directory is classified as secret without having to remember to
    name itself a certain way. A name-prefix rule would let a producer opt out of
    being treated as secret by accident.
    """
    entries = [
        ("innocuous_name", "sk-SECRET", f"{wiz.INJECT_APIKEY_DIR}/anthropic"),
        ("apikey_looking_name", "public", f"{wiz.INJECT_CONFIG_DIR}/.claude/x.json"),
    ]
    public, secrets = wiz.split_injected(entries)
    assert [t for t, _v in secrets] == [f"{wiz.INJECT_APIKEY_DIR}/anthropic"]
    assert [n for n, _c, _t in public] == ["apikey_looking_name"]


def test_a_failed_value_never_releases_the_wait(wiz, monkeypatch):
    """If a value fails to land, the container must NOT be told delivery finished."""
    seen: list = []

    def _fake_run(argv, **kw):
        seen.append(" ".join(argv))
        return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    monkeypatch.setattr(wiz.subprocess, "run", _fake_run)
    monkeypatch.setattr(wiz, "driver_runtime_argv", lambda h: ["docker"])
    with pytest.raises(wiz.Fatal):
        wiz.deliver_secrets("local", {}, "acme", [("/run/agent-container/apikeys/a", "1")])
    assert not any(".delivered" in c for c in seen), "released the wait after a failure"


def test_the_container_only_waits_when_there_is_something_to_wait_for(wiz, monkeypatch, tmp_path):
    """AGENT_CONTAINER_AWAIT_DELIVERY must be absent with no secrets declared.

    Otherwise every deployment that declares nothing would pay the wait, and the
    common path must be unaffected to the second.
    """
    captured: dict = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        wiz, "build_compose_model",
        lambda name, ctx, *a, **k: (
            captured.update(env=k.get("environment")),
            {"name": name, "services": {"agent": {}}, "volumes": {}},
        )[1],
    )  # fmt: skip
    for stub, val in (
        ("resolve_build_context", lambda *a, **k: tmp_path / "repo"),
        ("write_compose_file", lambda *a, **k: tmp_path / "c.yaml"),
        ("resolve_sidecar_override", lambda n: None),
        ("driver_up_argv", lambda *a, **k: ["true"]),
        ("port_free", lambda p: True),
        ("write_state", lambda *a, **k: None),
        ("driver_reachable_address", lambda r: "localhost"),
    ):
        monkeypatch.setattr(wiz, stub, val)
    wiz.compose_up_exec("local", {"driver": "docker", "context": ""}, "acme",
                        tmp_path / "acme.env", [], None, [])  # fmt: skip
    assert "AGENT_CONTAINER_AWAIT_DELIVERY" not in (captured["env"] or {})


def test_delivery_refuses_without_an_operator_declared_identity(wiz, monkeypatch):
    """The tool must NOT mint a key to solve its own auth problem.

    A tool-generated private key would be a standing credential on the operator's
    disk granting entry to every environment it deploys — a worse exposure than the
    delivery gap it would close. So an undeclared identity is a refusal with
    instructions, not a silent fallback to a channel we cannot secure.
    """
    monkeypatch.setattr(wiz, "delivery_identity", lambda cwd=None: None)
    ran: list = []
    monkeypatch.setattr(wiz.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(wiz.Fatal) as e:
        wiz.deliver_secrets("local", {}, "acme", [("/run/x", "sk-SECRET")])
    msg = str(e.value)
    assert "delivery_identity" in msg and "will not generate a key" in msg
    assert not ran, "attempted delivery with no identity"


def test_delivery_uses_ssh_with_the_agent_disabled(wiz, monkeypatch, tmp_path):
    """`-i` with IdentitiesOnly and IdentityAgent=none, and the TOOL-OWNED known_hosts.

    An approval-gated agent key must never be able to satisfy this auth instead, and
    the operator's own known_hosts is never touched (018).
    """
    ident = tmp_path / "id_delivery"
    ident.write_text("KEY")
    monkeypatch.setattr(wiz, "delivery_identity", lambda cwd=None: ident)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda h: "localhost")
    monkeypatch.setattr(wiz, "port_for_name", lambda n: 2222)
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    seen: list = []

    def _run(argv, **kw):
        seen.append((argv, kw.get("input")))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(wiz.subprocess, "run", _run)
    wiz.deliver_secrets("local", {}, "acme", [("/run/agent-container/apikeys/a", "sk-SECRET")])
    argv, stdin = seen[0]
    assert argv[0].endswith("ssh")
    assert "-i" in argv and str(ident) in argv
    assert "IdentitiesOnly=yes" in argv and "IdentityAgent=none" in argv
    assert f"UserKnownHostsFile={wiz.known_hosts_path('local')}" in argv
    assert stdin == b"sk-SECRET"
    assert "sk-SECRET" not in " ".join(argv)  # never on argv


def test_the_sentinel_is_written_last_over_ssh(wiz, monkeypatch, tmp_path):
    """Releasing the wait early would hand the container a partial set."""
    ident = tmp_path / "id"
    ident.write_text("K")
    monkeypatch.setattr(wiz, "delivery_identity", lambda cwd=None: ident)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda h: "localhost")
    monkeypatch.setattr(wiz, "port_for_name", lambda n: 2222)
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    order: list = []
    monkeypatch.setattr(
        wiz.subprocess, "run",
        lambda argv, **kw: (
            order.append("sentinel" if argv[-1] == "sentinel" else "value"),
            subprocess.CompletedProcess(argv, 0, b"", b""),
        )[1],
    )  # fmt: skip
    wiz.deliver_secrets("local", {}, "acme", [("/run/a", "1"), ("/run/b", "2")])
    assert order == ["value", "value", "sentinel"]


def test_delivery_identity_is_read_from_settings_and_absence_is_reported(wiz, tmp_path):
    """A reader reports absence; the caller decides what it means (Principle VIII)."""
    assert wiz.delivery_identity(tmp_path / "nowhere") is None
    wiz.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (wiz.CONFIG_DIR / "settings.yaml").write_text("delivery_identity: ~/.ssh/id_automation\n")
    got = wiz.delivery_identity(tmp_path / "nowhere")
    assert got is not None and got.name == "id_automation" and "~" not in str(got)


def test_delivery_calls_the_in_container_receiver_with_a_logical_ref(wiz, monkeypatch, tmp_path):
    """The CONTAINER owns the layout; the CLI hands over a ref and a value.

    Without this seam the CLI would have to know in-container paths, and every change
    to them would be a change to the deployment side too. The value stays on stdin.
    """
    ident = tmp_path / "id"
    ident.write_text("K")
    monkeypatch.setattr(wiz, "delivery_identity", lambda cwd=None: ident)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda h: "localhost")
    monkeypatch.setattr(wiz, "port_for_name", lambda n: 2222)
    monkeypatch.setattr(wiz, "query", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    seen: list = []
    monkeypatch.setattr(
        wiz.subprocess, "run",
        lambda argv, **kw: (seen.append((argv, kw.get("input"))),
                            subprocess.CompletedProcess(argv, 0, b"", b""))[1],
    )  # fmt: skip
    wiz.deliver_secrets("local", {}, "acme", [(f"{wiz.INJECT_APIKEY_DIR}/anthropic", "sk-SECRET")])
    argv, stdin = seen[0]
    assert argv[-2:] == [wiz.RECEIVE_SECRET_BIN, "apikey/anthropic"]  # a REF, not a path
    assert stdin == b"sk-SECRET"
    assert "sk-SECRET" not in " ".join(argv)
    assert seen[-1][0][-1] == "sentinel"  # released last


def test_the_receiver_refuses_a_traversing_ref():
    """The script's charset bars '.' entirely, so '..' cannot appear."""
    import re

    body = pathlib.Path("image/receive-secret.sh").read_text()
    m = re.search(r"\[\[ \"\$\{ref\}\" =~ (\^\S+\$) \]\]", body)
    assert m, "the ref guard is gone"
    pat = re.compile(m.group(1))
    for bad in ("../etc/passwd", "apikey/../../x", "a/./b", "/abs", "APIKEY/x", "a/b/c"):
        assert not pat.fullmatch(bad), f"guard accepted {bad!r}"
    for good in ("apikey/anthropic", "sentinel", "apikey/open-ai_2"):
        assert pat.fullmatch(good), f"guard rejected {good!r}"


# --- R8: credentials PERSIST, on one volume each ------------------------------


def test_a_credential_volume_is_named_from_its_ref(wiz):
    """The NAME is the lifecycle handle (Principle IV, and the operator's point).

    One volume per credential rather than one shared volume, so
    `docker volume rm agent-container-acme-cred-apikey-anthropic` revokes exactly one
    credential and touches nothing else — not the ssh volume, not the others.
    """
    assert wiz.cred_volume_name("acme", "apikey/anthropic") == (
        "agent-container-acme-cred-apikey-anthropic"
    )
    assert wiz.cred_volume_name("acme", "apikey/openai").startswith(wiz.cred_volume_prefix("acme"))
    # Distinct credentials never collide onto one volume.
    assert wiz.cred_volume_name("acme", "apikey/a") != wiz.cred_volume_name("acme", "apikey/b")


def test_credential_volumes_are_declared_and_mounted_but_not_in_the_identity_contract(wiz):
    """Dynamic, so they are NOT in the fixed ten-volume list — found by prefix instead.

    Putting them in `per_container_volumes` would make the identity contract depend on
    which credentials happen to be declared, which is exactly what that contract is
    for pinning against.
    """
    m = wiz.build_compose_model("acme", "/repo", cred_refs=["apikey/anthropic"])
    vol = wiz.cred_volume_name("acme", "apikey/anthropic")
    assert m["volumes"][vol] == {"name": vol}
    assert f"{vol}:{wiz.SECRETS_DIR}/apikey/anthropic" in m["services"]["agent"]["volumes"]
    assert vol not in wiz.per_container_volumes("acme")


def test_no_credentials_declares_no_credential_volumes(wiz):
    """A deployment without credentials is byte-identical to before."""
    m = wiz.build_compose_model("acme", "/repo")
    assert not [v for v in m["volumes"] if wiz.CRED_VOLUME_INFIX in v]


def test_reconcile_removes_only_undeclared_credential_volumes(wiz, monkeypatch):
    """PERSISTENCE WITHOUT RECONCILIATION IS THE UNION BUG AGAIN.

    A volume outlives the container, so without pruning, a credential the operator
    stopped declaring would still be mounted — config says gone, container still has
    it. The declaration stays the authority because every deploy prunes what it no
    longer names, the same rule as the managed region.
    """
    keep = wiz.cred_volume_name("acme", "apikey/anthropic")
    drop = wiz.cred_volume_name("acme", "apikey/openai")
    other = "agent-container-acme-ssh"  # must never be touched
    monkeypatch.setattr(
        wiz, "query",
        lambda argv, **k: subprocess.CompletedProcess(
            argv, 0, "\n".join([keep, drop, other]) if "ls" in argv else "", ""
        ),
    )  # fmt: skip
    removed: list = []
    real_query = wiz.query

    def _q(argv, **k):
        if argv[-2:-1] == ["rm"] or "rm" in argv:
            removed.append(argv[-1])
        return real_query(argv, **k)

    monkeypatch.setattr(wiz, "query", _q)
    got = wiz.reconcile_cred_volumes({"driver": "docker", "context": ""}, "acme",
                                     ["apikey/anthropic"])  # fmt: skip
    assert got == [drop]
    assert removed == [drop], f"touched more than the undeclared volume: {removed}"
    assert other not in removed


def test_reconcile_with_nothing_declared_removes_them_all(wiz, monkeypatch):
    """The revocation path: stop declaring a credential and it goes."""
    vol = wiz.cred_volume_name("acme", "apikey/anthropic")
    monkeypatch.setattr(
        wiz, "query",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, vol if "ls" in argv else "", ""),
    )  # fmt: skip
    assert wiz.reconcile_cred_volumes({"driver": "docker", "context": ""}, "acme", []) == [vol]


# --- `creds` — revoking through the tool, not through the runtime -------------


def test_held_refs_come_from_the_volumes_not_the_config(wiz, monkeypatch):
    """Read from the VOLUMES, because the two can differ — and that is the point.

    A credential still held but no longer declared is exactly what an operator needs
    to see; asking the config would only ever confirm the config.
    """
    vol = wiz.cred_volume_name("acme", "apikey/anthropic")
    monkeypatch.setattr(
        wiz, "query",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, vol if "ls" in argv else "", ""),
    )  # fmt: skip
    assert wiz.held_cred_refs({"driver": "docker", "context": ""}, "acme") == ["apikey/anthropic"]


def test_revoke_deletes_in_the_running_container_and_drops_the_volume(wiz, monkeypatch, tmp_path):
    """BOTH, because either alone is incomplete.

    Deleting the value takes effect on a RUNNING environment — which `docker volume
    rm` cannot do while the volume is in use, and which is the case an operator
    actually cares about. Dropping the volume stops it coming back on restart.
    """
    ident = tmp_path / "id"
    ident.write_text("K")
    monkeypatch.setattr(wiz, "delivery_identity", lambda cwd=None: ident)
    monkeypatch.setattr(wiz, "driver_reachable_address", lambda h: "localhost")
    monkeypatch.setattr(wiz, "port_for_name", lambda n: 2222)
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *a, **k: True)
    seen: list = []

    def _q(argv, **k):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(wiz, "query", _q)
    deleted, dropped = wiz.revoke_cred("local", {"driver": "docker", "context": ""},
                                       "acme", "apikey/anthropic")  # fmt: skip
    assert deleted and dropped
    # Deletion goes through the in-container receiver: the CLI names a CREDENTIAL,
    # never a path, so the container keeps owning its layout.
    assert any(a[-3:] == [wiz.RECEIVE_SECRET_BIN, "-r", "apikey/anthropic"] for a in seen)
    assert any(a[-2:] == ["volume", "rm"] or "rm" in a for a in seen)


def test_revoke_says_so_when_it_cannot_delete_inside_a_running_container(wiz, monkeypatch):
    """A value still live in a running container must not read as a clean revocation."""
    monkeypatch.setattr(wiz, "delivery_identity", lambda cwd=None: None)
    monkeypatch.setattr(wiz, "runtime_container_exists", lambda *a, **k: True)
    monkeypatch.setattr(
        wiz, "query", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", "")
    )
    warned: list = []
    monkeypatch.setattr(wiz, "warn", lambda m: warned.append(m))
    deleted, _ = wiz.revoke_cred("local", {"driver": "docker", "context": ""}, "acme", "apikey/x")
    assert deleted is False
    assert any("still live" in w for w in warned)
