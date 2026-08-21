"""Feature 017 — the control plane, and the dual-stack observability it widened to.

Hermetic tests only. What lives here is what a real container cannot show more
cheaply than a function call can: the export-state transitions, the single
payload definition, the provenance closure, the semver rule, and scope
resolution. The absences — a passphrase that exists nowhere, an image with no
agents, a `collect` that names an unreachable host — are in the acceptance tier,
because an absence is never demonstrated by working output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# --- the ONE payload definition (FR-009e/FR-009f, T044/T045) -----------------


def test_there_is_exactly_ONE_payload_definition(wiz):
    """FR-009f, data-model §6: both legs read one field set.

    Asserted on the SHARED CONSTANT rather than by comparing two lists that
    happen to agree today. Two lists are precisely the failure mode — they drift
    the moment one is edited, and the drift is invisible because each leg still
    looks correct on its own. Nothing fails until someone compares them, which
    is what SC-020 does and what it could not do if the legs carried different
    things.
    """
    # Derived, not duplicated: the payload comes OUT of the provenance table.
    assert set(wiz.RECORD_PAYLOAD_FIELDS) <= set(wiz.RECORD_FIELD_PROVENANCE)
    # And every non-excluded provenance field IS in the payload, so adding a
    # field to the table cannot silently fail to reach either leg.
    expected = set(wiz.RECORD_FIELD_PROVENANCE) - wiz._PAYLOAD_EXCLUDED
    assert set(wiz.RECORD_PAYLOAD_FIELDS) == expected


def test_the_payload_carries_run_id_unconditionally(wiz):
    """SC-019/C18f: `run_id` exports whatever the `task` setting is.

    Correlation is what makes excluding the task text cheap rather than lossy:
    without it, the exclusion removes the reason to look at the record at all.
    """
    assert "run_id" in wiz.RECORD_PAYLOAD_FIELDS


def test_the_payload_carries_the_task_by_default(wiz):
    """FR-009f0/C18a: a task is NOT a credential channel, so its text is exported.

    Credentials arrive by injection; the single exception is the SSH keys a
    container generates itself. Withholding the task would design around an
    operator error the tool already provides the correct alternative for — and it
    is the most useful field for "this run failed, what was it doing", on a
    phone, with no laptop to correlate against.
    """
    assert "task" in wiz.RECORD_PAYLOAD_FIELDS


# --- `build` and the two images (T004) ---------------------------------------


def test_build_REFUSES_the_control_plane_image_without_a_resolvable_version(wiz):
    """The control-plane image PINS the CLI it installs, so building it without a
    resolvable version would need a default — and a default is a pin that goes
    stale on every release. The first version of that Dockerfile defaulted to
    0.31.0 and 0.32.0 shipped the same day, which would have installed a CLI older
    than the tree it was built from while the image carried no label to say so.

    The agent image is deliberately NOT refused: it carries no CLI, so an absent
    version label there is honestly *unknown* and costs nothing.
    """
    body = _func_body(Path(wiz.__file__).read_text(), "do_build")
    skip = body.index("skipping the control-plane image")
    # The refusal is conditioned on the stamp, not on the directory existing.
    assert "elif not stamped:" in body[:skip]
    assert "AGENT_CONTAINER_PYPI_VERSION" in body


def test_the_control_plane_dockerfile_has_NO_default_version(wiz):
    """Asserted on the file, because the CLI's refusal and the Dockerfile's
    default are two independent ways to end up installing a version nobody chose,
    and closing one says nothing about the other."""
    df = (Path(wiz.__file__).parents[1] / "image-control-plane" / "Dockerfile").read_text()
    assert "ARG AGENT_CONTAINER_PYPI_VERSION=\n" in df, (
        "the pinned CLI version has a DEFAULT, which goes stale on every release"
    )
    assert 'if [ -z "${AGENT_CONTAINER_PYPI_VERSION}" ]' in df, (
        "a bare `docker build` with no version would install whatever pip resolves"
    )


# --- the closure that IS the no-credentials claim (FR-009c, T046) ------------


def test_attribution_adds_no_second_operator_field(wiz):
    """FR-009c, C18e: EXACTLY ONE `operator` row in the whole table.

    Asserted on the table itself, not on a sample record. That single row is the
    no-credentials claim: a second free-text field would falsify it while every
    other test in this suite still passed, because every other test looks at
    values and this one looks at the shape.
    """
    operator_fields = sorted(
        f for f, prov in wiz.RECORD_FIELD_PROVENANCE.items() if prov == "operator"
    )
    assert operator_fields == ["task"], (
        f"expected exactly one operator-authored field ('task'), found "
        f"{operator_fields}. A second free-text field opens a second place a "
        f"credential can arrive, and falsifies FR-009c's closure."
    )


def test_every_new_017_field_is_tool_provenance(wiz):
    """The fields this feature added must not widen the operator surface."""
    for field in ("attribution", "egress_decision", "export_state"):
        assert wiz.RECORD_FIELD_PROVENANCE[field] == "tool"


def test_the_passphrase_has_no_slot_in_the_record(wiz):
    """T013, data-model §3: asserted STRUCTURALLY, not by grepping one run.

    The passphrase is the one thing in the data model with no durable
    representation on purpose. Grepping a sample record proves that record is
    clean; asserting on the closed field set proves there is nowhere to put it.
    """
    fields = " ".join(wiz.RECORD_FIELD_PROVENANCE).lower()
    for forbidden in ("passphrase", "password", "secret", "key"):
        assert forbidden not in fields, (
            f"a record field name contains {forbidden!r} — the passphrase and its "
            f"kin must have no slot in the payload at all"
        )
    assert "passphrase" not in " ".join(wiz.RECORD_PAYLOAD_FIELDS).lower()


# --- the export state (FR-009h/FR-009i, T049-T054) --------------------------


def test_four_states_and_no_more(wiz):
    """data-model §7. An `ingested`/`confirmed` state is deliberately absent: it
    is not observable without querying a backend, which FR-009d forbids."""
    assert wiz.EXPORT_STATES == ("pending", "accepted", "rejected", "failed")
    assert "ingested" not in wiz.EXPORT_STATES
    assert "confirmed" not in wiz.EXPORT_STATES


def test_rejected_and_failed_stay_DISTINCT(wiz):
    """T054, C15, R10, S20 — they decide whether a retry is worth attempting.

    A refusal will be refused again unchanged; an unreachable endpoint may simply
    be back later. Collapsing them would either retry forever against a refusal
    or abandon a recoverable record — and both failures look like working
    software until someone counts.
    """
    assert wiz.EXPORT_REJECTED != wiz.EXPORT_FAILED
    assert wiz.export_state_is_retryable(wiz.EXPORT_FAILED)
    assert not wiz.export_state_is_retryable(wiz.EXPORT_REJECTED)


def test_accepted_and_rejected_are_TERMINAL(wiz):
    """Re-exporting an accepted record duplicates it at the collector;
    re-exporting a rejected one repeats a refusal."""
    for terminal in (wiz.EXPORT_ACCEPTED, wiz.EXPORT_REJECTED):
        assert wiz.EXPORT_TRANSITIONS[terminal] == frozenset()
        for target in wiz.EXPORT_STATES:
            assert not wiz.export_transition_is_legal(terminal, target)


def test_failed_returns_to_pending_on_a_collect_retry(wiz):
    """R10/T068: what makes `collect` the recovery path, not only a downloader."""
    assert wiz.export_transition_is_legal(wiz.EXPORT_FAILED, wiz.EXPORT_PENDING)


@pytest.mark.parametrize(
    ("status", "rejected", "records", "expect"),
    [
        (200, 0, 1, "accepted"),
        (204, 0, 1, "accepted"),
        # A 2xx IS NOT ACCEPTANCE. This row is the whole point of the function.
        (200, 1, 1, "rejected"),
        (200, 5, 5, "rejected"),
        # Partially refused batch: it cannot tell WHICH record, so it does not guess.
        (200, 1, 5, "pending"),
        (400, 0, 1, "rejected"),
        (404, 0, 1, "rejected"),
        (422, 0, 1, "rejected"),
        # Transient 4xx are retryable despite being 4xx.
        (408, 0, 1, "failed"),
        (429, 0, 1, "failed"),
        (500, 0, 1, "failed"),
        (503, 0, 1, "failed"),
        (None, 0, 1, "failed"),
    ],
)
def test_state_is_derived_from_the_RESPONSE(wiz, status, rejected, records, expect):
    """FR-009i/C14/R9 — never from the fact that an export was attempted."""
    assert wiz.export_outcome_from_response(status, rejected, records) == expect


def test_a_2xx_with_a_rejected_count_is_NOT_accepted(wiz):
    """T051, stated as its own test because it is the naive implementation.

    OTLP's export response carries `partial_success` with a rejected-record
    count. An implementation that treats 2xx as success marks refused records as
    delivered — and the local leg then claims a delivery the collector never
    made, which is exactly the divergence SC-020 exists to detect. Only a
    collector CONFIGURED TO REFUSE exposes this; a compliant one passes either
    way, which is why SC-021 specifies a refusing collector.
    """
    assert wiz.export_outcome_from_response(200, partial_rejected=1) != wiz.EXPORT_ACCEPTED


def test_the_state_never_claims_backend_arrival(wiz):
    """C14: `accepted` means the CONFIGURED ENDPOINT returned success, nothing more.

    Checked in the DOCSTRING as well as the values, because the failure mode here
    is a later reader naming it "delivered" or "ingested" and quietly changing
    what the field asserts. Establishing arrival needs the backend's own API —
    the vendor coupling FR-009d forbids.
    """
    doc = wiz.export_outcome_from_response.__doc__ or ""
    assert "nothing more" in doc.lower()
    assert "not acceptance" in doc.lower()


# --- the two-level settings contract (FR-009d, T058/T059) -------------------


def _settings(tmp_path, monkeypatch, wiz, *, project=None, user=None):
    """A tree with either/both settings levels populated."""
    import textwrap

    proj = tmp_path / "proj"
    (proj / ".agent-container").mkdir(parents=True)
    if project is not None:
        (proj / ".agent-container" / "settings.yaml").write_text(textwrap.dedent(project))
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    if user is not None:
        (cfg / "settings.yaml").write_text(textwrap.dedent(user))
    monkeypatch.setattr(wiz, "CONFIG_DIR", cfg)
    return proj


def test_project_settings_override_user_settings(wiz, tmp_path, monkeypatch):
    proj = _settings(
        tmp_path,
        monkeypatch,
        wiz,
        project="otlp_endpoint: https://project.example/v1/logs\n",
        user="otlp_endpoint: https://user.example/v1/logs\n",
    )
    assert wiz.resolve_settings_key("otlp_endpoint", proj) == "https://project.example/v1/logs"


def test_a_deployment_outside_any_project_resolves_the_USER_endpoint(wiz, tmp_path, monkeypatch):
    """C18g: project-level-only declaration would leave every container outside a
    project with no endpoint at all — and C18d requires each container to export
    its own, control plane or not, project or not."""
    _settings(tmp_path, monkeypatch, wiz, user="otlp_endpoint: https://user.example/v1/logs\n")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert wiz.resolve_settings_key("otlp_endpoint", outside) == "https://user.example/v1/logs"


def test_a_project_setting_does_not_unset_an_unmentioned_user_setting(wiz, tmp_path, monkeypatch):
    """Precedence is per-KEY, and this is the difference that matters.

    If the winning FILE won entirely, a project declaring only
    `control_plane_hosts` would silently unset a user-level `otlp_endpoint` it
    never mentioned — and the operator would find export had stopped with nothing
    saying so.
    """
    proj = _settings(
        tmp_path,
        monkeypatch,
        wiz,
        project="control_plane_hosts: [vps1]\n",
        user="otlp_endpoint: https://user.example/v1/logs\n",
    )
    assert wiz.resolve_settings_key("control_plane_hosts", proj) == ["vps1"]
    assert wiz.resolve_settings_key("otlp_endpoint", proj) == "https://user.example/v1/logs"


def test_an_undeclared_key_is_None_not_empty(wiz, tmp_path, monkeypatch):
    """Absent is not the same as declared-empty: `allow: []` means nothing is
    permitted, absence means no declaration exists. Feature 012 learned this."""
    proj = _settings(tmp_path, monkeypatch, wiz, project="control_plane_hosts: []\n")
    assert wiz.resolve_settings_key("otlp_endpoint", proj) is None
    assert wiz.resolve_settings_key("control_plane_hosts", proj) == []


def test_settings_are_parsed_with_a_real_parser(wiz, tmp_path, monkeypatch):
    """Flow style and quoted keys must resolve — a regex scanner silently misses
    both, and this project has already shipped that bug once."""
    proj = _settings(
        tmp_path, monkeypatch, wiz, project='{"otlp_endpoint": "https://flow.example/v1"}\n'
    )
    assert wiz.resolve_settings_key("otlp_endpoint", proj) == "https://flow.example/v1"


# --- the role, and what it refuses (FR-001/FR-015a, T005) -------------------


def test_control_plane_role_refuses_headless(wiz):
    """FR-015a: no agent is installed, so a headless request must fail loudly
    rather than deploy a container that cannot do what was asked."""
    spec = wiz.ExecSpec(role=wiz.ROLE_CONTROL_PLANE, mode="headless")
    with pytest.raises(wiz.Fatal, match="installs no agent"):
        spec.validate()


def test_control_plane_role_refuses_a_named_agent(wiz):
    spec = wiz.ExecSpec(role=wiz.ROLE_CONTROL_PLANE, agent="opencode")
    with pytest.raises(wiz.Fatal, match="no agent CLI is installed"):
        spec.validate()


def test_control_plane_role_ACCEPTS_the_default_agent_value(wiz):
    """The distinction that keeps the refusal usable: `--agent` keeps its default
    in this role and is never read, so refusing the DEFAULT too would reject
    every ordinary `up --role control-plane`."""
    wiz.ExecSpec(role=wiz.ROLE_CONTROL_PLANE).validate()


def test_control_plane_role_refuses_a_task(wiz):
    spec = wiz.ExecSpec(role=wiz.ROLE_CONTROL_PLANE, task="do a thing")
    with pytest.raises(wiz.Fatal, match="no agent to give a task to"):
        spec.validate()


def test_an_unknown_role_is_refused(wiz):
    with pytest.raises(wiz.Fatal, match="--role must be one of"):
        wiz.ExecSpec(role="supervisor").validate()


# --- provenance (FR-014a, T040) ---------------------------------------------


def test_provenance_is_operator_on_the_operators_machine(wiz, monkeypatch):
    monkeypatch.delenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", raising=False)
    assert wiz.deploy_provenance() == "operator"


def test_provenance_names_the_control_plane_it_was_deployed_from(wiz, monkeypatch):
    """SC-011: nesting lets standing keys grow from inside the system, and a
    count nobody can see is a count nobody audits."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub")
    assert wiz.deploy_provenance() == "control-plane:hub"


def test_provenance_VALIDATES_the_name_rather_than_trusting_it(wiz, monkeypatch):
    """The inventory's guarantee is that every field is tool-generated, so there
    is nowhere for a credential to arrive (FR-010). An env var is settable by
    whoever runs the CLI, so passing it through unchecked would put
    operator-controlled free text into the field set pinned closed to prevent
    exactly that — and the closure test would still pass, because it checks WHICH
    fields exist and not what they may contain.
    """
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub; export TOKEN=abc")
    assert wiz.deploy_provenance() == "control-plane:unknown"


def test_the_inventory_entry_carries_role_and_provenance(wiz, monkeypatch):
    """Persisted, so a STOPPED control plane is still identifiable — which
    inspecting the container could not tell you, the container being exactly what
    is not running."""
    monkeypatch.delenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", raising=False)
    e = wiz.build_inventory_entry("hub", "local", True, role=wiz.ROLE_CONTROL_PLANE)
    assert e["role"] == "control-plane"
    assert e["provenance"] == "operator"
    assert tuple(e) == wiz.INVENTORY_FIELDS


# --- the passphrase read-out (FR-007, C4, R3, T011) -------------------------


def _func_body(src: str, name: str) -> str:
    """A function's source, sliced to the next top-level `def` rather than a
    fixed character count — a magic window silently shrinks the assertion every
    time the code grows, which has cost this project four false failures."""
    i = src.index(f"\ndef {name}(")
    j = src.index("\ndef ", i + 1)
    return src[i:j]


def test_the_passphrase_reader_returns_a_BOOLEAN_not_the_value(wiz):
    """R3: the value must not outlive the printing call's scope.

    A function that returned it would put it in the caller's frame, and from
    there into whatever the caller does next — a log line, a record, a `--json`
    payload. The boolean says whether one was printed, which is all a caller can
    legitimately act on.
    """
    body = _func_body(Path(wiz.__file__).read_text(), "print_control_plane_passphrase_once")
    assert "-> bool:" in body
    returns = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("return ")]
    assert returns, "expected explicit returns"
    assert all(r in ("return True", "return False") for r in returns), (
        f"print_control_plane_passphrase_once returns something other than a "
        f"boolean: {returns}. The passphrase must not leave this call."
    )


def test_the_passphrase_is_never_passed_to_log_or_warn(wiz):
    """It goes to stdout, once. `log()`/`warn()` are the tool's own output path,
    which is captured, prefixed and in some modes redirected — and a secret in
    that path is a secret in whatever collects it."""
    body = _func_body(Path(wiz.__file__).read_text(), "print_control_plane_passphrase_once")
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "lines[i + 1]" in stripped:
            assert not stripped.startswith(("log(", "warn(")), (
                f"the passphrase value reaches the tool's log path: {stripped}"
            )


def test_the_sentinels_are_matched_exactly(wiz):
    """A looser parse could scrape an adjacent log line into a password manager,
    and the value's whole purpose is that it is the only copy."""
    body = _func_body(Path(wiz.__file__).read_text(), "print_control_plane_passphrase_once")
    # Exact list membership, not a substring scan or a regex over the log.
    assert "lines.index(_PASSPHRASE_BEGIN)" in body
    assert "j != i + 2" in body, (
        "the block's shape is not validated, so a malformed block could print the wrong line"
    )


def test_the_entrypoint_generates_an_ENCRYPTED_key(wiz):
    """FR-007/C3: `-N "${passphrase}"`, not the agent image's `-N ''`.

    That single difference IS the feature: an unencrypted key on this volume
    means possessing the volume is possessing the fleet.
    """
    ep = (Path(wiz.__file__).parents[1] / "image-control-plane" / "entrypoint.sh").read_text()
    assert '-N "${_cp_passphrase}"' in ep
    assert "-N ''" not in ep.split("CONTROL_PLANE_KEY=")[1], (
        "the control-plane key is generated with an EMPTY passphrase somewhere "
        "after the key path is set"
    )


def test_the_entrypoint_never_logs_the_passphrase(wiz):
    """`log()` writes to stderr, which the runtime captures into the container
    log — durable, and nothing rotates it."""
    ep = (Path(wiz.__file__).parents[1] / "image-control-plane" / "entrypoint.sh").read_text()
    for line in ep.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "_cp_passphrase" in stripped:
            assert not stripped.startswith("log "), f"passphrase reaches log(): {stripped}"
            assert not stripped.startswith("log("), f"passphrase reaches log(): {stripped}"
