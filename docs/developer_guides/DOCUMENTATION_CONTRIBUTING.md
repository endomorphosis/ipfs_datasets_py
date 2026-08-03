# Documentation Contributing Guide

| Field | Value |
| --- | --- |
| Interface | `DocumentationPageContract@1` (contributor workflow) |
| Task | `IPFSDOC-003` |
| Status | `canonical` |
| Owner | documentation-governance |
| Source of truth | [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md), live `docs/` tree, `mkdocs.yml`, `CONTRIBUTING.md` |
| Last verified | 2026-08-03 |
| Audience | developer, maintainer, agent |

## Purpose

This guide tells humans and implementation agents how to add or change
documentation in this repository **under the information architecture
contract**. It is the workflow companion to:

- [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) —
  audiences, lifecycle states, placement, metadata, diagrams/examples/citations,
  ADR lifecycle, review cadence, deprecation, archive;
- [ARCHITECTURE_GUIDE_TEMPLATE.md](../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md);
- [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md).

For general code contribution (branching, tests, PRs), see root
[CONTRIBUTING.md](../../CONTRIBUTING.md) and [developer_guide.md](../developer_guide.md).

## Principles (must follow)

1. **Sources outrank prose.** Prefer tests, implementation, packaging, and
   accepted ADRs over older guides and completion reports.
2. **One canonical home** per concern. Do not create a parallel "better" root
   page without routing or deprecating the previous authority.
3. **State is honest.** Label `plan`, `evidence`, and `historical` material so
   it is never mistaken for current product authority.
4. **Preserve history.** Do not rewrite archived or completion-era docs to match
   new APIs; add banners and pointers instead.
5. **Evidence over adjectives.** Avoid unverified counts, "complete", and
   "production-ready" claims copied from session summaries.
6. **Agents and humans share the same contract.** Stable headings, concrete
   paths, and validation commands are required, not optional polish.

---

## Before you write

1. Read the relevant sections of
   [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md).
2. Search for an existing page that already owns the concern:
   - product entry roots under `docs/*.md`;
   - `docs/architecture/`, `docs/developer_guides/`, `docs/guides/`;
   - package-local docs (e.g. `ipfs_datasets_py/mcp_server/docs/`).
3. Decide **lifecycle state**: `canonical` | `generated` | `plan` | `evidence` |
   `historical` | `draft` | `deprecated`.
4. Decide **primary audience**: `end-user` | `developer` | `architect` |
   `operator` | `agent` | `maintainer`.
5. List **source paths** you will verify (modules, tests, config).
6. If the change is architectural *why*, plan an **ADR** rather than only
   expanding a component list.

### Do not edit (without explicit task ownership)

- Protected program inputs (examples):
  - `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH_PLAN_2026_08_03.md`
  - `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.objectives.md`
  - `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.todo.md`
- Generated site output (`site/`) and other build artifacts.
- Production package code unless the task explicitly owns a code fix (doc tasks
  record product defects; they do not silently change behavior to match old docs).

---

## Creating a new page

### Step 1: Choose placement and name

Use the placement decision tree in the information architecture doc. Summary:

| Content | Place under |
| --- | --- |
| Install / first success / user workflow | `docs/` roots or `user_guides/`, `tutorials/`, `examples/` |
| System design, domain ownership, flow | `docs/architecture/` (+ domain subfolder) |
| Decision (why) | `docs/architecture/decisions/ADR-NNN-....md` |
| Extension, testing, agent handoff | `docs/developer_guides/` |
| Ops / security procedures | `docs/guides/operations/` or `guides/security/` |
| Source-grounded API domain map | `docs/api/` |
| Measurements, audits, drift | `docs/maintenance/` |
| Future intent | `docs/implementation/plans/` (`plan` state) |
| No longer current | Banner + disposition; archive only under policy |

Naming:

- Architecture durable guides: `SCREAMING_SNAKE.md`.
- ADRs: `ADR-NNN-kebab-title.md`.
- Avoid session- or date-stamped names for **canonical** pages.

### Step 2: Copy the right template

| Page kind | Start from |
| --- | --- |
| Architecture guide | [ARCHITECTURE_GUIDE_TEMPLATE.md](../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md) |
| ADR | [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md) |
| Other canonical guide | Metadata table + shared sections below |
| Evidence | Metadata + commit/date/method (see IA §5.5) |

### Step 3: Fill required metadata

```markdown
# <Title>

| Field | Value |
| --- | --- |
| Status | canonical |
| Owner | <team-or-role> |
| Source of truth | `<path>`, `<path>`, … |
| Last verified | YYYY-MM-DD |
| Audience | <primary> |
```

`Owner`, `Source of truth` / `Source`, and `Last verified` are **required** on
canonical and evidence pages. See IA §4 for the full field set.

### Step 4: Write required sections

Minimum for any new **canonical** page:

1. Purpose  
2. Audience  
3. Scope / non-goals  
4. Source grounding (paths)  
5. Body (type-specific)  
6. Validation (commands)  
7. Related pages  

Architecture guides must also cover ownership, flow, contracts, failure modes,
extension points, invariants, and rationale (template checklist).

### Step 5: Diagrams, examples, citations

Follow IA §6. Short form:

- Diagrams: Mermaid or ASCII; caption; real module names; mark current vs target.
- Examples: current imports; prerequisites; no secrets; optional-capability honesty.
- Citations: repo paths and tests; no summary-only authority; label historical quotes.

### Step 6: Wire navigation carefully

- Link from the appropriate **hub** (`docs/architecture/README.md`,
  `docs/developer_guides/` index when present, product `index.md` for user journeys).
- Add to `mkdocs.yml` `nav` only when the page is a maintained product entry or
  an approved hub leaf — `nav` is not a full inventory.
- Do not add archive or completion reports to primary user navigation.

### Step 7: Validate before merge

```bash
# Page exists and is non-empty
test -s path/to/your_page.md

# Named paths exist (example)
test -e ipfs_datasets_py/some_module.py

# Optional: site build when MkDocs and deps are provisioned
# mkdocs build --strict
```

Also:

- Resolve relative links you added.
- Syntax-check or run bounded offline examples when claimed executable.
- Update **Last verified** to the verification date.
- If you superseded another page, add its deprecation banner and fix inbound
  links from other canonical pages.

---

## Updating an existing page

1. Confirm you are editing the **canonical** home (or explicitly updating a
   plan/evidence page in its own state).
2. Re-verify sources; do not only rephrase stale claims.
3. Bump **Last verified** when sources were checked.
4. If the page is wrong because the **product** is wrong, document current
   behavior and record the defect (e.g. drift matrix); do not invent APIs.
5. If the page should no longer be authority, follow deprecation (below) instead
   of endless patches to a superseded narrative.

### Refresh vs replace

| Situation | Action |
| --- | --- |
| Same concern, outdated details | Refresh in place; keep stable path and anchors when possible |
| Concern split across domains | Split into linked leaves; one hub owns navigation |
| Better home under IA target tree | Create/refresh target; deprecate old path with pointer |
| Only historical value | Deprecate → archive per policy; do not "modernize" content |

---

## ADR contribution workflow

1. Copy [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md) to
   `docs/architecture/decisions/ADR-NNN-short-title.md` with the next free
   number in that directory.
2. Status starts as `proposed`.
3. Fill context, decision, alternatives, consequences, invariants, compliance.
4. Review with domain owner; set `accepted` and date when approved.
5. Link from the relevant architecture guide and the decisions index (create or
   update `docs/architecture/decisions/README.md` when that hub exists).
6. Never delete an accepted ADR; use `superseded` / `deprecated` and link the
   successor.

Package-local ADRs under `ipfs_datasets_py/mcp_server/docs/adr/` (ADR-001 …
ADR-006 as of 2026-08-03) remain valid until an authority-map task promotes or
points them. Do not duplicate full ADR bodies in two trees.

---

## Deprecation and archive (contributor checklist)

### Deprecate a page

1. Set `Status` to `deprecated`.
2. Top-of-page banner: reason, date, replacement link.
3. Remove from primary hubs / `mkdocs.yml` nav if listed as current.
4. Retarget links from other **canonical** pages.
5. Note disposition for the legacy map when that maintenance artifact exists.

### Archive

1. Only after deprecation (or explicit historical disposition).
2. Prefer `docs/archive/` (or established archive subtrees) **with** a reviewed
   move when doing bulk relocation.
3. Keep git history meaningful; do not rewrite archived bodies to current APIs.
4. Ensure archive README still warns that content is not authority.
5. Mass moves need a dedicated reviewed task — not drive-by cleanup in unrelated PRs.

---

## Review cadence expectations for authors

When you touch a page class, you inherit its freshness obligation (IA §8):

| Class | Expectation on change |
| --- | --- |
| Entry / install / user journey | Verify commands against current packaging and CLI |
| Architecture | Verify module paths; update ADR links if decisions changed |
| ADR | Status transitions only for accepted bodies; no silent history rewrite |
| Evidence | New measurement → new dated artifact or clearly versioned section |
| Historical | Banner/pointer only; no fake currency |

Release owners may require a docs freshness pass; authors should not leave
known-stale **Last verified** dates on pages they substantially edit.

---

## Ownership

- Every new canonical page names an **Owner** (role or team).
- If unknown, use `documentation-governance` and flag for assignment.
- Shared hubs (`docs/index.md`, architecture `README.md`, etc.) should have a
  single clear owner for merge conflicts; leaf pages own their domain content.
- Documentation tasks in the supervised program declare exclusive output paths;
  do not edit another task's exclusive outputs.

---

## Style baseline

1. **Stable headings** — prefer durable section titles so agents and deep links
   do not break unnecessarily.
2. **Second person or imperative** for procedures; present tense for current
   behavior.
3. **Spell out** uncommon acronyms on first use on user-facing pages; architecture
   pages may rely on the glossary once it is canonical.
4. **Tables** for matrices (ownership, status, options); prose for rationale.
5. **No emoji-required style**; existing pages may use emoji but new governance
   pages prefer plain text for agent readability.
6. **Inclusive, precise language** — distinguish discovery, availability,
   validation, policy admission, proof, and authorization when those concepts
   appear.

---

## Common mistakes

| Mistake | Correct approach |
| --- | --- |
| New root summary that duplicates install/user guide | Extend or fix the canonical page; deprecate the duplicate |
| Treating a plan as shipped architecture | Keep `plan` state; write architecture guide + ADR when true |
| Updating archive content to match new code | Leave historical text; fix the canonical guide |
| Examples with removed modules | Verify imports on current tree |
| Feature counts without date/method | Remove or move to dated evidence page |
| ADR without consequences/invariants | Use full template |
| Silent dual authority (docs + package-local) | One body, one pointer; record in authority map |

---

## Validation commands (this guide)

```bash
test -s docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md
test -s docs/maintenance/INFORMATION_ARCHITECTURE.md
test -s docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md
test -s docs/architecture/decisions/ADR_TEMPLATE.md
```

---

## Related documents

- [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md)
- [ARCHITECTURE_GUIDE_TEMPLATE.md](../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md)
- [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md)
- [CREATING_TOOLS.md](CREATING_TOOLS.md) — MCP tool authoring (code pattern)
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — repository contribution
- [developer_guide.md](../developer_guide.md) — developer entry
- [docs/archive/README.md](../archive/README.md) — historical material

---

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial contributor workflow for IPFSDOC-003 |
| 2026-08-03 | Cross-check against IA lifecycle and live package-local ADR paths |
