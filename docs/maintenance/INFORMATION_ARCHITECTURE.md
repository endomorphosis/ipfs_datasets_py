# Documentation Information Architecture

| Field | Value |
| --- | --- |
| Interface | `DocumentationPageContract@1` |
| Task | `IPFSDOC-003` |
| Status | `canonical` |
| Owner | documentation-governance |
| Source of truth | This file; grounded in the live `docs/` tree layout, `mkdocs.yml`, and package-local docs under `ipfs_datasets_py/` |
| Last verified | 2026-08-03 |
| Audience | maintainers, documentation authors, implementation agents |

## Purpose

This document freezes the writing and lifecycle contract for the IPFS Datasets
Python documentation corpus. Parallel documentation lanes use it to decide:

- who a page is for;
- whether a page is current authority or history;
- where a page lives and how it is named;
- which metadata every maintained page must carry;
- how diagrams, examples, and citations are written;
- what an architecture guide and an ADR must contain;
- how pages are reviewed, deprecated, and archived.

It does **not** claim that every existing page already complies. Compliance is
enforced as pages are created or refreshed under this program.

## How to read this document

- **Required** — Must be present on new and refreshed maintained pages.
- **Target** — Canonical location or structure the program converges on; legacy
  pages may still live elsewhere until a disposition task routes them.
- **Historical** — Describes past material that is preserved but is not current
  authority.

Authority order when sources disagree (same as the program plan):

1. executable tests and schemas that define a contract;
2. current implementation and packaging/configuration metadata;
3. current operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides;
6. historical plans, completion reports, generated summaries, and archive material.

---

## 1. Audiences

Every page declares a primary audience. Secondary audiences are optional.

| Audience ID | Who | Primary needs | Typical homes |
| --- | --- | --- | --- |
| `end-user` | Operators and data practitioners using Python API, CLI, or MCP tools | Install, configure, run supported journeys, understand failures and fallbacks | `docs/index.md`, `docs/getting_started.md`, `docs/installation.md`, `docs/configuration.md`, `docs/user_guide.md`, `docs/user_guides/`, `docs/tutorials/`, `docs/examples/` |
| `developer` | Contributors extending the package | Repository map, extension recipes, tests, coding patterns | `docs/developer_guide.md`, `docs/developer_guides/`, `CONTRIBUTING.md` |
| `architect` | Designers of subsystem boundaries | Domain ownership, data/control flow, invariants, ADRs | `docs/architecture/`, `docs/architecture/decisions/` |
| `operator` | Deployers and on-call | Deployment, performance, diagnostics, security boundaries | `docs/deployment/`, `docs/guides/operations/`, `docs/guides/security/` |
| `agent` | Implementation agents and automation | Stable headings, concrete paths, validation commands, explicit non-goals | `docs/developer_guides/FOR_AGENTS.md` (target), architecture guides, ADRs |
| `maintainer` | Doc owners and release owners | Inventory, drift, coverage, freshness, disposition | `docs/maintenance/` |

### Audience rules

1. One **primary** audience per page. Multi-audience pages state the primary
   first and link out for secondary depth.
2. Do not bury end-user journeys inside architecture leaves or package-local
   history directories.
3. Agent-facing pages prefer stable anchors, absolute-from-repo paths, and
   copy-pasteable validation commands over narrative alone.
4. Do not target "everyone" without a primary; that produces un-owned pages.

---

## 2. Document lifecycle states

Every documentation artifact has exactly one **lifecycle state**. The state
determines whether the page may be cited as current authority.

| State | Meaning | May be current authority? | Typical locations |
| --- | --- | --- | --- |
| `canonical` | Maintained, reviewed description of current product or process | **Yes** | Target tree under `docs/` (entry pages, architecture, developer guides, API domains, operations) |
| `generated` | Machine-produced listing or stub regenerated from source | Only for the facts it regenerates; never for design rationale | Generated API stubs, auto indexes, build outputs under package or `site/` |
| `plan` | Intent for future or in-flight work; not a description of shipped behavior | **No** | `docs/implementation/plans/`, domain `*.objectives.md` / `*.todo.md` where used as planning |
| `evidence` | Point-in-time measurement, receipt, audit, or verification artifact | Only for the measured commit/date it records | `docs/maintenance/*BASELINE*`, `docs/reports/`, verification receipts, performance snapshots |
| `historical` | Superseded, archived, or completion-era material preserved for audit trail | **No** | `docs/archive/`, `docs/archived_stubs/`, completion summaries, old session reports |

### State rules

1. **One home of authority.** For a given concern there is at most one
   `canonical` page. Other pages link to it or carry a disposition banner.
2. **Plans are not architecture.** A plan may propose an architecture; only an
   accepted ADR or a `canonical` architecture guide records the decision as
   current.
3. **Evidence is dated.** Evidence pages must state the commit, date (UTC), and
   measurement method. They must not be rewritten to look like evergreen guides.
4. **Generated content is secondary.** Generated listings may support search and
   API surfaces; conceptual and decision documentation remains hand-maintained.
5. **Historical is preserved, not promoted.** Do not move historical claims into
   entry pages without re-verification against the current tree.
6. **State is explicit.** New and refreshed pages set `Status` in the metadata
   table (section 4). Legacy pages without metadata are treated as
   *review-needed* until classified.

### Disposition labels (for legacy mapping)

When classifying existing pages that are not yet rewritten, use one of:

| Disposition | Meaning |
| --- | --- |
| `current` | Already serves as the canonical home; refresh in place if needed |
| `superseded` | Replaced by a named canonical page; keep with pointer banner |
| `historical` | Archive or treat as historical; not current authority |
| `duplicate` | Same concern as another page; consolidate or pointer |
| `review-needed` | Not yet classified; do not cite as authority until reviewed |

Destructive archive moves require a separately reviewed task. This contract
defines the map; it does not authorize bulk deletion.

---

## 3. Naming and placement

### 3.1 Target tree (canonical homes)

```text
docs/
|-- index.md                         # product entry (end-user primary)
|-- getting_started.md
|-- installation.md
|-- configuration.md
|-- user_guide.md
|-- developer_guide.md
|-- architecture/
|   |-- README.md                    # architecture hub
|   |-- SYSTEM_CONTEXT.md
|   |-- DOMAIN_MAP.md
|   |-- END_TO_END_DATA_FLOW.md
|   |-- DEPENDENCY_AND_INITIALIZATION.md
|   |-- INTEGRATION_BOUNDARIES.md
|   |-- processing/ | storage/ | retrieval/ | knowledge/
|   |-- logic/ | mcp/ | runtime/
|   |-- WALLET_TRUST_AND_PRIVACY.md
|   |-- ARCHITECTURE_GUIDE_TEMPLATE.md
|   `-- decisions/                   # ADRs + index
|       |-- README.md
|       |-- ADR_TEMPLATE.md
|       `-- ADR-NNN-short-title.md
|-- developer_guides/
|   |-- DOCUMENTATION_CONTRIBUTING.md
|   |-- FOR_AGENTS.md                # target
|   |-- EXTENSION_RECIPES.md         # target
|   |-- TESTING_AND_EVIDENCE.md      # target
|   `-- TROUBLESHOOTING.md           # target
|-- guides/
|   |-- operations/
|   `-- security/
|-- api/
|   |-- README.md
|   `-- domains/
|-- tutorials/
|-- examples/
|-- maintenance/
|   |-- INFORMATION_ARCHITECTURE.md  # this file (canonical policy)
|   |-- CURRENT_STATE_BASELINE.md    # evidence (IPFSDOC-001)
|   |-- DRIFT_AND_CLAIM_MATRIX.md    # evidence / claim audit
|   |-- COVERAGE_MATRIX.md           # target
|   |-- LEGACY_DISPOSITION.md        # target
|   |-- PACKAGE_LOCAL_DOCUMENTATION_MAP.md  # target (authority map)
|   `-- RELEASE_EVIDENCE.md          # target
|-- archive/                         # historical only
`-- implementation/plans/            # plan state; protected program inputs
```

Existing equivalent pages are reviewed before a new canonical page is created.
When a maintained page already owns the concern, refresh or route to it.
Labels `target` mark deliverables owned by later tasks; do not invent competing
homes for the same concern while those tasks land.

### 3.2 File naming conventions

| Kind | Pattern | Examples |
| --- | --- | --- |
| Product entry / journey | `snake_or_lower.md` or established root names | `getting_started.md`, `user_guide.md` |
| Architecture guides | `SCREAMING_SNAKE.md` for durable system docs; domain folders lowercase | `DOMAIN_MAP.md`, `architecture/mcp/` |
| ADRs | `ADR-NNN-kebab-title.md` (three-digit zero-padded) | `ADR-007-thin-wrapper-engines.md` |
| Maintenance / evidence | `SCREAMING_SNAKE.md` with role in the name | `CURRENT_STATE_BASELINE.md` |
| Plans | descriptive `SCREAMING` or domain plans as already established | program plan files under `implementation/plans/` |
| Package-local docs | stay under the owning package until a map task promotes or pointers them | `ipfs_datasets_py/mcp_server/docs/` |

Rules:

1. Prefer **stable names** that describe the concern, not the authoring session
   (`SESSION_SUMMARY_*` is evidence/historical, not canonical).
2. Do not invent competing roots for the same concern (e.g. both
   `MCP_TOOLS_GUIDE.md` and `architecture/mcp/` claiming sole authority without
   a declared primary).
3. Directory `README.md` files are hubs: navigation and purpose only; deep
   content lives in leaf pages.
4. Avoid date stamps in **canonical** names. Dates belong in evidence metadata
   or historical filenames when the artifact is inherently point-in-time.

### 3.3 Placement decision tree

1. Is it a **user journey** (install, first success, workflow)? → root entry or
   `user_guides/` / `tutorials/` / `examples/`.
2. Is it **why / invariant / boundary**? → `architecture/` or
   `architecture/decisions/`.
3. Is it **how to extend or test**? → `developer_guides/` (or developer entry).
4. Is it **ops/security procedure**? → `guides/operations/` or
   `guides/security/`.
5. Is it **API surface with provenance**? → `api/` (hand-maintained domain pages
   over pure generation).
6. Is it **measurement or audit of docs**? → `docs/maintenance/`.
7. Is it **future intent**? → `implementation/plans/` (plan state).
8. Is it **no longer current**? → disposition banner + eventual `archive/`
   (historical), never delete without review.

### 3.4 Package-local documentation

Package-local trees (for example `ipfs_datasets_py/mcp_server/docs/`) may hold
domain-proximate ADRs and development notes. They are **not** automatically
canonical for the whole product:

- A later authority-map task records each package-local corpus and whether the
  canonical home is promoted under `docs/` or remains package-local with a
  pointer from the architecture hub.
- Do not duplicate an ADR body in two trees. Prefer one body and one pointer.
- Existing MCP ADRs under `ipfs_datasets_py/mcp_server/docs/adr/` remain valid
  sources until explicitly superseded or relocated with an index update.

---

## 4. Required page metadata

Every **new or refreshed** page that is `canonical`, `plan`, or `evidence`
starts with a metadata table (or equivalent YAML front matter mapped to the
same fields). Minimum required fields:

| Field | Required for | Description |
| --- | --- | --- |
| **Title** | all | H1 matches the concern |
| **Status** | all | One of: `canonical`, `generated`, `plan`, `evidence`, `historical`, `draft`, `deprecated` |
| **Owner** | `canonical`, `plan`, `evidence` | Team or role accountable for freshness (e.g. `mcp-runtime`, `documentation-governance`) |
| **Source** / **Source of truth** | `canonical`, `evidence` | Concrete paths, modules, tests, or configs the page is grounded in |
| **Last verified** | `canonical`, `evidence` | ISO date `YYYY-MM-DD` (UTC intent) of last source check |
| **Audience** | `canonical` | Primary audience id from section 1 |
| **Interface** (optional) | program outputs | Stable contract id when the page is a named deliverable |

### Recommended additional fields

| Field | When useful |
| --- | --- |
| `Supersedes` | Replaces another page or ADR |
| `Superseded by` | No longer authority; points forward |
| `Review cadence` | Override of default cadence (section 8) |
| `Related ADRs` | Architecture pages |
| `Validation` | Commands that prove claims on this page |

### Metadata example (canonical guide)

```markdown
# Domain map

| Field | Value |
| --- | --- |
| Status | canonical |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/` package layout, `pyproject.toml`, domain `__init__` exports |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
```

### Draft and deprecated

- `draft` — work in progress; not citeable as authority; PR or task must finish
  or mark historical.
- `deprecated` — still in tree but must not be used for new work; banner must
  name the replacement and target removal or archive window.

---

## 5. Page contracts by type

### 5.1 Shared contract (all canonical pages)

Required sections or equivalent content:

1. **Purpose** — one short paragraph: what question this page answers.
2. **Audience** — primary (and optional secondary).
3. **Scope / non-goals** — what the page does not cover.
4. **Source grounding** — modules, paths, tests, or configs.
5. **Body** — type-specific sections (below).
6. **Validation** — at least one offline command or check that a reader can run
   to confirm the page still matches the tree (may be "existence + link check"
   for pure navigation hubs).
7. **Related pages** — links to parent hub, siblings, ADRs.

### 5.2 User journey pages

Must include: prerequisites; capability/extra if optional; shortest success
path; failure and fallback behavior; next steps into deeper guides.

### 5.3 Architecture guide pages

Must follow [ARCHITECTURE_GUIDE_TEMPLATE.md](../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md).
Minimum sections (names may vary slightly but content must exist):

| Section | Intent |
| --- | --- |
| Context | Why this subsystem exists in the product |
| Ownership and boundaries | What this domain owns and does not own |
| Components | Current modules/packages (not aspirational) |
| End-to-end flow | Data and/or control flow across the boundary |
| Contracts | Inputs, outputs, schemas, public APIs |
| Failure modes and fallbacks | Degraded paths, optional deps, stubs vs complete behavior |
| Extension points | How to add backends, tools, or processors correctly |
| Invariants | Rules a change must not break |
| Rationale / decisions | Links to ADRs; short summary of *why* |
| Validation | Focused commands or tests |
| Related | Sibling domains and entry points |

Architecture pages explain **rationale and invariants**, not only component
lists. Point-in-time counts require date and method or are omitted.

### 5.4 ADR pages

Must follow [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md).
Lifecycle is defined in section 7.

### 5.5 Evidence pages

Must include: measurement time (UTC), commit, host/tooling constraints, method
commands, tracked vs derived vs estimate vs not-measured labels where counts
appear, and an explicit statement that the page is not evergreen product docs.

### 5.6 Plan pages

Must include: outcome, in/out of scope, and a clear banner that the plan is not
a description of shipped behavior. Protected program inputs under
`docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` must not be
edited by implementation workers.

---

## 6. Diagrams, examples, and citations

### 6.1 Diagrams

1. Prefer **fenced diagrams** (Mermaid or ASCII) checked into the Markdown so
   the source is reviewable without binary assets.
2. Every diagram has a one-line caption stating what is in scope and what is
   simplified.
3. Label real package or module names when claiming ownership; do not invent
   layers that do not exist in the tree.
4. Distinguish **current** vs **target** architecture explicitly if both appear.
5. Do not use diagrams alone as authority for security or proof claims; pair
   with prose and source paths.

### 6.2 Examples

1. Examples must match **current** public APIs and import paths.
2. Prefer small, copy-pasteable snippets over multi-file novels.
3. Mark prerequisites (Python version, extras, services) above the fence.
4. Prefer examples that are syntax-checked or executed with a **bounded offline**
   command. If execution is not practical, state that and still verify imports
   and paths against the tree.
5. Do not present pseudo-APIs as if they were shipped.
6. Optional capabilities: show discovery/fallback behavior, not only the happy
   path with every extra installed.
7. Secrets, private keys, and live network endpoints do not appear in examples.

### 6.3 Citations and source references

1. Cite **repository paths** relative to the repo root using backticks, e.g.
   `` `ipfs_datasets_py/mcp_server/server.py` ``.
2. For tests that define a contract, cite the test module path.
3. For packaging facts, cite `pyproject.toml` (or the resolved metadata source).
4. Do not use another summary document as the sole evidence for a factual claim
   about code behavior.
5. External links: allow for standards and upstream projects; mark them as
   external. Prefer local links for in-repo docs.
6. Historical citations: when quoting old plans or completion reports, label them
   historical and do not treat them as current product claims.
7. Disagreements between sources are recorded (e.g. in the drift matrix), not
   silently resolved toward convenience.

### 6.4 Claims policy (short form)

Forbidden without current-tree evidence:

- feature counts, test counts, or coverage percentages presented as current;
- "production-ready" or "complete" labels copied from session summaries;
- Python version or extras matrices that contradict packaging metadata;
- authority escalation (e.g. claiming a model result or discovery probe equals
  policy approval or proof).

---

## 7. Architecture Decision Records (ADR) lifecycle

Canonical ADR home (target): `docs/architecture/decisions/`.

Package-local ADRs may continue under their package until mapped; new
cross-cutting product ADRs are authored under `docs/architecture/decisions/`
using [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md).

### 7.1 States

| ADR status | Meaning |
| --- | --- |
| `proposed` | Under review; not binding |
| `accepted` | Binding for new work |
| `deprecated` | No longer preferred; still historically true that it was accepted |
| `superseded` | Replaced by a newer ADR (must link successor) |
| `rejected` | Considered and not adopted (optional to keep) |

### 7.2 Lifecycle workflow

1. **Draft** from the template with status `proposed`.
2. **Review** with the domain owner and at least one architect/maintainer.
3. **Accept** — status `accepted`, date set, linked from the relevant
   architecture guide and the decisions index.
4. **Implement** — code and docs changes reference the ADR number.
5. **Supersede or deprecate** when the decision no longer holds; never silently
   rewrite history. Create a new ADR or mark `superseded` with `Superseded by`.
6. **Index** — every accepted/superseded ADR appears in
   `docs/architecture/decisions/README.md` (target index).

### 7.3 Numbering

- Use the next free `ADR-NNN` in the canonical decisions directory.
- Do not reuse numbers. Package-local numbers are not automatically global;
  when promoting, either keep the original identifier in a "Origin" field or
  assign a new global number and record the mapping.

### 7.4 Required ADR content

Context; decision; alternatives considered; consequences (positive/negative);
invariants; compliance/validation notes; status and dates. See the template.

---

## 8. Review cadence and freshness

| Page class | Default review cadence | Trigger for out-of-band review |
| --- | --- | --- |
| Product entry (`index`, install, getting started, user guide) | Every release and at least quarterly | Packaging, CLI, or public API change |
| Architecture guides | Semi-annual or when domain changes land | New subsystem boundary, ADR accept/supersede |
| ADRs | On status change only (immutable body once accepted, except errata) | Superseding decision |
| Developer guides | Semi-annual | Extension pattern or test layout change |
| Operations / security | Quarterly | Incident, threat model change, deploy path change |
| Evidence / baselines | On measurement only | New program wave or major tree change |
| Historical / archive | No freshness obligation | None — do not "update" history to look current |

### Freshness rules

1. **Last verified** is updated only after a human or agent re-checks sources
   against the current tree (not merely after typo edits).
2. Stale `canonical` pages (past cadence without review) are not automatically
   demoted, but release evidence must list them as risk until verified.
3. Point-in-time numbers must include date and method or be removed.
4. Owners are roles, not only individuals; when ownership is unclear, default
   owner is `documentation-governance` until assigned.

---

## 9. Deprecation policy (documentation)

Deprecation applies to **docs pages** (and to doc claims about deprecated
product APIs). Product API deprecation schedules live in their own canonical
product docs (e.g. deprecation schedules); documentation deprecation is about
the pages themselves.

### When to deprecate a page

- A newer canonical page fully owns the concern.
- The described surface was removed or never shipped.
- The page mixes historical completion claims with guidance in a way that
  misleads readers.

### Required deprecation steps

1. Set `Status` to `deprecated` (or `historical` if immediately archival).
2. Add a **banner** at the top with replacement link and reason.
3. Remove the page from MkDocs `nav` and from "current" hubs if present; leave
   a pointer from the hub if readers may still land on the old URL/path.
4. Update inbound links from other **canonical** pages to the replacement.
5. Record disposition in the legacy disposition map when that artifact exists.
6. After the review window (default: one minor release or 30 days, whichever the
   maintainer sets), archive per section 10.

### Banner example

```markdown
> **Deprecated (2026-08-03).** This page is not current authority.
> Use [Architecture domain map](../architecture/DOMAIN_MAP.md) instead.
> Historical context only; do not cite feature counts from this page.
```

---

## 10. Archive policy

### Goals

- Preserve history for audit and migration understanding.
- Prevent historical material from being read as current product documentation.
- Avoid bulk deletion; prefer disposition + archive.

### Archive locations

| Location | Use |
| --- | --- |
| `docs/archive/` | General historical docs, completion reports, old reorganizations |
| `docs/archived_stubs/` | Retired stub catalogs and similar |
| In-place with `historical` status | When a move is not yet approved; banner required |

### Archive admission rules

1. Page has disposition `historical` or `superseded` with a known replacement
   (or explicit "no replacement — removed surface").
2. Banner or archive README states **not maintained** and **not authority**.
3. Prefer git history + archive path over rewriting the historical file to match
   current APIs.
4. Do not archive the only copy of an accepted ADR without leaving the body
   reachable from the decisions index (superseded ADRs stay indexed).
5. Destructive moves (large renames, mass relocation) require a dedicated
   reviewed task and an updated disposition map — not ad-hoc worker cleanup.

### Archive README obligations

`docs/archive/README.md` (and similar) must continue to warn that contents may
be outdated and must link back to current entry points (`docs/index.md`,
getting started, architecture hub).

### What not to archive

- Active `canonical` pages solely because they need edits.
- Protected program plan inputs.
- The sole evidence baseline still referenced by an open program wave (copy or
  supersede with a newer evidence page first).

---

## 11. Preserve history without presenting it as current authority

Summary of non-negotiable rules:

1. Historical plans, session summaries, and completion reports stay in
   `plan` / `evidence` / `historical` state — they do not get relabeled
   `canonical` without a full rewrite against the live tree.
2. Entry pages and hubs link to **canonical** leaves, not to completion reports,
   as the primary path.
3. When a historical page is useful for context, quote it with date and state,
   and route the reader to the current guide for what to do next.
4. Do not "fix" historical documents to match new APIs; that destroys audit
   value and creates fake authority.
5. Feature and test counts on historical pages are frozen narrative, not metrics
   dashboards.
6. Package-local history directories (e.g. under `mcp_server/docs/history/`) are
   historical unless a map task promotes a specific file.

---

## 12. MkDocs and navigation

- `mkdocs.yml` `nav` is a **product navigation** surface, not a complete
  inventory of every Markdown file.
- Canonical entry and architecture hubs should appear in `nav` as they are
  refreshed; exhaustive listing of archives is not required.
- Absence from `nav` does not make a page historical; state and disposition do.
- Site build (`site/`) is generated output and is not a documentation source of
  truth.

---

## 13. Validation of this contract

Authors and agents check:

```bash
test -s docs/maintenance/INFORMATION_ARCHITECTURE.md
test -s docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md
test -s docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md
test -s docs/architecture/decisions/ADR_TEMPLATE.md
```

When refreshing any page under this contract, also verify named paths and
imports against the current tree and update **Last verified**.

---

## 14. Related documents

| Document | Role |
| --- | --- |
| [DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md) | How to contribute docs under this IA |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md) | Architecture page skeleton |
| [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md) | ADR skeleton and status fields |
| [CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md) | Evidence: measured tree baseline |
| [architecture/README.md](../architecture/README.md) | Architecture hub (refresh target) |
| [docs/archive/README.md](../archive/README.md) | Historical material warning |

---

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial `DocumentationPageContract@1` for IPFSDOC-003 |
| 2026-08-03 | Align maintenance tree labels with live baseline/drift artifacts |
