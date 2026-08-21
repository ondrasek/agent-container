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


# --- the semver rule (FR-016, C10, T037) -------------------------------------


def test_pre_1_0_the_BREAKING_CHANNEL_IS_MINOR(wiz):
    """T037: `major_on_zero = false`, so pre-1.0 a breaking change lands as MINOR.

    Not obvious from the numbers, which is exactly why it is tested rather than
    assumed. Get this wrong and 0.31 vs 0.32 reads as compatible — a control
    plane confidently driving an environment across a breaking change.
    """
    assert wiz.breaking_channel((0, 31, 9)) != wiz.breaking_channel((0, 32, 0))
    # And post-1.0 the minor is NOT the channel, or every feature release would
    # refuse.
    assert wiz.breaking_channel((1, 2, 0)) == wiz.breaking_channel((1, 9, 0))


@pytest.mark.parametrize(
    ("cp", "env", "expect"),
    [
        # PATCH differences are ignored ENTIRELY — not warned about. This is the
        # common case after any `fix` release, and reporting it would train the
        # operator to ignore the report that matters.
        ("0.32.0", "0.32.5", "ok"),
        ("0.32.9", "0.32.0", "ok"),
        # Post-1.0 minor is not the breaking channel.
        ("1.4.0", "1.9.9", "ok"),
        # Control plane NEWER: advisory. The normal state after an upgrade.
        ("0.33.0", "0.32.0", "advisory"),
        ("2.0.0", "1.9.9", "advisory"),
        # Environment NEWER: REFUSED. Where interfaces the control plane does not
        # know about may exist.
        ("0.32.0", "0.33.0", "refused"),
        ("1.9.9", "2.0.0", "refused"),
        # A pre-1.0 control plane is older than any 1.x, whatever the minor says.
        ("0.99.0", "1.0.0", "refused"),
        ("1.0.0", "0.99.0", "advisory"),
        # Unreadable on either side: unknown, NEVER assumed compatible.
        (None, "0.32.0", "unknown"),
        ("0.32.0", None, "unknown"),
        ("garbage", "0.32.0", "unknown"),
        ("0.32", "0.32.0", "unknown"),
    ],
)
def test_version_verdict_by_precedence(wiz, cp, env, expect):
    assert wiz.version_verdict(cp, env) == expect


def test_the_unknown_SENTINEL_is_not_treated_as_version_zero(wiz):
    """`_resolve_version()` returns "0.0.0+unknown" when it cannot tell.

    Discarding build metadata would turn that into the genuine version 0.0.0 —
    the lowest there is — so every environment would read as newer and every
    comparison would REFUSE. A safety check that refuses everything is one people
    route around, so this failure mode is worse than being wrong in one case.
    """
    assert wiz.parse_semver("0.0.0+unknown") is None
    assert wiz.version_verdict("0.0.0+unknown", "0.32.0") == wiz.VERSION_UNKNOWN
    # And a REAL 0.0.0 is still a version, so the sentinel check must be exact.
    assert wiz.parse_semver("0.0.0") == (0, 0, 0)


def test_ok_says_nothing_at_all(wiz):
    """Silence, not a quiet message. A line per patch bump is the noise that
    makes the refusal invisible."""
    assert wiz.version_verdict_message("acme", wiz.VERSION_OK, "0.32.0", "0.32.1") is None


def test_a_refusal_NAMES_REDEPLOY(wiz):
    """C10/SC-012. A refusal that does not say what would fix it converts a
    safety check into a dead end, and the operator's next move is to reach for
    whatever bypass exists."""
    msg = wiz.version_verdict_message("acme", wiz.VERSION_REFUSED, "0.32.0", "0.33.0")
    assert msg is not None
    assert "redeploy" in msg.lower()
    assert "0.33.0" in msg and "0.32.0" in msg


def test_unknown_does_not_claim_compatibility(wiz):
    msg = wiz.version_verdict_message("acme", wiz.VERSION_UNKNOWN, None, "0.32.0")
    assert msg is not None
    assert "not assumed compatible" in msg.lower()


# --- export mechanics (FR-009d/FR-009g, C16, C18a-c, T055-T058, T062-T063) ---


def _entrypoint(wiz, image="image"):
    return (Path(wiz.__file__).parents[1] / image / "entrypoint.sh").read_text()


def _code_lines(text: str) -> str:
    """Shell source with comment lines removed.

    These scans look for what the script DOES. The export block explains at
    length what it deliberately does not do — it names `opentelemetry` and
    "entropy" precisely to say they are not reached for — so scanning raw text
    would fail on the documentation of the property being asserted.
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))


def _otlp_block(wiz) -> str:
    """The export block, BOUNDED. It sits before the authorized_keys shared block
    in the file, so slicing to end-of-file would pull in unrelated sentinels."""
    ep = _entrypoint(wiz)
    start = ep.index("# --- OTLP export")
    end = ep.index("# Complete the record.", start)
    return ep[start:end]


def test_export_is_curl_and_adds_no_python_package(wiz):
    """C18b/R5: OTLP/HTTP+JSON is a POST of a JSON document, and curl already
    ships. Zero Python packages, zero image additions — and NO backend-specific
    package, ever, which is the condition the OTel dependency was accepted under.
    """
    ep = _entrypoint(wiz)
    assert "curl -sS -m" in ep
    # The export path must not reach for a telemetry SDK.
    for banned in ("opentelemetry", "pip install", "npm i -g"):
        assert banned not in _code_lines(_otlp_block(wiz)), (
            f"the export path references {banned!r}; the dependency-free path is "
            "the condition FR-009d set"
        )


def test_export_fires_at_WRITE_TIME_after_the_record_is_durable(wiz):
    """FR-009g/C16. Not batched at exit, not on a timer: anything held for later
    is lost exactly when a container is killed, which is the case an audit trail
    exists for.

    And AFTER the rename, not before — exporting first would risk a record at the
    collector that the local leg never had, the one divergence SC-020 cannot
    explain.
    """
    ep = _entrypoint(wiz)
    body = ep[ep.index("runs_emit() {") : ep.index("# --- OTLP export")]
    rename = body.index('mv -f "${tmp}" "${final}"')
    export = body.index("runs_otlp_export")
    assert rename < export, "export fires before the record is durable"


def test_the_unreachable_case_is_RETRYABLE_not_terminal(wiz):
    """curl writes 000 to %{http_code} when it never got a status line, and 000
    is ALL DIGITS — so a numeric guard does not catch it.

    It fell through to the catch-all and was marked `rejected`, which is
    terminal: a collector that was merely down would have permanently discarded
    every record written while it was down. Found by pointing the exporter at a
    closed port and reading the state, which is the only way it surfaces — the
    export "worked" either way.
    """
    ep = _entrypoint(wiz)
    assert '""|000|*[!0-9]*)' in ep, (
        "the no-response branch does not name 000, so an unreachable endpoint "
        "falls through to the terminal branch and is never retried"
    )


def test_a_2xx_is_subtracted_before_anything_is_accepted(wiz):
    """T051/C14/R9, asserted in the SHELL leg too. The Python helper honouring
    partial_success says nothing about the exporter that actually runs."""
    ep = _entrypoint(wiz)
    assert "partialSuccess.rejectedLogRecords" in ep
    accepted_at = ep.index('state="accepted"')
    subtract_at = ep.index("partialSuccess.rejectedLogRecords")
    assert subtract_at < accepted_at, (
        "the rejected count is read AFTER the accepted state is set, so refused "
        "records would be recorded as delivered"
    )


def test_export_never_fails_the_run(wiz):
    """C18c: fail-open, always. An export that could fail the run would make
    observability a reason for work not to happen — and under enforced egress an
    undeclared collector would then break every container rather than merely
    leaving the trail local."""
    ep = _entrypoint(wiz)
    fn = ep[ep.index("runs_otlp_export() {") :]
    fn = fn[: fn.index("\n}\n")]
    # Every exit from the exporter is a success. A `return 1` would propagate
    # into runs_emit under `set -e`.
    assert "return 1" not in fn
    assert 'runs_otlp_export "${final}" || true' in ep


def test_the_task_is_stripped_BY_NAME_never_by_pattern(wiz):
    """FR-009f/T063. The tool cannot know whether the collector is the operator's
    own VPS or a shared backend, and a redactor that misses one value converts
    caution into false confidence — whereas omitting a named field either happens
    or it does not."""
    ep = _entrypoint(wiz)
    assert "del(.task)" in ep
    # No heuristic redaction anywhere near the export path.
    export_path = _code_lines(_otlp_block(wiz))
    for heuristic in ("entropy", "[A-Za-z0-9]{20", "ghp_", "sk-", "sed -E s/"):
        assert heuristic not in export_path, (
            f"the export path contains a pattern-based redactor ({heuristic!r})"
        )


def test_run_id_is_exported_whatever_the_task_setting(wiz):
    """C18f/SC-019: correlation is what makes excluding the task cheap rather
    than lossy. Without it the exclusion removes the reason to look at the record
    at all."""
    ep = _entrypoint(wiz)
    payload = (
        ep[ep.index("runs_otlp_payload() {") : ex]
        if (ex := ep.index("runs_otlp_export() {"))
        else ep
    )
    # run_id is read from the record AFTER the task filter is applied, so it
    # survives the exclusion by construction rather than by a second copy.
    assert "$rec.run_id" in payload
    assert payload.index("del(.task)") < payload.index("$rec.run_id")


def test_an_undeclared_endpoint_leaves_the_record_PENDING(wiz):
    """Not `failed`. `pending` is what `telemetry collect` retries, so declaring
    an endpoint later still exports what was written before it existed —
    `failed` would be a claim that an attempt was made."""
    ep = _entrypoint(wiz)
    fn = ep[ep.index("runs_otlp_export() {") :]
    guard = fn[: fn.index("payload=")]
    assert '[[ -n "${endpoint}" ]] || return 0' in guard
    assert 'state="failed"' not in guard


def test_the_otlp_block_claims_no_drift_guard_it_does_not_have(wiz):
    """A SHARED-BLOCK sentinel around a block that exists in ONE file would claim
    a guarantee no guard provides, and that reads as coverage.

    The control-plane image writes no run records in shell, so a copy there would
    be dead code. The block says so instead of being marked shared.
    """
    assert "SHARED-BLOCK BEGIN" not in _otlp_block(wiz), (
        "the export block carries a shared-block sentinel but exists in one file"
    )
    # And the block SAYS why, so the next reader does not add one.
    assert "would be dead code" in _otlp_block(wiz)
    assert "runs_otlp_export" not in _entrypoint(wiz, "image-control-plane")


# --- the endpoint and the task switch, operator side (T058, T062) ------------


def test_an_endpoint_without_a_scheme_is_REFUSED_not_prefixed(wiz, tmp_path, monkeypatch):
    """Guessing the scheme would decide, on the operator's behalf, whether an
    audit trail crosses the network in plaintext — and http:// is the guess that
    silently does."""
    proj = _settings(tmp_path, monkeypatch, wiz, project="otlp_endpoint: collector.example/v1\n")
    with pytest.raises(wiz.Fatal, match="http:// or https://"):
        wiz.resolve_otlp_endpoint(proj)


def test_the_task_is_exported_by_DEFAULT(wiz, tmp_path, monkeypatch):
    """FR-009f0/C18a: a task is not a credential channel."""
    proj = _settings(tmp_path, monkeypatch, wiz)
    assert wiz.export_task_text(proj) is True


def test_the_task_switch_REFUSES_a_string(wiz, tmp_path, monkeypatch):
    """ "false" as a STRING is truthy in Python, so a coercing reader would export
    the task text for an operator who wrote the word false and believed they had
    turned it off — a silent failure in the direction that discloses."""
    proj = _settings(tmp_path, monkeypatch, wiz, project='export_task_text: "false"\n')
    with pytest.raises(wiz.Fatal, match="must be true or false"):
        wiz.export_task_text(proj)


def test_the_task_switch_is_delivered_as_an_explicit_value(wiz):
    """An ABSENT variable is indistinguishable from a deploy predating the switch,
    and this is a field whose exposure the operator chose."""
    # A METHOD, so it is indented — `_func_body` slices top-level defs only.
    src = Path(wiz.__file__).read_text()
    i = src.index("    def compose_environment(")
    body = src[i : src.index("\nINHERITABLE = ", i)]
    assert "AGENT_CONTAINER_EXPORT_TASK" in body
    assert '"0" if not export_task_text() else "1"' in body


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


# --- panic self-exclusion (FR-010, R6, T038/T039) ---------------------------


def _active(name, host="local"):
    return {"name": name, "host": host, "outcome": "active"}


def test_no_control_plane_means_no_exclusion(wiz, monkeypatch):
    """Control. On the operator's own machine nothing is protected, or `panic`
    would quietly narrow its own scope — the false guarantee FR-013 names."""
    monkeypatch.delenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", raising=False)
    entries = [_active("a"), _active("b")]
    keep, excluded = wiz.partition_self_exclusion(entries)
    assert keep == entries and excluded == []


def test_a_control_plane_excludes_ITSELF_and_nothing_else(wiz, monkeypatch):
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub")
    keep, excluded = wiz.partition_self_exclusion([_active("a"), _active("hub"), _active("b")])
    assert [e["name"] for e in keep] == ["a", "b"]
    assert [e["name"] for e in excluded] == ["hub"]


def test_exclusion_matches_by_NAME_not_by_reachability(wiz, monkeypatch):
    """It must work for an entry whose host is unreachable — the case where the
    operator most wants the kill switch and least wants it to take the shell they
    are typing in."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub")
    keep, excluded = wiz.partition_self_exclusion([_active("hub", host="dead-vps")])
    assert keep == []
    assert excluded[0]["host"] == "dead-vps"


def test_an_invalid_control_plane_name_protects_NOTHING_rather_than_guessing(wiz, monkeypatch):
    """An unvalidated value could match nothing while READING as protection,
    which is the worse of the two failures: the operator believes the container
    they are in is safe."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "Hub; rm -rf /")
    keep, excluded = wiz.partition_self_exclusion([_active("hub")])
    assert excluded == [] and len(keep) == 1


def test_the_exclusion_report_names_how_to_stop_it_instead(wiz, monkeypatch, capsys):
    """SC-010/C9. An exclusion that does not say what to do instead is a dead
    end, and the operator's next move is to look for a flag that overrides it."""
    lines: list[str] = []
    monkeypatch.setattr(wiz, "log", lambda m: lines.append(m))
    wiz.report_self_exclusion([_active("hub", host="vps1")], "destroy")
    out = "\n".join(lines)
    assert "EXCLUDED" in out
    assert "hub" in out
    # The remedy, with the host, so it is copy-pasteable rather than a hint.
    assert "agent-container destroy hub --host vps1" in out
    # And WHY, because the reason is the non-obvious part.
    assert "report would never be delivered" in out


def test_the_report_is_never_silent(wiz, monkeypatch):
    """Only the report is checkable. This is the one container whose stopping
    would make any report undeliverable, so 'it worked and said nothing' and 'it
    stopped itself before reporting' look identical from outside."""
    lines: list[str] = []
    monkeypatch.setattr(wiz, "log", lambda m: lines.append(m))
    wiz.report_self_exclusion([_active("hub")], "stop")
    assert lines, "the exclusion produced no output at all"


def test_panic_json_carries_self_excluded(wiz):
    """A consumer reading only `results` would see the container it asked about
    simply ABSENT — the silent skip this requirement forbids."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_panic")
    # Every emit_json in do_panic must carry the field, not just the last one:
    # the early-return branches are the ones an operator with a single recorded
    # environment actually hits.
    envelopes = body.count("emit_json(")
    assert envelopes >= 3, f"expected three emit_json branches, found {envelopes}"
    assert body.count('"self_excluded"') == envelopes, (
        "not every panic --json branch reports the self-exclusion; a machine "
        "consumer would read a protected container as absent"
    )


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


# --- collect and retry (FR-009e/FR-009h, C18, R10/R13, T066-T068) -----------


def test_collect_is_drain_GENERALISED_not_a_second_puller(wiz):
    """C18/R13. Two pullers of the same volumes would diverge on what they
    consider pending, and the divergence would be diagnosable only by reading
    both implementations."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_collect")
    assert "drain_host_records(" in body, (
        "collect does not go through Feature 016's drain, so it is a second puller"
    )
    # And it must not have grown its own extraction path.
    for reimplemented in ("tarfile", "pending_records_from_tar", "ingest_records"):
        assert reimplemented not in body, (
            f"collect reimplements {reimplemented}; that is the second puller R13 forbids"
        )


def test_collect_reports_UNREACHABLE_HOSTS_BY_NAME(wiz):
    """SC-015: so "collected nothing" is distinguishable from "collected nothing
    FROM THAT HOST", and a skipped host never reads as a complete trail.

    A LIST, not a count — "2 hosts unreachable" is not actionable, the names are.
    """
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_collect")
    assert '"unreachable": unreachable' in body
    assert '"complete": not unreachable' in body, (
        "the envelope has no completeness flag, so a consumer comparing against a "
        "collector cannot tell the local side was partial"
    )


def test_collect_distinguishes_ATTACH_ONLY_from_unreachable(wiz):
    """The host is fine and nothing is wrong, but no records can come from it.
    Calling that "unreachable" would send the operator to debug a network."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_collect")
    assert '"attach-only"' in body


def test_retry_acts_only_on_RETRYABLE_states(wiz):
    """R10/T068. `accepted` and `rejected` are terminal: re-exporting an accepted
    record duplicates it at the collector, and re-exporting a rejected one repeats
    a refusal. Retrying everything would do both."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_retry")
    assert "export_state_is_retryable(" in body
    # No override. A flag to force a terminal re-export is the duplication path.
    assert "--force" not in body and "force" not in body


def test_retry_SKIPS_an_unknown_state_rather_than_guessing(wiz):
    """A record written by a future version may mean something this one cannot
    act on, and guessing is how a terminal state gets re-exported."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_retry")
    assert "state not in EXPORT_STATES" in body


def test_retry_without_an_endpoint_is_a_NO_OP_that_says_so(wiz):
    """Nothing is wrong: the local trail is the whole trail, and there is nothing
    to re-export to. An error here would make a healthy configuration look broken.
    """
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_retry")
    assert "endpoint is None" in body
    assert "nothing to re-export to" in body


def test_an_unparseable_export_response_is_not_read_as_ZERO_rejections(wiz):
    """Zero would mark the record accepted on the strength of a response we did
    not understand — the same defect as treating 2xx as success."""
    body = _func_body(Path(wiz.__file__).read_text(), "export_record_via_endpoint")
    assert "rejected = 1" in body


def test_both_legs_derive_the_state_from_ONE_rule(wiz):
    """The CLI leg and the shell leg are two implementations; the verdict must be
    one. `export_outcome_from_response` is the rule the hermetic tests pin, so
    routing the CLI leg through it is what stops the two disagreeing about what a
    200-with-rejections means."""
    body = _func_body(Path(wiz.__file__).read_text(), "export_record_via_endpoint")
    assert "export_outcome_from_response(" in body


def test_the_cli_exporter_adds_no_package(wiz):
    """C18b: stdlib urllib, from the side that has Python. No requests, no OTel
    SDK, and no backend-specific client ever."""
    body = _func_body(Path(wiz.__file__).read_text(), "export_record_via_endpoint")
    assert "urllib.request" in body
    for banned in ("import requests", "httpx", "opentelemetry"):
        assert banned not in body


def test_both_legs_build_the_SAME_payload_shape(wiz):
    """SC-020 compares SETS of records. Two payload shapes would make a
    collector's records depend on which leg sent them, and the comparison would
    report divergence that came from the exporter rather than from delivery."""
    py = _func_body(Path(wiz.__file__).read_text(), "otlp_log_payload")
    sh = _otlp_block(wiz)
    for key in (
        "resourceLogs",
        "scopeLogs",
        "logRecords",
        "observedTimeUnixNano",
        "agent_container.run_id",
        "agent_container.kind",
        "service.name",
    ):
        assert key in py, f"the CLI payload lacks {key}"
        assert key in sh, f"the shell payload lacks {key}"


def test_the_cli_payload_carries_only_the_shared_field_set(wiz):
    """FR-009f: the ONE definition. A field added to the provenance table must
    reach the wire without a second edit here."""
    body = _func_body(Path(wiz.__file__).read_text(), "otlp_log_payload")
    assert "RECORD_PAYLOAD_FIELDS" in body


def test_telemetry_is_offered_by_BOTH_completions(wiz):
    """The cross-file guard already pins the command LIST; this pins the two
    verbs, which the list check cannot see."""
    root = Path(wiz.__file__).parents[1] / "completions"
    for fname in ("agent-container.bash", "agent-container.zsh"):
        body = (root / fname).read_text()
        assert "telemetry" in body, f"{fname} does not offer `telemetry`"
        assert "collect" in body and "retry" in body, (
            f"{fname} offers `telemetry` but not its subcommands"
        )
