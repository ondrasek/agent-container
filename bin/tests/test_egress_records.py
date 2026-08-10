"""Feature 012 US3 (T032/T033/T034) — the durable egress record.

Hermetic: no docker, no podman, no network. Every retention test passes its own
`now`; the DRAIN deliberately prunes against the real clock, so the log fixtures are
stamped relative to it — recent enough to be inside the age bound and in the past, so
the watermark's clamp does not treat them as future-dated. The boundary is represented
by the BYTES its log produces, because that is the whole interface: T032 is "read the boundary's
own stream", so what is left to prove here is that the tool reads the shapes that
stream really carries, stores the events FR-010 is about and nothing else, and
never lets an empty answer mean two things.

  * **T032** — the event's fields are data-model §6's and no more, and the parser is
    bound to `logformat egress` in image/egress/squid.conf in BOTH directions: a
    format that moved must be counted as unreadable, not silently ignored, because a
    reader that has stopped matching presents as "nothing was refused".
  * **T033** — the events land in the durable store, through Feature 016's write and
    list helpers (FR-011a), under this schema and this retention.
  * **T034** — the three silences are told apart. That is the hard part of the task
    and most of the surface tests here exist for it.

Several tests exist only to prove another test can fail, because a check that
passes while the thing it names is broken is this repo's recurring defect.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import types
from pathlib import Path

import pytest

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    # Rich colourises the figures it prints, so a captured line carries escapes
    # between a number and the word beside it. Stripped here rather than switched
    # off in the product: the assertion is about what an operator reads.
    return _ANSI_RE.sub("", text)


LOCAL_HOST = {"driver": "docker", "context": "", "address": "localhost"}
_ROOT = Path(__file__).resolve().parents[2]
_SQUID_CONF = _ROOT / "image" / "egress" / "squid.conf"
_UNBOUND_CONF = _ROOT / "image" / "egress" / "unbound.conf"
_DOC = _ROOT / "docs" / "egress.md"

# The two line shapes the boundary really produces, transcribed from the
# measurements recorded in image/egress/squid.conf and in T130's task note. They are
# the fixtures for everything below, so a wrong assumption here would be a wrong
# assumption everywhere — which is why the squid one is ALSO derived from the
# logformat directive in test_the_parser_is_bound_to_the_image_logformat.
# An hour ago, to the second: recent enough that the drain's own prune (real clock)
# keeps it, and past enough that the watermark's clamp does not read it as future-dated.
# A hard-coded date would satisfy exactly one of those two and only until it aged out.
_BASE = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3600))
STAMP = f"{_BASE}.123456789Z"  # as the runtime writes it, sub-second and all
STAMP_UTC = f"{_BASE}Z"  # as §6 records it
# All five MEASURED on a live boundary (docker, squid 6.12, declared
# `api.anthropic.com`, undeclared-but-resolvable `github.com`), transcribed verbatim
# apart from the client address. Every one is exactly SQUID_LOG_FIELDS fields.
TERMINATED_TLS = (
    "1786361194.045      1 172.18.0.2 NONE_NONE/000 0 CONNECT 140.82.121.4:443 "
    "HIER_NONE/- sni=codeload.github.com bump=terminate"
)
# THE LINE THAT MADE THIS FIELD NECESSARY. A permitted request logs this FIRST and its
# TCP_TUNNEL line second; everything but `bump` is identical to TERMINATED_TLS above.
SPLICED_PEEK = (
    "1786361194.002      1 172.18.0.2 NONE_NONE/000 0 CONNECT 160.79.104.10:443 "
    "HIER_NONE/- sni=api.anthropic.com bump=splice"
)
PERMITTED_TUNNEL = (
    "1786361194.032     29 172.18.0.2 TCP_TUNNEL/200 3823 CONNECT api.anthropic.com:443 "
    "ORIGINAL_DST/160.79.104.10 sni=api.anthropic.com bump=splice"
)
DENIED_PLAIN_HTTP = (
    "1786361194.052      0 172.18.0.2 TCP_DENIED/403 3789 GET http://github.com/ "
    "HIER_NONE/- sni=- bump=-"
)
# What the container HEALTHCHECK's request-less TCP connection logs (research R25) —
# it names no destination.
NO_DESTINATION = (
    "1786361194.053      0 127.0.0.1 NONE_NONE/000 0 - "
    "error:transaction-end-before-headers HIER_NONE/- sni=- bump=-"
)
DNS_REFUSED = "unbound[7:0] info: 10.89.0.4 api.openai.com. A IN REFUSED 0.000000 0 45"
DNS_NXDOMAIN = "unbound[7:0] info: 10.89.0.4 nope.example.com. A IN NXDOMAIN 0.010000 0 45"
DNS_NOERROR = "unbound[7:0] info: 10.89.0.4 api.anthropic.com. A IN NOERROR 0.020000 0 68"
# Past the age bound against any real clock, for the two tests that exercise the
# prune the DRAIN performs (which reads the real one, deliberately).
ANCIENT = "2020-01-01T00:00:00Z"


def _line(rest: str, stamp: str = STAMP) -> str:
    """One log line as the RUNTIME hands it over: its own timestamp, then the
    producer's line (`logs --timestamps`)."""
    return f"{stamp} {rest}"


@pytest.fixture
def boundary(wiz, monkeypatch):
    """An environment whose LAST DEPLOYED model has a boundary, plus a fake runtime
    that answers `logs` from `state.stdout`/`state.stderr`.

    The compose artifact is real (written through `write_compose_file`) because two
    separate things read it: the gate that decides whether this environment has a
    boundary at all, and the allowlist `declared` is judged against. A hand-built
    dict would let those drift from what the tool actually writes.
    """
    state = types.SimpleNamespace(
        stdout=[], stderr=[], rc=0, exists=True, calls=[], warnings=[], logs=[]
    )

    def _deploy(name: str = "acme", acl: str = "api.anthropic.com\n") -> None:
        wiz.write_compose_file(
            "local",
            name,
            {
                "services": {"agent": {}, wiz.EGRESS_SERVICE_KEY: {}},
                "configs": {"egress_acl": {"content": acl}},
            },
        )

    def fake_run(argv, capture_output=False, timeout=None, **kw):
        state.calls.append(list(argv))
        return subprocess.CompletedProcess(
            list(argv),
            state.rc,
            "\n".join(_line(r) for r in state.stdout).encode(),
            "\n".join(_line(r) for r in state.stderr).encode(),
        )

    def fake_query(argv, timeout=None):
        state.calls.append(list(argv))
        out = "agent-egress-acme\n" if state.exists else ""
        return subprocess.CompletedProcess(list(argv), 0, out, "")

    monkeypatch.setattr(wiz.subprocess, "run", fake_run)
    monkeypatch.setattr(wiz, "query", fake_query)
    monkeypatch.setattr(wiz, "warn", state.warnings.append)
    monkeypatch.setattr(wiz, "log", state.logs.append)
    state.deploy = _deploy
    return state


def _events(wiz, host="local", env="acme") -> list[dict]:
    return wiz.stored_egress_events(host, [env])


# --- T032: the parser is bound to the format the image actually writes --------


def test_the_parser_is_bound_to_the_image_logformat(wiz):
    """The one binding that keeps this reader honest.

    `logformat egress` is nine space-separated fields and this parser reads three of
    them BY POSITION. If the directive gains, loses or reorders a field, the parser
    reads the wrong ones — and a parser reading the wrong ones stores nothing, which
    an operator sees as "nothing was refused". So the positions are asserted against
    the directive itself, in the image, and a synthetic line built from that
    directive must parse.
    """
    m = re.search(r"^logformat egress (.+)$", _SQUID_CONF.read_text(), re.M)
    assert m, "image/egress/squid.conf no longer defines `logformat egress`"
    fields = m.group(1).split()
    assert len(fields) == wiz.SQUID_LOG_FIELDS
    assert fields[0].startswith("%ts")
    assert "%Ss" in fields[wiz.SQUID_FIELD_STATUS]
    assert fields[wiz.SQUID_FIELD_TARGET] == "%ru"
    assert fields[wiz.SQUID_FIELD_SNI].startswith("sni=")
    # The field that separates a refusal from a permitted request's own first line.
    # Without it in the directive, the reader below cannot tell them apart at all.
    assert fields[wiz.SQUID_FIELD_BUMP] == "bump=%ssl::bump_mode"

    # A line built from the directive's own arity, with values in the fields this
    # parser claims to read. If the arity moved, this line has the wrong length and
    # the assertion below fails rather than the tool going quiet in production.
    synthetic = ["-"] * len(fields)
    synthetic[0] = "1754820610.000"
    synthetic[wiz.SQUID_FIELD_STATUS] = "NONE_NONE/000"
    synthetic[wiz.SQUID_FIELD_TARGET] = "1.2.3.4:443"
    synthetic[wiz.SQUID_FIELD_SNI] = "sni=api.openai.com"
    synthetic[wiz.SQUID_FIELD_BUMP] = "bump=terminate"
    parsed = wiz.parse_squid_egress_line(" ".join(synthetic))
    assert parsed == {
        "host": "api.openai.com",
        "decision": "refused",
        "stage": "connect",
        "declared": None,
    }


def test_a_logformat_that_grew_a_field_is_LOUD_rather_than_quiet(wiz, boundary):
    """Proof the binding above can fail, at RUNTIME and not only in this suite.

    A ten-field access-log line is what a future `logformat` edit produces. The
    parser cannot read it — that is unavoidable — but the outcome must be a warning
    naming the divergence, never an empty store. This is the exact shape of the
    defect this repo keeps finding: a check (here, the store) that passes while the
    thing it names is broken.
    """
    boundary.deploy()
    boundary.stdout = [TERMINATED_TLS + " extra_field=1"]
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert _events(wiz) == []
    assert any("could not be read as events" in w for w in boundary.warnings)


def test_a_line_that_is_correctly_discarded_warns_about_NOTHING(wiz, boundary):
    """The other half of that guard, and the reason it is narrow.

    squid's own diagnostics, an NXDOMAIN, ordinary permitted traffic and a
    request-less connection are all discarded on purpose. If any of them counted as
    unreadable, every drain of a live boundary would warn — and a warning that fires
    always is a warning an operator stops reading, which would cost exactly the case
    above.
    """
    boundary.deploy()
    boundary.stdout = [SPLICED_PEEK, PERMITTED_TUNNEL, NO_DESTINATION]
    boundary.stderr = [DNS_NXDOMAIN, DNS_NOERROR, "squid[1]: Squid Cache (Version 6.12): Ready"]
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert boundary.warnings == []
    assert _events(wiz) == []


def test_a_terminated_tls_connection_is_a_refusal_named_by_its_SNI(wiz):
    """The measured shape of the record that matters (squid.conf, T150). The address
    is NOT the destination: on a CDN it answers for thousands of sites, which is why
    `%ssl::>sni` was added to the format in the first place."""
    assert wiz.parse_squid_egress_line(TERMINATED_TLS) == {
        "host": "codeload.github.com",
        "decision": "refused",
        "stage": "connect",
        "declared": None,
    }


def test_a_permitted_tunnel_is_not_reported_as_a_refusal(wiz):
    """The control. A reader that called everything a refusal would pass every test
    that only ever feeds it refusals."""
    parsed = wiz.parse_squid_egress_line(PERMITTED_TUNNEL)
    assert parsed["decision"] == "permitted"
    assert parsed["host"] == "api.anthropic.com"


@pytest.mark.parametrize(
    "status,bump",
    [
        # A declared host that did not answer. The old classifier got this one right.
        ("TCP_MISS/503", "-"),
        # THE SHAPE THE OLD CLASSIFIER GOT WRONG WHILE THIS TEST NAMED IT. A `403`
        # clause sat beside the tag check, so a declared host answering 403 ITSELF — a
        # WAF, a bot block, a stale API key, a CDN — was stored as a policy refusal.
        # The test that was written to prevent exactly that asserted only `TCP_MISS/503`
        # and `TCP_DENIED/403`, the two cases the code already handled, so it passed
        # while the behaviour it is named for was broken. That is this repository's
        # recurring defect, inside the guard written against it.
        ("TCP_MISS/403", "-"),
        ("TCP_MISS/401", "-"),
        ("TCP_REFRESH_MODIFIED/200", "-"),
    ],
)
def test_an_upstream_failure_is_not_turned_into_a_policy_refusal(wiz, status, bump):
    """An upstream's own status code is not a policy event. Recording one as refused
    would put a fabricated finding in the one store whose value is that its findings
    are real — and a genuine denial by this configuration always carries `TCP_DENIED`,
    so the tag check loses nothing by being the only source of a refusal."""
    assert wiz.squid_decision(status, bump) == "permitted"
    assert wiz.squid_decision("TCP_DENIED/403", "-") == "refused"


def test_a_PERMITTED_request_is_not_stored_as_a_refusal_by_its_own_FIRST_line(wiz, boundary):
    """MEASURED, and it is the whole reason `%ssl::bump_mode` is in the format.

    A permitted HTTPS request to a DECLARED host logs two lines, and the first one is
    `NONE_NONE/000 … CONNECT <address>:443 HIER_NONE/- sni=<the declared host>` —
    identical in status tag, code, byte count, method, hierarchy and `%err_code` to a
    terminated connection's line. So a reader that classified on the status tag alone
    recorded EVERY permitted request as a refusal of the host it was permitted to
    reach, and did it at the rate the agent makes requests.

    Both lines are fed, as the boundary really emits them, and the store must be
    empty: one is not an event and the other is ordinary declared traffic."""
    boundary.deploy(acl="api.anthropic.com\n")
    boundary.stdout = [SPLICED_PEEK, PERMITTED_TUNNEL]
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert _events(wiz) == [], "a permitted request was recorded as a refusal"
    assert boundary.warnings == []


def test_the_verdict_comes_from_the_BOUNDARYS_OWN_bump_decision(wiz):
    """The two measured lines differ in exactly one field, so that field is where the
    verdict has to come from. Asserted as a pair: a reader that answered `refused` for
    both, or `permitted`/None for both, fails here."""
    terminated = wiz.parse_squid_egress_line(TERMINATED_TLS)
    assert terminated == {
        "host": "codeload.github.com",
        "decision": "refused",
        "stage": "connect",
        "declared": None,
    }
    assert wiz.parse_squid_egress_line(SPLICED_PEEK) is None
    # And the two lines really are one field apart, so nothing else could be carrying
    # the distinction. Compared field by field to name WHICH one when this changes.
    a, b = TERMINATED_TLS.split(), SPLICED_PEEK.split()
    differing = {i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y}
    assert wiz.SQUID_FIELD_BUMP in differing
    assert differing - {wiz.SQUID_FIELD_BUMP} <= {0, 1, wiz.SQUID_FIELD_TARGET, wiz.SQUID_FIELD_SNI}


def test_a_measured_NON_POLICY_failure_of_a_declared_host_is_not_a_refusal(wiz):
    """`NONE_NONE/409`, MEASURED in research R24 for a DECLARED, permitted destination:
    squid's intercepted-CONNECT host verification rejected 10 of 12 HTTPS requests to
    `s3.amazonaws.com` because its ipcache and the agent's answer had diverged
    (`SECURITY ALERT: Host header forgery detected`). That is a divergent-resolution
    failure, not a policy event — FR-010 scopes this store to UNDECLARED egress, and an
    event reading `declared: true, decision: refused` is neither undeclared nor blocked.

    Neither verdict is invented for it: `permitted` would claim a connection that never
    happened, and `refused` fabricates a policy finding."""
    line = (
        "1786361194.045      1 172.18.0.2 NONE_NONE/409 0 CONNECT 52.216.0.1:443 "
        "HIER_NONE/- sni=s3.amazonaws.com bump=splice"
    )
    assert len(line.split()) == wiz.SQUID_LOG_FIELDS
    assert wiz.squid_decision("NONE_NONE/409", "splice") is None
    assert wiz.parse_squid_egress_line(line) is None


def test_a_DNS_reply_line_is_never_read_as_an_ACCESS_LOG_line(wiz, boundary):
    """The arity is not an identity, measured the moment the format grew its tenth
    field: unbound's reply lines are also ten whitespace-separated tokens, so
    `nope.example.com. A IN NXDOMAIN 0.010000 0 45` parsed as an access-log line whose
    status field was a hostname — not `TCP_DENIED`, not starting with `NONE`, therefore
    PERMITTED — and every DNS reply became an undeclared-permitted event at the host
    `nxdomain`. Field 0 is squid's own `%ts.%03tu`, so it is checked as an identity."""
    for line in (DNS_NXDOMAIN, DNS_NOERROR, DNS_REFUSED):
        assert len(line.split()) == wiz.SQUID_LOG_FIELDS, "the collision this guards is gone"
        assert wiz.parse_squid_egress_line(line) is None
    boundary.deploy()
    boundary.stderr = [DNS_NXDOMAIN, DNS_NOERROR]
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert _events(wiz) == []


def test_a_request_less_connection_names_no_destination_and_yields_no_event(wiz):
    """`error:transaction-end-before-headers` is a syntactically fine hostname, so a
    naive reader records a refusal of the host `error` — a fabricated event, which is
    worse than the silence US3 asks for."""
    assert wiz.parse_squid_egress_line(NO_DESTINATION) is None
    assert wiz.bare_host("error:transaction-end-before-headers") is None


def test_no_part_of_a_url_but_its_host_can_reach_the_store(wiz):
    """Constitution III, and the one place this feature could have leaked a
    credential. `%ru` on a plain-HTTP request is the FULL URL: a query string can
    carry a token and `user:pass@` carries one outright. Asserted on a KNOWN
    sentinel, not on "nothing key-shaped" — that would test the assertion's
    imagination."""
    line = TERMINATED_TLS.replace(
        "CONNECT 140.82.121.4:443", "GET http://tok:SENTINEL-abc@evil.example.com/v1?key=SENTINEL"
    ).replace("sni=codeload.github.com", "sni=-")
    parsed = wiz.parse_squid_egress_line(line)
    assert parsed is not None
    assert parsed["host"] == "evil.example.com"
    assert "SENTINEL" not in json.dumps(parsed)


def test_the_destination_is_lower_cased_so_one_host_is_one_event(wiz):
    """DNS is case-insensitive and the allowlist is generated in the operator's
    spelling. Without this, `Api.OpenAI.com` is a second record for the same
    destination AND misses an `api.openai.com` allowlist entry."""
    assert wiz.bare_host("Api.OpenAI.Com") == "api.openai.com"


def test_an_ipv6_destination_is_not_dropped_in_silence(wiz):
    """HOSTNAME_RE cannot match one, and a dropped event in a store whose promise is
    that silence means nothing happened is the worst available outcome."""
    assert wiz.bare_host("[2001:db8::1]:443") == "2001:db8::1"


# --- T032: the DNS half, and what it deliberately excludes -------------------


def test_a_REFUSED_resolution_is_recorded_and_is_undeclared_by_construction(wiz):
    """The resolver's verdict IS the allowlist test: build_unbound_conf gives every
    declared name a `local-zone … transparent` and the baked catch-all refuses the
    rest. So `declared` needs no second source — and a second source could
    disagree."""
    assert wiz.parse_unbound_egress_line(DNS_REFUSED) == {
        "host": "api.openai.com",
        "decision": "refused",
        "stage": "dns",
        "declared": False,
    }


def test_an_NXDOMAIN_is_not_a_policy_event(wiz):
    """T131 built the resolver choice around keeping these distinguishable. An
    NXDOMAIN is a fact about the internet; storing it would fill the store with an
    agent's typos and dilute the refusals FR-010 is about."""
    assert wiz.parse_unbound_egress_line(DNS_NXDOMAIN) is None
    assert wiz.parse_unbound_egress_line(DNS_NOERROR) is None


def test_a_reply_format_that_moved_is_counted_rather_than_ignored(wiz, boundary):
    """The DNS side of the drift guard. A reply line the pattern no longer matches is
    the only way this reader can go quiet, and the loose form is what notices."""
    boundary.deploy()
    boundary.stderr = ["unbound[7:0] info: 10.89.0.4 api.openai.com. A IN 5 0.0 0 45"]
    assert wiz.looks_like_unbound_reply_line(boundary.stderr[0]) is True
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert any("could not be read as events" in w for w in boundary.warnings)


def test_both_streams_are_read_because_the_two_producers_use_different_ones(wiz, boundary):
    """squid's access log is on stdout and unbound's replies on stderr. Reading one
    would lose a whole class of refusal — and the DNS one is the COMMON shape, since
    an undeclared name never gets as far as a connection."""
    boundary.deploy()
    boundary.stdout = [TERMINATED_TLS]
    boundary.stderr = [DNS_REFUSED]
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert {(e["host"], e["stage"]) for e in _events(wiz)} == {
        ("codeload.github.com", "connect"),
        ("api.openai.com", "dns"),
    }


def test_the_runtime_timestamp_is_normalised_to_utc(wiz):
    """podman stamps its logs with a local offset. A record that silently carried
    local time would sort and prune against records that carried UTC, and this
    store's whole ordering is by time."""
    assert wiz.split_log_stamp("2026-08-10T12:10:10.000+02:00 x")[0] == "2026-08-10T10:10:10Z"
    assert wiz.split_log_stamp("2026-08-10T10:10:10Z x")[0] == "2026-08-10T10:10:10Z"


def test_a_line_with_no_runtime_timestamp_yields_no_event_and_is_counted(wiz, boundary):
    """§6's `timestamp` is not optional, and stamping "now" on a line whose time is
    unknown would fabricate an ordering. Loud, because if `--timestamps` ever stops
    working EVERY event is lost."""
    boundary.deploy()
    boundary.stdout = []
    monkey = subprocess.CompletedProcess(["logs"], 0, TERMINATED_TLS.encode(), b"")
    assert wiz._store_egress_events("local", "acme", monkey) == []
    assert any("could not be read as events" in w for w in boundary.warnings)


# --- T033: what reaches the durable store, and what must not -----------------


def test_the_event_carries_exactly_the_fields_data_model_6_declares(wiz, boundary):
    """The closure that makes §6's narrowness checkable. "No headers, no bodies, no
    tokens" is a Constitution III claim about this store, and a claim about a
    record's fields is worth exactly as much as the thing that enumerates them."""
    boundary.deploy()
    boundary.stderr = [DNS_REFUSED]
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    (event,) = _events(wiz)
    assert set(event) == set(wiz.EGRESS_FIELD_PROVENANCE)
    assert event["environment"] == "acme"
    assert event["deployment_host"] == "local"
    assert event["timestamp"] == STAMP_UTC
    assert event["host"] == "api.openai.com"
    assert event["provider"] == "openai"
    assert event["decision"] == "refused"
    assert event["declared"] is False
    assert event["stage"] == "dns"
    assert event["schema"] == wiz.EGRESS_SCHEMA


def test_the_destination_field_and_the_deployment_host_field_are_not_confused(wiz, boundary):
    """The one inherited collision: §6 names the destination `host` while Feature
    016's run record uses `host` for the machine. Both meanings are in this record, so
    a test pins which is which — a swap would be invisible in every other test that
    only ever looks at one of them."""
    boundary.deploy()
    boundary.stderr = [DNS_REFUSED]
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    (event,) = _events(wiz)
    assert event["host"] == "api.openai.com"  # the destination
    assert event["deployment_host"] == "local"  # the machine


def test_the_same_log_line_read_twice_stores_ONE_event(wiz, boundary):
    """THE property that makes an unclearable source safe. A run record is deleted
    from its volume once stored; a container log cannot be, so every drain re-reads
    what it already ingested. Without content-addressed names the store would grow by
    a copy of itself on every single command."""
    boundary.deploy()
    boundary.stderr = [DNS_REFUSED]
    first = wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    second = wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert len(first) == 1
    assert second == []  # nothing NEW, so nothing announced either
    assert len(_events(wiz)) == 1


def test_the_store_is_not_a_traffic_log(wiz, boundary):
    """An agent talking to its declared provider produces a line per request —
    thousands a session, every one expected. Keeping them would bury the events
    FR-010 exists for and set retention to work evicting refusals to make room for
    ordinary traffic."""
    boundary.deploy(acl="api.anthropic.com\n")
    boundary.stdout = [PERMITTED_TUNNEL] * 5
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert _events(wiz) == []


def test_a_destination_PERMITTED_while_undeclared_is_stored_and_is_the_loudest_event(
    wiz, boundary, capsys, monkeypatch
):
    """The shape that would have been easy to omit, and it is a stronger finding than
    any refusal: the running boundary admitted a destination the deployed allowlist
    does not name, so the allowlist in force is not the one this tool generated."""
    boundary.deploy(acl="api.anthropic.com\n")
    boundary.stdout = [PERMITTED_TUNNEL.replace("api.anthropic.com", "api.openai.com")]
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    (event,) = _events(wiz)
    assert (event["decision"], event["declared"]) == ("permitted", False)

    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])
    wiz.do_egress("acme", None, False)
    out = _plain(capsys.readouterr().out)
    assert "PERMITTED while UNDECLARED" in out


def test_declared_is_judged_against_the_DEPLOYED_allowlist(wiz, boundary):
    """Not against the project spec. The spec is what the NEXT deploy would apply, so
    judging a refusal that already happened against it can report an attempt as
    declared that the running boundary terminated — an error in the permissive
    direction, which is the one that matters."""
    boundary.deploy(acl=".githubusercontent.com\n")
    permitted_subdomain = PERMITTED_TUNNEL.replace("api.anthropic.com", "raw.githubusercontent.com")
    boundary.stdout = [permitted_subdomain]
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []  # declared: kept out

    boundary.stdout = [PERMITTED_TUNNEL]  # api.anthropic.com is NOT in this allowlist
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert [e["host"] for e in _events(wiz)] == ["api.anthropic.com"]


def test_an_unreadable_allowlist_keeps_refusals_and_invents_nothing(wiz, boundary, monkeypatch):
    """Without the allowlist, a permitted event cannot be told from ordinary traffic.
    The alternatives are to fabricate findings or to store everything; recording the
    refusals is what remains true."""
    boundary.deploy()
    monkeypatch.setattr(wiz, "deployed_egress_allowlist", lambda h, n: None)
    boundary.stdout = [PERMITTED_TUNNEL, TERMINATED_TLS]
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    stored = _events(wiz)
    assert [e["host"] for e in stored] == ["codeload.github.com"]
    assert stored[0]["declared"] is None


def test_an_environment_with_no_boundary_costs_no_remote_call(wiz, boundary):
    """The gate is a LOCAL file read, because this drain runs in front of almost every
    command and most environments have no declaration at all. A remote probe here
    would tax every deploy on every host to learn nothing."""
    wiz.write_compose_file("local", "plain", {"services": {"agent": {}}})
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "plain") == []
    assert boundary.calls == []


def test_a_torn_down_boundary_is_silent_and_a_broken_one_warns(wiz, boundary):
    """A torn-down environment is the normal end state and its stored events survive
    precisely so they can be read afterwards (US3 scenario 2). Warning on every
    contact would be a permanent complaint about nothing — and this feature's one
    rule about noise is that silence must stay meaningful. A boundary that EXISTS and
    will not answer is the opposite: events are accruing and nothing collects them."""
    boundary.deploy()
    boundary.rc = 1
    boundary.exists = False
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert boundary.warnings == []

    boundary.exists = True
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert any("would not hand over its log" in w for w in boundary.warnings)


def test_the_events_are_collected_on_the_same_contact_as_the_run_records(wiz, monkeypatch):
    """The contact point that cannot be missed is teardown's: `down_container` stops,
    drains, THEN removes — and removing the boundary destroys the log the events are
    still in. Sharing `drain_host_records` is what keeps that from becoming a second
    list of contact points to forget one from.
    """
    monkeypatch.setattr(wiz, "drain_host_records", wiz.real_drain_host_records)
    monkeypatch.setattr(wiz, "ensure_tunnel", lambda h, **k: None)
    monkeypatch.setattr(wiz, "host_drain_facts", lambda h: ({}, set()))
    monkeypatch.setattr(wiz, "ingest_records", lambda *a, **k: [])
    seen: list[str] = []
    monkeypatch.setattr(wiz, "ingest_egress_events", lambda h, r, n: seen.append(n) or [])
    wiz.drain_host_records("local", dict(LOCAL_HOST), ["acme"])
    assert seen == ["acme"]


def test_the_announcement_names_the_destinations_and_only_fires_for_new_events(wiz, boundary):
    """An operator learns of a refusal without thinking to ask — and the events worth
    knowing about are exactly the ones nobody expects to exist. "recorded 3 events"
    answers a question no operator has, so the destinations are named."""
    boundary.deploy()
    boundary.stderr = [DNS_REFUSED]
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert any("api.openai.com" in m for m in boundary.logs)
    boundary.logs.clear()
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert boundary.logs == []  # US3 scenario 3: nothing new happened, so nothing is said


# --- T033: retention, with its own rule (FR-011a) ----------------------------


def _stamp(wiz, day: int, second: int = 0) -> str:
    return f"2026-06-{day:02d}T10:{second // 60:02d}:{second % 60:02d}Z"


def _put(
    wiz, host_dest: str, day: int, second: int = 0, env: str = "acme", stamp: str | None = None
) -> Path:
    event = wiz.build_egress_event(
        env,
        "local",
        stamp or _stamp(wiz, day, second),
        {"host": host_dest, "decision": "refused", "stage": "dns"},
        False,
    )
    return wiz.atomic_write_json(
        wiz.egress_store_dir("local", env), f"{wiz.egress_event_id(event)}.json", event
    )


def _epoch(wiz, day: int) -> float:
    import calendar
    import time as _t

    return float(calendar.timegm(_t.strptime(_stamp(wiz, day), wiz.TIME_FORMAT)))


def test_the_age_bound_prunes_and_reads_the_events_own_time(wiz, tmp_path):
    """From `timestamp`, not from mtime: mtime is when the tool last contacted the
    host, so an age rule built on it keeps a year-old refusal alive because a drain
    re-read the line this morning."""
    _put(wiz, "old.example.com", 1)
    _put(wiz, "new.example.com", 20)
    d = wiz.egress_store_dir("local", "acme")
    just_inside = _epoch(wiz, 1) + wiz.EGRESS_RETENTION_MAX_AGE_DAYS * 86400 - 60
    assert wiz.prune_egress_store(d, now=just_inside) == []
    past_the_first = _epoch(wiz, 1) + wiz.EGRESS_RETENTION_MAX_AGE_DAYS * 86400 + 60
    assert len(wiz.prune_egress_store(d, now=past_the_first)) == 1
    assert [e["host"] for e in _events(wiz)] == ["new.example.com"]


def test_a_burst_on_ONE_destination_does_not_evict_the_others(wiz):
    """The failure this store's own rule bounds, and it is not the run store's.

    There a burst is the tool's restart loop, so the axis is the DAY. Here a burst is
    one destination an agent retries — a misconfigured provider is refused on every
    attempt — and what an operator asks of this store is WHICH hosts were reached
    for. Under plain newest-first, the five single events are gone; under
    round-robin every distinct destination keeps its newest before any host gets a
    second.
    """
    others = [f"h{i}.example.com" for i in range(5)]
    for i, h in enumerate(others):
        _put(wiz, h, 10, second=i)
    burst = wiz.EGRESS_RETENTION_MAX_RECORDS + 100
    for s in range(burst):
        _put(wiz, "retried.example.com", 20, second=s)
    removed = wiz.prune_egress_store(wiz.egress_store_dir("local", "acme"), now=_epoch(wiz, 21))
    kept = _events(wiz)
    assert len(kept) == wiz.EGRESS_RETENTION_MAX_RECORDS
    survivors = {e["host"] for e in kept}
    assert set(others) <= survivors, "the burst evicted the destinations it was hiding"
    assert len(removed) == burst + len(others) - wiz.EGRESS_RETENTION_MAX_RECORDS


def test_newest_first_alone_WOULD_have_evicted_them(wiz):
    """Proof the test above can fail — the fixture really is a burst that a plain
    newest-first rule loses the other destinations to, rather than one that would
    have survived either way."""
    rows = [(float(1000 + s), "retried.example.com", Path(f"/b/{s}")) for s in range(600)]
    rows += [(float(10 + i), f"h{i}.example.com", Path(f"/o/{i}")) for i in range(5)]
    rows.sort(key=lambda r: r[0], reverse=True)
    newest_first = {p for _e, _h, p in rows[: wiz.EGRESS_RETENTION_MAX_RECORDS]}
    assert not any(p.parent.name == "o" for p in newest_first)
    assert any(p.parent.name == "o" for p in wiz._round_robin_keeps(rows, 500))


def test_the_newest_event_is_never_taken_by_the_count_bound(wiz):
    """It is first in the fill order and every bucket's share is at least one. The
    age bound will take it at 90 days — that is the rule working, and the only
    legitimate way this store becomes empty."""
    for s in range(wiz.EGRESS_RETENTION_MAX_RECORDS + 50):
        _put(wiz, "one.example.com", 20, second=s)
    newest = max(e["timestamp"] for e in _events(wiz))
    wiz.prune_egress_store(wiz.egress_store_dir("local", "acme"), now=_epoch(wiz, 21))
    assert max(e["timestamp"] for e in _events(wiz)) == newest


def test_retention_runs_even_when_STORING_raises(wiz, boundary, monkeypatch):
    """Feature 016 learned this the hard way (see `ingest_records`): a bound skipped
    exactly when the drain fails is a bound that stops existing on the environment
    generating the most records."""
    boundary.deploy()
    # ANCIENT rather than merely old: the drain prunes against the real clock (that is
    # the code path under test), so the fixture has to be past the age bound on any
    # machine whose clock is not set before 2020.
    _put(wiz, "old.example.com", 1, stamp=ANCIENT)
    boundary.stderr = [DNS_REFUSED]
    monkeypatch.setattr(
        wiz, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk"))
    )
    with pytest.raises(RuntimeError):
        wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert _events(wiz) == []


def test_a_prune_that_itself_fails_does_not_MASK_the_drains_own_failure(wiz, boundary, monkeypatch):
    """An exception from a `finally` REPLACES the original. The operator would be told
    retention is unhappy and never told why the drain failed — the C11 masking
    failure exactly."""
    boundary.deploy()
    boundary.stderr = [DNS_REFUSED]
    monkeypatch.setattr(
        wiz, "prune_egress_store", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
    )
    monkeypatch.setattr(
        wiz,
        "atomic_write_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the real one")),
    )
    with pytest.raises(RuntimeError, match="the real one"):
        wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    assert any("could not apply egress-record retention" in w for w in boundary.warnings)


def test_a_prune_announces_what_it_deleted_and_which_rule_took_it(wiz, boundary):
    """Deleting a durable record is the last thing that may happen quietly: the whole
    feature is that the account outlives the container."""
    boundary.deploy()
    _put(wiz, "old.example.com", 1, stamp=ANCIENT)
    wiz._prune_egress_and_announce("local", "acme")
    assert any("pruned 1 egress event(s) past retention" in m for m in boundary.logs)
    assert any(str(wiz.EGRESS_RETENTION_MAX_AGE_DAYS) in m for m in boundary.logs)


def test_a_WITHDRAWN_declaration_still_has_its_store_pruned(wiz, boundary):
    """The prune wraps the early returns, not just the reading path.

    An environment whose `egress:` block was removed never reads a log again, so a
    prune reachable only through that path would keep its events past the documented 90
    days forever — while the store's own help text still promised otherwise. A number
    in the help that the code does not enforce is this project's recurring defect, and
    this is the branch where it would have been true.
    """
    wiz.write_compose_file("local", "acme", {"services": {"agent": {}}})  # no boundary
    _put(wiz, "old.example.com", 1, stamp=ANCIENT)
    assert wiz.ingest_egress_events("local", LOCAL_HOST, "acme") == []
    assert _events(wiz) == []
    assert any("pruned 1 egress event(s)" in m for m in boundary.logs)


def test_retention_can_never_reach_an_UNINGESTED_event(wiz, monkeypatch):
    """The one loss nobody could notice, made impossible by construction rather than
    by care: the pending events are in a container log, and this function issues no
    command to a host at all. Asserted as "reaches no runtime" because that survives a
    refactor, where "does not delete the log" would not."""
    monkeypatch.setattr(
        wiz, "query", lambda *a, **k: pytest.fail("retention contacted the runtime")
    )
    monkeypatch.setattr(
        wiz.subprocess, "run", lambda *a, **k: pytest.fail("retention contacted the runtime")
    )
    _put(wiz, "old.example.com", 1)
    wiz.prune_egress_store(wiz.egress_store_dir("local", "acme"), now=_epoch(wiz, 1) + 400 * 86400)


# --- T034: the three silences ------------------------------------------------


@pytest.fixture
def reader(wiz, monkeypatch):
    """`egress` as a READER: a registry it can resolve, and no drain."""
    monkeypatch.setattr(wiz, "resolve_deploy_host", lambda h: ("local", dict(LOCAL_HOST)))
    monkeypatch.setattr(wiz, "drain_host_records", lambda *a, **k: [])
    # Rich FOLDS a cell that does not fit, so on an 80-column console a destination
    # arrives split across two lines and every substring assertion below fails for a
    # reason having nothing to do with the tool. Folding is the deliberate product
    # behaviour (nothing is ellipsised away), so the test widens the console rather
    # than the product dropping a column.
    monkeypatch.setenv("COLUMNS", "200")
    return wiz


def test_silence_for_a_WATCHED_environment_says_nothing_was_refused(reader, wiz, capsys):
    """Case 1 of three. The good news, and it has to be said in one line: an empty
    screen is indistinguishable from the other two."""
    wiz.write_compose_file("local", "acme", {"services": {"agent": {}, wiz.EGRESS_SERVICE_KEY: {}}})
    wiz.do_egress("acme", None, False)
    err = _plain(capsys.readouterr().err)
    assert "nothing collected from that boundary's log was refused" in err


def test_silence_for_an_UNWATCHED_environment_says_nothing_was_WATCHING(reader, wiz, capsys):
    """Case 2, and the whole point of T034. The same empty answer means the opposite
    here: no boundary was deployed, so nothing observed this environment's egress. A
    reader that printed nothing — or printed case 1's line — would state that nothing
    was refused about a container nothing was watching."""
    wiz.write_compose_file("local", "acme", {"services": {"agent": {}}})
    wiz.do_egress("acme", None, False)
    err = _plain(capsys.readouterr().err)
    assert "deploys NO egress boundary" in err
    assert "unrestricted and unrecorded" in err
    assert "was refused" not in err


def test_silence_for_an_UNKNOWN_environment_claims_neither(reader, wiz, capsys):
    """Case 3: nothing deployed that the tool can ask, e.g. after `--purge` removed
    the model. Its events would still be here; none are, and that is not evidence
    none happened."""
    wiz.do_egress("gone", None, False)
    err = _plain(capsys.readouterr().err)
    assert "no deployment the tool can ask" in err
    assert "not that none happened" in err


def test_the_json_distinguishes_all_three_without_prose(reader, wiz, capsys):
    """A consumer cannot read prose, and would otherwise treat all three silences as
    "clean". `boundary` is always present for the same reason `unpushed` always is in
    Feature 016: a key that appears only when interesting makes the uninteresting
    case indistinguishable from a schema change."""
    wiz.write_compose_file(
        "local", "watched", {"services": {"agent": {}, wiz.EGRESS_SERVICE_KEY: {}}}
    )
    wiz.write_compose_file("local", "plain", {"services": {"agent": {}}})
    wiz.set_json_mode(True)
    wiz.do_egress(None, None, True)
    data = json.loads(capsys.readouterr().out)["data"]
    states = {e["environment"]: e["boundary"] for e in data["environments"]}
    assert states == {"watched": "watched", "plain": "unwatched"}
    assert data["events"] == []


def test_a_listing_names_the_environments_it_does_NOT_cover(reader, wiz, capsys):
    """Two refusals listed for one environment would otherwise read as the complete
    account of a host where another environment has no boundary at all — an
    incomplete answer presented as a complete one, which is the C16 lesson."""
    wiz.write_compose_file("local", "acme", {"services": {"agent": {}, wiz.EGRESS_SERVICE_KEY: {}}})
    wiz.write_compose_file("local", "plain", {"services": {"agent": {}}})
    _put(wiz, "api.openai.com", 10)
    wiz.do_egress(None, None, False)
    out = _plain(capsys.readouterr().out)
    assert "api.openai.com" in out
    assert "not covered above" in out
    assert "plain" in out


def test_an_environment_that_is_watched_appears_even_with_no_events(reader, wiz, capsys):
    """`boundary: watched` is the field that makes silence readable, so it must be
    reachable for an environment that has never had a finding — otherwise it is only
    ever visible where there is already bad news."""
    wiz.write_compose_file(
        "local", "quiet", {"services": {"agent": {}, wiz.EGRESS_SERVICE_KEY: {}}}
    )
    wiz.set_json_mode(True)
    wiz.do_egress("quiet", None, True)
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["environments"] == [
        {
            "environment": "quiet",
            "boundary": "watched",
            "events": 0,
            "refused": 0,
            "permitted_undeclared": 0,
        }
    ]


def test_a_declared_that_is_UNKNOWN_renders_as_the_word(reader, wiz, capsys):
    """`declared: null` means the tool could not read the allowlist in force. A dash
    beside a `no` reads as "no" for the one case where the answer is "we cannot
    say"."""
    event = wiz.build_egress_event(
        "acme",
        "local",
        "2026-06-10T10:00:00Z",
        {"host": "api.openai.com", "decision": "refused", "stage": "connect"},
        None,
    )
    wiz.atomic_write_json(
        wiz.egress_store_dir("local", "acme"), f"{wiz.egress_event_id(event)}.json", event
    )
    wiz.do_egress("acme", None, False)
    assert "unknown" in _plain(capsys.readouterr().out)


def test_an_event_survives_the_environment_it_came_from(reader, wiz, capsys):
    """US3 scenario 2 / SC-006, and the reason this store exists at all: the events
    are readable with no container, no compose model and no boundary anywhere."""
    _put(wiz, "api.openai.com", 10, env="demolished")
    assert not wiz.compose_file_path("local", "demolished").exists()
    wiz.do_egress("demolished", None, False)
    assert "api.openai.com" in _plain(capsys.readouterr().out)


# --- T034: the record's source must still be switched ON ---------------------


def test_the_record_source_is_still_switched_on(wiz):
    """Silence must mean "nothing was refused", which is only true while both
    producers are still writing to the stream this reads. Both have already regressed
    once — T130 found unbound's replies going to a syslog nobody ran, T150 found
    squid's access log in a file no verb could read — and either regression makes
    this whole feature quietly return nothing.
    """
    squid = _SQUID_CONF.read_text()
    assert "access_log stdio:/dev/stdout" in squid
    assert "logfile_rotate 0" in squid
    assert "log-replies: yes" in _UNBOUND_CONF.read_text()
    generated = wiz.build_unbound_conf([("anthropic", "api.anthropic.com", None, "tool")])
    assert "use-syslog: no" in generated
    assert 'logfile: ""' in generated


def test_the_documented_numbers_are_the_enforced_ones(wiz):
    """A number typed into prose beside a different number in the code is this
    project's recurring defect. Bound in both directions: the constants must appear in
    the help an operator reads at the point of use AND in docs/egress.md."""
    help_text = wiz.egress_cmd.__doc__ or ""
    doc = _DOC.read_text()
    for value in (
        wiz.EGRESS_RETENTION_MAX_AGE_DAYS,
        wiz.EGRESS_RETENTION_MAX_RECORDS,
        wiz.EGRESS_LOG_TAIL_LINES,
    ):
        assert str(value) in help_text, f"{value} is not in the `egress` help"
        assert str(value) in doc, f"{value} is not in docs/egress.md"


def test_a_number_that_drifted_from_its_documentation_is_caught(wiz):
    """Proof the check above can fail. Without this, a guard that merely searched for
    "90" somewhere in a long document would pass forever."""
    doc = _DOC.read_text()
    assert str(wiz.EGRESS_RETENTION_MAX_RECORDS + 1) not in re.sub(r"\d{4}-\d{2}-\d{2}", "", doc), (
        "the assertion is vacuous: an arbitrary neighbouring number is also in the doc"
    )


# --- T033: the watermark, which is what stops retention from being theatre ----


def test_a_PRUNED_event_is_not_re_created_by_the_next_drain(wiz, boundary):
    """Without the watermark this feature has a bound that never converges.

    The log cannot be cleared, so a line whose event retention has deleted is still in
    the window: the next drain re-creates it, the next prune deletes it again, and both
    announce — on every command the operator runs. A store that oscillates and a pair
    of messages that never stop is a worse outcome than no retention at all.

    The event deleted here is the OLDER of two, which is the only case that can arise:
    both bounds delete oldest-first, and the mark deliberately admits the whole of its
    own second (so a read split across that second loses nothing). The newest second is
    therefore the one thing a prune never takes and the one thing a re-read can
    re-create — the two cannot meet.
    """
    boundary.deploy()
    older = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))
    window = subprocess.CompletedProcess(
        ["logs"],
        0,
        b"",
        f"{older} {DNS_REFUSED}\n{_line(DNS_REFUSED.replace('api.openai.com', 'x.example.com'))}".encode(),
    )
    assert len(wiz._store_egress_events("local", "acme", window)) == 2

    pruned = min(
        wiz.list_stored_records(wiz.egress_store_dir("local", "acme")), key=lambda p: p.name
    )
    pruned.unlink()  # stand in for the prune, whose own rules are tested above
    boundary.logs.clear()
    assert wiz._store_egress_events("local", "acme", window) == []
    assert [e["host"] for e in _events(wiz)] == ["x.example.com"]
    assert boundary.logs == []


def test_a_FUTURE_dated_line_cannot_blind_the_store(wiz, boundary):
    """The hazard the watermark introduces, closed at the same time as the watermark.

    One line stamped in the future — a skewed host clock, a runtime bug — would park the
    mark ahead of every real event and silence this store permanently, with nothing
    saying so. Strictly worse than the duplicate work the mark exists to avoid, so the
    mark is clamped to this tool's own clock.
    """
    boundary.deploy()
    store = wiz.egress_store_dir("local", "acme")
    far_future = subprocess.CompletedProcess(
        ["logs"], 0, f"2999-01-01T00:00:00Z {TERMINATED_TLS}".encode(), b""
    )
    wiz._store_egress_events("local", "acme", far_future)
    now = time.strftime(wiz.TIME_FORMAT, time.gmtime())
    assert wiz.read_egress_watermark(store) <= now, "a bogus stamp parked the mark in 2999"

    # And a line arriving NOW — which is what the log appends next — still lands.
    fresh = subprocess.CompletedProcess(["logs"], 0, b"", f"{now} {DNS_REFUSED}".encode())
    assert len(wiz._store_egress_events("local", "acme", fresh)) == 1


def test_a_log_clock_that_STEPS_BACK_does_not_silently_blind_the_store(wiz, boundary):
    """The other direction, and it is the one that needs no second failure.

    The clamp above defends only a log clock running AHEAD of this tool's. It does
    nothing when the boundary's clock steps BACKWARD from a value at or below it — a
    restored snapshot, a resumed VM, an operator correcting a clock. Every line of the
    new window is then older than a mark this tool wrote perfectly correctly, so each is
    skipped BEFORE the parser and before the unreadable-line counter: nothing stored,
    nothing warned, and `egress` reporting the environment as watched with nothing
    refused. Silence that means breakage is what T034 forbids.

    So the window is read in full and the operator is told. Idempotence makes the
    re-read free of duplicates (an event id is its content) and the cursor is reset so
    the next drain is quiet again rather than warning about the same step forever.
    """
    boundary.deploy()
    store = wiz.egress_store_dir("local", "acme")
    wiz.advance_egress_watermark(store, time.strftime(wiz.TIME_FORMAT, time.gmtime()))
    ahead = wiz.read_egress_watermark(store)

    stepped_back = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))
    window = subprocess.CompletedProcess(["logs"], 0, b"", f"{stepped_back} {DNS_REFUSED}".encode())
    stored = wiz._store_egress_events("local", "acme", window)
    assert len(stored) == 1, (
        "a refusal logged after the boundary's clock stepped back was dropped, and "
        f"nothing said so (mark was {ahead}, line was {stepped_back})"
    )
    assert any("stepped BACK" in w for w in boundary.warnings), boundary.warnings
    # And it converges: the cursor was re-earned from this window, so a second drain of
    # the same window is silent rather than repeating the complaint on every command.
    boundary.warnings.clear()
    assert wiz._store_egress_events("local", "acme", window) == []
    assert boundary.warnings == []


def test_an_EMPTY_window_is_not_mistaken_for_a_clock_that_stepped_back(wiz, boundary):
    """A boundary that has logged nothing since the last drain is the ordinary quiet
    case. Treating it as drift would put a warning about clocks on every command run
    against an idle environment, which is how an operator learns to ignore the one
    warning that means something."""
    boundary.deploy()
    store = wiz.egress_store_dir("local", "acme")
    wiz.advance_egress_watermark(store, time.strftime(wiz.TIME_FORMAT, time.gmtime()))
    mark = wiz.read_egress_watermark(store)
    empty = subprocess.CompletedProcess(["logs"], 0, b"", b"")
    assert wiz._store_egress_events("local", "acme", empty) == []
    assert boundary.warnings == []
    assert wiz.read_egress_watermark(store) == mark


def test_the_watermark_is_never_listed_as_an_event(wiz, boundary):
    """It is a cursor, not a record. `list_stored_records`' suffix filter is what keeps
    it out, and a store whose reader had to know which of its files are records would be
    one refactor from reporting the cursor as an egress event."""
    boundary.deploy()
    boundary.stderr = [DNS_REFUSED]
    wiz.ingest_egress_events("local", LOCAL_HOST, "acme")
    store = wiz.egress_store_dir("local", "acme")
    assert (store / wiz.EGRESS_WATERMARK).is_file()
    assert len(_events(wiz)) == 1
    assert all(p.suffix == ".json" for p in wiz.list_stored_records(store))


def test_the_watermark_never_moves_backwards(wiz, boundary):
    """A drain that read an older window must not re-open one already closed —
    otherwise a single `--tail`-truncated read undoes the convergence above."""
    store = wiz.egress_store_dir("local", "acme")
    wiz.advance_egress_watermark(store, "2026-08-10T10:00:00Z")
    wiz.advance_egress_watermark(store, "2026-06-01T10:00:00Z")
    assert wiz.read_egress_watermark(store) == "2026-08-10T10:00:00Z"


# --- the MIXED window: a step-back with the pre-step lines still present -------


def test_a_step_back_in_a_MIXED_window_does_not_silently_blind_the_store(wiz, tmp_path, capsys):
    """The half of the step-back defect the maximum-based guard cannot see.

    `_usable_egress_watermark` compares the window's HIGHEST stamp against the cursor,
    so it only fires once the pre-step lines have aged out of the tail. This log is
    append-only and never cleared, so the ordinary next drain holds BOTH pre- and
    post-step lines: the maximum still clears the mark, the guard stays quiet, and
    every post-step line is dropped by `stamp < mark` before the parser sees it.

    Measured through the real function before the fix: a benign line followed by a
    genuine REFUSED after the clock moved back an hour stored NOTHING and warned
    NOTHING — silence indistinguishable from "nothing was refused", which is exactly
    what T034 forbids.
    """
    store = tmp_path / "store"
    store.mkdir()
    wiz.advance_egress_watermark(store, "2026-01-01T11:00:00.000000000Z")

    # Pre-step line still in the tail, then the clock steps back an hour and a real
    # refusal is logged. The maximum of this window still clears the mark.
    stdout = (
        b"2026-01-01T11:00:00.000000000Z benign DNS_NOERROR api.anthropic.com\n"
        b"2026-01-01T10:00:00.000000000Z TCP_DENIED/403 CONNECT api.openai.com:443\n"
    )
    streams = [
        [wiz.split_log_stamp(ln) for ln in stdout.decode().splitlines()],
        [],
    ]
    assert wiz._stamps_step_back(streams) is True, (
        "a decrease WITHIN one stream is direct proof of a step-back, and it is the only "
        "proof that survives the pre-step lines still being present"
    )


def test_the_stream_seam_is_not_read_as_a_step_back(wiz):
    """The mirror defect. squid writes stdout and unbound writes stderr, two
    independently ordered producers — so the seam between them is a stamp decrease
    that means nothing. A detector that fired there would fire on every drain, which
    is as useless as one that never fires."""
    assert (
        wiz._stamps_step_back(
            [
                [("2026-01-01T11:00:00Z", "squid line")],
                [("2026-01-01T10:00:00Z", "unbound line")],
            ]
        )
        is False
    )


def test_an_unstamped_line_is_not_read_as_time_zero(wiz):
    """An unstamped line is a format the reader does not recognise —
    `_egress_line_is_unreadable` accounts for it. Treating it as time 0 would fake a
    step-back on every window containing one."""
    assert (
        wiz._stamps_step_back(
            [[("2026-01-01T11:00:00Z", "a"), (None, "?"), ("2026-01-01T12:00:00Z", "b")]]
        )
        is False
    )
