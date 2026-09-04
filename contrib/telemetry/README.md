# Host telemetry (contrib)

Signals an agent container **cannot** produce about itself: the container
host's systemd journal and its machine-wide resource usage.

Deliberately OUTSIDE the tool. `agent-container` exports its own trail with
curl and speaks the protocol only — never a backend package, never a
supervised second process (Constitution VI, and see `docs/observability.md`).
Host-level collection is a property of the *host*, not of an environment, so
it is run next to the collector it feeds rather than shipped in the image.

## host-collector.yaml — machine metrics

An OpenTelemetry Collector config: CPU, memory, filesystem, network, load and
process counts, tagged `service.name=lima-host`.

    podman run -d --name hostcol \
      -v ./host-collector.yaml:/etc/otelcol/config.yaml:ro \
      -v /:/hostfs:ro \
      docker.io/otel/opentelemetry-collector-contrib:latest \
      --config /etc/otelcol/config.yaml

## journal-to-otlp.sh — systemd logs

The collector's `journald` receiver shells out to `journalctl`, which the
distroless collector image does not contain — and under **rootless** podman a
container cannot read `/var/log/journal` at all: the files are `0640`
root-owned, which maps to `nobody` inside the user namespace. So the journal is
read where it lives, on the host, and posted with the same curl+jq idiom the
agent containers use for their own records.

    OTLP_ENDPOINT=http://127.0.0.1:4318/v1/logs ./journal-to-otlp.sh

Follows from NOW rather than replaying history: a cold start would otherwise
push the entire journal into the collector at once.

Priorities are mapped to OTel severities EXPLICITLY, not arithmetically —
journald counts 0 (emerg) to 7 (debug) and OTel counts the other way, so a
wrong direction here would file every emergency as a debug line.
