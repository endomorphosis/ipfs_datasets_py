# Open US Law exact-51 sparse GraphRAG reindex plan

## Outcome

Build, validate, publish, and operate an exact-51 statutory corpus covering all 50 states and the District of Columbia. The release will:

- use fresh, exhaustive, official-source evidence for every jurisdiction;
- admit the existing Hugging Face Bucket only as a reconciled seed snapshot, never as proof of completeness or freshness;
- regenerate every dense vector with real `thenlper/gte-small` inference at revision `17e1f347d17fe144873b1201da91788898c639cd`;
- build a field-weighted BM25 inverted index, a legal/provenance graph, and a postings-backed lexical graph;
- cluster normalized vectors with deterministic balanced spherical k-means;
- cap every physical vector, corpus, BM25, graph, and route page at 4,096 rows or pointers where the schema defines that bound;
- sort vector shards by descending cosine similarity to their centroid and stable `entry_cid`;
- route sparse lexical retrieval by BM25 term ranges and dense retrieval by embedding centroids;
- traverse graph frontiers with embeddings through an explicit entry-to-vector-shard locator;
- answer direct Hugging Face queries by fetching only manifests, routing metadata, selected shards, and final corpus rows;
- publish an immutable Dataset revision and an additive content-addressed Bucket mirror without overwriting or deleting the raw snapshot.

The authoritative public Dataset target is `justicedao/open-us-law-sparse-graphrag`. It did not exist when this plan was sealed, so creation is part of the authorized additive publication task. The source and optional mirror Bucket is `justicedao/open-us-law-bucket`.

## Observed baseline on 2026-08-13

The live Bucket was observed as public, 1,134,269,198 bytes, and 107 objects. It contains 103 Parquet objects plus four control/media objects. It contains no BM25, vector, centroid, graph, adjacency, locator, or routing artifacts.

The current statute objects cover federal law, Puerto Rico, and only 49 of the required state/DC jurisdictions. Georgia and North Carolina statutes are absent. DC statutes are present. The default exact-51 seed contains 1,904,919 rows across those 49 state/DC jurisdictions. Federal, Puerto Rico, and constitutions are useful corpora but are not members of the exact-51 default state-statute acceptance set.

The Bucket README identifies snapshot `v2026.07`, observed from sources on 2026-07-21, and says Georgia and North Carolina were withdrawn on 2026-08-12 because navigation and footer contamination was embedded in section bodies. Its checksum manifest is stale: it still lists the withdrawn Georgia and North Carolina statute files, and at least one live federal-constitution object differs from the descriptor. The current `SHA256SUMS.json` bytes had SHA-256 `20c7f327d38810da9168e53dd90babcae25fb634114e3cebbbe201c4726306b0`; that digest identifies the stale file, not a valid source snapshot.

A read-only recursive inventory produced a provisional canonical object-list digest `ef84263ab604460297fadfefa4268aee974b1ba1ed914188cc591df62e6ff65b` over sorted path/type/size/Xet-identity/upload-time records. OUL-001 must reobserve and define the canonical algorithm before this value can authorize downstream work, because Buckets are mutable and non-versioned.

The source admission audit classifies:

- blocked until clean official replacement: GA and NC;
- quarantine or official reacquisition required: AR, MS, NM, NV, OR, TN, and WY;
- per-row source-link repair or typed quarantine required: AK, AL, CA, LA, MA, and NJ;
- candidate seed only, pending fresh frontier reconciliation: the other 36 required jurisdictions.

All 51 local scraper adapters import and register, but existing completion ledgers and cohort reports are not sufficient evidence. Several old counts are implausibly small, and available cohort receipts are two-row fixtures. No jurisdiction is deemed production-complete merely because a filename exists, a row count is nonzero, or an earlier task says completed.

## Architectural decision: Bucket input, immutable Dataset authority

A Hugging Face Bucket is mutable object storage and has no Git commit history. It cannot supply the 40-hex immutable revision required by the reused USCode resolver. The release therefore has two coordinated representations:

1. The Dataset repository is the authoritative query and publication surface. Every production query pins an exact 40-hex commit. The Dataset card exposes explicit Viewer-safe configurations and excludes quarantine/recovery data from the default split.
2. The Bucket mirror stores the identical sealed release under `releases/<manifest_sha256>/...`. Those paths are immutable by policy. A tiny `LATEST.json` pointer may be updated only after the complete prefix is uploaded and redownload-verified; clients never trust the pointer without verifying the referenced manifest digest.

No task may overwrite the 103 raw Parquet objects, use `sync --delete`, remove a release prefix, rewrite Dataset history, force-push, or change visibility. Raw `v2026.07` objects remain legacy provenance evidence.

## Completeness and admission contract

“Full scrape” means all of the following for each of the 50 states and DC:

- exact jurisdiction and code-family identity;
- an allowed official host/path and a source-rights/attribution decision;
- edition, legal as-of time, and independent observation time;
- immutable request, response, and admitted-body hashes;
- exhaustive bundle, table-of-contents, pagination, and continuation enumeration;
- boundary probes and replayed frontier digest equality;
- `discovered = fetched + excluded + quarantined + failed_final`;
- `failed_final = 0`;
- no sample limit, runtime cap, fixture transport, synthetic receipt, or partial-checkpoint promotion;
- logical-key uniqueness and an explicit current/history disposition;
- navigation/footer/placeholder rejection and minimum usable statutory text;
- source CID, entry CID, acquisition receipt CID, and rights receipt CID;
- typed evidence for every exclusion and quarantine.

The aggregate gate requires exact set equality with the 51-code allowlist, DC exactly once, no PR/federal rows in the default configuration, deduplicated union/count/hash equality, and key parity from canonical corpus through BM25, vectors, graph, locators, and release descriptors.

The existing state-laws supervisor may contribute live receipts, but OUL-006 treats them as untrusted inputs. It validates their exact source projection, body bytes, frontier closure, and identity before reuse and uses jurisdiction leases so the OUL board does not duplicate a live scrape. Invalid, incomplete, fixture, stale, or conflicting evidence causes a targeted repair task or a new leased scrape.

## Canonical corpus and identity

Every admitted statutory section and chunk carries:

- `jurisdiction_code`, code family, edition, title/chapter/section/subsection hierarchy, status, effective/as-of metadata;
- canonical `legal_id`, `entry_cid`, `source_cid`, `text_cid`, and acquisition/rights receipt CIDs;
- source URL, official authority, observed time, response/body hashes, transformation version, and parent-child chunk coordinates;
- stable document index, chunk ordinal, and corpus row locator.

Structure-aware text chunks obey the pinned model’s actual 512-token ceiling. The requested 4,096 value is the maximum number of rows in a physical index/data shard, not a 4,096-token embedding input. Corpus construction is bounded-memory, externally sorted, checkpointed per jurisdiction/partition, and deterministic across clean resumes.

Default configuration: current exact-51 state/DC statutes. Separate explicit configurations preserve federal US Code, Puerto Rico, constitutions, historical rows, recovery records, and quarantine without letting them satisfy the exact-51 gate.

## BM25 and lexical graph

BM25 uses one versioned legal token stream for both build and query, Unicode normalization, explicit title/body fields, and recorded `k1`, `b`, field weights, average lengths, tokenizer revision, and stopword policy.

Physical layout:

- documents sorted by stable document index;
- terms sorted lexicographically and routed by inclusive term ranges;
- postings sorted by `(term, entry_cid)`;
- at most 4,096 physical rows per document/term/posting shard;
- at most 4,096 posting pointers per posting cell;
- hierarchical route pages when descriptors exceed one 4,096-row page;
- descriptor SHA-256, byte size, row count, schema ID, first/last key, and parent route digest.

BM25 sparse retrieval never uses vector centroids. It routes through lexicographic term ranges, reads only shards whose ranges cover query terms, then fetches the required postings and only corpus shards needed to hydrate final hits.

The BM25 index is also the canonical lexical graph:

- term-to-document and document-to-term traversal is virtual over postings;
- durable expansion into millions of redundant lexical edges is disabled by default;
- optional `BM25_NEIGHBOR_OF` edges use postings-driven candidate accumulation and bounded top-k selection, never an all-pairs scan;
- lexical scores are explicitly non-authoritative and cannot establish citation, amendment, or legal validity.

## GTE vectors and centroid routing

Production embedding is mandatory sentence-transformers inference with:

- model `thenlper/gte-small`;
- revision `17e1f347d17fe144873b1201da91788898c639cd`;
- 384 dimensions;
- mean pooling;
- L2 normalization;
- actual tokenizer truncation at 512 tokens;
- input text and configuration hashes;
- model-file/revision, runtime, device, precision, batch, and checkpoint evidence.

A local deterministic projection may exist for unit fixtures but can never authorize a production candidate.

The normalized vectors use deterministic balanced spherical k-means. The release records seed, iterations, objective, empty-cluster handling, membership hashes, and recall evaluation. Bounds are:

- target approximately 2,048 rows per centroid;
- at most 8,192 rows per centroid;
- at most two physical shards per centroid;
- at most 4,096 rows per physical vector shard;
- rows sorted by descending cosine-to-centroid, then `entry_cid`;
- an integrity-bound centroid route and hierarchical descriptor pages;
- a dedicated `entry_cid -> centroid/shard/row` locator.

Dense queries embed with the same pinned model and probe an evaluated number of centroids, defaulting to four only if recall evidence supports it. Vector spaces from patents, CVE, SkillCenter, old USCode, or fixtures are never compared directly unless model, revision, pooling, normalization, dimension, tokenizer, and input contract are identical.

## Legal graph and embedding-guided traversal

The durable graph models jurisdiction, code, title, chapter, section, subsection, citation, public-law/amendment relation, source, edition, and provenance. Unresolved citations remain typed unresolved nodes/edges instead of disappearing. Nodes and edges are deterministically CID-sorted.

Incoming and outgoing adjacency is paged with at most 4,096 pointers per row and 4,096 rows per physical shard. Route metadata is hierarchical and content verified. The BM25 lexical overlay supplies virtual term edges and bounded scored neighbors.

Semantic traversal begins with dense or hybrid seeds, expands legal and lexical edges under explicit depth/node/edge/shard/byte/time budgets, and ranks frontier candidates with the pinned embeddings. Off-centroid nodes are hydrated through the dedicated vector entry locator; shard first/last keys are never misused as lexical CID ranges after cosine sorting.

## Direct Hugging Face query flow

A query performs the smallest verified sequence:

1. Resolve an exact Dataset commit or a Bucket `releases/<manifest_sha256>/manifest.json`.
2. Fetch and verify the small manifest and relevant top-level route pages.
3. Route BM25 terms lexicographically and/or route the normalized query embedding to candidate centroids.
4. Fetch only selected postings/vector shards.
5. Resolve selected keys through corpus and vector-entry locators.
6. Optionally fetch bounded graph adjacency pages and off-centroid vectors for traversal.
7. Hydrate only final corpus rows.
8. Return ranked results plus a `fetch_trace` containing paths, byte counts, cache status, shard counts, route decisions, budgets, and verification outcomes.

The resolver confines paths, rejects symlinks and traversal, validates schema before parse, checks digest/size/row-count bounds, scopes caches by immutable release identity, and stops before budget overrun.

## Parallel supervisor program

The board contains 49 initial tasks, `OUL-000` through `OUL-048`, and 14 goals. `OUL-000` is completed by this committed control plane; eight file-disjoint foundation tasks become initially ready. Strict assignment is `sha256(full_task_id) % 4`.

| Phase | Goals | Tasks | Parallel shape |
|---|---|---|---|
| Foundation | OUL-G010 | OUL-001–008 | bucket, rights, oracle, transport, identity, coordination, safety, reuse audit |
| Acquisition | OUL-G020–024 | OUL-009–023 | 13 jurisdiction cohorts across four lanes, then exact-51 join and refill |
| Corpus/substrate | OUL-G030 | OUL-024–026 | corpus and streaming join, then shared scale primitives |
| Indexes | OUL-G040 | OUL-027–032 | BM25, embeddings, and legal graph in parallel; vectors and lexical graph join |
| Query | OUL-G050 | OUL-033–035 | resolver, hybrid/graph engine, CLI/API |
| Assurance | OUL-G060 | OUL-036–039 | gold set, evaluation, security/determinism, full build |
| Publication | OUL-G070–080 | OUL-040–046 | candidate, staging, canary, seal, serialized public mutation, verification |
| Operations | OUL-G090 | OUL-047–048 | rollback/update rehearsal and terminal evidence |

Each task declares exact outputs, dependencies, validation, acceptance, resource class, token class, predicted files, lane, and conflict policy. Output collisions require dependency ordering. Remote publication is serialized and callback-gated.

The first supervised run completed OUL-001 through OUL-008 and exposed a real acquisition-contract gap rather than live corpus evidence: cohort tasks wrote `open_us_law_reindex/cohort_X.json`, while their validator read only the older `legal_corpora_reindex` receipt directory. The bounded recovery refinement adds OUL-049 through OUL-057. OUL-049 owns the shared acquisition/evidence bridge and repairs the retry renderer; the remaining generated tasks preserve one durable, source-specific retry decision for each exhausted cohort. All cohort tasks now own their exact adapters, integration test, and report, and consume that report directly.

Acquisition and certification are separate. A resumable uncapped runner writes retained official response bodies, an exhaustive frontier ledger, canonical row shards, and immutable hashes beneath an isolated evidence root. The offline certifier reopens and rehashes those artifacts; `raw_bytes_checked=false`, zero-row success, placeholder hashes/CIDs, truncated key lists, samples, open frontiers, and self-asserted replay digests fail closed. Generated retry receipts prove only that the repaired software path is current—they never prove a jurisdiction was scraped. OUL-025 may implement data-independent streaming/checkpoint/sort primitives in parallel, while OUL-024, OUL-039, and every publication task remain gated on exact-51 live evidence.

The objective and codebase refill scans are enabled. Refills:

- start at the next contiguous task and goal IDs;
- require evidence-bound findings and explicit parent lineage;
- preserve file ownership and dependency order;
- deduplicate equivalent gaps;
- maintain at least four open tasks when real work remains;
- cannot weaken the exact-51, rights, model, shard, integrity, immutability, or publication contracts;
- block staging/publication while any applicable generated task is nonterminal;
- stop when scans find no material gap and every acceptance/canary is satisfied.

## Publication and rollback

OUL-040 seals a candidate manifest before network mutation. OUL-041 uses a reviewed dry-run/plan-apply workflow to upload identical bytes to an explicit Dataset staging revision and a unique Bucket staging prefix. OUL-042 redownloads from a clean cache and canaries all query modes.

OUL-043 creates a short-lived prepublication seal bound to the exact candidate, staging pin, bucket content root, target IDs, credential principal/scope, current clean commit, task/goal closure, and all source/rights/evaluation receipts.

OUL-044 is the only public mutation task. It revalidates the seal immediately before each callback, creates or updates `justicedao/open-us-law-sparse-graphrag` additively, copies exact bytes to `releases/<manifest_sha256>/`, and updates a small pointer last. It never uses deletion. OUL-045 verifies the public Dataset Viewer, immutable commit, Bucket content root, all descriptors, exact-51 coverage, attribution, and sparse queries.

Rollback changes only a pointer or recommended Dataset revision; immutable prior releases remain available. Quarterly updates use new source observations, delta admission receipts, affected-index rebuilds, a new manifest digest, a new Dataset commit, and a new Bucket prefix.

## Supervisor provider and liveness contract

Four strict lanes use Grok `grok-4.6` as the primary worker. Codex `gpt-5.6-terra` at medium reasoning is available only after a typed, non-consuming `primary_quota_exhausted` receipt; generic errors, auth failures, model errors, timeouts, or malformed output do not authorize fallback.

The supervisor uses bounded implementation, validation, merge, retry, and restart budgets; a serialized merge queue; protected control files; objective/codebase refills; task janitor; and goal completion reconciliation.

Health is not inferred from a PID. Monitoring requires:

- exactly one master, one outer supervisor, and one managed daemon per lane;
- command/namespace/state/prefix identity and PID birth identity;
- fresh master log and lane heartbeats;
- advancing heartbeats across an observation longer than one check interval;
- live recognized workers for worker-required phases;
- active log age below the stall threshold and active duration below the hard timeout;
- no duplicate/orphan processes, protected-path incidents, blocked tasks, retry exhaustion, restart storm, unresolved merge failure, or ready-without-worker past grace;
- typed future-bounded provider-capacity backoff only;
- task counts/projections consistent with the current board;
- clean terminal proof before an absent master is classified completed.

A separate older state-laws supervisor was live during planning. OUL-006 coordinates and leases jurisdictions rather than duplicating those scrapes. The OUL supervisor uses its own namespace, runtime, worktrees, state, logs, and merge queue. If both boards would write the same branch path or acquire the same jurisdiction concurrently, the OUL task waits on the lease or consumes a verified immutable receipt; it does not race.

## Completion criteria

The program is complete only when OUL-048 proves:

- fresh official exhaustive evidence for exactly all 50 states plus DC;
- clean official replacements for GA and NC and typed resolution of every source-risk row;
- rights and attribution compliance;
- canonical key/digest parity across corpus, BM25, vectors, graph, adjacency, and locators;
- real pinned GTE-small embeddings;
- all 4,096-row/pointer and centroid bounds;
- sorted term, posting, vector, graph, and route layouts;
- BM25-backed lexical graph and embedding-guided traversal;
- sparse direct-HF fetch traces and quality/security/determinism thresholds;
- immutable Dataset and content-addressed Bucket release identities;
- successful staging, canary, public upload, verification, benchmark, rollback rehearsal, and quarterly update rehearsal;
- zero blocked, in-progress, ready, waiting, externally reserved, or unclosed refill tasks;
- healthy supervisor evidence through terminal completion.
