# Data Model: Kill Switch (Feature 015)

## §1 No new store

This feature **adds no persistent store**. It reads Feature 014's inventory and writes back through
014's existing helpers. Everything below is either transient (one invocation's report) or a field 014
already defines.

That is deliberate: a kill switch that needed its own durable state would have one more thing to be
wrong about at the moment it is trusted most.

## §2 Kill action (transient — one invocation)

| Field | Notes |
|---|---|
| `form` | `stop` \| `destroy`. Never defaulted to `destroy` (FR-006) |
| `scope` | which entries were targeted; everything by default (FR-011) |
| `excluded` | what the scope left out, stated rather than silently dropped (FR-011) |
| `preview` | when true, nothing is acted on (FR-008) |
| `results` | one §3 outcome per environment |
| `ok` | **false if any outcome is not `stopped`/`already-stopped`** (FR-005) |

`ok` is computed, never asserted. *Undetermined* counts as **not ok**: "we do not know" is not
success, and this is the requirement the whole feature turns on.

## §3 Per-environment outcome

| Value | Means |
|---|---|
| `stopped` | acted on, **and observed absent** on the host's re-query (FR-014) |
| `already-stopped` | not running before we acted; still not running after |
| `failed` | the runtime refused, and the host answered |
| `undetermined` | **the host did not answer, or the deployment lock was held** |

**`undetermined` is the load-bearing value.** It is what an unreachable host produces (FR-004,
SC-002), and it is what a contended lock produces (research R5). Both mean the same thing to an
operator: *we did not stop this, and we cannot tell you its state*. Collapsing either into `failed`
or `stopped` is the failure this feature exists to prevent.

**`stopped` may never be inferred from an exit status** (FR-014, SC-002b). The two forms verify
differently:

| Form | Verified absent from |
|---|---|
| `stop` | the **running** set — a stopped container still exists |
| `destroy` | `ps -a` — it is really gone |

## §4 What is written back to the inventory (FR-012)

| Form | Effect on the 014 entry |
|---|---|
| `stop` | append one line to `notes`; **`outcome` unchanged** |
| `destroy` | `outcome = removed` via 014's `set_inventory_outcome` |

A stopped environment is still `active` in 014's vocabulary — it **exists**. 014's outcome set is
closed and describes existence, not runstate, so there is no `stopped` outcome to write and reusing
`removed` would be a lie that survives in the store a later audit reads (research R4).

## §5 Enumeration and ownership are the same decision

Candidates are the inventory's **`active`** entries only.

- `removed` / `host-gone` are already accounted for; re-attempting them would manufacture failures.
- A live container matching the tool's naming but **absent from the inventory is never touched**
  (FR-009). Feature 014 established that the naming convention can be imitated and reported such
  containers without claiming them; this feature *acts*, so the same rule now has teeth.

## §6 Lifecycle of one invocation

```text
read inventory ── unreadable ─> REFUSE, naming the store          (FR-013)
               └─ absent/empty ─> succeed: "nothing recorded"
                                  (recorded, NOT "nothing exists")
      │
      ├─ preview ─> print the plan, touch nothing, exit           (FR-008/SC-007)
      │
      └─ per HOST, in parallel, each with its own timeout:        (FR-004a)
             per environment, sequentially:
                 take the deployment lock ── held ─> undetermined (R5)
                 stop/destroy the project by LABEL                (R1)
             ONE re-query for this host  ──── no answer ─> undetermined for all of its envs
             classify each against what the host reported         (§3)
      │
      write back per §4, then report; exit non-zero unless every outcome is
      stopped or already-stopped                                  (FR-005)
```

**A host that fails does not stop the others** (FR-003): each host's task is independent, and a
timeout or exception yields `undetermined` for that host's environments rather than aborting the run.
