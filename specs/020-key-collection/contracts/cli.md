# Contracts: Public-key collection

Behavioural contracts, each testable. `C#` ids are cited by tasks and by the tests
that pin them.

---

## Resolution

**C1** — With a collection at the user level and none at the project level, a deploy
from anywhere admits the user collection.

**C2** — With collections at BOTH levels, a deploy from inside the project admits
**exactly** the project collection. No entry of the user collection appears — the
file wins entirely, it is not merged (R3).

**C3** — With no collection at either level, the compose model contains **no**
`ssh_authorized_keys` config and the container's `authorized_keys` is byte-identical
to today's. Undeclared changes nothing (FR-009).

**C4** — A collection that exists with no entries (empty, or only comments) resolves
to an **empty** admit set, is honoured, and is **warned about** at deploy naming the
file. Distinguishable from C3 in both behaviour and output (Constitution VIII).

**C5** — Resolution is identical for both roles: an agent environment and a control
plane deployed from the same directory admit the same set (FR-003).

---

## Validation — before anything is created

**C6** — A collection with a malformed entry **refuses the deploy**, naming the file
and the line number. Exit non-zero, **no container created, no volume created**.

**C7** — A collection containing a **private** key refuses, and the message says
explicitly that the entry is a private key and must not be in the collection. Zero
bytes of it reach any container or any staged file.

**C8** — A collection file that cannot be read (missing after resolution, unreadable
mode) refuses before any runtime call (FR-012).

**C9** — Every refusal above happens **before** the first runtime invocation. A test
asserts the refusal path reaches no runtime call, rather than asserting only the
exit code.

---

## Statement of the admit set

**C10** — Before deploying, the tool prints the admit set as `fingerprint  comment`
lines, and names which file the collection came from. Full key blobs are not printed
(they are noise, and the fingerprint is what identifies a device).

**C11** — `--authorized-key` is **additive**: the stated set is the union of the
collection and the flag values, and the output attributes each entry to its source
so neither appears to have won silently (FR-008).

**C12** — What the pre-deploy statement listed and what the container actually
admits **agree** for an unchanged collection (SC-006). The test compares the printed
fingerprints against `ssh-keygen -l` over the container's managed block — not
against the input file, which would be circular.

---

## The managed block

**C13** — The container's `~/.ssh/authorized_keys` contains exactly one
`# BEGIN agent-container managed keys` / `# END` pair, and the admit set lies
between them.

**C14** — A line placed in `authorized_keys` **outside** the block survives a
down/up cycle byte-for-byte.

**C15** — A key present in the collection at first boot and **removed** before a
recreate is **absent from the block** afterwards — and an SSH attempt with that key
is **refused**. This is FR-006, and the test must assert the refused connection, not
merely the absent line: an absent line with a stale `authorized_keys.d` entry or a
cached session would still admit.

**C16** — A collection that becomes absent empties the block rather than leaving the
previous set in place.

**C17** — An `authorized_keys` with a `BEGIN` marker and no `END` (or the reverse) is
**refused, not repaired** — the tool reports the file rather than guessing where the
block ends and risking deleting an operator's keys.

---

## Injection channel

**C18** — The collection travels as a compose **`config`** (non-secret), never as a
`secret`. Public keys are public; labelling them secret misrepresents them (FR-010).

**C19** — The config uses the **`content:`** form, not `file:`. A test asserts the
generated model has no `file:` key for `ssh_authorized_keys` — the 001/003 lesson,
and the resolution of the docstring contradiction in R4.

**C20** — The admit set arrives non-empty in a container deployed over a **remote**
context. This is the contract the two contradicting docstrings disagree about, and
it is settled by observation on a real remote target, not by reading either one.

---

## Documentation

## Resume, query and out-of-band grants

**C23** — After the collection changes, `start` **warns** and names the differing keys and
`redeploy`; it does **not** re-resolve or re-apply. A test asserts the resumed environment
still admits the old set *and* that the operator was told so — the warning is the contract,
not a courtesy (FR-013).

**C24** — The post-deploy query prints **projected** and **observed** sets and states
disagreement. With the environment unreachable, observed is **`undetermined`**; a test
asserts it is never backfilled from the projection (FR-014).

**C25** — A key injected by `keys` is admitted immediately and is **absent after a
recreate**, with the SSH attempt refused. `keys` states at injection that the grant lasts
until the next recreate (FR-015).

**C26** — A key added **by hand from inside** the environment survives a recreate
byte-for-byte (FR-016). C25 and C26 must both hold: the tool removes what it wrote and
nothing else.

**C27** — `inject_keys` writes **within** the delimited region. A test asserts the region
markers still form exactly one pair afterwards — an injection that appended past the `END`
marker would satisfy C25's "admitted immediately" and silently fail C25's second half.

---

**C21** — Both managed-block sites (`~/.ssh/config`, `~/.ssh/authorized_keys`) state
in-line whether they are **write-once** or **replaced every boot**, and why. Same
idiom, opposite rule; an unlabelled pair is a defect waiting to happen.

**C22** — The docstring proven wrong by C20 is corrected in the same change. Leaving
both claims in the tree guarantees the next reader trusts the wrong one.
