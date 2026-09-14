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
import shutil
import subprocess
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


def _payload(body: str, *, stream: str = "stdout", run_id: str = "20260914T101010Z-ab12") -> dict:
    script = (
        "set -uo pipefail\n"
        "log() { :; }\n"
        f"AGENT_CONTAINER_NAME=demo\nAGENT_CONTAINER_AGENT=claude\nAGENT_CONTAINER_MODE=headless\n"
        f"RUNS_ID={run_id}\n"
        + _extract("agent_log_payload")
        + f"cat | agent_log_payload {stream} 7\n"
    )
    r = subprocess.run(
        ["bash", "-c", script], input=body, capture_output=True, text=True, timeout=60
    )
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


def test_the_tee_writes_to_a_FILE_and_never_a_pipe():
    """FR-007a, asserted against the source because it is a property of the shape
    rather than of a behaviour a test can provoke.

    A FIFO or a pipe applies BACK-PRESSURE the moment its reader is slow, wedged
    or dead — and the reader here talks to a network endpoint that is allowed to
    be all three, because export is fail-open by design. An agent blocked writing
    a log line is observability breaking the work it exists to observe.
    """
    src = _ENTRYPOINT.read_text()
    i = src.index('if [[ -n "${AGENT_LOG_BUF_DIR:-}" && -d "${AGENT_LOG_BUF_DIR}" ]]; then')
    block = src[i : i + 400]
    assert "tee -a" in block, "the agent's output must be teed"
    assert "mkfifo" not in src, "a FIFO would let a stalled exporter block the agent"
    # And the original invocation survives untouched on the else branch, so an
    # environment with export off is byte-for-byte what it was before 024.
    assert '"${cmd[@]}" <&0 &' in block


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
        + _extract("agent_log_payload")
        + "printf 'hello\\n' | agent_log_payload stdout 1\n"
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
