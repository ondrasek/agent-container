"""Feature 024 US2: the agent's output stream becomes a third payload class.

THE ONE THING THAT CAN GO SILENTLY WRONG HERE IS ESCAPING, and it is why these
tests exist at all. The body of a log payload is ARBITRARY AGENT OUTPUT: quotes,
backslashes, newlines, tabs, control characters, whatever bytes a tool the agent
ran decided to print. Hand-assembled JSON survives that until the first agent
that prints a quote, and then produces a 400 against a fail-open exporter — a gap
that nothing anywhere reports, because failing open is the whole design.

So the payload is built by `jq`, a real serializer, and these tests feed it the
input that would break a naive one. They exercise the SHIPPED shell function,
extracted from `image/entrypoint.sh`, rather than a Python re-implementation of
it: a test of a copy proves the copy correct.
"""

import json
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ENTRYPOINT = _ROOT / "image" / "entrypoint.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("bash") is None,
    reason="needs jq and bash, which the image bakes and a dev machine may not have",
)


def _extract(fn: str) -> str:
    """The shipped function, lifted out of the entrypoint by name.

    Sourcing the entrypoint would RUN it — it configures sshd, git identity and a
    tmux session — so the function under test is cut out instead. Anchored on the
    `name() {` ... `\\n}` pair, which is the file's own consistent shape.
    """
    src = _ENTRYPOINT.read_text()
    m = re.search(rf"^{fn}\(\) \{{\n(.*?)^\}}$", src, re.S | re.M)
    assert m, f"{fn}() not found in entrypoint.sh — did it get renamed?"
    return f"{fn}() {{\n{m.group(1)}}}\n"


def _consts() -> str:
    """The module-level constants the extracted functions read.

    Taken FROM THE SOURCE rather than restated here: a second literal in the test
    would agree with the first today and silently stop agreeing the moment either
    is tuned — which is the same drift the batch interval was just consolidated to
    avoid.
    """
    src = _ENTRYPOINT.read_text()
    out = []
    for name in ("AGENT_LOG_BUF_DIR", "AGENT_LOG_MAX_BATCH_BYTES"):
        m = re.search(rf"^{name}=.*$", src, re.M)
        assert m, f"{name} not found in entrypoint.sh"
        out.append(m.group(0))
    return "\n".join(out) + "\n"


def _payload(body: str, *, stream: str = "stdout", run_id: str = "20260914T101010Z-ab12") -> dict:
    """Build one payload from `body`, through the SHIPPED function.

    The body travels as a FILE because that is how the function takes it — via
    `jq --rawfile`. It used to arrive through `$(...)`, which strips every
    trailing newline while the caller's offset advances by the full byte count,
    so batches silently lost their terminating newlines and reassembled glued
    together at the collector.
    """
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "body"
        f.write_bytes(body.encode())
        script = (
            "set -uo pipefail\n"
            "log() { :; }\n"
            f"AGENT_CONTAINER_NAME=demo\nAGENT_CONTAINER_AGENT=claude\n"
            f"AGENT_CONTAINER_MODE=headless\n"
            f"RUNS_ID={run_id}\n"
            + _consts()
            + _consts()
            + _extract("agent_log_payload")
            + f"agent_log_payload {stream} 7 {f}\n"
        )
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"payload build failed: {r.stderr[-800:]}"
    return json.loads(r.stdout)


def _attrs(doc: dict) -> dict:
    return {
        a["key"]: a["value"]["stringValue"]
        for a in doc["resourceLogs"][0]["resource"]["attributes"]
    }


def test_a_plain_line_becomes_a_well_formed_otlp_document():
    doc = _payload("hello world\n")
    a = _attrs(doc)
    assert a["service.namespace"] == "agent-container"
    assert a["agent_container.signal"] == "log"
    assert a["agent_container.stream"] == "stdout"
    assert a["agent_container.environment"] == "demo"
    assert a["agent_container.agent"] == "claude"
    body = doc["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    assert body == "hello world\n"


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param('he said "hello"', id="double-quote"),
        pytest.param(r"C:\path\to\thing", id="backslash"),
        pytest.param('{"looks": "like json"}', id="embedded-json"),
        pytest.param("line1\nline2\ttabbed", id="newline-and-tab"),
        pytest.param("bell\x07 and vertical\x0btab", id="control-characters"),
        pytest.param("unicode: ✓ é 日本語", id="unicode"),
        pytest.param('"}]}]}" trying to close the envelope', id="envelope-escape-attempt"),
        pytest.param("$(whoami) `id` ${HOME}", id="shell-metacharacters"),
    ],
)
def test_hostile_output_survives_intact(hostile):
    """THE TEST THIS FILE EXISTS FOR.

    Each of these breaks a hand-assembled payload in a different way, and the
    last two are the ones that matter most: an agent that prints `"}]}]}` is
    trying, deliberately or not, to close the JSON envelope early, and an agent
    that prints shell metacharacters is one line away from command substitution
    if the body ever reaches an unquoted expansion.
    """
    doc = _payload(hostile)
    got = doc["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    assert got == hostile, "the body did not survive the round trip byte for byte"


def test_the_run_id_is_OMITTED_when_record_keeping_failed():
    """An empty run id would JOIN UNRELATED RUNS under one key.

    RUNS_ID is empty only when the record could not be opened at all. Exporting
    `run_id: ""` would make every such batch, from every environment, correlate
    with every other — which is worse than a batch nobody can correlate, because
    it produces a confident wrong answer instead of an obvious gap.
    """
    a = _attrs(_payload("orphaned\n", run_id=""))
    assert "agent_container.run_id" not in a
    assert "service.instance.id" not in a


def test_the_streams_stay_DISTINCT():
    """stderr is where the useful part of a failing run usually is. Folding the
    two together would make "what went wrong" unfilterable at the far end."""
    assert _attrs(_payload("x", stream="stdout"))["agent_container.stream"] == "stdout"
    assert _attrs(_payload("x", stream="stderr"))["agent_container.stream"] == "stderr"


def test_the_truncation_marker_is_an_ATTRIBUTE_not_a_body_string():
    """FR-008. A consumer must be able to find the marker by attribute rather
    than by matching text inside a body it does not control — an agent can print
    anything, including a line that looks exactly like our marker."""
    a = _attrs(_payload("agent log export reached the 10MB cap", stream="truncated"))
    assert a["agent_container.stream"] == "truncated"


def test_the_EXPORTER_cannot_apply_back_pressure_to_the_agent():
    """What is actually guaranteed, stated precisely — because the previous
    version of this test was named for a stronger property than it checked.

    It was called `..._never_a_pipe` and asserted `"mkfifo" not in src`. A review
    measured the truth: the agent's stdout goes into `>(tee …)`, which IS a pipe,
    and with `tee` SIGSTOPped the agent plateaus after one 64 KiB pipe buffer. The
    assertion greps for a string that was never going to appear, so it would pass
    against an implementation where the agent genuinely blocks.

    THE REAL GUARANTEE is narrower and still worth having: the EXPORTER — the
    thing that talks to a network endpoint allowed to be slow, wedged or absent —
    only ever READS the buffer files. It cannot stall the agent no matter what the
    collector does, which is the failure FR-007a is aimed at. The residual risk is
    `tee` itself (see the next test), and it is documented rather than hidden.
    """
    src = _ENTRYPOINT.read_text()
    i = src.index("agent_log_export_once() {")
    j = src.index("agent_log_export_flush() {")
    exporter = src[i:j]
    # The exporter opens the buffer for READING only. A `>` or `>>` onto the
    # buffer here would put the exporter in the agent's write path.
    assert '> "${buf}"' not in exporter and '>> "${buf}"' not in exporter
    assert "tail -c" in exporter and "wc -c" in exporter
    tee_i = src.index('if [[ -n "${AGENT_LOG_BUF_DIR:-}" && ')
    block = src[tee_i : tee_i + 400]
    assert "tee -a" in block, "the agent's output must be teed"
    # And the original invocation survives untouched on the else branch, so an
    # environment with export off is byte-for-byte what it was before 024.
    assert '"${cmd[@]}" <&0 &' in block


def test_the_tee_BACK_PRESSURE_RISK_is_documented_not_hidden():
    """The residual risk the test above narrows to, recorded in the source.

    A review measured it: with `tee` stopped the agent blocks after 64 KiB; with
    `tee` killed the agent takes SIGPIPE and exits 141, so a working run would be
    failed by its own log export. This project's standing rule is that a limit is
    stated rather than discovered, so the entrypoint must say so where the tee is.
    """
    src = _ENTRYPOINT.read_text()
    i = src.index('if [[ -n "${AGENT_LOG_BUF_DIR:-}" && ')
    window = src[max(0, i - 2600) : i + 400]
    assert "SIGPIPE" in window, (
        "the tee's residual back-pressure risk is not documented at the tee. "
        "Measured: a stopped tee blocks the agent after one pipe buffer, and a "
        "dead tee kills it with SIGPIPE — that is a limit, and limits are stated."
    )


def test_export_off_changes_NOTHING_about_how_the_agent_is_invoked():
    """`<&0` is documented in the entrypoint as load-bearing: without it bash
    redirects an asynchronous command's stdin from /dev/null. A change about
    telemetry must not ride along with a change to that."""
    src = _ENTRYPOINT.read_text()
    assert src.count('"${cmd[@]}" <&0') == 2, (
        "expected exactly two invocations — the teed one and the untouched original"
    )


def test_the_export_path_has_NO_PER_AGENT_BRANCH(monkeypatch):
    """FR-025a. The output stream is treated identically for every supported
    agent, and that is a property of the code's SHAPE, not of a behaviour a test
    can provoke for four agents in a tier that takes an hour.

    The alternative the operator rejected — reading each agent's native session
    data — would have meant four formats to track, each free to change under us.
    This asserts the narrow reading stayed narrow: the exporter never asks which
    agent it is exporting for, so no agent can break it by changing its own
    output conventions, and no agent can be accidentally privileged.
    """
    src = _ENTRYPOINT.read_text()
    i = src.index("agent_log_payload() {")
    j = src.index("host_metrics_export_once() {")
    block = src[i:j]
    # WORD BOUNDARIES, not substrings. The first version of this test asserted
    # `"pi" not in block` and failed on `pipefail` — an assertion that fires on
    # text having nothing to do with the property is one that gets deleted rather
    # than fixed, taking the property with it.
    for agent in ("claude", "codex", "opencode", "pi"):
        hit = re.search(rf"\b{agent}\b", block)
        assert hit is None, (
            f"the log export path names the agent '{agent}' at offset {hit.start()} "
            f"— the stream must be the same for every agent, or the AGENTS list "
            f"stops being the whole of the agent-specific surface"
        )
    # The agent's NAME rides along as an attribute, which is the opposite of
    # branching on it: the far end can filter, the exporter stays uniform.
    assert "AGENT_CONTAINER_AGENT" in block


def test_the_payload_is_COMPACT_because_the_guard_matches_a_literal_prefix():
    """THE BUG THIS TEST EXISTS FOR, and it shipped past every other test here.

    `agent_log_export_once` validates what it is about to POST by matching the
    literal prefix `{"resourceLogs"` — the same shape check `host_metrics_export_once`
    makes, and for the same reason: a jq COMPILE ERROR would otherwise be posted as
    if it were a log body.

    jq pretty-prints by default. Without `-c` the document begins `{\\n  "resourceLogs"`,
    the guard rejects every payload as malformed, and because export is fail-open the
    only symptom is a run that exports records and no logs. Every test above passed
    throughout, because they parse the JSON — which is valid either way — and none of
    them exercised the guard that consumes it.

    So this asserts the property the GUARD needs, not the property a parser needs.
    """
    script = (
        "set -uo pipefail\n"
        "log() { :; }\n"
        "AGENT_CONTAINER_NAME=demo\nRUNS_ID=r1\n"
        + _consts()
        + _extract("agent_log_payload")
        + "printf 'hello\\n' > /tmp/_acbody$$; agent_log_payload stdout 1 /tmp/_acbody$$\n"
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    out = r.stdout
    assert out.startswith('{"resourceLogs"'), (
        "the payload is not compact, so the shape guard in agent_log_export_once "
        f"will discard it and nothing will ever be exported. Got: {out[:60]!r}"
    )
    assert out.count("\n") <= 1, "a multi-line payload means jq -c was dropped"


def test_every_jq_in_the_export_path_is_COMPACT():
    """The prefix guard is used by more than one exporter in this file, so the
    property belongs to the file rather than to one function."""
    src = _ENTRYPOINT.read_text()
    i = src.index("agent_log_payload() {")
    j = src.index("host_metrics_export_once() {")
    for line in src[i:j].splitlines():
        stripped = line.strip()
        if stripped.startswith("jq ") and not stripped.startswith("jq -c"):
            raise AssertionError(f"non-compact jq in the export path: {stripped!r}")


def test_the_cap_bounds_DISK_not_only_export():
    """The cap's second job, which the first version of it did not do.

    Capping stopped the exporter loop with a `break`. That bounded what reached
    the collector and left `tee -a` appending to the buffers for the rest of the
    run with nothing draining them — so an agent in a print loop, the exact case
    the cap exists for, filled the container's writable layer without limit.

    That is worse than a generic disk-full. A full disk is what this project
    measured making Loki accept every record and store none, which is the silent
    telemetry loss 023 exists to detect. A log cap that can cause it is a control
    that moved the problem.
    """
    src = _ENTRYPOINT.read_text()
    i = src.index("agent_log_export_start() {")
    j = src.index("host_metrics_export_once() {")
    loop = src[i:j]
    assert "capped=1" in loop
    # The loop must keep running after capping, and truncate.
    assert "] && break" not in loop.split("capped=1", 1)[1], (
        "the exporter still breaks out of its loop on cap, leaving tee appending "
        "to buffers nobody drains"
    )
    assert ': > "${AGENT_LOG_BUF_DIR}/stdout"' in loop.split("capped=1", 1)[1], (
        "capped state must TRUNCATE the buffers, or the cap bounds export and not disk"
    )


def test_truncating_under_an_open_append_tee_is_safe():
    """The mechanism the fix depends on, demonstrated rather than assumed.

    `tee -a` opens with O_APPEND, so a truncation under it lands the next write at
    the new end. Without O_APPEND the file offset would be stale and the next
    write would leave a sparse hole — the file would keep growing on disk while
    reading almost empty, which is the failure mode the fix is supposed to prevent
    wearing a disguise.
    """
    import os
    import tempfile
    import time

    with tempfile.TemporaryDirectory() as d:
        buf = os.path.join(d, "buf")
        open(buf, "w").close()
        proc = subprocess.Popen(
            [
                "bash",
                "-c",
                f'for i in $(seq 1 200); do echo "line$i"; sleep 0.01; done | tee -a {buf} >/dev/null',
            ]
        )
        time.sleep(0.4)
        open(buf, "w").close()  # truncate under the running tee
        proc.wait(timeout=30)
        size = os.path.getsize(buf)
        assert size < 2000, (
            f"the file is {size} bytes after truncation — tee is not appending at "
            f"the new end, so truncation does not actually reclaim anything"
        )


def _drive_export(passes: list[str]) -> tuple[bytes, list[str]]:
    """Drive the REAL `agent_log_export_once` across several passes.

    Returns (what the buffer ended up containing, the bodies that were POSTed).
    `curl` is stubbed by a shell function that records the payload, so this
    exercises the offset bookkeeping rather than the network.

    This harness is the one the suite did not have, and its absence is why two
    defects shipped: every other test here either builds a payload or greps the
    source, so nothing drove the loop that decides WHAT to send and how far to
    advance.
    """
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        buf, state, sent = dd / "stdout", dd / "stdout.off", dd / "sent"
        buf.write_text("")
        script = [
            "set -uo pipefail",
            "log() { :; }",
            "AGENT_CONTAINER_NAME=demo",
            "RUNS_ID=r1",
            # Record the payload instead of posting it.
            f'curl() {{ cat >> "{sent}"; printf "\\n" >> "{sent}"; }}',
            _consts(),
            _extract("agent_log_payload"),
            _extract("agent_log_export_once"),
        ]
        # EACH PASS'S CONTENT GOES THROUGH A FILE, never into the script text.
        #
        # Embedding it inline works on macOS and dies on Linux with
        # `OSError: [Errno 7] Argument list too long` — a single argv element is
        # capped at MAX_ARG_STRLEN (128KB, 32 pages) there, and the large-backlog
        # test feeds 200KB. It passed locally and failed in CI, which is the only
        # place the difference shows.
        for n, chunk in enumerate(passes):
            src = dd / f"pass{n}"
            src.write_text(chunk)
            script.append(f"cat {shlex.quote(str(src))} >> {shlex.quote(str(buf))}")
            script.append(
                f'agent_log_export_once "http://x/v1/logs" stdout '
                f"{shlex.quote(str(buf))} {shlex.quote(str(state))}"
            )
        r = subprocess.run(
            ["bash", "-c", "\n".join(script)], capture_output=True, text=True, timeout=120
        )
        assert r.returncode == 0, r.stderr[-600:]
        bodies = []
        if sent.exists():
            for line in sent.read_text().splitlines():
                if not line.strip():
                    continue
                doc = json.loads(line)
                bodies.append(
                    doc["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
                )
        return buf.read_bytes(), bodies


def test_what_was_sent_reassembles_to_the_buffer_BYTE_FOR_BYTE():
    """THE TEST THAT WOULD HAVE CAUGHT BOTH SHIPPED DEFECTS.

    Concatenating every body that was POSTed must equal the file exactly: no
    gaps, no repeats, no lost newlines. That single assertion covers

      * the duplication race — the offset advanced to a size captured before the
        build-and-post while the chunk was read to EOF after it, so every batch
        re-sent the window in between; and
      * the trailing-newline loss — `$(...)` strips them while the offset advances
        by the full byte count, so `"foo\\n"` and `"bar\\n"` arrived as `foobar`.

    Both are invisible to a test that only checks one payload is well formed.
    """
    content, bodies = _drive_export(["first\n", "second\nthird\n", "\n\n", "fourth\n"])
    assert b"".join(b.encode() for b in bodies) == content, (
        f"sent {bodies!r} does not reassemble to the buffer {content!r} — "
        f"either bytes were dropped, duplicated, or their newlines were eaten"
    )


def test_a_pass_with_nothing_new_sends_NOTHING():
    """An exporter that re-sends an unchanged buffer duplicates the whole run's
    output every interval, which is the same defect in its loudest form."""
    _, bodies = _drive_export(["only\n", "", ""])
    assert len(bodies) == 1, f"an idle pass sent something: {bodies!r}"


def test_a_TRUNCATED_buffer_does_not_kill_the_stream(tmp_path):
    """`/tmp` survives a container restart; the offsets used not to be cleared.

    With a stale offset past the end of a buffer that restarts at zero, `size >
    off` is never true again and the stream is dead for the whole new run — with
    nothing logged, because nothing failed.
    """
    buf, state, sent = tmp_path / "b", tmp_path / "b.off", tmp_path / "sent"
    buf.write_text("")
    state.write_text("999999")  # a previous run's offset
    script = "\n".join(
        [
            "set -uo pipefail",
            "log() { :; }",
            "AGENT_CONTAINER_NAME=demo",
            "RUNS_ID=r1",
            f'curl() {{ cat >> "{sent}"; printf "\\n" >> "{sent}"; }}',
            _consts(),
            _extract("agent_log_payload"),
            _extract("agent_log_export_once"),
            f"printf 'after-restart\\n' >> {buf}",
            f'agent_log_export_once "http://x/v1/logs" stdout {buf} {state}',
        ]
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert sent.exists() and "after-restart" in sent.read_text(), (
        "a stale offset from a previous boot permanently silenced the stream"
    )


def test_the_tee_is_gated_on_the_EXPORTER_not_on_a_leftover_directory():
    """`/tmp` survives a restart of the same container.

    Gating the tee on the buffer DIRECTORY meant that "deploy with export on, set
    `export_agent_logs: false`, restart" left the directory behind: the tee ran,
    no exporter drained it, and the buffers grew for the whole life of a run whose
    operator had just turned export off.

    The sentinel means "an exporter is running NOW", so it must be cleared on
    every path out of `agent_log_export_start` that does not start one — including
    the early return when export is disabled, which is the exact path the bug
    travelled.
    """
    src = _ENTRYPOINT.read_text()
    i = src.index('if [[ -n "${AGENT_LOG_BUF_DIR:-}" && ')
    gate = src[i : i + 200]
    assert "/exporting" in gate, "the tee is gated on something other than the exporter sentinel"
    assert ' -d "${AGENT_LOG_BUF_DIR}" ]]; then' not in gate, (
        "the tee is gated on the directory existing, which outlives the exporter"
    )
    start = src[src.index("agent_log_export_start() {") : src.index("host_metrics_export_once() {")]
    before_return = start[: start.index("agent log export disabled")]
    assert "rm -f" in before_return and "/exporting" in before_return, (
        "the sentinel is not cleared before the disabled early-return, so turning "
        "export off and restarting leaves the tee running with nothing draining it"
    )


def test_a_large_backlog_is_split_across_SEVERAL_bounded_posts():
    """One batch is one OTLP log RECORD, so an unbounded batch is an unsendable one.

    A pass following a stall used to ship everything accumulated — up to the full
    10MB cap — as a single `body.stringValue`. Loki's default `max_line_size` is
    256KB and OTLP receivers bound request size independently, so that record is
    rejected. The response is never read while the offset commits regardless, so
    a rejected batch is gone PERMANENTLY: exactly the "2xx is not acceptance"
    failure 023 exists to kill, and loudest for the runs that produced the most.
    """
    big = "x" * 200_000 + "\n"
    content, bodies = _drive_export([big, "", "", "", ""])
    assert len(bodies) > 1, "a 200KB backlog went out as one record"
    ceiling = int(
        re.search(r"AGENT_LOG_MAX_BATCH_BYTES=\D*(\d+)", _ENTRYPOINT.read_text()).group(1)
    )
    for b in bodies:
        assert len(b.encode()) <= ceiling, (
            f"a post carried {len(b.encode())} bytes, over the ceiling"
        )
    # And splitting must still be lossless — the whole point of bounding the read
    # rather than dropping the overflow.
    assert b"".join(x.encode() for x in bodies) == content


def test_a_cap_of_ZERO_is_refused_rather_than_meaning_export_nothing():
    """`0` is digits, so it slipped the guard and became a threshold of zero: the
    run was capped on its first pass and — now that capping truncates — its output
    discarded every pass after. Most operators read `0` as "no cap"."""
    src = _ENTRYPOINT.read_text()
    start = src.index("agent_log_export_start() {")
    block = src[start : src.index("host_metrics_export_once() {")]
    assert "0) log" in block and "means 'export nothing'" in block, (
        "a cap of 0 is not refused, so it silently means the opposite of what it reads as"
    )


def test_export_is_gated_on_HEADLESS_mode():
    """Only `run_headless_agent` tees into the buffers.

    In interactive mode the loop spun every two seconds forever over buffers
    nothing wrote to, while `up` promised the operator that everything the agent
    printed reached their collector. A trail claiming a completeness it does not
    have is what 016 spends a section refusing.
    """
    src = _ENTRYPOINT.read_text()
    block = src[src.index("agent_log_export_start() {") : src.index("host_metrics_export_once() {")]
    assert 'AGENT_CONTAINER_MODE:-interactive}" != "headless"' in block, (
        "the exporter starts regardless of mode, so it runs where nothing tees to it"
    )


def test_the_cap_notice_is_not_swallowed_by_the_subshell_redirect():
    """`log` writes to stderr; the subshell used to close with `> /dev/null 2>&1`.

    The one line in that loop an operator must see — that their run hit the cap
    and the rest of its output is being discarded — went to /dev/null, leaving a
    marker at the collector as the only evidence, findable only by first noticing
    a gap.
    """
    src = _ENTRYPOINT.read_text()
    block = src[src.index("agent_log_export_start() {") : src.index("host_metrics_export_once() {")]
    assert ") > /dev/null &" in block
    assert ") > /dev/null 2>&1 &" not in block, "stderr is discarded, taking the cap notice with it"


def test_every_payload_SHAPE_GUARD_matches_what_its_builder_produces():
    """A guard whose literal does not match its builder rejects everything.

    `host_metrics_export_once` checked for `{"resourceLogs"` while
    `host_metrics_payload` builds `{"resourceMetrics"` — copied from the record
    exporter, whose payload really is a logs document. Every sample therefore took
    the failure branch, which interpolated an `${agent}` that is neither local
    there nor global anywhere: under `set -u` in a disowned subshell that is an
    abort, so the host-metrics sampler died on its first tick and has never
    produced a second sample.

    Nothing reported it: the exporter is deliberately silent, its subshell's
    output is discarded, and an empty host-metrics panel reads as a quiet host.
    This pairs each guard with its builder so the next copy-paste is caught.
    """
    for fn, expected in (
        ("agent_log_export_once", '{"resourceLogs"'),
        ("host_metrics_export_once", '{"resourceMetrics"'),
    ):
        block = _extract(fn)
        assert f"'{expected}'*)" in block, (
            f"{fn}'s shape guard does not match the document its builder produces; "
            f"expected the literal {expected!r}"
        )


def test_no_shape_guard_failure_branch_uses_an_UNBOUND_variable():
    """The second half of the same bug, and the half that turned a rejected
    payload into a dead exporter.

    These run under `set -u` inside disowned subshells, so an undefined name in
    the branch that reports a problem kills the thing that was reporting it.
    """
    for fn in ("agent_log_export_once", "host_metrics_export_once"):
        block = _extract(fn)
        branch = [ln for ln in block.splitlines() if "could not build" in ln]
        assert branch, f"{fn} has no shape-guard failure branch"
        for ln in branch:
            assert "${agent}" not in ln, (
                f"{fn}'s failure branch interpolates ${{agent}}, which is unbound "
                f"there — under set -u that aborts the exporter it was meant to warn about"
            )


def test_the_interpreter_bridge_is_verified_by_IMPORT_not_by_presence():
    """The bridge once shipped with 3.14-only syntax that parsed where it was
    edited and was a SyntaxError where it runs. A presence check would have
    reported everything fine while the container supervised nothing.

    And a missing or unimportable bridge must be LOUD: an interpreter that looks
    deployed, answers ssh and silently supervises nothing is the exact failure
    this feature exists to remove.
    """
    src = _ENTRYPOINT.read_text()
    i = src.index('if [[ "${AGENT_CONTAINER_ROLE:-agent}" == "interpreter" ]]; then')
    block = src[i : i + 2000]
    assert "importlib.util" in block, "the bridge is checked by existence rather than by import"
    assert block.count("ERROR:") >= 2, "a broken bridge does not report loudly"
    assert "supervise NOTHING" in block
