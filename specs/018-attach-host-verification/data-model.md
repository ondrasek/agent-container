# Data Model: Verified Attach (Feature 018)

## §1 The pinned entry

There is no new record type. The tool writes a standard OpenSSH `known_hosts` file, and its **lines
are the data model**:

```
[<address>]:<port> ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA...
```

| Element | Source |
|---|---|
| `<address>` | the address `attach` connects to for that environment |
| `<port>` | the environment's published port (`port_for_name`) |
| key type + key | captured verbatim from the container's `~/.ssh/hostkeys/ssh_host_ed25519_key.pub` |

**Standard format on purpose.** Inventing a container-specific store would mean re-implementing
matching, and `ssh` would not read it — the file has to be something `-o UserKnownHostsFile` accepts.
It also means the operator can copy a line elsewhere unchanged (US3, FR-010).

**`[address]:port` is load-bearing, and measured** (research R3): `ssh-keygen -F` matches
`[127.0.0.1]:2222`, and does **not** match `[127.0.0.1]:2223` or the bare `127.0.0.1`. That is what
stops two containers on one host verifying each other's connections (FR-005) — and the bare-host form
would have broken it silently.

**No private key material appears anywhere** (FR-001, FR-012). Every element above is public.

## §2 Location

```text
$XDG_STATE_HOME/agent-container/<host>/known_hosts
```

**Derived host state**, beside `<name>.port` — the category Feature 011 documents as *"computed; safe
to delete"*, which is literally true here: delete it and the next deploy re-captures (research R2).

Per **host**, not per environment: one file, one line per environment. When a host goes its containers
go, so its pins are meaningless — the file dying with the host is correct rather than lossy.

**Deliberately NOT `$XDG_DATA_HOME/agent-container/…`**, where Feature 016's run records, 012's egress
events and 014's inventory live. Those are durable and must outlive their hosts; this must not, and
storing it there invites someone to preserve a pin whose container is long gone.

**And never the operator's `~/.ssh/known_hosts`** (FR-006). SC-007 asserts that file is byte-identical
before and after any tool operation.

## §3 Lifecycle

```text
deploy (any path)  -> capture the .pub through the runtime; write/replace this environment's line
attach             -> ssh -o UserKnownHostsFile=<file> -o StrictHostKeyChecking=yes ...
down / host rm     -> the line may remain; it is re-derived, so staleness costs nothing
capture fails      -> no line written, WARN that attach is unverified, deploy still succeeds
```

**Capture happens on EVERY deploy, and that is what makes FR-007 free** (research R4). The pinned
entry is by construction whatever the tool last saw, so a mismatch at attach means the key changed
*without a deploy* — not by us — and refusing is correct with nothing to attribute. `--purge` +
recreate re-pins because the recreate is a deploy.

**Capture polls for the file.** It does not exist when the container reports `Up`: Feature 016
measured the runtime publishing `Up` before the entrypoint executes a line, with its first write
0.27–0.57 s later, and host-key generation later still. An empty or unparseable read MUST be refused
rather than written — "pinned nothing" and "pinned correctly" are indistinguishable by exit code.

## §4 What this model REMOVES

| Artefact | Status |
|---|---|
| `<state>/<host>/<name>.host_key` | **deleted, and no longer written.** A plaintext private key at mode 0644 that `--purge` did not remove |
| `--host-key` | **removed** (FR-002) |
| `INJECT_HOST_KEY_PATH` + the entrypoint's injected-key branch | removed |

The strongest evidence this feature works is a file that no longer exists — SC-001 measures it at
100%, and FR-011 requires an upgrade to delete any left behind and *say* that it did.
