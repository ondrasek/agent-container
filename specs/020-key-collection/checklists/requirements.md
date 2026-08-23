# Specification Quality Checklist: Public-key collection, auto-injected

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-23
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

**FR-006 is the requirement that will decide this feature, and it was found by reading the code
rather than by reasoning about the user story.** The entrypoint assembles `authorized_keys` as a
UNION of the persisted file, the injected file and an env var, then writes the union back to the
persisted file. So every key ever injected is retained. A collection built naively on that mechanism
could ADD access and never REMOVE it — and US3 ("I lost the iPad") would fail while every other
scenario passed. Planning must confront that before anything else.

**No [NEEDS CLARIFICATION] markers were needed.** The two questions a reader might expect —
merge-vs-replace for project override, and whether keys are secrets — both have answers the project
has already committed to: Constitution VIII (absent ≠ defaulted ≠ declared-empty) makes
declared-empty meaningful, and Feature 017 established that public material rides the non-secret
channel. Inventing a clarification round for settled questions would be theatre.

**Clarification session 2026-08-23 — one item REGRESSED, deliberately.** Five questions were
answered and integrated (FR-013 through FR-018, SC-008 through SC-012 — FR-019/FR-020 and
SC-013/SC-014 came later, from the post-plan analysis round, not from a question). Fifteen of sixteen items
still pass; *"written for non-technical stakeholders"* no longer does, and it is being reported
rather than quietly re-checked.

FR-015 and FR-016 now turn on a **tool-managed region** within the environment's authorised keys,
and FR-018 turns on the fact that `show`, `ls` and `add` are legal environment names. That is
mechanism, and a non-technical reader will not follow it. The alternative was to state the
requirements at a level a general reader could follow — which is exactly the level at which the
union defect, the vacuous SC-006 comparison, and the `show`-name collision are all invisible. Three
of the five clarifications this session produced were only findable *below* that level.

So the trade is stated instead of hidden: this spec is written for someone who will implement or
review it, and the readability item is failed on purpose. If a stakeholder-facing summary is wanted,
it belongs beside this document, not in place of it.

**What the session changed, in one line each.** `start` must report a drifted collection rather than
resume silently (FR-013). The post-deploy query must observe the environment, not re-resolve the
file, or SC-006 compares a projection with itself (FR-014). The tool must not create a grant it
cannot revoke, which changes the shipped `keys` command (FR-015), while content the tool did not
write survives (FR-016). Declared-empty is honoured and warned about, and the undeclared path stays
silent because it already is (FR-017). The query lands in a `keys` subgroup, forcing the grant form
to `keys add`, because a bare positional would strand an environment named `show` (FR-018).

**Post-plan analysis, 2026-08-23 — two rounds, and the second one mostly found the first
one's repairs.** Round 1 raised two CRITICAL items: an existing *executing* test
(`test_entrypoint.sh` §7e) pinned the union the design deletes, and FR-013/FR-014 compared
against a "created-with" set that no artifact gave a home. Both are closed — the second by
recording that the generated compose file already holds it inline, which made the `content:`
decision load-bearing twice rather than once.

Round 2 found six more, **five of them introduced or left by round 1's own repairs**. The
one worth keeping on the record: the terminology sweep was reported clean after grepping for
the exact strings that had just been replaced — a check that could only confirm the edit, never
the goal. Fourteen prose uses of the old term survived it. That is the same defect shape this
feature exists to remove, committed by the instrument checking for it, and it is the reason the
quickstart's success-criteria coverage was audited by enumerating **all fourteen** criteria
rather than by re-reading the diff: six had no scenario, and two analysis passes had missed them.

**Readability item RESOLVED, 2026-08-23 — by moving mechanism out, not by diluting requirements.**
The item was previously failed on purpose, on the argument that the detail which made three
clarifications findable could not survive a general-reader rewrite. That argument was wrong about
*where* the detail had to live. The requirements now state what must be true for the operator; the
delimited region, its update rule, the command spellings and the file the created-with set is read
from are specified in `data-model.md`, `contracts/cli.md` and `plan.md`, which is where the template
intends them. Nothing was lost — each mechanism fact was checked to still exist elsewhere before the
spec stopped stating it.

The tell that this was the right fix: two *other* items — "no implementation details" and "no
implementation details leak into specification" — were marked passing the whole time the spec
carried union internals and a name-charset argument. Failing one item honestly while leaving its two
near-duplicates checked was itself an inconsistency, and de-mechanising resolves all three at once
rather than trading one against another.

**Command names were deliberately kept.** For a CLI, the command surface *is* the user interface, so
naming it is no more an implementation detail than "the checkout button" would be for a web app. The
`## Clarifications` entries were also left verbatim: they are a decision log, and rewriting a record
of what was asked and answered would falsify it.
