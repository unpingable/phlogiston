# ATProto Portable Communities — doctrine

**Status:** ratified for the V0 authorized by `BUILD.md`. Captured 2026-07-06 from the parking
discussion. These clauses are architectural law, while `BUILD.md` bounds implementation scope
and `IDEAS.md` remains non-authorizing context.

---

## The one dangerous slope

Labelwatch reuse is allowed as **plumbing theft, not identity inheritance.**

> `communitywatch` may observe and compile.
> `communityd` may emit authority.
> **They must not share keys, authority identity, or moral vocabulary.**

Otherwise the whole thing quietly mutates from "observer over governance records" into a
"moderation actor wearing an auditor's jacket." Bad coat. Familiar smell. This is the
observer/emitter split from the workbench's **detect-only-is-structural** constraint, applied to
a project that — unlike the observatories — is *allowed* to emit. The emitter half is exactly why
the identity firewall has to be hard.

---

## Doctrine clauses

1. **PDS is custody substrate, not community sovereign.**
2. **Community is a signed actor, not a server bucket.**
3. **Admission is context, not ownership.** (Post stays in the user's repo; community mints
   acceptance, not custody.)
4. **Removal from community view is not deletion from substrate.**
5. **Fork/replay is the differentiator, not a garnish.**
6. **Ranking is view policy, not truth.**
7. **Observer code may be reused; observer authority may not.** (`communitywatch` keys ≠
   `communityd` keys, ever.)

---

## The V0 acceptance question

The MVP proves ergonomics; the differentiator (fork/replay) comes later. So V0's entire job is to
answer exactly one question:

> Does "submit → admit → render as community" feel like a **real place**, or just a feed wearing a
> trench coat?

- **Feels real** → the fork/replay problem (clause 5) becomes worth formalizing.
- **Doesn't** → congratulations, you invented another custom feed with a constitution. History's
  most irritating paperwork exercise. Park it again.

---

## Build conditions

- **Authorization is limited by `BUILD.md`.** Ideas outside that contract remain parked.
- **Build method: automation-first, not hands-on.** This project is a good candidate for building
  with heavier agent automation — especially *mining the existing labelwatch codebase* for the
  plumbing (per the reuse map in `IDEAS.md`) rather than the manual, hand-carried method used to
  date. The mechanical "compile records into a page" core plus a well-mapped donor codebase is
  close to ideal fan-out/workflow substrate. If/when this reopens, reach for orchestration.
