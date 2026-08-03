# Source authority policy

| Field | Value |
| --- | --- |
| Interface | `DocumentationSourceAuthority@1` |
| Task | `IPFSDOC-005` |
| Status | `canonical` |
| Owner | documentation-governance |
| Source of truth | Program plan §3.1; `INFORMATION_ARCHITECTURE.md`; `PACKAGE_LOCAL_DOCUMENTATION_MAP.md`; live tests, code, packaging, and ADRs |
| Last verified | 2026-08-03 |
| Audience | maintainers, documentation authors, architecture writers, implementation agents |

## Purpose

This policy defines **which sources win** when documentation, plans, reports,
package-local notes, and product surfaces disagree. Every architecture guide,
audience page, ADR, and maintenance audit for this program must apply this
order. It does not change product behavior; it only governs how documentation
claims are selected and how discrepancies are recorded.

Companion deliverable: [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) maps production
domains and audiences to canonical coverage status and priority gaps.

## Authority order (highest wins)

When sources disagree about a fact that documentation would present as current
product truth, resolve in this order:

| Rank | Source class | What it includes | What it may authorize |
| ---: | --- | --- | --- |
| **1** | **Executable tests and schemas that define a contract** | Pytest/contract tests that assert behavior; JSON/YAML/Protobuf/IR schemas; feature files used as accepted behavioral contracts; golden vectors tied to validation helpers | Public contracts, input/output shapes, fail-closed paths, identity/CID rules, tool schemas, policy admission gates |
| **2** | **Current implementation** | Python under `ipfs_datasets_py/` (and thin root facades), including `__init__` exports and runtime routers | What the package actually does today; module ownership; real import paths |
| **3** | **Packaging and project configuration** | `pyproject.toml`, `setup.py`, `MANIFEST.in`, `requirements*.txt`, console entry points, optional-dependency extras, package metadata | Install surface, extras names, CLI entry points, declared Python version, package name/version |
| **4** | **Current operator configuration and deployment manifests** | `config.yaml.example`, `configs.yaml.example`, `sql_configs.yaml.example`, `.env.example`, `docker/*`, `deployments/`, systemd units, CI workflow definitions as **current** ops evidence | Env keys, defaults, deployment topology, service start shapes—as implemented in those files, not as prose claims |
| **5** | **Accepted architecture decision records (ADRs)** | Accepted ADRs under `ipfs_datasets_py/mcp_server/docs/adr/` and future `docs/architecture/decisions/`; status must be Accepted (or equivalent) | **Why** a boundary exists, alternatives rejected, invariants that future work must preserve—**not** a substitute for re-measuring runtime counts |
| **6** | **Maintained guides** | Pages with lifecycle `canonical` (or refreshed `current` disposition) under the target tree: product entry, architecture leaves, developer guides, ops/security guides | Journeys, explanations, diagrams, and operator procedures **when grounded** in ranks 1–5 |
| **7** | **Historical artifacts** (lowest) | Plans, completion reports, session summaries, generated stubs, ARCHIVE trees, `docs/archive/`, `docs/archived_stubs/`, phase STATUS files, undated “project complete” narratives, old drift reports | **Audit trail and intent history only.** Never sole authority for current capability, versions, tool counts, or “production ready” claims |

**Ranks 1–4 describe product reality.** Ranks 5–6 describe durable design and
navigable guidance. Rank 7 preserves history and must not be promoted without
re-verification.

### Compact form (program plan alignment)

The same order is stated in the documentation refresh plan and in
`INFORMATION_ARCHITECTURE.md`:

1. executable tests and schemas that define a contract;
2. current implementation and packaging/configuration metadata;
3. current operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides;
6. historical plans, completion reports, generated summaries, and archive material.

This document expands ranks **2** and **3** of that list into implementation
versus packaging, and treats packaging plus operator manifests as adjacent but
distinct classes when they disagree (implementation still outranks install
metadata for *behavior*; packaging outranks guides for *install surface*).

---

## 1. Class definitions and citation rules

### 1.1 Tests and schemas (rank 1)

**Use when:** documenting a behavioral contract, fail-closed rule, schema field,
CID/canonicalization rule, tool input schema, or policy gate.

**Citation requirements:**

- Prefer tests that fail if the contract is broken (not pure existence smoke).
- Name the test module path and, when useful, the test id or fixture.
- Schemas must be the files the runtime loads or validates against—not a prose
  table copied from a plan.

**Do not:** invent contracts from tutorials; treat coverage percentage claims
in ADRs or reports as evergreen without re-measurement.

### 1.2 Implementation (rank 2)

**Use when:** naming modules, ownership, call graphs, feature flags, routers,
or “where the code lives.”

**Citation requirements:**

- Prefer package paths under `ipfs_datasets_py/` resolvable in the current tree.
- Distinguish **implemented behavior** from **stubs**, empty submodule checkouts,
  and compatibility aliases (see [Kinds of truth](#2-kinds-of-truth)).

**Do not:** treat empty submodule directories as proof a feature works; treat
docstrings alone as stronger than tests when they conflict with tests.

### 1.3 Packaging and project configuration (rank 3)

**Use when:** install commands, Python version floor, extra names, console
scripts, package version, included package data.

**Primary files:** `pyproject.toml`, `setup.py`, `MANIFEST.in`,
`requirements.txt`, `requirements-*.txt`.

**Do not:** copy README install blocks when `pyproject.toml` extras or scripts
differ; invent extras that are not declared.

### 1.4 Operator configuration and deployment manifests (rank 4)

**Use when:** environment variables, config key precedence, container entry,
service units, deployment topology.

**Primary trees:** `config.yaml.example`, `docker/`, `deployments/`,
`.env.example`, root systemd units, CI under `.github/` when documenting how
this repo is built or released.

**Do not:** promote a one-off deployment blog or phase execution report over the
checked-in compose/Dockerfile unless the report is reclassified as evidence for
a dated release.

### 1.5 Accepted ADRs (rank 5)

**Use when:** explaining *why* a boundary, dual-runtime, hierarchical tools,
thin-wrapper engines, or MCP++ alignment exists.

**Current MCP ADR bodies (canonical until relocated):**  
`ipfs_datasets_py/mcp_server/docs/adr/` (ADR-001 through ADR-006). See
`PACKAGE_LOCAL_DOCUMENTATION_MAP.md` §4.

**Rules:**

- Only **Accepted** (or formally Superseded-with-replacement) ADRs are
  decision authority.
- ADRs do not override tests or code for *what runs*; they constrain *how*
  documentation frames design and future change.
- Metric or coverage numbers inside ADRs are **evidence-dated**, not evergreen.

### 1.6 Maintained guides (rank 6)

**Use when:** teaching journeys, architecture flow, ops runbooks, security
procedures—after ranks 1–5 ground the facts.

**Lifecycle:** Only pages in state `canonical` (see
`INFORMATION_ARCHITECTURE.md`) are citeable as current product guidance.
`refresh-and-surface` material may be used after refresh against ranks 1–5.

### 1.7 Historical artifacts (rank 7)

**Includes:** `docs/implementation/plans/**` (including this program’s protected
plan files—**readable**, never rewritten by workers as status authority),
`docs/reports/`, `docs/archive/`, `docs/archived_stubs/`, package `ARCHIVE/`,
`*_COMPLETION_*`, `*_SESSION_*`, `MASTER_STATUS.md`, versioned logic refactor
plans, generated `*_stubs.md`, Sphinx `_build/` outputs.

**Allowed uses:** disposition mapping, provenance of past intent, “what we
tried,” training context for agents with explicit non-authority banners.

**Forbidden uses:** sole evidence for “feature is complete,” tool counts,
Python version, import paths, or production readiness.

---

## 2. Kinds of truth

Documentation must not collapse distinct truth kinds. When a page mixes them,
label each claim:

| Kind | Meaning | Strongest sources |
| --- | --- | --- |
| **Discovery** | Something is importable, listed, or registered | Implementation, registries, tests |
| **Availability** | Dependency or backend is present on the machine | Packaging extras, lazy deps, runtime probes, tests |
| **Capability** | A successful probe or operation was demonstrated | Tests, verified examples, operator evidence |
| **Syntax validity** | Structure parses | Schemas, parsers, tests |
| **Semantic / policy validity** | Meaning and admission rules hold | Schemas + policy tests + implementation |
| **Proof** | External prover or attestation succeeded | Prover integration tests, attestation code—not UI |
| **Authorization** | Side effects are allowed | Policy engines, UCAN/intent gates, fail-closed defaults |
| **Canonical vs compat** | Preferred path vs alias/deprecated | Implementation + ADR + packaging |
| **Preferred vs optional vs stub** | Complete path vs degraded vs incomplete | Implementation + tests + packaging |

**Hard rules (program invariants):**

- Discovery is not capability.
- Syntax is not semantics.
- Model output is not proof.
- Proof is not authorization.
- Monitoring is not proof.
- UI visibility is not execution authority.
- Preferred backend is not the only backend; optional is not guaranteed;
  stub is not complete behavior.

---

## 3. Conflict resolution procedure

When a documentation task finds a disagreement:

1. **Identify the claim** (version, import, command, count, feature, contract).
2. **Collect sources** at each rank that speak to that claim.
3. **Apply the authority order.** Higher rank wins for the fact class it owns.
4. **Document the discrepancy** in the drift matrix or in the page’s validation
   / non-goals section—do not silently pick the most convenient narrative.
5. **Do not change production code** to make stale documentation true (out of
   scope for this documentation program).
6. **Do not delete historical pages** to hide the conflict; disposition and
   pointer instead.

### Packaging vs implementation

| Situation | Winner |
| --- | --- |
| Extra name or console script | Packaging (`pyproject.toml` / setup) |
| Runtime behavior of an installed module | Implementation + tests |
| Guide says install works; packaging omits extra | Packaging; fix the guide |
| Code path exists; no test/schema contract | Implementation for “exists”; mark contract **unverified** until tests exist |

### ADR vs tests

| Situation | Winner |
| --- | --- |
| ADR describes intended architecture; tests enforce different contract | **Tests** for runtime claims; open an ADR revision or drift entry for design drift |
| ADR lists rejected alternatives | ADR remains authoritative for rationale |
| ADR cites coverage % | Re-measure; do not copy as current |

### Guide vs historical plan

Maintained guide (rank 6) wins only if grounded in ranks 1–5. A plan never
outranks a maintained guide for *intent*, but neither outranks tests/code for
*shipped behavior*.

---

## 4. Package-local versus `docs/` authority

Package-local Markdown (`ipfs_datasets_py/**/*.md`) is **not** automatically
product-wide canonical. Disposition is recorded in
[PACKAGE_LOCAL_DOCUMENTATION_MAP.md](PACKAGE_LOCAL_DOCUMENTATION_MAP.md).

| Location | Default role | Citation rule |
| --- | --- | --- |
| `ipfs_datasets_py/mcp_server/docs/adr/` | **Canonical ADR bodies** (until IPFSDOC-016 relocates/index) | Cite for accepted MCP design decisions |
| `ipfs_datasets_py/mcp_server/docs/` (non-ADR) | Domain-proximate; often `refresh-and-surface` | Prefer after architecture leaves exist; do not duplicate ADR bodies under `docs/` |
| `ipfs_datasets_py/mcp_server/ARCHIVE/` | Historical | Rank 7 only |
| `ipfs_datasets_py/processors/**/*.md` | Split: useful design notes vs omni_converter history | Prefer `docs/guides/processors/` + future `docs/architecture/processing/`; package READMEs for subpackage detail |
| `ipfs_datasets_py/logic/**/*.md` | Mostly pointer / subsystem README | Prefer `docs/logic/` product guides + future `docs/architecture/logic/` |
| `ipfs_datasets_py/**/*_stubs.md` | Generated | Rank 7 / generated; never design authority |
| `docs/architecture/**` (target leaves) | Canonical architecture after program wave | Preferred product architecture home |
| `docs/implementation/plans/**` | Plan state | Rank 7 for product claims; protected program inputs are never worker-edited |

**One body of record:** Do not maintain two full ADR or architecture bodies for
the same decision. Prefer one body and one pointer.

---

## 5. Generated content

| Kind | Authority |
| --- | --- |
| Signature / API stubs (`*_stubs.md`, `docs/archived_stubs/`) | Regenerated facts only |
| Sphinx `docs/tdfol/_build/` | Build output; not design authority |
| MkDocs `site/` | Build output when present; not source of truth |
| Auto indexes | Navigation aid only |

Hand-maintained conceptual and decision documentation always outranks generated
listings for *why* and *how to use safely*.

---

## 6. Evidence pages and baselines

Evidence artifacts (`CURRENT_STATE_BASELINE.md`, drift matrices, verification
receipts, performance snapshots):

- Are authoritative for the **measured commit, date, and method** they record.
- Are **not** evergreen product guides.
- May outrank older historical counts for inventory questions.
- Must not be silently rewritten to look like current architecture without a
  new measurement.

---

## 7. Protected program inputs

The following paths are operator-protected plan inputs. Workers may **read**
them as program intent; they must **never** create, modify, rename, delete,
replace, or regenerate them to “fix” authority or completion:

- `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH_PLAN_2026_08_03.md`
- `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.objectives.md`
- `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.todo.md`

Program intent lives there; **product truth** still follows ranks 1–6 above.

---

## 8. Required behavior for documentation authors and agents

1. Ground every new or refreshed `canonical` page in ranks 1–5 before expanding
   narrative (rank 6).
2. Prefer concrete paths and offline validation commands over summary documents.
3. When a higher-rank source is unavailable (e.g. tests not collected), state
   **not measured** or **unverified**—do not fill gaps from rank 7.
4. Record product defects found while documenting in the drift matrix; do not
   “fix” them in prose alone.
5. Apply [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) lifecycle
   states so historical material is never cited as `canonical` by accident.
6. Use [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) to find the intended canonical
   home and gap priority before inventing a second root for the same domain.

---

## 9. Related artifacts

| Artifact | Role |
| --- | --- |
| [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) | Audiences, lifecycle, page contracts |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Package vs docs disposition map |
| [CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md) | Dated inventory evidence |
| [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) | Claim-level stale/wrong queue |
| [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) | Domain and audience coverage + P0/P1 gaps |

---

## 10. Validation

```bash
test -s docs/maintenance/SOURCE_AUTHORITY.md && \
  rg -n 'executable tests|Accepted architecture|Maintained guides|Historical' \
    docs/maintenance/SOURCE_AUTHORITY.md
```

## Acceptance checklist (IPFSDOC-005 — authority half)

| Criterion | Evidence |
| --- | --- |
| Order among tests/schemas, implementation, packaging/config, ADRs, guides, historical | Authority order table + compact form |
| Conflict resolution without silent preference | §3 |
| Package-local vs docs | §4 |
| Generated and evidence limits | §5–§6 |
| Agent-enforceable rules | §8 |
