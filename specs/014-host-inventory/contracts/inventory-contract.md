# Contract: Durable Host Inventory (Feature 014)

Numbered so tasks and tests can cite them. Each is testable.

## C1 — `inventory list [--json]`

Lists entries newest-first. `--json` emits `{"entries": [<entry>, ...]}` per Feature 009's
conventions (FR-011). An empty inventory yields `{"entries": []}` and, in human mode, one line
saying so rather than a blank screen.

## C2 — Every created environment appears

Every path that creates an environment produces exactly one entry (FR-001, SC-001 = 100%). Asserted
as a **census over the source**, not only by exercising known paths: the failure mode is a NEW path
added later that records nothing, which is invisible because everything it does works.

## C3 — An entry outlives container, registration and host

After the container is removed, the host is `host rm`'d and its state directory is gone, the entry
is still listed (FR-003, SC-002).

## C4 — The stored outcome set is closed and `unknown` is unrepresentable

Constructing an entry with any value outside `active` / `removed` / `vanished` / `host-gone` is
refused, and `unknown` specifically is refused (FR-004, SC-003).

## C5 — A reused name yields another entry, and the earlier one is untouched

Create, remove, create with the same name → **two** entries; the first retains its own outcome and
timestamps (FR-015, SC-003a). Holds by construction: `entry_id` is the key.

## C6 — `reconcile` classifies every entry into exactly one class

Each entry is `agreeing`, `missing`, `unrecorded` or `unknown` — zero unclassified (FR-005, SC-003).

## C7 — An unreachable host yields `unknown`, never `missing`

Zero occurrences of `missing` for a host that could not be reached (FR-006, SC-004).

## C8 — `unrecorded` never becomes a claim of ownership

A container present on a host that the tool did not create is reported as `unrecorded`, and neither
human nor `--json` output describes it as the tool's (FR-007, SC-005).

## C9 — `list` hints at disagreement without doing the full comparison

When record and live state disagree, `list` prints one brief line and does not print the
classification (FR-005a). A discrepancy an operator must already suspect is one nobody finds.

## C10 — A write failure surfaces and does not fail the deploy

A failed entry write leaves the deploy's exit status untouched (FR-008) and warns — an unrecorded
environment is the blind spot this feature exists to remove, so it must never be silent.

## C11 — Concurrency loses and corrupts nothing

N concurrent deployments produce N complete entries (FR-009, SC-007).

## C12 — No field can carry a credential

Every field is tool-generated; the field set is closed and asserted so (FR-010, SC-006). Unlike
Feature 016 there is no free-text field, so this is structural — and the test exists because that is
the only thing keeping it structural.

## C13 — An absent store changes nothing

With the inventory directory deleted, every existing command behaves exactly as before and none
fails (FR-013, SC-008). Verified by deleting the store and running the existing suite, not by
constructing an empty one.

## C14 — Growth is bounded by a backstop, not by tidying

A large cap exists; age-based pruning is NOT the default, and the documented cap is the enforced one
(FR-012).

## C15 — The authority split is documented

`docs/orchestration.md` states that live state is authoritative for "what is running" and the record
for "what we created" (FR-014).
