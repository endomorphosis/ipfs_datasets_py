# Legal Corpora Federal Register + 50 States + DC Reindex Plan

Status: execution-ready supervisor plan  
Board namespace: `legal-corpora-reindex-v1`  
Task prefix: `LCR-`  
Goal prefix: `LCR-G`  
Target package: `ipfs_datasets_py`  
Target datasets: [`justicedao/ipfs_state_laws`](https://huggingface.co/datasets/justicedao/ipfs_state_laws) and [`justicedao/ipfs_federal_register`](https://huggingface.co/datasets/justicedao/ipfs_federal_register)  
Planning date: 2026-08-10  
Pinned remote baselines: state laws `42f0546acc7c6cd55627eaf51fb820d5613b9021`; Federal Register `720668ae016cc400916dda884c9005e03618edfa`  
Implementation base: `feature/uscode-sparse-graphrag` at `1ade8211360bee8ad8e26552c885e51eaf6d9fdb`

## 1. Outcome

Produce and publish two additive, immutable, directly queryable legal-corpus releases that:

1. contain a verified full scrape of the codified statutes for all 50 states and the District of Columbia;
2. contain a cutoff-bound, fully enumerated Federal Register corpus whose official API inventory and full-text acquisition frontier reconcile without silent pagination or date gaps;
3. account for every official-source discovery item in both corpora as admitted, duplicate, excluded, quarantined, or failed with a retry disposition;
4. use the working US Code `publicus-ir-graphrag/v2` methods: stable content/legal identity, bounded Parquet families, term-routed BM25, pinned embeddings, deterministic centroid routing, a legal/provenance graph, compact adjacency, immutable-Hub resolution, bounded direct-Hub queries, evaluation, staging, canary, rollback, and publication receipts;
5. correct the shortcomings found in the US Code execution rather than copying them;
6. preserve legacy remote artifacts and configurations for rollback while making each coherent v2 corpus the documented default;
7. upload the validated releases only to `justicedao/ipfs_state_laws` and `justicedao/ipfs_federal_register`, resolve both resulting immutable commit SHAs, redownload them, and prove that the public revisions—not merely local builds—satisfy all gates.

The executable objective heap is `legal_corpora_reindex.objectives.md`; the task DAG is `legal_corpora_reindex.todo.md`. The supervisor may add refinement goals and continuation tasks when scans find evidence gaps. Generated work must remain in this namespace, keep the same metadata contract, and preserve output ownership and dependency ordering.

## 2. Pinned baselines and why both rebuilds are required

### 2.1 State laws

The baseline audit on 2026-08-10 found:

- remote revision `42f0546acc7c6cd55627eaf51fb820d5613b9021`, last modified 2026-05-31;
- 2,116 repository files and 51 `STATE-XX.parquet` filenames, including DC;
- only 49 state summaries; CA and DC summaries are absent;
- the Hugging Face Viewer canonical config has 47,204 rows, all labeled `IA`;
- the Viewer embedding config has 17,338 rows over 51 jurisdictions, but most jurisdictions have only 1–104 rows; it has zero CID overlap with the canonical config and represents an older sample;
- the 51 remote per-jurisdiction canonical files total 212,103 rows but include obvious truncations such as GA=2, HI=4, IN=4, MS=1, WA=1, and WV=1, plus logical-identifier duplication and derived-index drift;
- the README claims 20,514 canonical rows, which conflicts with the Viewer and current combined Parquet;
- `manifest.json` contains absolute local paths and old sampled counts;
- the repo-tracked completed-state registry has only 47 jurisdictions and marks obviously truncated results such as NJ=1, GA=2, LA=4, CO=5, and MA=14 as `success`;
- a recoverable prior three-shard run under the local legal-scraper workspace reports much larger 51-jurisdiction outputs; it is comparison/salvage evidence only until the new provenance and frontier gates validate it;
- the existing refresh path can treat file existence and an unqualified `success` registry entry as completion, so filename coverage is not proof of corpus coverage.

The guardrail task must remediate the concrete unsafe paths, not merely route around them: `refresh_state_laws_corpus.py` currently defines `all` as 50 states with DC opt-in, merges by content CID before logical identity, rebuilds the combined Parquet from only the requested subset, and permits upload using requested-scope `is_complete`; `check_state_law_coverage.py` defaults to one row; `report_state_law_corpus_gaps.py` omits DC; and `processors/legal_scrapers/state_laws_scraper.py` treats a nonzero, error-free requested subset as full coverage. Regression tests must make each of those behaviors fail closed for a production candidate.

These contradictions make the current aggregate, indexes, manifests, embeddings, and graph unsuitable as the source of truth. Existing remote artifacts are evidence inputs only. They may seed differential audits, but no prior row or `success` flag is admitted without the new provenance and completeness gates.

### 2.2 Federal Register

The Federal Register baseline audit on 2026-08-10 found:

- remote revision `720668ae016cc400916dda884c9005e03618edfa`, last modified 2026-04-18, with 555 files and no dataset card declaring a coherent release contract;
- legacy root-level JSON-LD, one-row-group Parquet, raw-JSON shards, and GTE-small FAISS/metadata artifacts rather than a descriptor-complete v2 layout;
- `metadata.json` claims 993,703 deduplicated documents observed from 1994-01-01 through 2026-03-02 across 255 date ranges, with `include_full_text=false`;
- the local canonical Parquet has 993,708 rows, so the advertised count and materialized count already disagree;
- 358,455 baseline rows have empty text and most remaining text is only an abstract capped near 500 characters; every Parquet `source_url` is empty because the JSON-LD/Parquet conversion mismatched `url` and `sourceUrl`;
- the five extra local rows are recovery placeholders rather than Federal Register documents and must be quarantined; the official API already exposes at least 11,784 documents from 2026-03-03 through the planning cutoff on 2026-08-10;
- the generic inventory configuration leaves `publish_embeddings_files` empty and aliases new FAISS output onto legacy filenames; its quality gate is state-law-specific and does not fail publication on a degraded Federal Register audit;
- existing upload code can publish individual artifacts in separate commits, which cannot prove that corpus, sparse index, dense index, graph, manifest, and card belong to one immutable candidate.

The rebuild therefore starts from a fresh official inventory rather than trusting the old date-range registry. It pins a UTC observation cutoff before acquisition; enumerates FederalRegister.gov API result pages across non-overlapping date partitions; records the API total, page cursors, response hashes, document numbers, publication dates, correction/withdrawal relationships, agencies, citations, and typed dispositions; then acquires official HTML/XML/PDF or GovInfo text for every admitted document when available. A metadata-only item is never represented as full text: a non-body disposition is allowed only after the attempt ledger proves every official alternative has no usable body. An available or retrieved body that is not fetched, hash-verified, successfully parsed, and admitted remains unresolved/failed-final; exclusion or quarantine cannot turn that acquisition failure into publication success.

Federal completeness is cutoff-relative, not a claim that a changing daily register is permanently current. Its receipt must prove `enumerated = fetched + duplicate + excluded + quarantined + failed-final`, zero unresolved pages/date partitions, zero unexplained document-number gaps relative to the official inventory, and an explicit delta from the old 2026-03-02 endpoint through the new cutoff. Any failed-final item, upstream count drift during a partition, or unresolved body-text disposition creates refill work and prevents publication.

## 3. Definition of a full jurisdiction scrape

Uniform record-count thresholds are not authoritative because state code structures differ. A jurisdiction is complete only when its signed/hashed scrape receipt proves all of the following:

1. **Authority**: the acquisition used the cataloged official legislature, code publisher, reviser, or DC Council source. A secondary source is quarantine evidence unless an explicit source-authority exception is approved and documented.
2. **As-of identity**: the receipt records the source edition/release/as-of statement when exposed, observation time, start URLs, redirects, source software version, and response/content hashes. Observation time is never represented as legal effective date.
3. **Frontier closure**: every discovered title/code/chapter/section/pagination/download-bundle item is fetched or assigned a typed disposition. There are no unvisited continuation links, silently capped loops, sample limits, or unexplained gaps in expected official index units.
4. **Reconciliation**: `discovered = fetched + excluded + quarantined + failed-final`, with duplicates separately reconciled; admitted source units and canonical rows also reconcile. Failed-final must be zero for the publication cohort unless a legally nonexistent/excluded unit is supported by official evidence.
5. **Content quality**: admitted statutes contain stable jurisdiction/citation identifiers, non-placeholder text, official URLs, source hashes, and parse provenance. Navigation, login, error, anti-bot, synthetic, summary-only, and duplicated rows are excluded or quarantined.
6. **No truncation**: runtime caps are absent in full mode, checkpoint completion is based on the source frontier, partial checkpoints cannot promote success, and boundary probes cover the first and last official hierarchy units plus pagination/bundle totals.
7. **Independent checks**: official index totals or hierarchy manifests are compared where available; unexplained material regression from prior credible receipts fails closed. Count comparison is corroboration, not the sole completion proof.
8. **Replay and resume**: an interrupted run resumes without losing or duplicating verified units; a second manifest-only traversal produces the same closed frontier or an explicit upstream-change delta.
9. **Evidence safety**: secrets, cookies, local absolute paths, and private headers are absent from committed receipts and release artifacts.

All 51 receipts must pass. `--states=all` without DC is forbidden in the release runner; the canonical jurisdiction set is an exact, versioned constant containing 50 states plus `DC`.

## 4. Reuse of the US Code method for both corpora

### 4.1 Identity and corpus admission

Every admitted retrieval record in either corpus has:

- `entry_cid`: content address of the canonical retrieval record and primary key;
- `legal_id`: stable jurisdiction/code/title/chapter/section/subsection identity for state law, or stable document-number/publication identity for the Federal Register, independent of content version;
- `source_cid`: content address of normalized official-source evidence;
- jurisdiction, code family, title/chapter/part/section/subsection, edition/as-of fields, official URL, acquisition receipt ID, source checksum, parser version, and admission status;
- explicit unknown values for effective/amendment dates instead of inferred currentness;
- a deterministic parent path and text/token offsets for semantic chunks.

Duplicate citations are not collapsed across editions, appendices, notes, code families, or source units. Durable identity never depends on row position. Recovery material, secondary-source material, navigation pages, and failed parses remain in named quarantine/recovery configurations and cannot enter default retrieval counts.

### 4.2 Bounded release layout

The additive v2 tree is descriptor-driven:

```text
README.md
manifest.json
release_metadata.json
data/corpus/jurisdiction=XX/part-*.parquet
data/bm25/documents/jurisdiction=XX/part-*.parquet
data/bm25/postings/part-*.parquet
data/vectors/centroid-*-part-*.parquet
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/*.parquet
receipts/scrape/jurisdiction-XX.json
reports/admission.json
reports/coverage.json
reports/quality.json
reports/reproducibility.json
recovery/...
```

State corpus paths partition by jurisdiction; Federal Register corpus paths partition by publication year/month and document type, with a document-number locator and per-date-partition acquisition receipts. Both layouts obey the same descriptor and physical bounds without pretending those corpus-specific partitions are interchangeable.

Every physical corpus, BM25-document, vector, graph-node, graph-edge, adjacency, posting cell, and routing page contains at most 4,096 rows or pointers. Descriptors bind path, media/schema type, rows, bytes, SHA-256, logical CID, inclusive key range, and optional jurisdiction/centroid/routing data. Paths are relative and confined to the release root.

Large lineage is normalized and deduplicated by source document. It must not repeat full lineage payloads on every posting, fixing the multi-gigabyte US Code lineage mistake. Builders stream by jurisdiction and family, use external sorting where needed, checkpoint atomic work units, and never require the whole 51-jurisdiction corpus in memory.

### 4.3 Sparse, dense, and graph indexes

- **BM25**: a versioned legal tokenizer, field-aware lengths/weights, postings sorted by `(term, entry_cid)`, posting cells bounded to 4,096 pointers, term shards bounded to 4,096 rows, and a compact inclusive term-range router. BM25 never routes through vector centroids.
- **Vectors**: regenerate every admitted semantic chunk with pinned `thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd`, 384 dimensions, mean pooling, L2 normalization, a bound input contract, and deterministic seeds. Deterministic balanced spherical clustering recursively splits oversized clusters; a centroid contains at most 8,192 rows and at most two 4,096-row shards. The packaged physical paths must actually be centroid-specific; a fake global `centroid-000` layout is rejected.
- **Graph**: jurisdiction/code/title/chapter/section/subsection/note nodes; official source, edition, public act/session law, agency/office, citation, and unresolved-reference evidence; typed structural, citation, amendment, repeal, transfer, provenance, version, and bounded BM25-neighbor edges. Incoming and outgoing adjacency families are both mandatory and reconciled.
- **Queries**: immutable 40-hex Hub revision, descriptor verification before parsing, revision-scoped cache, safe relative paths, and explicit budgets for files, bytes, rows, centroids, nodes, edges, depth, and wall time. Supported modes are BM25, vector, hybrid, neighbors, bounded graph walk, and semantic graph walk, all with jurisdiction filters and safe fetch traces.

### 4.4 Corrections required from the US Code experience

Neither release can pass if it:

- duplicates lineage per posting;
- packages all vectors under a nominal single centroid or omits centroid routes;
- omits incoming/outgoing adjacency promised by its manifest;
- carries stale model/release digests into candidate or publication receipts;
- substitutes a fixture canary for an immutable live staging canary;
- creates a publication seal after public mutation;
- validates only generic files while missing required semantic families;
- materializes the full corpus/postings/graph in memory;
- retains legacy files without exposing coherent legacy Viewer configurations;
- hard-codes one acquisition vintage for all jurisdictions;
- treats the previous combined Parquet as a full scrape.

## 5. Goals, subgoals, tasks, and parallel lanes

The root goal is `LCR-G000`. Its child goals and subgoals are:

| Goal | Outcome | Tasks |
|---|---|---|
| `LCR-G010` | Pinned baseline, source authority, schema, and completeness contracts | `LCR-001`–`008` |
| `LCR-G020` | Full official-source acquisition for all jurisdictions | `LCR-009`–`023` |
| `LCR-G021` | Cohorts A–D | `LCR-009`–`012` |
| `LCR-G022` | Cohorts E–H | `LCR-013`–`016` |
| `LCR-G023` | Cohorts I–M, including DC | `LCR-017`–`021` |
| `LCR-G024` | Cross-cohort reconciliation and refill | `LCR-022`–`023` |
| `LCR-G030` | Canonical corpus, identity, chunking, and bounded layouts | `LCR-024`–`026` |
| `LCR-G040` | BM25, vectors, graph, adjacency, manifest, and locators | `LCR-027`–`032` |
| `LCR-G050` | Direct immutable-Hub retrieval and public API/CLI | `LCR-033`–`034` |
| `LCR-G060` | Gold set, quality, security, reproducibility, and local E2E | `LCR-035`–`038` |
| `LCR-G070` | Candidate build, staged upload, and immutable canary | `LCR-039`–`041` |
| `LCR-G080` | Authorized public upload and production-pin verification | `LCR-042`–`044` |
| `LCR-G090` | Compatibility, rollback, final evidence, and update operations | `LCR-045`–`047` |
| `LCR-G100` | Federal Register baseline, official inventory, schema, and gold-set contracts | `LCR-048`–`051` |
| `LCR-G110` | Cutoff-bound Federal Register acquisition, full text, identity, and corpus | `LCR-052`–`055` |
| `LCR-G120` | Federal Register BM25, vectors, graph, immutable-Hub query, and API/CLI | `LCR-056`–`060` |
| `LCR-G130` | Federal Register build orchestration, release packaging, evaluation, and staging canary | `LCR-061`–`064` |
| `LCR-G140` | Authorized Federal Register publication, dual-release verification, and final evidence | `LCR-065`–`069` |
| `LCR-G141` | Source rights, terms, attribution, redistribution admissibility, and fail-closed release binding | `LCR-077`–`079` |
| `LCR-G142` | Canonical live-evidence publication authority | `LCR-080` |
| `LCR-G143` | Complete authenticated live baseline provenance | `LCR-081` |
| `LCR-G144` | Evaluator-complete, time-trusted source-rights admission | `LCR-082` |
| `LCR-G145` | Resealed live source rights and publication authority | `LCR-083` |
| `LCR-G146` | Candidate-bound exact-51 live state scrape and protected-Hub mutation closure | `LCR-084` |
| `LCR-G147` | Complete, content-bound, verifier-time-trusted Federal full-text exhaustion | `LCR-085` |

The 51 jurisdictions are partitioned into file-disjoint scrape cohorts:

| Task | Jurisdictions |
|---|---|
| `LCR-009` | AL, AK, AZ, AR |
| `LCR-010` | CA, CO, CT, DE |
| `LCR-011` | FL, GA, HI, ID |
| `LCR-012` | IL, IN, IA, KS |
| `LCR-013` | KY, LA, ME, MD |
| `LCR-014` | MA, MI, MN, MS |
| `LCR-015` | MO, MT, NE, NV |
| `LCR-016` | NH, NJ, NM, NY |
| `LCR-017` | NC, ND, OH, OK |
| `LCR-018` | OR, PA, RI, SC |
| `LCR-019` | SD, TN, TX, UT |
| `LCR-020` | VT, VA, WA, WV |
| `LCR-021` | WI, WY, DC |

Each cohort uses an isolated output/checkpoint root, may parallelize only across different official domains, and owns only its state modules, cohort tests, and cohort receipt. Shared registry/build files are changed only by later integration tasks. A cohort with a failed jurisdiction does not report success. It emits evidence and the supervisor refines the corresponding acquisition subgoal into jurisdiction-specific repair tasks.

Lane ownership is the pinned supervisor runtime's SHA-256 rule: `int(sha256(full_task_id)[:8], 16) % 4`. State and Federal Register tasks share four total lanes so this program does not launch eight workers on an already busy host. `LCR-001`–`008` and `LCR-048`–`051` begin file-disjoint foundation work across all lanes. The merge queue serializes accepted commits; task dependencies serialize shared files. Preflight binds a clean paired `ipfs_accelerate_py` worktree at `3a33f78ee9689efa3ae8d87a43f0d1229e45f948` and verifies the same full-task-ID hash rule used by the runtime.

## 6. Refill and anti-stall policy

Both objective and codebase refill scans are enabled. Refill is triggered when open work drops below the configured floor, a cohort receipt contains a gap, an acceptance command exposes missing evidence, or a live remote canary differs from the candidate.

Generated work must:

- use the next available `LCR-NNN` identifier and a valid `LCR-GNNN` goal or child goal;
- include the pinned supervisor's canonical task identity, goal lineage, concrete implementation outputs, validation, acceptance evidence, and discovery evidence; optional board-specific fields may be absent from native renderer output;
- depend on or content-address the task/receipt that discovered the gap, so the origin remains auditable even when the native renderer has no explicit dependency;
- never edit the protected plan/config/initial-board contract directly from an implementation worktree;
- use unique outputs or an explicit dependency on their prior owner;
- preserve the terminal publication/final-evidence dependency chain.

The monitor declares the board unhealthy when any of these hold:

- master, lane supervisor, or managed daemon PID is dead or mismatched;
- heartbeat exceeds 120 seconds after startup grace;
- `blocked > 0`, even if processes remain alive;
- `ready == 0`, no active worker exists, and incomplete work remains;
- active work exceeds the hard timeout or its implementation log is stale, even when a provider PID remains live;
- a protected-path incident, duplicate supervisor, orphaned worker, malformed state, merge-queue error, or provider error is present;
- the branch tip and board state stop progressing beyond the configured threshold.

For a nonterminal idle board, the response order is: inspect evidence and dependency state; reconcile an already-produced merge/result; run objective/codebase refill; split an oversized or repeatedly failing task; retry within budget; create a typed operator task for genuine external requirements. Process liveness alone is never considered healthy. This directly avoids the prior US Code condition where all four lanes stayed alive with one blocked task, no ready task, and no worker.

The board validator is refill-aware: it seals the initial `LCR-000`–`LCR-069` population and invariants while accepting the native objective- and codebase-refill record shapes emitted by the pinned supervisor. For generated work it derives the authoritative hash lane, tolerates renderer-specific optional metadata, and still enforces namespace, safe outputs, valid references, acyclic dependencies, and ordered output ownership. It recomputes the live DAG/projection instead of requiring the launch-time ready set forever, so legitimate refill does not make restart preflight impossible. Refill mutation is lease-serialized, bounded by configured timeouts and findings limits, and triggered before complete drain; completion reconciliation remains enabled so liveness cannot substitute for goal evidence.

### 6.1 Monitored hardening continuations and controlled reseal

Successive live monitoring epochs exposed evidence gaps that the sealed launch projection could not safely defer until post-publication. The operator monitor therefore admitted `LCR-070`–`LCR-085` and deliberately resealed only the affected waiting dependencies. These tasks remain publication blockers through explicit phase requirements or goal-parent lineage; later generic refills remain valid without rewriting the initial population.

| Task | Fail-closed purpose | Gated descendants |
|---|---|---|
| `LCR-070` | Replace self-consistent baseline constants with authenticated live Hub responses, hashes, exact revisions, complete remote inventories, Viewer evidence, and local salvage inventory. | State and Federal staging |
| `LCR-071` | Execute one authenticated, non-fixture Federal inventory/full-text/corpus/index/graph/package/evaluation/API-CLI production run. | Federal staging |
| `LCR-072` | Bind the exact state candidate, immutable staging SHA, operation set, identity, previous pin, and manifest in a no-mutation seal created before main upload. | State public upload |
| `LCR-073` | Bind the corresponding Federal candidate and staging evidence in a no-mutation seal created before main upload. | Federal public upload |
| `LCR-074` | Provide the reusable phase- and target-specific policy gate every uploader must invoke before its first network mutation. | Both staging and main upload paths |
| `LCR-075` | Require per-document/per-authority full-text attempt, response-hash, retry, exhaustion, typed-disposition, and real-time cutoff/seal evidence. | Federal inventory and full-text acquisition |
| `LCR-076` | Reconcile BM25-derived lexical neighbors, graph edges, bounded outgoing/incoming adjacency, and key/locator parity. | Federal query and build orchestration |
| `LCR-077` | Define a source/content-scope rights schema and deny-on-unknown redistribution policy instead of copying the US Code card's generic `license: other`. | Both release contracts |
| `LCR-078` | Produce a current, source-by-source rights/terms/robots/attribution catalog and content-addressed compliance receipt for both corpora. | Both staging and main upload paths |
| `LCR-079` | Bind the exact compliance receipt into both release schemas, candidate manifests/cards, and the shared pre-mutation gate. | Both staging and main upload paths |
| `LCR-080` | Replace caller-asserted publication authority with a canonical runtime that independently derives and rechecks repository, task, receipt, manifest, principal, and seal evidence immediately before mutation. | Both staging and main upload paths |
| `LCR-081` | Reobserve complete authenticated Hub inventories, Viewer responses, Parquet counts/hashes, and local salvage evidence; reject sampled, missing, stale, or synthetic baseline success. | Both staging and main upload paths |
| `LCR-082` | Make every rights selector use the same canonical-license, robots/access, derivative/archive, identity, and trusted-time evaluator. | Both staging and main upload paths |
| `LCR-083` | Regenerate live source-rights evidence after hardening and reseal both schemas and the canonical mutation runtime to its exact digest. | Both staging and main upload paths |
| `LCR-084` | Reobserve every state/DC official frontier, bind exact-51 rows/keys/content to the candidate, and route every protected-Hub operation through one payload-bound runtime. | All four protected-repository mutation phases |
| `LCR-085` | Replace the merged Federal full-text fail-open with an exact authority-by-format ledger, verified body-byte binding, v2 identity, and explicit zero-skew verifier time. | Federal acquisition, staging, and main upload paths |

The controlled reseal also makes `LCR-058` depend on Federal BM25, attaches `LCR-060` to the full-live publication ancestry, requires the two seal receipts before either main-branch mutation, and makes both release-card assemblers depend on the source-rights gate. Source authority is not redistribution authority: each admitted source/content scope must distinguish government text from annotations, editorial matter, layout, and database presentation; record current terms/robots/attribution evidence and a legal basis; quarantine unknown or prohibited scopes; and bind the resulting receipt digest into cards, manifests, schemas, and every pre-mutation decision. Staging and main authorization are separate contracts: staging requires its complete candidate/live-evidence receipt set but cannot require the post-canary main seal; main requires the immutable staging canary plus its corpus-specific prepublication seal. Registry lists are informational unions and never authorize a mutation. For each phase, the gate verifies the full dependency ancestry of its named predecessors and denies while any nonterminal task numbered `LCR-077` or later belongs to that phase's goal-parent lineage; unknown or unscoped generated lineage denies every phase. The validator rejects any regression in the exact controlled-reseal titles, goals, dependencies, outputs, validation/acceptance contracts, required receipt paths, phase-specific gate sets, dynamic-refill policy, or terminal ancestry.

Control-plane changes are never applied silently during active implementation snapshots. A protected-path fence must latch, the master must stop, worktrees and incident evidence must be preserved, the changed commits must be explicitly approved through the proof-checked clearance command, and clean preflight must pass before a fresh launch. This procedure was exercised during the first monitoring epoch rather than bypassing the fence.

## 7. Publication authorization and safe upload

This plan records the 2026-08-10 operator request to upload both completed datasets as authorization to perform additive updates to exactly `justicedao/ipfs_state_laws` and `justicedao/ipfs_federal_register`. It does not authorize deletion, force-push, history rewrite, visibility change, credential rotation, or publication to another repository.

Publication proceeds only after all earlier dependencies pass:

1. build a descriptor-complete candidate in an isolated local release root;
2. upload additively to an explicit staging branch/revision;
3. resolve its immutable SHA, redownload it through the public/authorized Hub transport, verify every descriptor, run Viewer/schema checks, and execute coverage/retrieval canaries;
4. generate the publication authorization receipt from the exact final manifest and staging SHA;
5. upload the same manifest-bound artifact set to the public target without deleting legacy paths;
6. resolve the new public SHA and repeat full remote verification;
7. write rollback receipts preserving the previous public pins `42f0546acc7c6cd55627eaf51fb820d5613b9021` and `720668ae016cc400916dda884c9005e03618edfa`.

Credentials come from the environment only and never enter argv, prompts, logs, receipts, or Git. Missing credentials park only the publication task with a typed external-requirement receipt; they do not permit false completion. Build, scrape, reindex, and staging-safe validation continue independently.

## 8. Acceptance gates

The root goal completes only when the following are true at the two manifest-bound immutable public revisions:

- the exact jurisdiction set equals the 50 postal state codes plus `DC`—no missing or extra values;
- 51 official-source receipts pass authority, frontier closure, reconciliation, content, truncation, resume, and safety gates;
- every discovered source item and every normalized row has one disposition; aggregate counts reconcile with per-jurisdiction receipts and Parquet metadata;
- default corpus, BM25, vectors, graph, incoming/outgoing adjacency, locators, manifests, and recovery configurations are present and mutually consistent;
- every required physical row/pointer bound is at most 4,096; centroid bounds are at most 8,192 rows/two shards and physical placement matches routing metadata;
- all admitted rows have valid `entry_cid`, `legal_id`, `source_cid`, jurisdiction, official provenance, and non-placeholder text; no duplicate primary keys exist;
- every admitted semantic chunk has exactly one embedding in the declared vector space and a valid direct locator;
- BM25 differential scoring, vector recall, hybrid relevance, graph integrity, adjacency inversion, sparse remote I/O, cache replay, and jurisdiction filters pass sealed evaluations;
- two clean builds have identical logical CIDs, routes, counts, and manifest digest under pinned tooling; permitted byte differences are explained and descriptor-bound;
- tamper, traversal, symlink, digest, decompression, row-count, resource-budget, mutable-revision, secret-redaction, and partial-checkpoint tests fail closed;
- the Dataset Viewer exposes coherent documented configurations and the default combined config contains all 51 jurisdictions, not a single-state overwrite;
- the immutable public redownload and query canary pass, and the publication/rollback/final evidence receipts name the exact public SHA.
- the Federal Register cutoff, official API partition/page inventory, document-number set, body-text dispositions, corpus admission ledger, and old-baseline delta reconcile exactly with no unresolved partition or failed-final item;
- both public revisions use the same pinned embedding contract and shared artifact semantics where interoperability is claimed, while corpus-specific identity, authority, and graph-edge semantics remain explicit;
- a combined terminal receipt binds both manifests, both prior pins, both new public SHAs, both remote canaries, and every unresolved-gap set as empty.

No task may redefine "full scrape" downward to make the board green. A discovered gap creates more work; it is not converted into success.
