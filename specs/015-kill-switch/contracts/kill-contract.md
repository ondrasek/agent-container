# Contract: Kill Switch (Feature 015)

Numbered so tasks and tests can cite them. Each is testable.

## C1 — One action stops everything, from the RECORD

A single invocation targets every `active` inventory entry across every host (FR-001, FR-002). The
enumeration source is the durable record, never "whatever hosts currently answer" — which fails
precisely when a kill switch matters.

## C2 — One failure never aborts the rest

A host that is unreachable, slow, or erroring leaves every other host's work unaffected (FR-003).

## C3 — Four outcomes, and `undetermined` is never `stopped`

Every environment is classified per data-model §3. An unreachable host yields `undetermined` for its
environments — **zero** may be reported `stopped` (FR-004, SC-002).

## C4 — `stopped` is OBSERVED, never inferred

Every `stopped` was confirmed by the host's re-query: absent from the **running** set for `stop`,
absent from `ps -a` for `destroy` (FR-014, SC-002b). An exit status alone is not evidence.

## C5 — Parallel, bounded by the slowest host

Hosts are contacted concurrently with a per-host timeout defaulting to **30 seconds** and overridable.
With one unreachable host among N, elapsed time is one timeout — **not** N (FR-004a, SC-002a).

The default must stay **above** the 20s bound the tool already applies to a host listing, or the
budget expires before the call it bounds and a healthy-but-slow host is misreported. The documented
number and the enforced number are the same value, and a test binds them.

## C6 — Incomplete means failure

If any outcome is not `stopped` or `already-stopped`, the run reports overall failure and exits
non-zero (FR-005, SC-003). *Undetermined* counts as incomplete.

## C7 — Two forms, destruction never implicit

`stop` and `destroy` both exist; `destroy` is never the default (FR-006). `stop` preserves all volumes
(SC-005). `destroy` has **purge reach** — containers and their volumes, and **never** locally-built
images, which are shared build artifacts holding no credential. `destroy` without explicit
confirmation performs **zero** destructive operations (FR-007, SC-006); `stop` requires **no**
confirmation, because it is recoverable and speed is its value.

## C8 — The tool says which form suits which emergency

The documentation states the mapping (FR-006a): a runaway or looping agent → **stop**; a suspected
credential leak → **destroy**, because stopping leaves volumes that may hold an operator-interactive
login. It also states plainly that revoking a credential at the provider is **outside this tool**.

## C9 — Preview affects nothing

The preview shows exactly what would be affected and changes no state — verified by comparing before
and after (FR-008, SC-007).

## C10 — Never touch what we did not create

A container matching the tool's naming but absent from the inventory is never acted on (FR-009,
SC-004). Enumeration and ownership are one decision.

## C11 — Repeatable, but repetition never launders an unknown

Running it again when everything is already stopped **and every host is reachable** succeeds without
error (FR-010, SC-008), and an interrupted run leaves a truthful record that a repeat can build on
(FR-016).

**A host that is still unreachable on the repeat still yields `undetermined`, and the run still
fails.** Repeatability means acting twice is safe — never that a host we cannot see stops being
reported. That is C6 holding, not C11 failing.

## C12 — Scopeable on STORED fields, and it says what it left out

The action accepts a scope by **host** and by **environment name**, each repeatable, resolved from
stored inventory fields **without contacting a host** — otherwise scoping would depend on the very
reachability this feature cannot assume. It **states what it excluded** (FR-011), and a scope matching
nothing says so rather than silently doing nothing.

## C13 — Outcomes are written back

A `stop` appends to the entry's `notes`; a `destroy` sets `outcome = removed` (FR-012, data-model §4).
No new outcome value is introduced into Feature 014's closed set.

## C14 — Unreadable refuses; empty succeeds

An inventory that cannot be read **refuses**, naming the store (FR-013, SC-009). An absent or empty
one **succeeds**, saying *nothing recorded* — and saying that this means nothing recorded, not nothing
exists.

## C15 — Machine-readable

The full result, including per-environment outcomes, is available through the existing `--json`
interface (FR-015).
