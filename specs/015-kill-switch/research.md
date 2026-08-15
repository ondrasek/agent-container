# Research: Kill Switch (Feature 015)

Phase 0. Each entry records a **decision**, its **rationale**, and what was **rejected** — and where a
fact is claimed, how it was established.

---

## R1 — `do_stop` cannot serve this feature, and the reason is structural

**Decision**: stop by **compose project label**, through the runtime, never via the compose file.

**Rationale**: read from the tree, not assumed. `do_stop` opens with:

```python
compose_file = compose_file_path(host_name, name)
if not compose_file.is_file():
    die(f"no deployment named '{name}' on {host_name} to stop …")
```

`compose_file_path` resolves under `<state>/<host>/` — **derived host state**, documented *"computed;
safe to delete"*, which dies with its host. Feature 014's entries **deliberately outlive that
directory**; that is the whole reason 014's store is flat.

So the environments this feature most needs to reach — a forgotten one on a host whose state was
cleared — are precisely the ones `do_stop` refuses. **Reusing it would make the kill switch fail
exactly where it matters**, and it would fail with a message claiming the deployment does not exist.

**Measured** (live daemon, during planning): a container carrying
`com.docker.compose.project=<project>` is enumerable by
`ps --filter label=com.docker.compose.project=<project>` with **no compose file present**. So the
project remains addressable after its state directory is gone.

**Rejected**: calling `do_stop` per environment (measured impossible for the interesting cases);
regenerating the compose file from the inventory (the inventory deliberately holds no deployment
parameters — see 014's closed field set — so any regeneration would be a fabrication);
`<runtime> stop <container-name>` (halts the agent and leaves the egress sidecar and operator helpers
running, so "everything stopped" would be false).

---

## R2 — "Verified" means a different query for each form

**Decision**: for **stop**, confirm the container is absent from the **running** set
(`host_ps_rows(include_stopped=False)`); for **destroy**, absent from `ps -a`.

**Rationale**: a stopped container still **exists**. Verifying a stop against `ps -a` would never
succeed and would report every stop as failed; verifying a destroy against the running set would
report success for a container that is merely paused. FR-014 says "absent from what it reports" and
the two forms mean different things by it.

**One re-query per host**, after that host's environments are done — FR-014's own cost bound, and it
keeps verification proportional to hosts rather than environments.

**Rejected**: inferring from the stop command's exit status (FR-014 forbids it explicitly, and
SC-002b counts occurrences); per-environment verification (N round-trips for one host's answer).

---

## R3 — Refuse on unreadable, succeed on empty

**Decision**: an inventory that cannot be **read** refuses; one that is absent or empty succeeds while
saying *nothing recorded*.

**Rationale**: FR-013's stated mischief is *"silently fall back to live enumeration"*. Emptiness does
not cause fallback — there is nothing to fall back from. And Feature 014 documents that the store
*begins at install and is not backfilled*, so on a fresh machine it legitimately does not exist;
refusing there would break the kill switch for an operator who has simply never deployed.

The empty message must say **nothing recorded, not nothing exists**, because 014's own documentation
warns about that confusion and here it would be read as reassurance at the worst possible moment.

**This is the one place the plan reads a requirement more narrowly than its literal wording**, which
is why it is written down rather than settled in code.

**Rejected**: refusing on absence (breaks a fresh install, and turns "nothing recorded yet" into a
hard error); treating unreadable as empty (silently narrows scope — the exact false guarantee FR-013
exists to prevent).

---

## R4 — Write `notes`, not a new outcome

**Decision**: the stopping form appends to the entry's `notes`; the destroying form sets
`outcome = removed`. No new outcome value.

**Rationale**: Feature 014's outcome set is **closed** and describes *existence*, not runstate:
`active` / `removed` / `vanished` / `host-gone`. A stopped environment is still `active` — it exists
and will start again. Adding `stopped` would break a closed set that a test pins, and reusing
`removed` for a stop would be a **lie that persists in the store a later audit reads**.

`notes` is already defined in 014's data model as tool-generated diagnostics, so this is the field's
intended use rather than a stretch.

**Rejected**: a fifth outcome (breaks 014's closed set and its `unknown`-is-unstorable argument);
reusing `removed` for a stop (false, and durable); a separate kill-action store (a second schema and a
second retention policy for something the inventory already keys correctly).

---

## R5 — A contended lock is UNDETERMINED

**Decision**: `deployment_lock` is non-blocking and `die`s when held; under the kill switch a
contended lock yields *could-not-determine* for that environment.

**Rationale**: the three candidate behaviours map cleanly onto the requirements. Dying aborts the run
(violates FR-003). Skipping silently reports success for something never touched (violates FR-005).
Reporting *undetermined* is simply true: we did not stop it, and we do not know its state.

**Rejected**: blocking on the lock (an emergency command that waits on an unrelated `up` is not a kill
switch); ignoring the lock (a concurrent teardown plus a concurrent stop is the corruption the spec's
edge case names).

---

## R6 — Parallel by host, sequential within a host

**Decision**: `concurrent.futures.ThreadPoolExecutor`, one task per host, per-host timeout with an
overridable default.

**Rationale**: FR-004a and SC-002a require total time bounded by the slowest host rather than the sum
— with N unreachable hosts, sequential contact costs N timeouts in the one command whose value is
speed. Stdlib, so Constitution VI is untouched.

Sequential **within** a host because that host's single verification re-query must happen after its
environments are done, and because hammering one daemon with parallel stops gains nothing.

The timeout is overridable because the spec's own edge case separates *slow* from *unreachable*: an
operator who knows their host is slow should be able to wait rather than be handed *undetermined*.

**Rejected**: asyncio (a second concurrency model in a codebase that uses none); a process pool (no CPU
work here); one global timeout (a slow host would consume the whole budget and starve the others).

---

## R7 — Ownership: 014 reported, 015 ACTS

**Decision**: enumerate only from inventory entries; never from a name match on a live host.

**Rationale**: Feature 014 established that `CONTAINER_PREFIX` is a naming convention an operator can
imitate, so a match is evidence of a *name* and nothing more — and it reported `unrecorded` containers
without claiming them. **This feature acts**, so the same rule now has teeth: acting on a name match
would stop a container the tool did not create (FR-009, SC-004 counts occurrences).

The inventory is therefore not merely the enumeration source but the **ownership record**, which is
why FR-002 and FR-009 are the same decision seen from two sides.

**Rejected**: enumerating live and filtering by prefix (stops other people's containers); enumerating
live and intersecting with the inventory (the intersection misses exactly the unreachable and
forgotten hosts the feature exists for).
