# Data Model: Durable Host Inventory (Feature 014)

## §1 Inventory entry

One **deployment** the tool made. A reused name produces additional entries, never a replacement.

| Field | Type | Notes |
|---|---|---|
| `schema` | int | starts at `1`, so a consumer can refuse a record it does not understand rather than misread it |
| `entry_id` | string | generated per deployment, sortable. Also the filename. **This is the key** — name and host are attributes (FR-015) |
| `name` | string | the environment name. NOT unique: a recreated environment yields another entry |
| `host` | string | the host short name **as it was at creation**, retained after that host leaves the registry (FR-003) |
| `host_provisioned` | bool | whether the tool created the host, so US3 can distinguish it from one merely registered |
| `created_at` | string | RFC 3339, UTC |
| `outcome` | string | one of the four in §2. **Mutated** over the entry's life |
| `outcome_at` | string \| null | when the outcome last changed; null while `active` |
| `notes` | array[string] | tool-generated diagnostics only (e.g. a write that had to be retried) |

**No free-text field exists** (research R10). Every field above is tool-generated, so unlike Feature
016 — which had to *state* its task-text exposure — FR-010's guarantee here is structural: there is
nowhere for a credential to arrive. A test pins the field set closed, because that is the only thing
holding the guarantee.

## §2 Stored outcome — closed, four values, `unknown` unrepresentable

| Value | Meaning |
|---|---|
| `active` | expected to exist |
| `removed` | torn down **while its host remained** |
| `vanished` | found absent with no action of ours |
| `host-gone` | its host went away and took it — whether the tool deprovisioned it or not |

The `removed` / `host-gone` distinction is **what disappeared**, not who caused it (FR-004). Keeping
the host's fate on the entry means an operator asking *"where did this go"* gets the answer in one
place rather than needing a second lookup.

**`unknown` MUST NOT be storable** (FR-004, SC-003), enforced where the entry is constructed. A
reconciliation that cannot reach a host has an obvious place to write it, and doing so would make the
record permanently lie about a host that later comes back.

## §3 Reconciliation result — computed, never stored

| Classification | Condition |
|---|---|
| `agreeing` | recorded `active` and present on its host |
| `missing` | recorded `active`, host reachable, container absent |
| `unrecorded` | container present on a host, matching the tool's naming, with no entry |
| `unknown` | the host could not be reached |

`unknown` is required for an unreachable host and `missing` is forbidden there (FR-006, SC-004) —
Feature 002's fail-closed rule, because invisible is indistinguishable from gone.

**`unrecorded` is an observation, not a claim.** The tool recognises its own containers by the
`CONTAINER_PREFIX` naming convention, which an operator can imitate — so a prefix match is evidence
of a *name* and nothing more. Reporting it is right; upgrading it to ownership is the false claim
SC-005 counts (FR-007).

## §4 Storage layout

```text
$XDG_DATA_HOME/agent-container/inventory/<entry-id>.json
```

**Flat — deliberately unlike `runs/<host>/<environment>/`** (research R2). FR-003 requires an entry to
outlive its host's removal, and a per-host directory is deleted with the host, destroying exactly the
entries the requirement exists to keep. Host is an attribute, not a path component.

One file per entry, rewritten atomically on an outcome change — the same `atomic_write_json` Feature
016 built and 012's egress events already reuse (research R3/R4). FR-009 then holds by shape: separate
entries are separate files, and two writers to one entry serialise on the rename.

**Retention is NOT 016's.** Entries are kept indefinitely with a large backstop cap; age-based pruning
is forbidden as a default (FR-012), because the entries most worth having are the oldest forgotten
ones. The write path is shared; the policy is not, and the policy does not live in the shared helper.

## §5 Lifecycle

```text
compose_up_exec        -> create entry, outcome=active            (every deploy path passes here)
down_container         -> outcome=removed
do_wipe                -> outcome=removed
host rm [--destroy]    -> outcome=host-gone for that host's active entries
reconcile (explicit)   -> computes §3; may set outcome=vanished for a confirmed absence
list                   -> a one-line hint when record and reality disagree (FR-005a)
```

**Reconciliation may write `vanished`, and only reconciliation may.** It is the one path that has
seen a reachable host report the container absent; anything else guessing would be recording an
inference as a fact.
