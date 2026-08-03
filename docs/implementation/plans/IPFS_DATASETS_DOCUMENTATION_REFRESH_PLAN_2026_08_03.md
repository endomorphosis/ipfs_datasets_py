# IPFS Datasets Documentation Renewal and Architecture Guide Plan

**Date:** 2026-08-03
**Program:** `ipfs-datasets-documentation-v1`
**Task prefix:** `IPFSDOC-`
**Working scope:** `docs/` in the `ipfs_datasets_py` repository
**Durable goals:** [IPFS_DATASETS_DOCUMENTATION_REFRESH.objectives.md](IPFS_DATASETS_DOCUMENTATION_REFRESH.objectives.md)
**Executable board:** [IPFS_DATASETS_DOCUMENTATION_REFRESH.todo.md](IPFS_DATASETS_DOCUMENTATION_REFRESH.todo.md)

## 1. Outcome

Renew the documentation so it describes the repository that exists now, then
add an architecture corpus that lets both developers and implementation agents
answer four questions without reverse-engineering the whole tree:

1. What are the supported product surfaces and how do I use them?
2. Which subsystem owns a responsibility, contract, or source of truth?
3. Why was a bespoke design chosen, and which invariant must a change retain?
4. How do I extend or operate the system and prove that the change is correct?

The program is intentionally evidence-led. Documentation is not considered
current because a page exists or reads plausibly. Each guide must be grounded
in live code, tests, configuration, packaging metadata, or a reviewed decision
record, and it must carry a reproducible validation receipt.

## 2. Why this program is needed

The repository has changed substantially since the last broad user-documentation
refresh. At planning time:

- `docs/` contains roughly 1,473 Markdown files and 1,834 files overall, which
  makes search useful but makes authority and navigation difficult to infer.
- Excluding obvious archives and generated builds still leaves roughly 913
  active Markdown pages. The root contains 117 Markdown files although the
  existing documentation README says the reorganization reduced it to 27.
- The current MkDocs navigation exposes only 7 of those 1,473 Markdown pages;
  41 of 68 maintained documentation directories also lack the README/index
  required by the repository's own convention.
- The main documentation landing page still labels February 2026 capabilities
  as the latest features and contains point-in-time counts and completion
  claims that cannot be treated as current evidence.
- `installation.md` still describes Python 3.7-era support and nonexistent
  extras, while current project metadata requires Python 3.12 and defines a
  capability-specific extras model. `user_guide.md` contains at least 18 direct
  references to removed modules, and a conservative scan found hundreds of
  candidate missing-module references across maintained pages that require
  classification rather than blind replacement.
- The existing architecture index primarily covers GitHub Actions, historical
  submodule migration, and an older MCP catalog. It does not explain the full
  current package topology or the design relationships among processing,
  content addressing, retrieval, logic, proof, policy, and MCP runtime layers.
- The old submodule architecture describes two obsolete dependencies while the
  current `.gitmodules` defines ten entries. Six useful MCP ADRs already live
  under package-local documentation, illustrating source-of-truth fragmentation
  that must be reconciled rather than duplicated.
- The package now has large bespoke domains under `processors/`, `logic/`,
  `mcp_server/`, `optimizers/`, `knowledge_graphs/`, `vector_stores/`,
  `web_archiving/`, `p2p_networking/`, `audit/`, and related packages.
- Packaging now exposes many capability-specific optional dependency groups and
  a lazy theorem-prover installation path. Import-time behavior, fallbacks, and
  optional capability discovery therefore need to be explained explicitly.
- Recent work introduced or expanded canonical IR families, semantic round-trip
  compilation, external prover boundaries, proof and attestation profiles,
  legal/security admissibility, invocation intent, policy enforcement, and
  MCP/P2P runtime surfaces. Historical completion plans are not a substitute
  for stable product architecture guides.
- Since the approximate March 2026 durable-documentation baseline, the audit
  found roughly 4,130 commits and very large code/test growth. Much of the
  accompanying documentation growth consists of plans, evidence, and status
  reports rather than navigated durable guidance.

These observations are planning inputs, not permanent product claims. The
first execution wave re-measures them against the supervisor worktree and
publishes the authoritative baseline.

## 3. Documentation principles

### 3.1 Sources outrank prose

Use this authority order when sources disagree:

1. executable tests and schemas that define a contract;
2. current implementation and packaging/configuration metadata;
3. current operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides;
6. historical plans, completion reports, generated summaries, and archive
   material.

A task encountering a disagreement must document the discrepancy. It must not
silently choose the most convenient source or restate an old completion claim.

### 3.2 Distinguish kinds of truth

Every new architecture guide must distinguish, where applicable:

- discovery from availability and availability from successful capability
  probing;
- syntax validation from semantic validation, policy admission, satisfiability,
  theorem proof, and runtime authorization;
- declaration identity from derived artifacts, observations, caches, and
  execution receipts;
- a preferred backend from an optional backend, graceful degradation, and a
  behaviorally incomplete stub;
- a canonical surface from a compatibility alias or deprecated path;
- user-visible controls from the authority to perform an external effect.

### 3.3 Explain decisions, not only components

Component guides describe what exists and how data/control flows through it.
Architecture decision records explain why the boundary exists, alternatives
that were rejected, consequences, and invariants future work must preserve.

### 3.4 Optimize for people and agents

Pages must have stable headings, explicit owners, concrete code paths, input and
output contracts, failure modes, extension points, and focused validation
commands. Avoid hidden prerequisites, unexplained acronyms, and claims whose
only evidence is another summary document.

### 3.5 Preserve history without making it canonical

This program does not mass-delete the existing 72 MB documentation tree.
Historical and superseded material receives a disposition and a route to a
canonical page. Destructive archive moves require a separately reviewed task;
the v1 board creates the map and navigation before any such cleanup.

## 4. Scope

### In scope

- Inventorying and classifying all documentation under `docs/`.
- Refreshing installation, configuration, getting-started, user, developer,
  testing, deployment, security, and navigation guides.
- Creating architecture guides and ADRs for the current bespoke system.
- Creating source-grounded API/domain maps and verified examples.
- Defining freshness, ownership, evidence, deprecation, and review policy.
- Producing link, example, claim, and coverage audits inside `docs/maintenance/`.
- Keeping all implementation-task output inside `docs/`.

### Out of scope

- Changing production behavior to make an old document true.
- Moving or renaming production packages.
- Changing public APIs, dependency resolution, registries, schemas, policy, or
  proof authority.
- Rewriting historical plans or completion receipts as if they were current
  architecture documentation.
- Bulk deletion or relocation of old pages before a reviewed disposition map.
- Treating generated API listings as a replacement for conceptual and decision
  documentation.

If source inspection reveals a product defect, the documentation task records
it in the drift matrix and documents current behavior. Product remediation is a
separate program.

## 5. Goal and subgoal structure

```text
IPFSDOC-G000  Truthful, navigable, decision-rich documentation system
|-- IPFSDOC-G010  Measured baseline and documentation governance
|   |-- IPFSDOC-G011  Inventory, drift, authority, and coverage baseline
|   `-- IPFSDOC-G012  Information architecture, style, ownership, and lifecycle
|-- IPFSDOC-G020  Current product entry and user journeys
|   |-- IPFSDOC-G021  Installation, configuration, optional capabilities
|   `-- IPFSDOC-G022  Python, CLI, MCP, and workflow journeys
|-- IPFSDOC-G030  System architecture and durable design rationale
|   |-- IPFSDOC-G031  Context, domains, data flow, and integration boundaries
|   `-- IPFSDOC-G032  ADR corpus and cross-cutting invariants
|-- IPFSDOC-G040  Processing, storage, and distribution architecture
|   |-- IPFSDOC-G041  Ingestion, processors, conversion, multimedia, web archives
|   `-- IPFSDOC-G042  IPFS/IPLD, storage, caching, P2P, and publication
|-- IPFSDOC-G050  Retrieval and knowledge intelligence architecture
|   |-- IPFSDOC-G051  Embeddings, vector stores, and search
|   `-- IPFSDOC-G052  Knowledge graphs, GraphRAG, and optimizers
|-- IPFSDOC-G060  Logic, proof, and governed authorization architecture
|   |-- IPFSDOC-G061  IRs, compilers, round trips, and prover boundaries
|   `-- IPFSDOC-G062  Legal/security constraints, attestations, and authority
|-- IPFSDOC-G070  MCP and runtime surfaces
|   |-- IPFSDOC-G071  Server, tool lifecycle, registries, dispatch, transports
|   `-- IPFSDOC-G072  Policy, audit, observability, and operations
|-- IPFSDOC-G080  Developer and implementation-agent enablement
|   |-- IPFSDOC-G081  Repository map, extension recipes, and testing
|   `-- IPFSDOC-G082  Agent context, invariants, troubleshooting, and handoff
|-- IPFSDOC-G090  API reference, examples, and tutorials
|   |-- IPFSDOC-G091  Domain/API inventories with provenance
|   `-- IPFSDOC-G092  Executable journeys and example verification
|-- IPFSDOC-G100  Operations, security, and reliability guidance
|   |-- IPFSDOC-G101  Deployment, performance, diagnostics, and recovery
|   `-- IPFSDOC-G102  Threat boundaries, audit, provenance, and secrets
`-- IPFSDOC-G110  Navigation, legacy disposition, quality gates, and release
    |-- IPFSDOC-G111  Canonical indexes, glossary, and legacy routing
    `-- IPFSDOC-G112  Cross-guide validation and freshness closure
```

The objective heap defines evidence and completion policy for every node. The
task board is the supervisor-executable projection and is not the source of
durable intent.

## 6. Target documentation architecture

The program converges on the following canonical areas without requiring an
immediate physical move of every legacy page:

```text
docs/
|-- index.md                         # audience-oriented product entry
|-- getting_started.md              # shortest verified first success
|-- installation.md                 # base + capability installation
|-- configuration.md                # precedence and environment reference
|-- user_guide.md                    # supported user journeys
|-- developer_guide.md               # contributor entry and repository map
|-- architecture/
|   |-- README.md                    # architecture hub
|   |-- SYSTEM_CONTEXT.md
|   |-- DOMAIN_MAP.md
|   |-- END_TO_END_DATA_FLOW.md
|   |-- DEPENDENCY_AND_INITIALIZATION.md
|   |-- INTEGRATION_BOUNDARIES.md
|   |-- processing/
|   |-- storage/
|   |-- retrieval/
|   |-- knowledge/
|   |-- logic/
|   |-- mcp/
|   |-- runtime/                     # agent supervisor and Profile G
|   |-- WALLET_TRUST_AND_PRIVACY.md
|   `-- decisions/                   # ADRs + decision index
|-- developer_guides/
|   |-- README.md
|   |-- FOR_AGENTS.md
|   |-- EXTENSION_RECIPES.md
|   |-- TESTING_AND_EVIDENCE.md
|   `-- TROUBLESHOOTING.md
|-- guides/
|   |-- operations/
|   `-- security/
|-- api/
|   |-- README.md
|   `-- domains/                     # source-grounded domain references
|-- tutorials/
|-- maintenance/
|   |-- README.md
|   |-- CURRENT_STATE_BASELINE.md
|   |-- DRIFT_AND_CLAIM_MATRIX.md
|   |-- COVERAGE_MATRIX.md
|   |-- LEGACY_DISPOSITION.md
|   |-- EXAMPLE_VERIFICATION.md
|   `-- RELEASE_EVIDENCE.md
`-- implementation/plans/           # protected program inputs
```

Names in this tree are targets from the executable board. Existing equivalent
pages are reviewed before a new canonical page is created. When a maintained
page already owns the concern, the task refreshes or routes to it instead of
creating a competing authority.

## 7. Delivery waves and parallelism

### Wave 0: Freeze plan inputs

The human plan, objective heap, and todo board are committed together and
passed to all lanes as protected paths. Workers may read but never update task
status or alter the program contract.

### Wave 1: Establish evidence and governance

`IPFSDOC-001` through `IPFSDOC-005` can use separate files and mostly execute
in parallel. Their outputs give later writers a common inventory, source
policy, terminology, and page template. `IPFSDOC-006` joins those artifacts
into a coverage matrix.

### Wave 2: Write architecture leaves in parallel

System, processing, storage, retrieval, knowledge, logic, MCP, security, and
operations guides use exclusive output files. Tasks are deliberately divided
by domain so 4-8 workers can inspect different code and tests concurrently
without sharing a Markdown target.

### Wave 3: Refresh audience guides and references

Installation/user/developer guides depend on the relevant architecture leaves
so examples do not invent interfaces. API-domain pages and tutorials remain
separate by package family and can run concurrently.

### Wave 4: Integrate navigation and legacy routing

Single-owner tasks update shared hubs (`docs/index.md`, `docs/README.md`,
`docs/architecture/README.md`, `docs/DOCUMENTATION_INDEX.md`) after leaf pages
have landed. The legacy disposition task records superseded/duplicate/current/
historical status without bulk deletion.

### Wave 5: Release evidence

Final tasks run link checks, code-fence/example checks, canonical-page coverage,
claim review, and a documentation build when the optional build tool is
available. A missing optional MkDocs binary is recorded as unavailable and
does not erase the deterministic checks; release still requires a successful
site build in a provisioned environment.

## 8. Supervisor execution contract

Each `## IPFSDOC-###` entry includes:

- exactly one durable `Goal id` and a declared dependency set;
- status, schedulability, priority, track, bundle, and parallel lane;
- exclusive `Outputs` and `Predicted files` under `docs/`;
- preconditions, effects, interfaces, resource and token estimates;
- a conflict policy and explicit concurrent siblings;
- a focused validation command and acceptance criteria;
- evidence expectations that distinguish source inspection from proof.

### Shared-file ownership

The following files are hot and have one late owner each:

| Shared file | Exclusive task |
| --- | --- |
| `docs/architecture/README.md` | `IPFSDOC-090` |
| `docs/api/README.md` | `IPFSDOC-091` |
| `docs/developer_guide.md` | `IPFSDOC-092` |
| `docs/installation.md`, `docs/configuration.md` | `IPFSDOC-093` |
| `docs/getting_started.md`, `docs/user_guide.md` | `IPFSDOC-094` |
| `docs/index.md`, `docs/README.md`, `docs/DOCUMENTATION_INDEX.md` | `IPFSDOC-100` |
| `docs/GLOSSARY.md` | `IPFSDOC-101` |

All earlier leaf tasks write new, exclusive files. Workers must not opportunistically
fix shared navigation while producing a leaf guide.

### Completion policy

Tasks use manual completion after fresh validation. A worker commit, a generated
page, or a status line is not completion evidence by itself. The supervisor may
retry implementation and validation failures, but it must not weaken acceptance
criteria or edit the protected plan inputs to make progress appear unblocked.

## 9. Blocker-prevention strategy

The launch profile is designed to avoid the common ways a documentation
supervisor stalls:

1. **Clean dedicated worktree and branch.** The program does not share the
   existing dirty submodule checkout or its unrelated nested-submodule change.
2. **Protected plan inputs.** Worker lanes cannot rewrite their own queue or
   completion policy.
3. **Strict deterministic shards.** Parallel lanes do not claim the same task;
   a shared merge queue serializes target-branch integration.
4. **Narrow file ownership.** Ready tasks use different Markdown paths. Shared
   indexes are late dependencies with one owner.
5. **No objective or codebase refill during v1 execution.** The reviewed board
   is already comprehensive; automatic refill could append unreviewed scope and
   mutate protected inputs.
6. **Retry limits and stall watchdog.** Repeated provider, validation, or merge
   failures become visible state rather than infinite silent retries.
7. **Source-only dependencies.** Early tasks do not require network access,
   external services, GPUs, native theorem provers, or a running MCP daemon.
8. **Optional-tool honesty.** Missing MkDocs or optional backends are recorded
   and deferred to a provisioned release gate, while deterministic validations
   continue.
9. **Health verification after launch.** A launch is accepted only when every
   supervisor and managed daemon has a live PID, fresh heartbeat/status, a
   parsed nonempty board, and no missing-dependency or dirty-target blocker.

## 10. Validation model

### Per-page validation

- The page exists and is nonempty.
- Required purpose, audience, source, ownership, flow, failure, extension, and
  validation sections are present where applicable.
- Named modules, commands, config keys, and paths resolve on the current tree.
- Examples are syntax-checked or executed with a bounded offline command.
- Links resolve locally or are explicitly classified as external.
- Point-in-time counts include provenance and date or are removed.

### Cross-corpus validation

- Every top-level production domain has a canonical map entry.
- Every architecture page appears in the architecture hub.
- Every canonical user/developer journey routes from the main index.
- Every old root-level summary has a current, superseded, historical, duplicate,
  or review-needed disposition.
- Glossary terms are used consistently for IR, CID, proof, policy, capability,
  tool, transport, receipt, provenance, and fallback concepts.
- No maintained guide claims that discovery, validation, policy approval, or a
  model result provides stronger authority than the implementation does.

## 11. Definition of done

The root objective closes only when:

- all child goals have fresh current-tree evidence;
- the drift and coverage matrices show no unresolved P0/P1 documentation gap;
- the canonical indexes route every maintained page and major production
  domain;
- architecture guides describe domain ownership, end-to-end flows, extension
  points, failure modes, and the rationale behind bespoke boundaries;
- installation and examples are reproducible for base and capability-specific
  use cases;
- developers and agents have explicit invariants and change recipes;
- deterministic link/example/claim checks pass and a provisioned site build
  succeeds;
- the release evidence identifies the repository commit, documentation tree,
  commands, results, known limitations, and reviewer disposition.

Until then, completed leaf tasks are useful progress but do not prove the
documentation corpus is current as a whole.
