"""Feature 017 — the control plane, and the dual-stack observability it widened to.

Hermetic tests only. What lives here is what a real container cannot show more
cheaply than a function call can: the export-state transitions, the single
payload definition, the provenance closure, the semver rule, and scope
resolution. The absences — a passphrase that exists nowhere, an image with no
agents, a `collect` that names an unreachable host — are in the acceptance tier,
because an absence is never demonstrated by working output.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

# A real host record. `{}` resolves to driver None, which dies as "attach-only"
# before reaching anything under test — a failure that looks like the assertion
# under test failing.
HOST = {"driver": "docker", "context": "", "address": "localhost"}

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


# --- revocation (FR-008, C7, SC-005, T029/T030) ------------------------------


def test_revoke_targets_EVERY_registered_host_not_the_declared_scope(wiz):
    """The declaration is intent; the key may have been authorised anywhere.

    Revoking only where the tool BELIEVES the key was authorised would leave
    exactly the authorisation an operator forgot about — the one revocation
    exists for.
    """
    reg = {"hosts": {"a": {}, "b": {}, "c": {}}}
    assert [h for h, _ in wiz.revoke_targets(reg)] == ["a", "b", "c"]
    # An empty registry still yields the implicit local host, or a single-host
    # operator could not revoke at all.
    assert [h for h, _ in wiz.revoke_targets({"hosts": {}})] == [wiz.DEFAULT_HOST]


def test_a_host_with_no_shell_path_is_UNSUPPORTED_not_success(wiz):
    """The tool holds an SSH identity only for hosts it PROVISIONED. For a host
    registered by handing over a docker context it can start containers and
    cannot log in — so the key may still be trusted there.

    Reporting that as done would be the exact false guarantee this command
    exists to prevent.
    """
    with pytest.raises(wiz.NoShellPath):
        wiz.host_shell_argv({"driver": "docker", "context": "", "address": "localhost"})


def test_the_shell_path_uses_the_automation_key_not_the_operators(wiz):
    """An unattended path must never involve an approval-gated personal key:
    IdentitiesOnly and IdentityAgent=none, with the key named explicitly."""
    rec = {
        "driver": "docker",
        "context": "agent-container-vps1",
        "address": "203.0.113.9",
        "provisioning": {"connection": "ssh-forward"},
    }
    argv = wiz.host_shell_argv(rec)
    assert "-o" in argv and "IdentitiesOnly=yes" in argv
    assert "IdentityAgent=none" in argv
    assert "BatchMode=yes" in argv
    assert argv[-1] == "root@203.0.113.9"


def test_unsupported_and_undetermined_BOTH_fail_the_run(wiz):
    """ "Mostly revoked" is worthless: an operator who believes a key is gone
    while a host still trusts it stops looking."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_revoke")
    assert '("undetermined", "unsupported")' in body
    assert "raise typer.Exit(1)" in body


def test_revoke_matches_the_KEY_MATERIAL_not_the_whole_line(wiz):
    """ssh-keygen writes a comment (`dev@<container-id>`) that differs between
    the file and the captured copy, so a whole-line comparison would find
    nothing and report a successful revocation that removed no access."""
    body = _func_body(Path(wiz.__file__).read_text(), "withdraw_key_from_host")
    assert 'material = f"{parts[0]} {parts[1]}"' in body
    # And it must VERIFY a line went, rather than trusting grep's exit status.
    assert "before" in body and "after" in body


def test_revoke_reads_the_public_half_from_LOCAL_state(wiz):
    """The container may be gone. A revocation that required the thing being
    revoked to be alive would be useless exactly when it is needed."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_revoke")
    assert "read_agent_ssh_pubkey(" in body


def test_revoke_leaves_the_CONTAINER_alone(wiz):
    """Revoking access and destroying an environment are different decisions;
    doing both here would make the safe action expensive."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_revoke")
    for destructive in ("do_purge", "do_destroy", "compose_down", '"rm"'):
        assert destructive not in body


# --- attribution (FR-009a/FR-009b, T047/T048) --------------------------------


def test_attribution_is_a_NO_OP_outside_a_control_plane(wiz, monkeypatch):
    """On the operator's own machine the operator IS the actor. A record saying so
    on every action would be noise that buries the records that matter."""
    monkeypatch.delenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", raising=False)
    assert wiz.record_attribution("local", {"driver": "docker"}, "acme", "stop") is None


def test_an_attach_only_host_is_reported_as_UNRECORDED(wiz, monkeypatch):
    """FR-009b: the gap is visible AS a gap. No container can run there, so no
    record can be written — and staying silent would make the action simply absent
    from the trail, which is indistinguishable from it never happening."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub")
    warned: list[str] = []
    monkeypatch.setattr(wiz, "warn", lambda m: warned.append(m))
    assert wiz.record_attribution("vps", {"driver": "ssh"}, "acme", "stop") is None
    assert warned and "UNRECORDED" in warned[0]


def test_a_write_failure_reports_the_gap_and_does_NOT_raise(wiz, monkeypatch):
    """FR-009b: the operator asked a question; refusing to answer because
    bookkeeping failed inverts the priority. The action already happened."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub")
    warned: list[str] = []
    monkeypatch.setattr(wiz, "warn", lambda m: warned.append(m))
    monkeypatch.setattr(
        wiz.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 1, b"", b"denied"),
    )
    # Returns None rather than raising — the caller has already acted.
    assert wiz.record_attribution("vps", HOST, "acme", "stop") is None
    assert warned and "UNRECORDED" in warned[0]


def test_the_attribution_record_names_WHICH_control_plane(wiz, monkeypatch):
    """SC-013. "A control plane did it" is not an answer when nesting means there
    may be several."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub")
    captured: dict = {}

    def fake_run(argv, **kw):
        captured["payload"] = json.loads(kw["input"].decode())
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    rid = wiz.record_attribution("vps", HOST, "acme", "stop")
    assert rid is not None
    rec = captured["payload"]
    assert rec["attribution"] == "control-plane:hub"
    assert rec["kind"] == "management"
    assert rec["environment"] == "acme"
    # No agent ran, and the record says so rather than borrowing a name.
    assert rec["agent"] is None
    # It is born `pending` like every other record, so `collect`/`retry` treat it
    # identically — one payload, one state machine.
    assert rec["export_state"] == "pending"


def test_the_attribution_record_lands_on_the_volume_the_DRAIN_reads(wiz):
    """Written where the action lands (FR-003a), and specifically to the volume
    Feature 016 already collects from — a record written anywhere else would be
    invisible to the mechanism that gathers it."""
    argv = wiz.driver_attribution_argv(HOST, wiz.runs_volume_name("acme"), "img", "r.json")
    assert f"{wiz.runs_volume_name('acme')}:{wiz.RUNS_INGEST_MOUNT}" in argv
    # WRITABLE — the one helper that must be — but still no network.
    assert ":ro" not in " ".join(argv)
    assert "--network" in argv and "none" in argv


def test_the_attribution_write_is_staged_then_renamed(wiz):
    """The tool's listing skips dot-prefixed .tmp names, so a half-written record
    can never be read as a finished one."""
    argv = wiz.driver_attribution_argv(HOST, "v", "img", "r.json")
    script = argv[-1]
    assert script.startswith("cat > /mnt/.r.json.tmp")
    assert "mv /mnt/.r.json.tmp /mnt/r.json" in script


def test_the_mutating_management_actions_are_attributed(wiz):
    """FR-009a/SC-013. Asserted per COMMAND, so adding a mutating command without
    attribution fails here rather than silently leaving a hole in the trail."""
    src = Path(wiz.__file__).read_text()
    # `compose_up_exec`, NOT `do_up`. It is the only choke point every deploy path
    # passes through — `up`, `apply`, `redeploy` and the wizard — and this file
    # already records why that distinction matters: an egress lookup placed in
    # `do_up` left `redeploy` unenforced while the declaration still read as
    # enforced. Attribution placed in `do_up` would leave every `redeploy`
    # unattributed while the trail read as complete, which is the same defect.
    for func, command in (
        ("compose_up_exec", "up"),
        ("do_stop", "stop"),
        ("do_start", "start"),
    ):
        body = _func_body(src, func)
        assert f'record_attribution(host_name, host_rec, name, "{command}")' in body, (
            f"{func} performs a management action without recording attribution"
        )


def test_deploy_attribution_sits_at_the_CHOKE_POINT_not_in_do_up(wiz):
    """Stated as its own test because the wrong location passes every other check.

    `do_up` serves `up` and `apply`; `do_redeploy` and the wizard call
    `compose_up_exec` directly. Attribution in `do_up` would therefore record
    every `up` and no `redeploy` — and a trail missing a whole command reads as a
    trail, which is worse than an obviously empty one.
    """
    src = Path(wiz.__file__).read_text()
    assert 'record_attribution(host_name, host_rec, name, "up")' not in _func_body(src, "do_up"), (
        "deploy attribution is in do_up, so `redeploy` and the wizard go unattributed"
    )


def test_attribution_is_recorded_AFTER_the_action(wiz):
    """So the record states what HAPPENED rather than what was attempted. A record
    written first would claim an action that may then have failed."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_stop")
    assert body.index("compose stop failed") < body.index("record_attribution")


# --- reconciliation (SC-020, C17, R12, T070) ---------------------------------


def _rec_file(d, rid, stamp, state):
    (d / f"{rid}.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "run_id": rid,
                "environment": "demo",
                "host": "local",
                "agent": "claude",
                "kind": "headless",
                "task": None,
                "started_at": stamp,
                "ended_at": None,
                "outcome": "finished",
                "exit_code": 0,
                "repository": None,
                "usage": {"reported": False},
                "attribution": None,
                "egress_decision": None,
                "export_state": state,
                "notes": [],
            }
        )
    )


@pytest.fixture
def store(tmp_path, monkeypatch, wiz):
    d = tmp_path / "runs" / "local" / "demo"
    d.mkdir(parents=True)
    monkeypatch.setattr(wiz, "DATA_DIR", tmp_path)
    return d


def test_PENDING_records_are_OUTSIDE_the_window(wiz, store):
    """C17/R12. They have not finished exporting, so counting them as divergence
    would make SC-020 fail against a perfectly healthy system with exports in
    flight — and a criterion that fails on healthy systems is one people stop
    running."""
    _rec_file(store, "a1", "2026-08-21T10:00:00Z", "accepted")
    _rec_file(store, "p1", "2026-08-21T10:01:00Z", "pending")
    inside, pending = wiz.records_in_window(wiz.stored_record_paths(), None, None)
    assert pending == 1
    assert [r["run_id"] for r in inside] == ["a1"]


def test_the_pending_count_is_REPORTED_not_dropped(wiz, store):
    """ "12 in flight" is the difference between a reconciliation an operator can
    trust and one they should re-run in a minute."""
    _rec_file(store, "p1", "2026-08-21T10:00:00Z", "pending")
    _, pending = wiz.records_in_window(wiz.stored_record_paths(), None, None)
    assert pending == 1


def test_the_window_defaults_to_the_last_successful_collect(wiz, store, monkeypatch):
    """R12: an undefined window makes the comparison unexecutable."""
    monkeypatch.setattr(wiz, "read_collect_watermark", lambda: "2026-08-01T00:00:00Z")
    assert wiz.reconciliation_window(None, None) == ("2026-08-01T00:00:00Z", None)
    # An operator-supplied range WINS.
    assert wiz.reconciliation_window("2026-05-05T00:00:00Z", None)[0] == "2026-05-05T00:00:00Z"


def test_no_watermark_means_FULL_HISTORY_not_an_empty_window(wiz, monkeypatch):
    """Wider than intended is safe; narrower is not. A window that silently
    excluded records would report agreement it never established."""
    monkeypatch.setattr(wiz, "read_collect_watermark", lambda: None)
    assert wiz.reconciliation_window(None, None) == (None, None)


def test_the_watermark_advances_ONLY_after_a_COMPLETE_collect(wiz):
    """A partial collect must not advance it: the next reconciliation would treat
    the hosts it could not reach as "before the window" and silently exclude
    exactly the records that are missing."""
    lines = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_collect").splitlines()
    write_at = next(i for i, ln in enumerate(lines) if "write_collect_watermark" in ln)
    guard_at = next((i for i, ln in enumerate(lines) if ln.strip() == "if not unreachable:"), None)
    assert guard_at is not None, "no completeness guard around the watermark write"
    assert guard_at < write_at, (
        "the watermark is written before checking that every host was reached"
    )
    # And the write must be INSIDE that block, not merely after it.
    assert lines[write_at].startswith(
        " " * (len(lines[guard_at]) - len(lines[guard_at].lstrip()) + 4)
    )


def test_divergence_is_reported_in_BOTH_directions(wiz):
    """Zero silent divergence. The two directions mean different things: local
    `accepted` missing at the collector is a delivery claim that did not land,
    while a record at the collector this machine never accepted is what a second
    exporter, a replay, or a lost local store looks like."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_reconcile")
    assert "accepted - remote" in body
    assert "remote - accepted" in body


def test_a_one_sided_read_reports_NO_COMPARISON_not_agreement(wiz):
    """Reporting "no divergence" from a one-sided read would be the worst possible
    answer: it asserts agreement that was never checked."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_reconcile")
    assert '"compared": False' in body
    assert '"agree": None' in body
    assert "NO COMPARISON WAS MADE" in body


def test_the_inner_verdict_is_not_called_ok(wiz):
    """The envelope already carries a top-level `ok` meaning "the command ran".
    A second `ok` inside it meaning "the legs agree" is how a consumer reads
    agreement off a run that made no comparison."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_reconcile")
    assert '"ok":' not in body, "the reconciliation payload has its own `ok` field"
    assert '"agree":' in body


def test_the_envelope_field_types_do_not_change_between_branches(wiz):
    """`local_accepted` as a list in one branch and an int in the other is how a
    machine consumer breaks on the case it did not happen to test first."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_reconcile")
    assert body.count('"local_accepted": len(accepted)') == 2, (
        "local_accepted is not the same type in both branches"
    )


def test_the_tool_does_NOT_query_the_collector(wiz):
    """C14/FR-009d: obtaining the collector's side requires the backend's own API,
    which is the vendor coupling that made end-to-end ingestion unobservable in
    the first place. The operator supplies the answer; the tool compares."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_telemetry_reconcile")
    for coupling in ("urlopen", "curl", "requests", "opener.open"):
        assert coupling not in body, f"reconciliation reaches out to the collector via {coupling}"
    assert "collector_ids.read_text()" in body


def test_reconciliation_is_only_expressible_because_the_legs_share_a_payload(wiz):
    """It compares run ids, which both legs export unconditionally (C18f). If the
    task exclusion had removed correlation, this comparison would have nothing to
    join on — which is why run_id exports whatever the task setting is."""
    assert "run_id" in wiz.RECORD_PAYLOAD_FIELDS


# --- narrow rendering (FR-011, C11, R7, SC-007, T021/T022) -------------------


def test_narrowness_is_MEASURED_not_flagged(wiz):
    """FR-011's motivating case is an operator on a phone. They are already
    inconvenienced; requiring them to remember `--narrow` puts the work on the
    person least able to do it, and one who forgets gets the unusable output the
    flag existed to prevent."""
    assert wiz.terminal_is_narrow(40) is True
    assert wiz.terminal_is_narrow(80) is True
    assert wiz.terminal_is_narrow(81) is False
    # No flag exists to force it.
    src = Path(wiz.__file__).read_text()
    assert '"--narrow"' not in src


def test_a_non_terminal_is_NOT_narrow(wiz):
    """Piped output wants the stable column form. Switching shape based on whether
    someone is watching is how a script breaks the day it is run by hand."""
    assert wiz.terminal_is_narrow(0) is False
    assert wiz.terminal_is_narrow(None) is False


def test_no_line_exceeds_the_width_at_80_columns(wiz):
    """SC-007, measured rather than asserted about the shape."""
    rows = [
        {
            "name": "a-fairly-long-environment-name",
            "host": "some-remote-vps-host",
            "port": 2206,
            "image": "localhost/agent-container:latest",
            "status": "Up 3 days",
            "uptime": "3 days",
        }
    ] * 3
    lines = wiz.render_rows_narrow(rows, wiz.LIST_FIELDS)
    over = [ln for ln in lines if len(ln) > wiz.NARROW_COLUMNS]
    assert not over, f"lines exceed {wiz.NARROW_COLUMNS} columns: {over}"


def test_every_field_gets_its_own_line(wiz):
    """A form that inlined short values and blocked long ones would give the same
    environment a different shape depending on its name length, and an operator
    scanning for a field would have to find it somewhere new each time."""
    lines = wiz.render_rows_narrow(
        [{"name": "a", "host": "b"}], (("name", "NAME"), ("host", "HOST"))
    )
    assert lines == ["NAME: a", "HOST: b"]


def test_rows_are_separated_so_two_do_not_read_as_one(wiz):
    lines = wiz.render_rows_narrow([{"name": "a"}, {"name": "b"}], (("name", "NAME"),))
    assert lines == ["NAME: a", "", "NAME: b"]


def test_staleness_survives_the_loss_of_COLOUR(wiz):
    """The wide form dims a stale row. At 80 columns the operator may be reading in
    sunlight on a phone, and a colour distinction that is the ONLY carrier of a
    fact is a fact that does not arrive — so staleness moves into the STATUS text.
    """
    body = _func_body(Path(wiz.__file__).read_text(), "do_list")
    narrow = body[body.index("if terminal_is_narrow():") : body.index("table = Table(")]
    assert "(stale)" in narrow
    # CODE lines only: the block explains that dim styling is dropped, so scanning
    # prose would fail on the documentation of the property being asserted.
    code = "\n".join(ln for ln in narrow.splitlines() if not ln.strip().startswith("#"))
    assert "dim" not in code, "the narrow form still relies on dim styling"


def test_the_field_set_is_shared_between_both_forms(wiz):
    """Two lists would drift, and the drift would be invisible: each form still
    renders correctly on its own, and only an operator switching widths would
    notice a column had gone."""
    body = _func_body(Path(wiz.__file__).read_text(), "do_list")
    narrow = body[body.index("if terminal_is_narrow():") : body.index("table = Table(")]
    wide = body[body.index("table = Table(") :]
    assert "LIST_FIELDS" in narrow and "LIST_FIELDS" in wide, (
        "one of the two forms carries its own column list, which will drift"
    )
    # The literal the wide form used to hold must be gone, or it is still a second
    # encoding regardless of what the narrow form reads.
    assert '("NAME", "HOST", "PORT", "IMAGE", "STATUS", "UPTIME")' not in body


# --- live enumeration (FR-003a, SC-002, T019/T020) ---------------------------


def test_list_json_NAMES_the_hosts_that_did_not_answer(wiz, monkeypatch):
    """SC-002: a short list that looks complete is worse than an error, because
    the operator acts on absence.

    The rows already carry status `unreachable`, but a consumer would have to scan
    and infer. The explicit field is the difference between "there are no
    containers there" and "nobody asked successfully".
    """
    rows = [
        {"name": "-", "host": "dead-vps", "port": "-", "image": "-",
         "status": "unreachable", "uptime": "-", "stale": False},
        {"name": "agent-container-acme", "host": "local", "port": 2206, "image": "img",
         "status": "Up", "uptime": "1h", "stale": False},
    ]  # fmt: skip
    monkeypatch.setattr(wiz, "gather_rows", lambda *a, **k: rows)
    monkeypatch.setattr(wiz, "migrate_flat_state", lambda: None)
    monkeypatch.setattr(wiz, "detect_runtime", lambda: "docker")
    captured: dict = {}
    monkeypatch.setattr(wiz, "emit_json", lambda d=None, error=None: captured.update(d or {}))
    wiz.do_list(as_json=True)
    assert captured["unreachable_hosts"] == ["dead-vps"]
    assert captured["complete"] is False


def test_list_json_says_COMPLETE_when_every_host_answered(wiz, monkeypatch):
    rows = [
        {"name": "agent-container-acme", "host": "local", "port": 2206, "image": "img",
         "status": "Up", "uptime": "1h", "stale": False}
    ]  # fmt: skip
    monkeypatch.setattr(wiz, "gather_rows", lambda *a, **k: rows)
    monkeypatch.setattr(wiz, "migrate_flat_state", lambda: None)
    monkeypatch.setattr(wiz, "detect_runtime", lambda: "docker")
    captured: dict = {}
    monkeypatch.setattr(wiz, "emit_json", lambda d=None, error=None: captured.update(d or {}))
    wiz.do_list(as_json=True)
    assert captured["unreachable_hosts"] == []
    assert captured["complete"] is True


def test_enumeration_never_syncs_the_operators_inventory(wiz):
    """FR-003a: the control plane queries permitted hosts LIVE and the live view IS
    its truth. Syncing the operator's durable file would need a laptop-to-container
    path FR-003a rules out, and a locked control plane could not receive it anyway.
    """
    body = _func_body(Path(wiz.__file__).read_text(), "gather_rows")
    for durable in ("read_inventory_entries", "inventory_store_dir", "kill_read_inventory"):
        assert durable not in body, (
            f"gather_rows reads the durable inventory ({durable}); the control plane "
            "cannot see that file and its live view is the truth"
        )


# --- scope: declared, visible, and refused when out of it (T028/T031/T033/T034)


def test_the_scope_renderer_is_SHARED_by_the_statement_and_status(wiz):
    """SC-004 is that intent is visible in advance and comparable later. Two
    renderers would let the before and after disagree, and the comparison would
    then be between two renderings rather than between intent and reality."""
    body = _func_body(Path(wiz.__file__).read_text(), "state_control_plane_consequences")
    assert "report_control_plane_scope(" in body


def test_an_empty_scope_says_it_reaches_NOTHING(wiz):
    """Absent and empty are opposite, and the empty case is the one an operator
    misreads as "everything"."""
    lines = wiz.report_control_plane_scope("hub", [])
    assert "EMPTY" in lines[0]
    assert "reaches" in lines[0] and "nothing" in lines[0]


def test_the_scope_report_ALWAYS_says_it_is_intent(wiz):
    """In both branches. An operator who read the host list as a boundary would be
    wrong, and the clause that says so must not be the one that only appears when
    the list is empty."""
    for hosts in ([], ["vps1", "vps2"]):
        lines = wiz.report_control_plane_scope("hub", hosts)
        assert any("INTENT" in ln for ln in lines), hosts
        assert any("authorised" in ln for ln in lines), hosts


def test_out_of_scope_is_a_NO_OP_outside_a_control_plane(wiz, monkeypatch):
    """On the operator's own machine there is no scope to be out of."""
    monkeypatch.delenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", raising=False)
    wiz.refuse_out_of_scope("", "any-host")  # must not raise


def test_an_out_of_scope_host_FAILS_VISIBLY(wiz, monkeypatch):
    """FR-005/SC-003: visibly, rather than partially succeeding. The difference is
    between "nothing happened" and "three hosts changed and then it stopped"."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub")
    monkeypatch.setattr(wiz, "control_plane_permitted_hosts", lambda _n: ["vps1"])
    with pytest.raises(wiz.Fatal, match="not in hub's declared scope"):
        wiz.refuse_out_of_scope("", "vps9")
    # And an in-scope host passes.
    wiz.refuse_out_of_scope("", "vps1")


def test_the_refusal_does_NOT_claim_to_be_a_boundary(wiz):
    """Reach is where the key is authorised, outside the container. A host omitted
    from the declaration but authorised anyway is still reachable, and an operator
    who read this refusal as a guarantee would be wrong."""
    doc = wiz.refuse_out_of_scope.__doc__ or ""
    assert "NOT THE SECURITY BOUNDARY" in doc


def test_the_scope_guard_wraps_the_resolver_rather_than_its_branches(wiz):
    """The resolver has four exits. A check placed in each would be bypassed by a
    fifth added later, while the declaration still read as governing — so the guard
    is a wrapper, which cannot miss a path."""
    src = Path(wiz.__file__).read_text()
    body = _func_body(src, "resolve_deploy_host")
    assert "_resolve_deploy_host_unscoped(" in body
    assert "refuse_out_of_scope(" in body
    # The inner resolver must NOT carry its own copy of the check.
    inner = _func_body(src, "_resolve_deploy_host_unscoped")
    assert "refuse_out_of_scope" not in inner


def test_the_key_is_LOCKED_at_boot_with_no_agent_started(wiz):
    """FR-007a/C5: locked whenever nobody is attached, and the passphrase is
    supplied on connect.

    Starting an ssh-agent at boot would unlock the key for the container's
    lifetime — precisely the property being refused — and nothing would look
    wrong.
    """
    ep = (Path(wiz.__file__).parents[1] / "image-control-plane" / "entrypoint.sh").read_text()
    code = "\n".join(ln for ln in ep.splitlines() if not ln.strip().startswith("#"))
    assert "ssh-agent" not in code, "the control-plane entrypoint starts an ssh-agent at boot"
    assert "ssh-add" not in code, "the control-plane entrypoint adds the key at boot"
    # And it NOTICES a pre-set agent socket rather than trusting the absence.
    assert "SSH_AUTH_SOCK" in ep


def test_the_pre_deploy_statement_names_ALL_THREE_consequences(wiz, monkeypatch):
    """T033/C19. Omitting the no-recovery clause is the one an operator only
    discovers after the loss, so its presence is asserted rather than assumed."""
    lines: list[str] = []
    monkeypatch.setattr(wiz, "log", lambda m: lines.append(m))
    wiz.state_control_plane_consequences("hub", ["vps1"])
    out = " ".join(lines)
    assert "holds whatever the container holds" in out
    assert "vps1" in out
    assert "NO RECOVERY" in out
    # And it names what to do about a loss, not only that it is unrecoverable.
    assert "redeploy" in out and "revoke" in out


# --- the injected host registry (FR-002/FR-004, R4, T014/T015/T023) ----------


def test_the_projection_carries_NO_CREDENTIAL_MATERIAL(wiz):
    """FR-004/R4: it is names, drivers, contexts and addresses. The capability is
    the authorised key, never the list."""
    reg = {
        "hosts": {
            "vps1": {
                "driver": "docker",
                "context": "agent-container-vps1",
                "address": "203.0.113.9",
                "provisioning": {"connection": "ssh-forward"},
                "created_by_tool": True,
                # Things that must NOT travel, whatever they are called.
                "token": "hcloud-secret",
                "api_key": "sk-live-xxxx",
                "password": "hunter2",
                "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----",
            }
        }
    }
    out = wiz.projected_host_registry(reg)
    blob = json.dumps(out)
    for secret in ("hcloud-secret", "sk-live-xxxx", "hunter2", "PRIVATE KEY"):
        assert secret not in blob, f"{secret!r} reached the injected registry"
    assert set(out["hosts"]["vps1"]) == set(wiz.REGISTRY_INJECTED_FIELDS)


def test_the_projection_is_an_ALLOW_LIST_not_a_redaction(wiz):
    """A pass that removed known-bad keys would carry whatever key someone adds
    next — which is how a snapshot grows a credential nobody decided to include.
    """
    out = wiz.projected_host_registry(
        {"hosts": {"v": {"driver": "docker", "some_future_field": "whatever"}}}
    )
    assert out == {"hosts": {"v": {"driver": "docker"}}}


def test_the_registry_is_injected_INLINE_not_as_a_file_bind(wiz):
    """R4/the 001-003 lesson, measured: a `file:` config is a read-only BIND of a
    local path and cannot reach a daemon that does not share the filesystem. A
    remote deploy would silently have no registry."""
    body = _func_body(Path(wiz.__file__).read_text(), "build_compose_model")
    block = body[body.index('model_configs["host_registry"]') :][:200]
    assert '"content"' in block
    assert '"file"' not in block


def test_an_AGENT_container_gets_no_registry(wiz):
    """Constitution III. An agent has no use for a map of the operator's
    infrastructure, and injecting one anyway would widen exposure for nothing."""
    model = wiz.build_compose_model("acme", "/ctx")
    assert "host_registry" not in (model.get("configs") or {})
    svc = model["services"]["agent"]
    targets = [c.get("source") for c in (svc.get("configs") or [])]
    assert "host_registry" not in targets


def test_a_CONTROL_PLANE_gets_the_registry_at_the_path_the_entrypoint_reads(wiz, monkeypatch):
    monkeypatch.setattr(wiz, "load_registry", lambda: {"hosts": {"vps1": {"driver": "docker"}}})
    model = wiz.build_compose_model("hub", "/ctx", role=wiz.ROLE_CONTROL_PLANE)
    assert "host_registry" in model["configs"]
    svc = model["services"]["agent"]
    entry = next(c for c in svc["configs"] if c["source"] == "host_registry")
    assert entry["target"] == wiz.INJECT_HOST_REGISTRY_PATH
    # And the content is the PROJECTION, not the raw registry.
    assert "vps1" in model["configs"]["host_registry"]["content"]


def test_the_entrypoint_installs_the_registry_where_the_CLI_LOOKS(wiz):
    """FR-002/C1: no on-arrival configuration. Copied to the CLI's own config
    location rather than teaching the CLI a second path."""
    ep = (Path(wiz.__file__).parents[1] / "image-control-plane" / "entrypoint.sh").read_text()
    assert "hosts.json" in ep
    # The CLI reads CONFIG_DIR/hosts.json, so the entrypoint must target the same
    # XDG location — asserted against the CLI's own constant name to catch drift.
    assert wiz.HOSTS_JSON.name in ep
    assert "XDG_CONFIG_HOME" in ep
    # COPIED, not symlinked: /run is tmpfs, and a dangling symlink reads as a
    # corrupt registry rather than an absent one.
    assert "ln -s" not in ep


def test_the_entrypoint_says_the_registry_is_a_SNAPSHOT(wiz):
    """A host registered after this deploy is invisible until redeploy. Stating it
    in the boot log means the operator meets the fact before it confuses them."""
    ep = (Path(wiz.__file__).parents[1] / "image-control-plane" / "entrypoint.sh").read_text()
    assert "SNAPSHOT" in ep
    assert "redeploy" in ep


def test_a_failed_registry_install_is_LOUD(wiz):
    """The CLI would otherwise start and resolve no hosts, which looks like an
    empty fleet rather than a broken install — and an operator who attached to
    manage something would conclude it was gone."""
    ep = (Path(wiz.__file__).parents[1] / "image-control-plane" / "entrypoint.sh").read_text()
    assert "will resolve NO hosts" in ep


# --- no backend-specific dependency (SC-016, C18b, T072) ---------------------

# OTel was accepted AT THE PROTOCOL LEVEL ONLY. A backend-specific package would
# couple an audit path to one vendor's API — the coupling that makes end-to-end
# ingestion unobservable in the first place (C14), and the exact thing FR-009d
# permits the protocol in order to avoid.
_BACKEND_PACKAGES = (
    "opentelemetry",
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp",
    "datadog",
    "ddtrace",
    "newrelic",
    "elastic-apm",
    "sentry-sdk",
    "honeycomb",
    "boto3",
    "google-cloud-logging",
    "azure-monitor-opentelemetry",
    "loki-logger-handler",
    "requests",
    "httpx",
)


def _declared_packages(text: str) -> set[str]:
    """Distribution names from a dependency list, stripped of version specifiers."""
    names = set()
    for raw in re.findall(r'"([^"]+)"', text):
        name = re.split(r"[<>=!~\[; ]", raw, maxsplit=1)[0].strip()
        if name:
            names.add(name.lower())
    return names


def test_the_INSTALLED_package_set_carries_no_backend_client(wiz):
    """SC-016, checked against the DECLARED DISTRIBUTIONS rather than the import
    list.

    The import list is the weaker check twice over: a package can be declared and
    imported lazily inside a function, where a module-level import scan never sees
    it — and a package can be installed as a transitive dependency and imported by
    nothing here while still shipping in the wheel.
    """
    root = Path(wiz.__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    deps = pyproject[pyproject.index("dependencies = [") :]
    deps = deps[: deps.index("]")]
    declared = _declared_packages(deps)
    assert declared == {"typer", "questionary", "rich", "pyyaml"}, (
        f"the runtime dependency set changed: {sorted(declared)}. PyYAML is the one "
        f"third-party dep this project accepts; justify any addition against "
        f"Constitution VI."
    )
    for banned in _BACKEND_PACKAGES:
        assert banned.lower() not in declared, (
            f"{banned} is a runtime dependency. OTel was accepted at the PROTOCOL "
            f"level only, and a backend-specific package couples an audit path to "
            f"one vendor's API — the coupling C14 exists to avoid."
        )


def test_the_PEP723_block_and_pyproject_agree(wiz):
    """Two encodings of the dependency set. A drift would let `uv run bin/…` install
    something the wheel does not, so the tested tool and the shipped tool would
    differ in exactly the dimension this criterion measures."""
    root = Path(wiz.__file__).parents[1]
    src = (root / "bin" / "agent-container").read_text()
    # The CLOSING marker, not the first `# ///` in the file — that is the OPENING
    # `# /// script` line, so searching from zero yields a reversed slice and an
    # empty dependency set, which would make this test pass on an empty block.
    start = src.index("# dependencies = [")
    block = src[start : src.index("# ///", start)]
    inline = _declared_packages(block.replace("#", ""))
    pyproject = (root / "pyproject.toml").read_text()
    deps = pyproject[pyproject.index("dependencies = [") :]
    deps = deps[: deps.index("]")]
    assert inline == _declared_packages(deps)


def test_the_export_path_imports_nothing_beyond_the_stdlib(wiz):
    """C18b. The CLI leg uses urllib and the container leg uses curl; neither may
    reach for a client library."""
    body = _func_body(Path(wiz.__file__).read_text(), "export_record_via_endpoint")
    imports = re.findall(r"^\s*import\s+(\S+)", body, re.M)
    for mod in imports:
        assert mod.split(".")[0] in {"urllib", "json", "time"}, (
            f"the exporter imports {mod}, which is not stdlib-only"
        )


# --- US3 identity (FR-013/FR-014, T041/T043) ---------------------------------


def test_multiple_control_planes_are_individually_identifiable(wiz, monkeypatch):
    """FR-014: they must not conflict. Identity is per-environment and per-host, so
    two control planes differ in exactly the way two environments do — no special
    case, which is the point of a control plane being an ordinary environment."""
    monkeypatch.delenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", raising=False)
    a = wiz.build_inventory_entry("hub-a", "local", False, role=wiz.ROLE_CONTROL_PLANE)
    b = wiz.build_inventory_entry("hub-b", "local", False, role=wiz.ROLE_CONTROL_PLANE)
    assert a["name"] != b["name"]
    assert a["entry_id"] != b["entry_id"]
    # Distinct ports, from the same deterministic hash every environment uses.
    assert wiz.port_for_name("hub-a") != wiz.port_for_name("hub-b")
    # And distinct container names and volume sets.
    assert wiz.container_name("hub-a") != wiz.container_name("hub-b")
    assert set(wiz.per_container_volumes("hub-a")).isdisjoint(wiz.per_container_volumes("hub-b"))


def test_a_nested_control_plane_records_its_PARENT(wiz, monkeypatch):
    """SC-011: nesting lets standing keys grow from inside the system, so the
    origin has to be readable. Persisted, so a stopped one still answers."""
    monkeypatch.setenv("AGENT_CONTAINER_CONTROL_PLANE_NAME", "hub-a")
    child = wiz.build_inventory_entry("hub-b", "local", False, role=wiz.ROLE_CONTROL_PLANE)
    assert child["provenance"] == "control-plane:hub-a"
    assert child["role"] == "control-plane"
