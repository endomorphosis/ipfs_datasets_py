# ADR Template

| Field | Value |
| --- | --- |
| Interface | `ADRTemplate@1` |
| Task | `IPFSDOC-003` |
| Status | `canonical` |
| Owner | documentation-governance |
| Source of truth | [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md); lifecycle for `docs/architecture/decisions/` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |

## Purpose of this template

Copy this file to create a new Architecture Decision Record (ADR):

```text
docs/architecture/decisions/ADR-NNN-short-kebab-title.md
```

Use the next free three-digit number in **this** directory. Do not reuse numbers.
Replace placeholders. Delete this preamble from the new ADR (keep the ADR
metadata block).

ADRs record **why** a durable boundary, pattern, or trade-off was chosen. They
complement architecture guides (what/how/flow). Accepted ADRs outrank ordinary
guides when sources disagree (see information architecture authority order).

### ADR lifecycle (summary)

| Status | Meaning |
| --- | --- |
| `proposed` | Under review; not binding for implementers |
| `accepted` | Binding for new work |
| `deprecated` | No longer preferred; historically accepted |
| `superseded` | Replaced by a newer ADR (link required) |
| `rejected` | Considered and not adopted (optional retention) |

Workflow: draft (`proposed`) → review → `accepted` → implement with references →
later `deprecated` or `superseded` (never silent rewrite of history).

Full policy: [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) §7.
Contributor steps: [DOCUMENTATION_CONTRIBUTING.md](../../developer_guides/DOCUMENTATION_CONTRIBUTING.md).

### Package-local ADRs

Existing ADRs under package trees (for example
`ipfs_datasets_py/mcp_server/docs/adr/`) remain valid until an authority-map task
promotes or points them. Do not copy full ADR bodies into two trees. New
**cross-cutting product** decisions should be filed under
`docs/architecture/decisions/` using this template.

### Relationship to prior MCP ADRs

Useful precedents for tone and structure (package-local; not the global index):

| Local id | Path |
| --- | --- |
| ADR-001 | `ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md` |
| ADR-002 | `ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md` |
| ADR-003 | `ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md` |
| ADR-004 | `ipfs_datasets_py/mcp_server/docs/adr/ADR-004-engine-extraction-pattern.md` |
| ADR-005 | `ipfs_datasets_py/mcp_server/docs/adr/ADR-005-v6-coverage-hardening.md` |
| ADR-006 | `ipfs_datasets_py/mcp_server/docs/adr/ADR-006-mcp++-alignment.md` |

Those files predate this global template; new **cross-cutting** product work
should follow the sections below even when the domain is MCP-related. Prefer
pointing from the architecture hub rather than duplicating bodies under
`docs/architecture/decisions/`.

---

<!--
=============================================================================
COPY FROM HERE when creating a new ADR.
=============================================================================
-->

# ADR-NNN: <Short title>

| Field | Value |
| --- | --- |
| Status | proposed |
| Date proposed | YYYY-MM-DD |
| Date accepted | <YYYY-MM-DD or empty until accepted> |
| Decision owners | <team-or-role, optional named reviewers> |
| Consulted | <optional teams or roles> |
| Source of truth | <modules, tests, configs that embody the decision> |
| Last verified | YYYY-MM-DD |
| Supersedes | <ADR-MMM or "none"> |
| Superseded by | <ADR-PPP or "none"> |
| Origin | <optional: prior package-local id or discussion link> |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

<Describe the forces that make a decision necessary: product requirements,
technical constraints, failure history, optional dependency reality, agent/LLM
context costs, security or proof requirements, interoperability, performance.
Ground claims in the current repository where possible.>

## Decision

<State the decision clearly and normatively. Use "We will…" / "We must…"
language. Prefer one primary decision per ADR; split independent decisions.>

### Decision details

- <bullet specifics: module layout, API shape, forbidden patterns, defaults>
- <…>

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| <option A> | <…> | <…> | <…> |
| <option B> | <…> | <…> | <…> |
| <do nothing> | <…> | <…> | <…> |

## Consequences

### Positive

- <benefit>
- <benefit>

### Negative

- <cost, complexity, constraint>
- <cost>

### Neutral / deferred

- <side effect that is accepted>
- <follow-up work that is explicitly out of this ADR>

## Invariants

Rules that remain true while this ADR is `accepted`:

1. <invariant — preferably testable or reviewable>
2. <invariant>
3. <invariant>

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

How reviewers and agents check that the codebase still honors this decision:

```bash
# Example checks — replace with real paths and tests
# rg -n '<forbidden pattern>' ipfs_datasets_py/<domain>
# pytest tests/<domain>/test_<contract>.py -q
```

Narrative compliance criteria (when automation is incomplete):

1. <criterion>
2. <criterion>

## Scope

### Applies to

- <packages, layers, or surfaces>

### Does not apply to

- <explicit exclusions>

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| <architecture guide path> | Describes flow/components under this decision |
| <test path> | Encodes contract |
| <prior ADR> | Related or parent decision |
| <issue/PR if any> | Discussion trail (optional) |

## Notes / errata

<Optional. Clarifications that do not change the Decision. Date each erratum.>

## Document history

| Date | Change |
| --- | --- |
| YYYY-MM-DD | Proposed |
| YYYY-MM-DD | Accepted |

---

<!--
=============================================================================
END OF COPY REGION
=============================================================================
-->

## Reviewer checklist

- [ ] Number `ADR-NNN` is unique in `docs/architecture/decisions/`
- [ ] Title is stable and descriptive
- [ ] Status is an allowed value
- [ ] Context is problem-focused, not a changelog
- [ ] Decision is unambiguous and implementable
- [ ] At least one serious alternative is recorded
- [ ] Consequences include costs, not only benefits
- [ ] Invariants are listed
- [ ] Compliance/validation is actionable
- [ ] Supersession links are correct when status is `superseded` / `deprecated`
- [ ] Architecture guide (or hub) links to this ADR when accepted
- [ ] No presentation of plan-only work as already shipped
- [ ] Metadata includes owner/source/last-verified as applicable

## Status transition rules

| From | To | Requirements |
| --- | --- | --- |
| (new) | `proposed` | Template complete enough for review |
| `proposed` | `accepted` | Owner approval; date accepted set; index updated |
| `proposed` | `rejected` | Reason recorded in Consequences or Notes |
| `accepted` | `deprecated` | Replacement guidance or rationale; guides updated |
| `accepted` | `superseded` | `Superseded by` set; successor ADR `accepted` or concurrent |
| `deprecated` / `superseded` | (content) | Body frozen except errata and link fixes |

## Index obligation

When the decisions index exists (`docs/architecture/decisions/README.md`), every
`accepted`, `deprecated`, and `superseded` ADR must appear there with status and
one-line summary. Creating the index is owned by the ADR corpus tasks; individual
ADR authors still add a row when the index is present.

## Related documents

- [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md)
- [DOCUMENTATION_CONTRIBUTING.md](../../developer_guides/DOCUMENTATION_CONTRIBUTING.md)
- [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md)
- [architecture/README.md](../README.md)

---

## Document history (template)

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial `ADRTemplate@1` for IPFSDOC-003 |
