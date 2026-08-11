# Architecture Guide Template

| Field | Value |
| --- | --- |
| Interface | `ArchitectureGuideTemplate@1` |
| Task | `IPFSDOC-003` |
| Status | `canonical` |
| Owner | documentation-governance |
| Source of truth | [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md); applied to guides under `docs/architecture/` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |

## Purpose of this template

Copy this file when creating a **canonical** architecture guide for a product
domain or cross-cutting concern. Replace placeholder text in angle brackets.
Remove this "Purpose of this template" section from the new page (keep the
metadata table, filled in for the real guide).

Architecture guides answer:

1. What responsibility does this domain own?
2. How do data and control flow through it?
3. What may callers rely on (contracts and invariants)?
4. Why was the boundary drawn this way (rationale / ADRs)?
5. How do I extend it without breaking the system?
6. How do I validate that the guide still matches the tree?

They are **not** session diaries, completion reports, or API laundry lists.
Component inventories are necessary but insufficient without flow, failure
modes, and rationale.

Contract reference:
[INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md).
Contribution workflow:
[DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md).
Decisions: [ADR_TEMPLATE.md](decisions/ADR_TEMPLATE.md).

---

<!--
=============================================================================
COPY FROM HERE when creating a new architecture guide.
File name target: docs/architecture/<DOMAIN_OR_TOPIC>.md
                 or docs/architecture/<domain>/<TOPIC>.md
=============================================================================
-->

# <Domain or concern name>

| Field | Value |
| --- | --- |
| Status | draft |
| Owner | <team-or-role> |
| Source of truth | `<package/module paths>`, `<tests>`, `<config files>` |
| Last verified | YYYY-MM-DD |
| Audience | architect, developer, agent |
| Related ADRs | <ADR-NNN, … or "none yet"> |
| Review cadence | semi-annual (default) or <override> |

> **Lifecycle:** Set `Status` to `canonical` only after sources are verified.
> Do not present plans or incomplete migrations as current architecture.

## 1. Purpose

<One short paragraph: what question this guide answers and for whom.>

## 2. Audience

- **Primary:** <architect | developer | operator | agent>
- **Secondary:** <optional>

## 3. Scope and non-goals

### In scope

- <Boundary, packages, and behaviors this guide covers>

### Non-goals

- <Adjacent domains owned elsewhere — link to those guides>
- <Future work that remains plan-only — link to plan if useful, labeled as plan>
- <Historical designs that are not current — link only with historical label>

## 4. Context

<Why this subsystem exists in the product. Product problem, constraints
(performance, decentralization, optional deps, proof/policy, etc.), and how it
relates to neighboring domains. Prefer current-tree facts over roadmap language.>

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| <responsibility> | <owned by <domain> — link> |
| <responsibility> | <owned by <domain> — link> |

**Inbound callers:** <who invokes this domain — CLI, MCP tools, Python API, peers>

**Outbound dependencies:** <what this domain calls — storage, provers, network>

**Authority notes:** <e.g. policy approval vs discovery; proof vs validation;
declaration identity vs receipts — only where applicable>

## 6. Components

Describe **what exists now**. Use real paths.

| Component | Path | Role |
| --- | --- | --- |
| <name> | `ipfs_datasets_py/...` | <one line> |
| <name> | `ipfs_datasets_py/...` | <one line> |

Optional package diagram (Mermaid or ASCII). Caption what is simplified.

```text
<caller>
   |
   v
<boundary module> ----> <dependency>
```

## 7. End-to-end flow

### 7.1 Happy path

<Numbered or sequenced flow of data and/or control. Name modules and major
functions or tool entry points.>

1. <step>
2. <step>
3. <step>

### 7.2 Sequence or flow diagram

```text
<ASCII or Mermaid sequence — current behavior only unless labeled target>
```

### 7.3 Initialization and lifecycle

<How the subsystem is constructed, configured, started, and shut down.
Reference dependency/init guides if cross-cutting.>

## 8. Contracts

### 8.1 Inputs

| Input | Type / source | Validation |
| --- | --- | --- |
| <name> | <type, path, or message> | <schema, tests, or rules> |

### 8.2 Outputs

| Output | Type / sink | Guarantees |
| --- | --- | --- |
| <name> | <type or store> | <what callers may assume> |

### 8.3 Public surfaces

- Python API: `<import paths>`
- CLI: `<commands if any>`
- MCP tools: `<tool names or categories if any>`
- Config keys / env: `<names>`

### 8.4 Persistence and identity (if applicable)

<CIDs, content addressing, cache keys, declaration vs derived artifacts,
receipts — only if this domain touches them. Distinguish kinds of truth.>

## 9. Failure modes and fallbacks

| Failure | Detection | User/caller-visible behavior | Fallback |
| --- | --- | --- | --- |
| <e.g. optional extra missing> | <import error / probe> | <message or status> | <degrade / disable / error> |
| <e.g. backend unavailable> | <…> | <…> | <…> |

Explicitly distinguish:

- **Not installed / not discovered** vs **installed but failed**
- **Syntax/structural validation** vs **semantic / policy / proof / auth**
- **Stub or incomplete path** vs **behaviorally complete path**

Do not document aspirational fallbacks that the code does not implement.

## 10. Extension points

How to add a backend, processor, tool, or policy hook **correctly**:

1. <step — where to put code>
2. <step — registration / discovery>
3. <step — tests required>
4. <step — docs to update>

Link to developer recipes when they exist
(`docs/developer_guides/EXTENSION_RECIPES.md` target).

Anti-patterns:

- <e.g. business logic inside MCP thin wrappers>
- <e.g. bypassing policy or proof boundaries>

## 11. Invariants

Rules that future changes **must** preserve:

1. <invariant>
2. <invariant>
3. <invariant>

If an invariant needs to change, require an ADR (or superseding ADR) and an
update to this guide in the same change set when practical.

## 12. Rationale and decisions

Short **why**, not a second component list.

| Topic | Summary | ADR / source |
| --- | --- | --- |
| <decision topic> | <one or two sentences> | [ADR-NNN](decisions/ADR-NNN-....md) or `path` |

Alternatives rejected (brief):

- <alternative> — rejected because <reason>

## 13. Security, privacy, and trust boundaries (if applicable)

- Trust boundaries: <…>
- Secrets handling: <…>
- Attestation / authorization notes: <…>
- What this layer **must not** claim authority over: <…>

## 14. Observability and operations (if applicable)

- Logs/metrics: <…>
- Diagnostics: <…>
- Runbooks: <link>

## 15. Validation

Commands and tests that prove this guide still matches the repository.
Prefer **bounded, offline** checks.

```bash
# Paths exist
test -e <primary module path>
test -e <secondary path>

# Focused tests (adjust to domain)
# pytest tests/path/to/domain -q --collect-only
# pytest tests/path/to/domain/test_contract.py -q
```

Record known limitations of the validation (missing optional deps, skipped
integration tests) rather than implying a full system proof.

## 16. Related documentation

| Document | Relationship |
| --- | --- |
| [architecture/README.md](README.md) | Architecture hub |
| <sibling domain guide> | Upstream / downstream |
| <user journey> | How users hit this surface |
| <API domain page> | Reference detail |
| <ADR> | Binding decision |

## 17. Document history

| Date | Change |
| --- | --- |
| YYYY-MM-DD | Initial guide |

---

<!--
=============================================================================
END OF COPY REGION
=============================================================================
-->

## Template compliance checklist

When reviewing a guide created from this template, confirm:

- [ ] Metadata includes **Status**, **Owner**, **Source of truth**, **Last verified**, **Audience**
- [ ] Purpose, scope, and non-goals are explicit
- [ ] Ownership table names real boundaries
- [ ] Components use repository paths that exist at last verification
- [ ] End-to-end flow describes current behavior
- [ ] Contracts cover inputs, outputs, and public surfaces as applicable
- [ ] Failure modes distinguish discovery, validation, policy, proof, and stubs
- [ ] Extension points and anti-patterns are actionable
- [ ] Invariants are testable or clearly normative
- [ ] Rationale links ADRs or source-backed decisions
- [ ] Validation section has concrete commands
- [ ] No unverified point-in-time counts without date and method
- [ ] No historical plan language presented as shipped architecture
- [ ] Related links resolve locally

## Minimal acceptable section map

If a short guide is justified, these section **intents** must still appear
(headings may be merged):

| Intent | Template sections |
| --- | --- |
| Why / context | 1, 4, 12 |
| Ownership | 5 |
| Structure | 6 |
| Flow | 7 |
| Contracts | 8 |
| Failures | 9 |
| Extend | 10 |
| Invariants | 11 |
| Validate | 15 |

## Related documents

- [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md)
- [DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md)
- [ADR_TEMPLATE.md](decisions/ADR_TEMPLATE.md)
- [architecture/README.md](README.md)

---

## Document history (template)

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial `ArchitectureGuideTemplate@1` for IPFSDOC-003 |
