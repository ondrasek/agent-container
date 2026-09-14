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
