# Documentation maintenance cadence and ownership

| Field | Value |
| --- | --- |
| Interface | `DocumentationMaintenanceLifecycle@1` |
| Task | `IPFSDOC-097` |
| Status | `canonical` |
| Owner | documentation-governance |
| Source of truth | This file; [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) §§4–10; [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md); [VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md); live owners on canonical pages under `docs/` |
| Last verified | 2026-08-03 |
| Audience | maintainer, developer, architect, agent, release reviewer |
| Depends on | `IPFSDOC-003`, `IPFSDOC-006`, `IPFSDOC-096` |
| Goal | `IPFSDOC-G112` |

## Purpose

This page is the **operational maintenance contract** for the IPFS Datasets
Python documentation corpus after the v1 documentation refresh. It defines:

1. **Who owns** each documentation class and product-domain surface.
2. **Routine cadence** and **change-triggered** reviews.
3. How **generated references** are refreshed.
4. How **examples** are revalidated.
5. How **drift** is triaged and closed.
6. **Release** documentation checks.
7. **Archive / disposition** review rules.
8. **Exception** (waiver / allowlist) expiry.
9. How **product code changes** must update architecture, ADRs, API maps, and
   user docs so the corpus does not freeze as a point-in-time snapshot.

It does **not** rewrite product behavior, mass-move archive trees, or replace
the page-writing contract in [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md).
When policy details conflict, prefer the information architecture for page
shape and this file for **who / when / how often / how to triage**.

---

## 1. Owners

Owners are **roles** (not only individuals). When ownership is unclear, default
to `documentation-governance` until a domain role is assigned. Product domain
ownership for *code* follows [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md);
documentation owners below are accountable for **freshness of the docs that
describe those domains**.

### 1.1 Governance and release roles

| Owner role | Accountable for | Primary homes |
| --- | --- | --- |
| `documentation-governance` | Corpus policy, maintenance hub, IA, authority, coverage/drift baselines, disposition map, release docs gates, unassigned pages | `docs/maintenance/*`, page contract, contributing workflow |
| `architecture` | System context, domain map, E2E flows, domain architecture leaves, ADR index hygiene | `docs/architecture/**` |
| `api-reference` | Hand-maintained API domain maps, generation/freshness policy, signature-drift detection | `docs/api/**` |
| `install-and-entry` | Install, getting started, configuration, product entry spine | `docs/installation.md`, `getting_started.md`, `configuration.md`, `index.md` (with late nav owner) |
| `user-journeys` | User guide, tutorials, high-traffic examples | `docs/user_guide.md`, `user_guides/`, `tutorials/`, `examples/` |
| `developer-experience` | Developer guide, extension recipes, testing/evidence, agent handoff | `docs/developer_guide.md`, `developer_guides/` |
| `operations` | Deployment, performance, diagnostics | `docs/deployment/`, ops guides under `docs/guides/operations/` |
| `security` | Threat model, secrets, audit/incident docs | `docs/guides/security/`, wallet/trust architecture pages |
| `release-docs` | Pre-release docs checklist, quality report re-run, release evidence (with IPFSDOC-098) | `QUALITY_REPORT.md`, future `RELEASE_EVIDENCE.md` |
| `archive-steward` | Disposition review queue, archive README honesty, exception expiry for historical allowlists | `LEGACY_DISPOSITION.md`, `docs/archive/**` |

### 1.2 Product-domain documentation owners

Align page `Owner` metadata with the domain that owns the **code concern**.
Typical mappings (override on the page when a leaf has a tighter owner):

| Code / concern cluster | Doc owner role | Canonical doc homes |
| --- | --- | --- |
| Processors, conversion, multimedia, web archives | `processing` | `docs/architecture/processing/`, related user guides |
| Storage, IPFS/IPLD, cache, P2P, publication | `storage` | `docs/architecture/storage/` |
| Embeddings, vector stores, search | `retrieval` | `docs/architecture/retrieval/` |
| Knowledge graphs, GraphRAG, optimizers | `knowledge` | `docs/architecture/knowledge/`, optimizer guides |
| Logic, IR, provers, semantic round-trip | `logic` | `docs/architecture/logic/`, logic docs |
| MCP server, tools, transports | `mcp-runtime` | `docs/architecture/mcp/`, MCP guides |
| Runtime entrypoints, acceleration, sessions | `runtime` | `docs/architecture/runtime/` |
| Wallet, trust, privacy, authorization | `security` / `trust` | `WALLET_TRUST_AND_PRIVACY.md`, security guides |

### 1.3 Ownership rules

1. Every **canonical** and **evidence** page declares `Owner` in metadata
   ([INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) §4).
2. One **canonical home** per concern; owners do not create competing roots.
3. Shared hubs (`docs/index.md`, architecture/API indexes, MkDocs nav) have a
   **single late owner** per change; parallel lanes edit leaf pages only.
4. Package-local docs remain under package-proximate ownership until
   [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](PACKAGE_LOCAL_DOCUMENTATION_MAP.md)
   promotes or points them; do not fork ADR bodies.
5. Agents inherit the page owner of the task output; unowned chores fall to
   `documentation-governance`.

---

## 2. Routine review cadence

Default cadences (from IA §8, operationalized here). Page metadata may set
`Review cadence` to override when a surface is higher risk.

| Page class | Cadence | Owner role | Routine actions |
| --- | --- | --- | --- |
| Product entry (index, install, getting started, user guide) | **Every release** and at least **quarterly** | `install-and-entry`, `user-journeys` | Re-check packaging/extras/imports; update `Last verified`; fix P0/P1 claims |
| Architecture guides | **Semi-annual** or when domain lands | `architecture` + domain owner | Diff against package layout and tests; refresh flows/invariants |
| ADRs | On **status change** only (body immutable after accept except errata) | `architecture` + domain owner | Index status; link successor when superseded |
| Developer guides | **Semi-annual** | `developer-experience` | Extension/test layout check; agent commands still offline-runnable |
| Operations / security | **Quarterly** | `operations`, `security` | Deploy path, threat, secrets hygiene |
| API domain maps | **Quarterly** and after export changes | `api-reference` | Signature/export drift; regenerate Track B dumps if used |
| Tutorials / examples | **Every release** for ledger rows; **semi-annual** for secondary | `user-journeys` | Re-run bounded commands; update [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) |
| Maintenance evidence (baseline, matrices, quality) | On **measurement** or major tree change | `documentation-governance` | Re-run measurement commands; new evidence page or superseding note |
| Generated references | After generator/input change; at least **quarterly** if still cited | `api-reference` | Regenerate; never promote to design authority |
| Historical / archive | **No freshness obligation** | `archive-steward` | Disposition review only; do not “refresh” history to look current |

### Freshness rules

1. Update `Last verified` only after sources are re-checked against the current
   tree—not for typo-only edits.
2. Stale canonical pages (past cadence without review) are **not** auto-demoted,
   but release evidence must list them as residual risk until verified.
3. Point-in-time counts require date and method or must be removed.
4. Filesystem mtime is **never** proof of freshness
   ([VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md)).

---

## 3. Change-triggered reviews

Out-of-band reviews fire when product or packaging changes land. The **code PR
owner** is responsible for the documentation updates; domain doc owners review.

| Trigger | Required doc updates | Minimum validation |
| --- | --- | --- |
| Packaging / extras / Python floor / console scripts | Install, getting started, configuration; any claim in drift matrix for that surface | `rg`/read of `pyproject.toml`; offline install-claim audit |
| Public import path or signature change | API domain page; user/developer examples; features list if advertised | AST or export check; `check_docs.py` on touched roots |
| New/removed MCP tool or transport behavior | MCP architecture leaf; tools guide; API MCP domain | Tool registry / test path citation |
| Domain boundary or ownership change | [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md); affected architecture leaves; coverage matrix note if program wave open | Architecture template sections still complete |
| New durable design decision | New or superseding **ADR**; link from architecture guide and ADR index | ADR template complete; index row |
| Failure mode / optional dep / stub vs complete change | Architecture failure sections; user journey fallbacks; honesty labels on examples | Capability probe language matches code |
| Security / wallet / authz change | Security guides; trust architecture; threat assumptions | No secrets in examples; fail-closed claims match tests |
| Generator or stub regeneration script change | [GENERATION_AND_FRESHNESS.md](../api/GENERATION_AND_FRESHNESS.md); regenerated dump if still published | Script help + regenerate dry path |
| Tutorial runnable fence change | Example verification ledger row | Bounded re-execution or explicit unavailable disposition |
| Nav / hub / entry route change | Single-owner hub PR; legacy disposition if demoting a page | Link check on hub + targets |

### Trigger checklist (paste into PR description)

```text
[ ] Owner role identified for each touched doc path
[ ] Canonical page metadata (Owner, Source, Last verified) updated if claims re-checked
[ ] Architecture / ADR / API / user surfaces updated per §9 product-change matrix
[ ] Examples/tutorials revalidated or disposition labeled
[ ] Drift claims opened or closed in DRIFT_AND_CLAIM_MATRIX (or linked issue/receipt)
[ ] check_docs.py run on affected roots (or full docs for release)
[ ] No expand-allowlist to hide P0/P1 on maintained pages
```

---

## 4. Generated-reference refresh

Generated material is **secondary discovery** only
([INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) lifecycle
`generated`; [GENERATION_AND_FRESHNESS.md](../api/GENERATION_AND_FRESHNESS.md)).

| Artifact class | Examples | Refresh trigger | Owner | Authority |
| --- | --- | --- | --- | --- |
| Optimizer / AST dumps | `docs/api/OPTIMIZERS_API_REFERENCE.md` | Script or walked module change; quarterly if cited | `api-reference` | Not public contract |
| Sphinx / TDFOL builds | `docs/tdfol/_build/` | RST/source change when build is required | domain + `api-reference` | Historical/generated; not product entry |
| Auto stubs | `docs/auto_generated_stubs/`, package stubs | Regeneration tasks only | generating lane | Discovery only |
| MkDocs / site output | `site/` | Provisioned build (IPFSDOC-098) | `release-docs` | Build evidence, not source |
| Quality / check reports | `QUALITY_REPORT.md` | Every release gate or major docs merge wave | `documentation-governance` | Evidence |

### Refresh procedure

1. Prefer **hand-maintained domain maps** (`docs/api/domains/`) for public API
   claims; regenerate dumps only to support discovery or drift detection.
2. Run the documented generator (see generation page); do not hand-edit
   “Do not edit manually” dumps.
3. After regeneration, run signature-drift / export checks described in
   [GENERATION_AND_FRESHNESS.md](../api/GENERATION_AND_FRESHNESS.md).
4. If generated output disagrees with tests or implementation, **fix the code
   citation on the canonical page**—do not “fix” by elevating the dump.
5. Record measurement time and commit when a dump is used as audit evidence.

---

## 5. Example revalidation

Maintained tutorials and high-traffic snippets are tracked in
[EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md).

| Cadence | Scope | Owner |
| --- | --- | --- |
| Every release | All ledger rows with `pass` or `mock` expected for offline CI | `user-journeys` + `release-docs` |
| Change-triggered | Any PR that edits a runnable fence or its imports | PR author |
| Semi-annual | Secondary examples not on the ledger | page Owner |

### Revalidation rules

1. **Execute** the bounded command (or extract-then-run pattern). Syntax-only
   `ast.parse` / `check_docs.py --checks python_syntax` is **hygiene**, not
   success proof.
2. Record **Tree** (git HEAD), exit code, expected evidence fields, and
   environment disposition (offline / network / native / service).
3. Allowed outcomes: `pass`, `fail`, `unavailable`, `mock`, `deferred`
   (provisioned gate). Prose “should work” is not evidence.
4. Failures open a **P0/P1 drift** row if the example is on a nav-spine journey;
   otherwise fix or demote the example before the next release.
5. Never put secrets, private keys, or live credentials in examples.

---

## 6. Drift triage

Primary inventory: [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md).
Quality findings: [QUALITY_REPORT.md](QUALITY_REPORT.md) from
`docs/maintenance/check_docs.py`.

### 6.1 Severity

| Priority | Meaning | SLA (target) |
| --- | --- | --- |
| **P0** | User-blocking falsehood on nav spine / install / first-run | Fix before release; block “docs current” claim |
| **P1** | High-impact wrong API, extra, command, or tool claim on maintained guides | Fix in current release train or exception with expiry |
| **P2** | Secondary surface, marketing, or non-spine guide | Next routine cadence |
| **P3** | Historical/status only | Disposition / archive; do not “fix” by rewriting history |

### 6.2 Triage workflow

```text
Discover (check_docs, claim audit, human/agent report)
    -> Classify (priority, claim kind, owner, canonical target)
    -> Disposition:
         rewrite-current | retarget-import | align-extra-name |
         intentional-migration (label only) | historical-only |
         open-product-defect (record only; do not change product in doc tasks) |
         exception (see §8)
    -> Verify offline
    -> Close row or supersede evidence page
```

### 6.3 Rules

1. Prefer rewriting **maintained guides** to match code; do **not** change
   product code to satisfy stale prose (program out-of-scope).
2. Do **not** expand allowlists to hide P0/P1 on maintained pages
   ([VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md)).
3. Intentional migration examples stay only when clearly labeled
   before-migration / legacy (fence tokens or path policy).
4. Product defects found during docs work are recorded as drift with owner
   **product lane**; docs describe **current** behavior until product remediates.
5. Authority order for resolving disputes:
   [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md).

### 6.4 Continuous detection

```bash
# Offline corpus checks (links, anchors, paths, modules, metadata, syntax)
python docs/maintenance/check_docs.py --root docs

# Focused lane while editing
python docs/maintenance/check_docs.py --root docs/architecture --checks links,anchors,metadata

# Release-style quality artifact
python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md
```

---

## 7. Release checks

Release documentation readiness is a **docs gate**, independent of optional
provisioned site build details owned by IPFSDOC-098
(`SITE_BUILD_AND_NAVIGATION.md`, `RELEASE_EVIDENCE.md` when published).

### 7.1 Mandatory offline release checklist

| # | Check | Command / artifact | Pass criterion |
| --- | ---: | --- | --- |
| 1 | Validator green enough for disclosed policy | `python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md` | No **unresolved** P0/P1 on **maintained** surfaces unless exception (§8) recorded; report published |
| 2 | Claim drift | Review [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) | No open P0; P1 either fixed or excepted with expiry |
| 3 | Example ledger | [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) | Spine tutorials revalidated on release tree or labeled deferred with provisioned plan |
| 4 | Install/entry claims | Install + getting started vs `pyproject.toml` | Python floor, extras, entry points match packaging |
| 5 | API freshness | Domain maps + [GENERATION_AND_FRESHNESS.md](../api/GENERATION_AND_FRESHNESS.md) | No known signature drift on advertised symbols |
| 6 | Architecture/ADR index | Domain map + [decisions/README.md](../architecture/decisions/README.md) | Accepted ADRs indexed; superseded linked |
| 7 | Disposition honesty | [LEGACY_DISPOSITION.md](LEGACY_DISPOSITION.md) | Historical pages not linked as current authority from hubs |
| 8 | Coverage gaps | [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) | P0 coverage gaps known and not silently claimed “done” |
| 9 | Exception register | §8 of this file | No expired open exceptions |
| 10 | Tree binding | `git rev-parse HEAD` | Release evidence (when present) cites commit/tree |

### 7.2 Optional / provisioned gates

| Gate | When | Notes |
| --- | --- | --- |
| MkDocs/Sphinx strict build | Provisioned env | Recorded in future release evidence; offline workers may defer |
| External link liveness | Provisioned network | Not required of `check_docs.py` |
| Live MCP/HTTP/native provers | Provisioned services | Example ledger `deferred` rows |

Do not mark the documentation program root complete without the provisioned
site build disposition required by the release evidence task.

---

## 8. Archive and disposition review

Maps and policy:

- Classification map: [LEGACY_DISPOSITION.md](LEGACY_DISPOSITION.md)
- Archive policy: [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) §10
- Package-local / generated authorities: [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](PACKAGE_LOCAL_DOCUMENTATION_MAP.md)

### 8.1 Cadence

| Activity | Cadence | Owner |
| --- | --- | --- |
| Disposition map refresh (new roots, new completion dumps) | After major doc waves; at least **semi-annual** | `archive-steward` + `documentation-governance` |
| Archive README honesty | **Annual** or when entry hubs change | `archive-steward` |
| Destructive moves (mass relocate/delete) | **Only** via reviewed dedicated tasks | Program / maintainer approval |

### 8.2 Disposition labels

| Label | Meaning | Maintenance action |
| --- | --- | --- |
| `current` | Canonical or navigated authority | Keep on routine/trigger cadence |
| `superseded` | Replaced by named page | Banner + hub pointer; schedule archive |
| `historical` | Audit trail only | No claim refresh; archive when approved |
| `duplicate` | Competing home | Consolidate; single owner |
| `review-needed` | Unclassified | Do not cite; queue for classification |
| `generated` | Machine output | Refresh per §4; never sole design authority |

### 8.3 Archive admission (summary)

1. Disposition is `historical` or `superseded` with known replacement (or
   explicit removed surface).
2. Banner or archive README states **not maintained** / **not authority**.
3. Prefer move + git history over rewriting historical files to new APIs.
4. Do not archive the only copy of an accepted ADR without index reachability.
5. Do not archive active canonical pages “to clean up” unfinished edits.
6. Protected program plan inputs are never archived or rewritten by workers.

Default deprecation window before archive: **one minor release or 30 days**,
whichever the maintainer sets ([INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) §9).

---

## 9. Exception expiry

Exceptions (waivers) are **time-bounded permissions** to ship with a known docs
defect or soft-fail. They are not permanent silence.

### 9.1 What may be excepted

| May exception | Must not exception |
| --- | --- |
| P1 on non-spine guide with workaround link | Silent P0 on install/getting-started/nav spine |
| Provisioned-only validation deferred with named follow-up | Expanding allowlists to hide maintained-page errors |
| Historical allowlisted findings under archive prefixes | Treating allowlisted archive noise as “fixed” |
| Temporary signature drift on non-advertised internal symbols | Advertising broken public imports as current |

### 9.2 Exception record (required fields)

Record exceptions in release evidence, a short appendix of the drift matrix, or
a dated section of this maintenance hub’s working notes. Each record needs:

| Field | Description |
| --- | --- |
| **ID** | `EXC-YYYYMMDD-NNN` |
| **Priority** | P0/P1/P2 of the waived finding |
| **Surfaces** | Paths / claim ids |
| **Reason** | Why ship is still safe |
| **Owner** | Role that must close the gap |
| **Opened** | ISO date |
| **Expires** | ISO date (**required**; default **30 days** or next minor release, whichever sooner) |
| **Exit criteria** | Concrete fix or re-measure command |
| **Status** | `open` / `closed` / `expired-escalated` |

### 9.3 Expiry rules

1. **Default expiry:** 30 days or next minor release, whichever is sooner.
2. **Renewal:** only with explicit re-approval and a new expiry; max two renewals
   without escalating to `documentation-governance` + domain owner.
3. **Expired open exceptions** become release blockers at the next release
   check (treat as unresolved P0/P1).
4. Closing requires verification evidence (commit, command, or disposition
   update)—not merely deleting the exception row.
5. Allowlist **prefix** changes in `check_docs.py` are code-reviewed exceptions
   with the same expiry discipline when they soft-fail maintained content.

---

## 10. Product changes must update architecture, ADR, API, and user docs

Any non-trivial product change is incomplete until the **documentation delta**
below is addressed. Prefer the same PR when the doc delta is small; otherwise
land a linked docs PR before release.

### 10.1 Change → documentation matrix

| Product change type | Architecture | ADR | API domain map | User / journey docs | Other |
| --- | --- | --- | --- | --- | --- |
| Behavior / algorithm in a domain | Update owning leaf (flow, failure, invariants) | New/supersede if **why** or boundary changes | Update listed symbols if public | Update journeys that teach the behavior | Tests cited as rank-1 authority |
| New public export / CLI / MCP tool | Entrypoints + domain leaf | Only if authority/boundary decision | **Required** domain page row | Getting started / user guide if user-facing | Tool registry docs |
| Removed or renamed public surface | Mark removed; fix inbound architecture links | Supersede if decision changes | Remove or mark compatibility | Fix imports/examples; deprecation banner | Drift row closed |
| Optional dependency / lazy install | Dependency and failure sections | ADR if policy changes | Optional flags on symbols | Install extras names | Packaging alignment |
| Security / authz / wallet | Trust architecture + security guides | Often required | Accurate side-effect/auth notes | No false “open” claims | Threat model |
| Packaging only | Usually none | Usually none | Entrypoints if scripts change | **Install / getting started required** | Extras matrix |
| Internal refactor, same contract | Maybe component list only | No | No if signatures stable | No if examples unchanged | Still run focused check_docs |
| Stub → complete or reverse | Failure/stub honesty | If completeness policy shifts | Stability labels | Journey prerequisites | Example ledger |

### 10.2 Definition of done (product + docs)

1. Code and tests land with truthful contracts.
2. Canonical architecture page still matches ownership and failure modes.
3. Binding design changes have an **accepted** or **superseding** ADR linked
   from the guide and [decisions index](../architecture/decisions/README.md).
4. Public callables appear on the correct [API domain](../api/README.md) page
   with stability and source paths—not only in generated dumps.
5. User-facing install/commands/examples match packaging and imports.
6. `Last verified` updated on pages whose claims were re-checked.
7. Drift/quality findings introduced by the change are fixed or excepted (§8).

### 10.3 Contributor path

Follow [DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md)
for page creation, metadata, diagrams, and restricted paths. Authority disputes
resolve via [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md).

---

## 11. v1 baseline and quality artifact index

All first-wave maintenance and quality artifacts under `docs/maintenance/`
(and closely related API generation policy). Link from release evidence and
from this hub; do not restate large matrices here.

### 11.1 Governance and baseline (v1)

| Artifact | Task / interface | Role |
| --- | --- | --- |
| [CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md) | `IPFSDOC-001` / `DocumentationBaseline@1` | Tree-bound inventory and counts |
| [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) | `IPFSDOC-002` / `DocumentationDriftMatrix@1` | Claim-level stale-surface matrix |
| [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) | `IPFSDOC-003` / `DocumentationPageContract@1` | Audiences, lifecycle, metadata, ADR, cadence, deprecation, archive |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | `IPFSDOC-004` / `DocumentationAuthorityMap@1` | Package-local, generated, competing authorities |
| [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md) | `IPFSDOC-005` / `DocumentationSourceAuthority@1` | Authority order when sources disagree |
| [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) | `IPFSDOC-005` / `DocumentationCoverageMatrix@1` | Domain × audience coverage status |
| [VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md) | `IPFSDOC-006` / `DocumentationValidator@1` (runbook) | How to run offline `check_docs.py` |
| [check_docs.py](check_docs.py) | `IPFSDOC-006` / `DocumentationValidator@1` | Deterministic offline checker |
| **This file** [README.md](README.md) | `IPFSDOC-097` / `DocumentationMaintenanceLifecycle@1` | Cadence, ownership, triage, release, exceptions |

### 11.2 Quality, examples, and disposition

| Artifact | Task / interface | Role |
| --- | --- | --- |
| [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) | `IPFSDOC-085` / `ExampleVerificationLedger@1` | Tutorial/snippet execution ledger |
| [LEGACY_DISPOSITION.md](LEGACY_DISPOSITION.md) | `IPFSDOC-094` / `LegacyDocumentationDisposition@1` | Legacy/duplicate/historical map |
| [QUALITY_REPORT.md](QUALITY_REPORT.md) | `IPFSDOC-096` / `DocumentationQualityReport@1` | Latest full-tree validator report |
| [../api/GENERATION_AND_FRESHNESS.md](../api/GENERATION_AND_FRESHNESS.md) | `IPFSDOC-082` / `APIGenerationAndFreshness@1` | API generate vs hand-maintain policy |

### 11.3 Related canonical surfaces (outside this directory)

| Artifact | Role |
| --- | --- |
| [../developer_guides/DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md) | Author workflow under the IA contract |
| [../architecture/DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md) | Product domain ownership |
| [../architecture/README.md](../architecture/README.md) | Architecture hub |
| [../architecture/decisions/README.md](../architecture/decisions/README.md) | ADR index |
| [../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md](../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md) | Architecture page template |
| [../architecture/decisions/ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md) | ADR template |
| [../api/README.md](../api/README.md) | API reference index |
| [../archive/README.md](../archive/README.md) | Archive warning and entry pointers |

### 11.4 Completion receipts and future release evidence

| Artifact | Role |
| --- | --- |
| [completion_receipts/](completion_receipts/) | Task-bound receipts (e.g. IPFSDOC-064, 074, 090–093, 095) |
| `SITE_BUILD_AND_NAVIGATION.md` (IPFSDOC-098, when published) | Provisioned MkDocs/Sphinx/nav disposition |
| `RELEASE_EVIDENCE.md` (IPFSDOC-098, when published) | Tree-bound release evidence closing the program wave |

### 11.5 How to re-bind evidence after tree change

1. Re-run baseline inventory commands from [CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md)
   or open a new dated evidence page—do not silently rewrite old measurements
   without stating a new commit.
2. Re-run `check_docs.py` and refresh [QUALITY_REPORT.md](QUALITY_REPORT.md).
3. Re-run spine rows in [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md).
4. Update open drift rows; close only with verification.
5. Cite the new `git rev-parse HEAD` in release evidence.

---

## 12. Operating calendar (summary)

| When | What | Primary owner |
| --- | --- | --- |
| Every docs-affecting PR | Change-triggered matrix (§3, §10); focused `check_docs` | PR author + page Owner |
| Every product release | Full offline release checklist (§7); example ledger; install claims | `release-docs` |
| Monthly (recommended) | Scan open exceptions for expiry; triage new QUALITY_REPORT P0/P1 | `documentation-governance` |
| Quarterly | Product entry, ops/security, API domain maps | respective owners |
| Semi-annual | Architecture leaves, developer guides, disposition map | `architecture`, `developer-experience`, `archive-steward` |
| On ADR accept/supersede | Index + linked architecture guide | `architecture` |
| On generator change | Regenerate dumps; refresh generation policy page | `api-reference` |
| Measurement events | Baseline / coverage / quality evidence pages | `documentation-governance` |

---

## 13. Validation

Offline checks that this maintenance contract remains discoverable and that the
validator tool still runs:

```bash
# This page present and non-empty; required vocabulary present
test -s docs/maintenance/README.md && rg -n 'owner|cadence|trigger|generated|drift|release|archive' docs/maintenance/README.md

# Peer baseline and quality artifacts exist
test -s docs/maintenance/INFORMATION_ARCHITECTURE.md
test -s docs/maintenance/SOURCE_AUTHORITY.md
test -s docs/maintenance/VALIDATION_RUNBOOK.md
test -s docs/maintenance/CURRENT_STATE_BASELINE.md
test -s docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md
test -s docs/maintenance/COVERAGE_MATRIX.md
test -s docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md
test -s docs/maintenance/LEGACY_DISPOSITION.md
test -s docs/maintenance/EXAMPLE_VERIFICATION.md
test -s docs/maintenance/QUALITY_REPORT.md
test -s docs/maintenance/check_docs.py

# Checker smoke
python -m py_compile docs/maintenance/check_docs.py
python docs/maintenance/check_docs.py --root docs/maintenance --checks metadata,links --fail-on never
```

---

## 14. Related pages

- [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) — page contract and lifecycle detail
- [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md) — authority order
- [VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md) — checker operation
- [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) — claim triage inventory
- [QUALITY_REPORT.md](QUALITY_REPORT.md) — latest quality scan
- [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) — example ledger
- [LEGACY_DISPOSITION.md](LEGACY_DISPOSITION.md) — archive disposition map
- [../developer_guides/DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md) — authoring workflow
- [../architecture/DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md) — code domain ownership
- [../api/GENERATION_AND_FRESHNESS.md](../api/GENERATION_AND_FRESHNESS.md) — generated API refresh

---

## 15. Non-goals

- Changing production package behavior to make historical docs true.
- Bulk deletion or relocation of archive trees without a reviewed task.
- Treating generated API dumps or completion reports as evergreen product
  authority.
- Editing protected program plan inputs under
  `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*`.
- Using mtime or green pytest alone as documentation freshness proof.
