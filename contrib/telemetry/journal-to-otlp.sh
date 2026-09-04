#!/bin/bash
# Ship the host's systemd journal to OTLP/HTTP.
#
# The collector's journald receiver shells out to `journalctl`, which the
# distroless collector image does not contain — so the journal is read here, in
# an image that has it, and posted with the same curl+jq idiom the agent
# containers use for their own records. No extra runtime, no backend package.
set -uo pipefail
ENDPOINT="${OTLP_ENDPOINT:?OTLP_ENDPOINT is required}"

# Follow from now rather than replaying history: this is a live signal, and a
# cold start would otherwise dump the whole journal into the collector at once.
journalctl --directory=/journal -o json -f -n 0 2>/dev/null | while read -r line; do
    [ -n "${line}" ] || continue
    printf '%s' "${line}" | jq -c '
        # PRIORITY -> OTel severity. journald priorities run 0 (emerg) to 7
        # (debug); OTel severity numbers run the other way, so the mapping is
        # explicit rather than arithmetic — a wrong direction here would file
        # every emergency as a debug line.
        def sev($p):
            if   $p == "0" then {n: 21, t: "FATAL"}
            elif $p == "1" then {n: 21, t: "FATAL"}
            elif $p == "2" then {n: 21, t: "FATAL"}
            elif $p == "3" then {n: 17, t: "ERROR"}
            elif $p == "4" then {n: 13, t: "WARN"}
            elif $p == "5" then {n:  9, t: "INFO"}
            elif $p == "6" then {n:  9, t: "INFO"}
            else                {n:  5, t: "DEBUG"} end;
        . as $j
        | sev(($j.PRIORITY // "6"))               as $s
        # journald gives microseconds since epoch; OTLP wants nanoseconds.
        | (($j.__REALTIME_TIMESTAMP // "0") + "000")  as $ns
        | {
            resourceLogs: [ {
              resource: { attributes: [
                { key: "service.name",      value: { stringValue: "lima-host" } },
                { key: "service.namespace", value: { stringValue: "agent-container" } },
                { key: "host.role",         value: { stringValue: "container-host" } },
                { key: "host.name",         value: { stringValue: ($j._HOSTNAME // "unknown") } }
              ] },
              scopeLogs: [ {
                scope: { name: "systemd/journal" },
                logRecords: [ {
                  timeUnixNano: $ns,
                  observedTimeUnixNano: $ns,
                  severityNumber: $s.n,
                  severityText: $s.t,
                  body: { stringValue: ($j.MESSAGE // "" | if type == "array" then "binary" else . end) },
                  attributes: [
                    { key: "systemd.unit",   value: { stringValue: ($j._SYSTEMD_UNIT // $j.UNIT // "none") } },
                    { key: "syslog.ident",   value: { stringValue: ($j.SYSLOG_IDENTIFIER // "none") } },
                    { key: "process.pid",    value: { stringValue: ($j._PID // "none") } },
                    { key: "systemd.slice",  value: { stringValue: ($j._SYSTEMD_SLICE // "none") } }
                  ]
                } ]
              } ]
            } ]
          }' 2>/dev/null \
    | curl -sS -m 10 -X POST "${ENDPOINT}" \
        -H 'Content-Type: application/json' --data-binary @- > /dev/null 2>&1 || true
done
