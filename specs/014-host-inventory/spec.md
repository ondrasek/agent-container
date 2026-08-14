# Feature Specification: Durable Host Inventory

**Feature Branch**: `014-host-inventory`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Host history tracked at user level — a durable record of what the tool has deployed, where, and when. Prerequisite for the kill switch."

## Overview

The tool can only see what is **currently answering**.

`list` is live-reconciled: it asks each registered host's daemon what exists and reconciles that
against local port state. This is the right design for *"what is running now"*, and it was made
fail-closed deliberately so an unreachable host renders as `unreachable` rather than as zero
containers. But it means the tool has **no memory**. It cannot answer:

- What did I deploy last week, and where?
- Is there a container on a host I have since removed from the registry?
- Something is billing me — did this tool create it?

That last question is the sharp one. A container on an unreachable, forgotten or deprovisioned
host is invisible to a tool that only asks live daemons — and invisible is indistinguishable from
gone. Constitution I says the *container* is disposable; it does not say the **record** of it
should be.

This feature gives the tool a durable, operator-machine-level inventory of everything it has
created: what, where, when, and what became of it.

> **It is also the prerequisite for a kill switch.** You cannot reliably destroy what you cannot
> enumerate, and enumerating by asking live hosts fails exactly when a kill switch matters most —
> when something is wrong, unreachable, or forgotten.

## Clarifications

### Session 2026-07-29

- Q: Do the inventory (this feature) and run observability (Feature 016) share one durable store?
  → A: **No — two separate stores.** They look alike but behave differently: the inventory is
  small, mutated in place, and its entries must be kept **indefinitely**, because the whole point
  is finding the environment forgotten six months ago. Run records are append-only, grow with
  every run, and want aggressive pruning. One store means one of them gets the wrong retention —
  either the valuable old inventory entries are pruned away, or the run log grows without bound.
  They may share *where they live* and *how writes are made safe*; they do not share a schema or
  a retention rule.
- Q: Where does the inventory live, given Feature 011 places derived host state under
  `<state>/<host>/`? → A: **Not there.** The inventory must survive a host's removal (FR-003),
  and a per-host directory is deleted with the host. It needs a place of its own, not scoped to any
  host. *(Amended after Feature 016 shipped: this was recorded as needing a **sixth location**, and
  016 then created that location — so it is a **new tenant** in it. See FR-002.)*

### Session 2026-07-29 (second pass)

- Q: What is the closed set of outcome values? → A: **`active` / `removed` / `vanished` /
  `host-gone`.** Four, keeping the host's fate on the environment itself rather than requiring a
  lookup against the host record — an operator asking *"where did this go"* gets the answer in one
  place. The disambiguation is by **what disappeared**, not by who caused it: `removed` = the
  environment was torn down while its host remained; `host-gone` = the host went away and its
  environments went with it, whether the tool deprovisioned it or not. `unknown` is deliberately
  **not** an outcome — it is a reconciliation *result*, computed, never stored.
- Q: How long are entries kept? → A: **Everything, indefinitely, with a large backstop cap.** The
  volume concern is largely theoretical: one row per environment ever created, so years of heavy
  use is hundreds of rows. Keeping everything is what makes the feature work, since its value is
  the entry you forgot. FR-012's bound is satisfied by a cap that exists for pathological cases,
  not for tidiness.
- Q: How is an entry identified, so a reused name does not overwrite history? → A: **A generated
  id per creation.** Every deployment mints a new entry; host and name are attributes to query by.
  FR-015 then holds **by construction** — there is no overwrite path to get wrong — and a reused
  name is simply several entries.
- Q: When does reconciliation run? → A: **An explicit command, plus a hint in `list`.** Full
  classification is paid for when asked, but `list` — which already queries every host — surfaces
  a one-line note when record and reality disagree. A discrepancy you must already suspect in
  order to find is a discrepancy nobody finds.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Remember everything the tool created (Priority: P1)

Every environment the tool creates is recorded on the operator's machine, and that record
survives the container, the host and the registry entry. The operator can ask what exists —
including things no live daemon will admit to.

**Why this priority**: Without the record there is no feature, and no kill switch. It is also the
only part that must be right from the first release: a record that begins late has a permanent
blind spot.

**Independent Test**: Create environments across two hosts, remove one host from the registry,
stop one container, and confirm the inventory still accounts for all of them with an accurate
state for each.

**Acceptance Scenarios**:

1. **Given** an environment is created, **When** the operator inspects the inventory, **Then** it
   records what was created, on which host, and when.
2. **Given** a host is removed from the registry, **When** the operator inspects the inventory,
   **Then** environments created on it are still listed, marked as belonging to a host no longer
   registered.
3. **Given** an environment is torn down through the tool, **When** the operator inspects,
   **Then** it is recorded as gone rather than silently dropped.
4. **Given** an environment removed **outside** the tool, **When** the operator inspects, **Then**
   the discrepancy is visible — the inventory does not claim it still exists.

---

### User Story 2 - Reconcile memory against reality (Priority: P1)

The operator can compare what the tool remembers with what hosts actually report, and see the
differences: things remembered but gone, things present but unrecorded, things on hosts that
cannot be reached.

**Why this priority**: A record that silently diverges from reality is worse than none, because
it is trusted. Reconciliation is what keeps the inventory honest, and it is what a kill switch
will act on.

**Independent Test**: Create a container outside the tool and delete one created by it, then
confirm reconciliation reports both discrepancies distinctly.

**Acceptance Scenarios**:

1. **Given** an environment recorded but absent from its host, **When** reconciling, **Then** it
   is reported as *missing*, not quietly deleted from the record.
2. **Given** a container present on a host but never recorded, **When** reconciling, **Then** it
   is reported as *unrecorded* — the tool must not claim ownership of what it did not create.
3. **Given** an unreachable host, **When** reconciling, **Then** its environments are reported as
   *unknown*, never as missing (Feature 002's fail-closed rule).
4. **Given** everything agrees, **When** reconciling, **Then** the result is unambiguous and
   quiet.

---

### User Story 3 - Account for what a deployment costs to leave running (Priority: P3)

For environments on hosts the tool provisioned, the operator can see how long each has existed —
enough to notice something forgotten and still billing.

**Why this priority**: Real, and the motivating anxiety behind the kill switch, but it depends
entirely on US1/US2 and adds no safety of its own. Lowest priority deliberately.

**Independent Test**: Create an environment, wait, and confirm the inventory reflects its age and
whether its host is one the tool provisioned.

**Acceptance Scenarios**:

1. **Given** a long-lived environment, **When** the operator inspects, **Then** its age is
   evident without arithmetic.
2. **Given** a tool-provisioned host, **When** the operator inspects, **Then** it is
   distinguishable from a host the operator registered but did not create.

---

### Edge Cases

- **A write that fails** (disk full, permissions) — must not fail the deploy it is recording, but
  must not silently lose the record either; an unrecorded environment is the exact blind spot
  this feature exists to remove.
- **Two invocations at once** — the record must not be corrupted by concurrent writes.
- **A container created outside the tool** — must never be claimed as the tool's own.
- **A host that is unreachable, versus one that is gone** — must be distinguishable; conflating
  them makes reconciliation lie. Unreachable yields the reconciliation result *unknown*; gone
  yields the stored outcome `host-gone`.
- **The record is deleted or missing** — must degrade to today's live-only behaviour, not fail.
- **The record disagrees with local port state** — one of them must be authoritative, stated.
- **An environment recreated with the same name** — must not silently overwrite the history of
  the previous one.
- **Sensitive values** — nothing recorded may contain a credential, token or key.
- **Unbounded growth** — the record must not grow without limit on a machine used for years.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST durably record every environment it creates: what, on which host,
  and when.
- **FR-002**: The record MUST live at **user level**, on the operator's machine, independent of
  any project and of any host. It MUST NOT live under the per-host state directory
  (`<state>/<host>/`), which is removed with its host — that would delete exactly the entries
  FR-003 requires be kept. Concretely: **`~/.local/share/agent-container/inventory/`**
  (`$XDG_DATA_HOME/agent-container/inventory/`).

  This is a **new tenant** in the durable-user-data location Feature 016 established, not a new
  location — when this spec was written that location did not exist, and it now holds `runs/`
  (Feature 016) and `egress/` (Feature 012 US3). Sharing the parent is exactly the "shared
  placement" FR-012a permits: one directory to back up or move, while schema and retention stay
  separate. `docs/layout.md` must name the tenant.

  **Flat, not `<host>/<environment>/` like its two siblings.** Their layout would defeat FR-003 —
  a per-host directory is deleted with its host — so `host` is an *attribute* of the entry. The
  layouts differ because the lifetimes do, and `docs/layout.md` must say so, or a later reader will
  "fix" the inconsistency.
- **FR-003**: The record MUST survive the container's removal, the host's removal from the
  registry, and the host's deprovisioning.
- **FR-004**: The tool MUST record the **outcome** of an environment from this closed set:
  **`active`** (expected to exist), **`removed`** (torn down while its host remained),
  **`vanished`** (found absent with no action of ours), **`host-gone`** (its host went away and
  took it). The distinction between `removed` and `host-gone` is **what disappeared** — the
  environment or the host — not who caused it. `unknown` MUST NOT be an outcome value: it is a
  reconciliation result, computed at comparison time, never stored.
- **FR-005**: The operator MUST be able to **reconcile** the record against what hosts report via
  an **explicit command**, seeing each entry classified as agreeing, recorded-but-missing,
  present-but-unrecorded, or unknown.
- **FR-005a**: `list` MUST surface a **brief indication** when the record and live state disagree,
  without performing or printing the full classification. `list` already queries every host, so
  this costs little — and a discrepancy an operator must already suspect in order to look for is
  one nobody finds.
- **FR-006**: An unreachable host MUST yield **unknown**, never *missing* — consistent with the
  existing fail-closed rule.
- **FR-007**: The tool MUST NOT claim ownership of a container it did not create.
- **FR-008**: A failure to write the record MUST NOT fail the operation being recorded, but MUST
  be surfaced — a silently unrecorded environment is the blind spot this feature removes.
- **FR-009**: Concurrent invocations MUST NOT corrupt the record.
- **FR-010**: **No credential, token or key value** may be written to the record (Constitution
  III).
- **FR-011**: The record MUST be readable through the existing machine-readable interface.
- **FR-012**: Entries MUST be kept **indefinitely** by default. Growth is bounded in practice —
  one entry per environment ever created — so the bound FR-012 requires is a **deliberately large
  backstop cap** for pathological cases, never routine tidying. Age-based pruning MUST NOT be the
  default: the entries most worth having are the oldest forgotten ones, which it deletes first.
- **FR-012a**: This record MUST be **separate** from Feature 016's run records — separate schema
  and separate retention. Shared placement and shared write-safety machinery are permitted and
  expected; a shared store is not, because their retention needs are opposite.
- **FR-013**: If the record is absent or unreadable, the tool MUST degrade to today's live-only
  behaviour rather than fail.
- **FR-014**: Where any two of the tool's three memories disagree, which is authoritative for which
  purpose MUST be defined and documented. There are **three**, not two, and the edge case below about
  local port state is why this requirement names them all:

  | Source | Authoritative for | Lifetime |
  |---|---|---|
  | the live daemon | what is running **now** | instant |
  | local port state (`<state>/<host>/*.port`) | the **port number**, and per-host enumeration | dies with its host |
  | this record | what the tool **ever created** | indefinite |

  The purposes do not overlap: port state is never consulted about history, this record is never
  consulted about the present, and nothing but port state decides a port (Constitution IV).
  A disagreement between port state and this record is therefore **information, not a conflict** — it
  means a host's state was cleared while the record kept its entries, which is exactly what FR-003
  asks for.
- **FR-015**: Each deployment MUST create a **new entry with its own generated identifier**; host
  and name are attributes, not the key. Recreating an environment with a previously-used name
  therefore yields an additional entry and cannot overwrite the earlier one — the guarantee holds
  by construction rather than by careful handling.

### Key Entities *(include if feature involves data)*

- **Inventory entry**: one *deployment* the tool made — a generated identifier, plus name, host,
  creation time, and outcome (`active` / `removed` / `vanished` / `host-gone`). A reused name
  produces additional entries, never a replacement.
- **Host reference**: which host an entry belongs to, retained even after that host leaves the
  registry, and whether the tool provisioned it.
- **Reconciliation result**: the comparison of record against live state, classifying each entry
  as agreeing, missing, unrecorded, or unknown.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every environment created through the tool appears in the inventory — **100%**.
- **SC-002**: An entry remains after its container, its host registration, and its host are all
  gone — **100%**.
- **SC-003**: Reconciliation classifies every entry into exactly one of agreeing / missing /
  unrecorded / unknown — **zero** unclassified — and every stored outcome is one of the four
  values in FR-004, with **zero** entries carrying `unknown` as a stored outcome.
- **SC-003a**: Recreating an environment with a previously-used name yields **two** entries, and
  the earlier one is unchanged — verified across repeated create/remove/create cycles.
- **SC-004**: An unreachable host never produces a *missing* classification — **zero**
  occurrences.
- **SC-005**: A container not created by the tool is never claimed — **zero** false ownership.
- **SC-006**: No credential value appears in the record — **100%** of runs.
- **SC-007**: Concurrent invocations produce no corrupted or lost entries — **zero** across a
  concurrency test.
- **SC-008**: With the record absent, every existing command behaves exactly as before — **zero**
  regressions.
- **SC-009**: For every entry the operator can see **how long it has existed** and **whether its host
  was tool-provisioned**, without computing either — **100%** of entries, *including entries whose
  host is gone*. The trailing clause is the one that can fail: the host reference is retained
  (FR-003), so age must still answer after the host does not exist, and a rendering that reaches for
  the live host to derive either value breaks exactly where this feature is most useful. Added after
  `/speckit-analyze` found US3 to be the only story with no measurable outcome (finding G2) — an
  unmeasured story is the one that quietly ships half-working, because its tasks pass and no
  criterion is failing.

## Assumptions

- **The record is a memory aid, not a source of truth about the present.** Live state is
  authoritative for *"what is running"*; the record is authoritative for *"what we created"*.
  FR-014 requires that division be stated rather than inferred.
- **User level, not project level.** An operator deploys the same project to several hosts and
  several projects to one host; the question *"what have I got running"* is about the operator,
  not the project — and it must survive deleting the project.
- **Recording is a side effect of acting**, not a separate step an operator can forget.
- **The inventory begins at install, and is not backfilled.** Entries are minted only at creation
  (FR-015), so environments created before this feature existed are not in it and will reconcile as
  `unrecorded`. That is **accurate rather than a defect** — they genuinely are not in the record, and
  `unrecorded` says exactly that without claiming ownership either way (FR-007). The gap is a
  one-time tail that shrinks with every subsequent deployment.

  Backfilling from local port state was considered and **rejected**: `<state>/<host>/*.port` is a
  census of *ports allocated and not released*, not of environments that exist — a container removed
  outside the tool leaves its port file behind. Reconstructed entries would therefore describe
  environments that are gone, with an outcome that cannot be determined: not `removed` (the tool did
  not record removing them) and not honestly `active`. **A fabricated entry is worse than an absent
  one**, especially in the store a kill switch reads.
- **This feature does not delete anything.** It remembers, compares and reports; acting on the
  result is the kill switch's job.
- Retention is bounded but generous — this is for a machine used for years, and the interesting
  entries are the old forgotten ones.

## Out of Scope

- Destroying or stopping anything (that is the kill switch).
- Cost or billing integration with any provider.
- Recording what an agent *did* inside a container (that is observability).
- Synchronising the record between machines.
- Managing containers the tool did not create.

## Dependencies

- **Feature 001 / 002 (hosts, lifecycle)**: the registry, per-host state, and the fail-closed
  enumeration rule FR-006 inherits.
- **Feature 006 (agent-as-code)**: provisioned hosts, whose deprovisioning must not erase history.
- **Feature 009 (agent-operable CLI)**: FR-011's machine-readable exposure.
- **Feature 011 (filesystem layout)**: the record is *derived host state*'s sibling — it must be
  placed per the settled vocabulary, and it is **not** configuration.
- **Constitution I (ephemerality)**: the container is disposable; the record of it is not.
- **Constitution III (least exposure)**: FR-010.
