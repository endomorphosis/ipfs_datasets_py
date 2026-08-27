# Exact-51 residual replay playbook (v1)

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Branch: `feature/legal-corpora-reindex`  
Status: acquisition playbook for remaining jurisdictions; **not a publication authorization**

This document is the operator playbook behind supervisor goals `LCR-G148`–`LCR-G153`
and tasks `LCR-086`–`LCR-106`. It extracts the patterns that already closed
current-bundle pairs and applies them to the 17 jurisdictions that still have
open residuals or missing authorizing ledgers.

## Closed-state pattern (do not invent a second pipeline)

Every closed current-bundle pair used the same six steps:

1. **Source-derived frontier.** Membership comes from retained official
   catalog/root bytes, not static lists or sample caps.
2. **Fresh evidence generation.** Seed a new root with hardlinks. Never
   overwrite a prior ledger or promote a failed canary.
3. **Direct-only reuse when possible.** Seed `--allowed-source-transport direct`.
   Historical Wayback bodies are diagnostics unless a current-equivalence proof
   exists.
4. **One residual wave.** Submit only the source-ordered difference as same-domain
   plural fetches. One Common Crawl inventory per domain/wave. Grouped/coalesced
   WARC reuse. Plural Wayback prefix inventory. Residual-only retries **without**
   archive reinventory. No per-page archive loop. No archive.is.
5. **Hard retained replay.** `--retained-replay-only` in an OS-isolated
   `--network none` worker. Kernel isolation authorizes zero-network; the Python
   audit hook and `strace` are defense/evidence only.
6. **Normalize and seal.** Canonical JSON-LD, parquet, normalized receipt, and
   run seal with `public_law_no_state_copyright`. Start/end producer identities
   must match. No Hub mutation.

Rights: enacted public-law text is not subject to state copyright. Editorial
annotations, database arrangement, and site chrome stay excluded.

## Shared substrate that remaining states must reuse

| Mechanism | Module / command | Closed-state lesson |
|---|---|---|
| Direct-only seed | `scripts/ops/legal_data/seed_state_laws_retained_evidence.py` | PA v7 seeded 75 direct inputs, 150 hardlinks, projection `425927…fd07`, zero copies |
| Isolated replay | `retained_replay_isolated_worker.py` + Docker `--network none --cap-drop ALL` | PA v7 sealed 14,620 rows, 75/75 retained replay, authorizing run seal `fa3225e…` |
| Network deny | `retained_replay_network_guard.py` | Process-wide audit hook, liveness proof, trusted absolute `pdftotext` |
| Archive fallback | `web_archiving` Common Crawl prefix/WARC batching + Wayback CDX/prefix inventory | One inventory per domain/wave; coalesced WARC ranges; residual-only retry |
| Normalization | `refresh_state_laws_corpus.py --strict-acquisition-evidence` | Identity projection must exclude mutable deny-lease state |
| Publication | none in this campaign | Indexing (`gte-small`, BM25, BM25 graph, centroids, sparse meta) stays disabled until exact-51 assembler succeeds |

## Remaining jurisdictions and parallel waves

Assembler-selected / closed pairs stay untouched. Remaining open set:

`AR GA KY LA MI MN MO MS MT NH NY RI TN VT WA WI WV`

| Wave | Goal | Jurisdictions | Why this grouping | First action |
|---|---|---|---|---|
| Shared substrate | LCR-G149 | all remaining | Unblocks every residual | Direct-only seed must skip unverifiable disallowed transports (MT v4 Wayback mismatch); isolated worker; grouped archive contract |
| Wave A | LCR-G150 | MT, KY | Bounded, GO or exact residual | Seed MT direct-only 40,132; acquire 5 missing catalogs + 6,652 leaves. KY: 11,641 unique leaf residual |
| Wave B | LCR-G151 | MN, MO, WA | Large leaf residuals, retained catalogs exist | Seed verified direct projection; one global leaf wave |
| Wave C | LCR-G152 | LA, RI, NH, VT, WV | Catalog-then-leaf or fresh current root | LA 21,531 residual; RI 29 nested catalogs first; NH/VT/WV start fresh current roots |
| Wave D | LCR-G153 | AR, GA, MI, MS, NY, TN, WI | Proof, delegated Lexis, or no authorizing ledger | Exact URL/proof residuals only; do not hunt unbounded |

Pennsylvania isolated replay is already sealed and is the canary for waves A–D.
Do not reuse fenced PA v2–v6 roots.

## Web-archiving rules for residuals

- Replay exact retained request identity before any network.
- Same-host plural GET/POST batches; never one HTTP client per URL.
- At most one Common Crawl inventory term per domain per logical wave.
- WARC recovery uses grouped byte-range coalescing; identical WARC files are
  opened once.
- Wayback uses prefix inventory, not per-page CDX.
- Retry waves contain only unresolved exact URLs and **must not** repeat grouped
  archive inventory.
- Media-aware inventory is required when the frontier is XML/PDF (MI lesson).
- `pdftotext` is only the import-time trusted absolute converter.

## Normalization and seal rules

- Produce `STATE-XX.jsonld`, parquet, raw and normalized receipts, frontier
  closure projection, and a run seal.
- Producer identity at run start equals identity at seal.
- Isolated worker identity must bind inside rootless Docker (host-root
  `pdftotext` appears as uid 65534; still the same `/usr/bin/pdftotext` bytes).
- One-state `partial_success` is expected and is not exact-51 success.
- No `--publish-to-hf`, no incremental Hub publish, no assembler input-map write
  until all 51 digest-bound pairs exist.

## Supervisor mapping

Four strict SHA-256 lanes. Shared substrate tasks have no dependencies so lanes
0/1/2/3 can start immediately (`LCR-086`, `LCR-087`, `LCR-106`, `LCR-088`).
Residual tasks depend on `LCR-086` and `LCR-088` (seed + archive contract) and
`LCR-087` (isolated replay helper). Each residual task owns only its report and
focused tests; adapters may be edited only for that jurisdiction.

Publication tasks `LCR-040+` remain blocked on exact-51 live acceptance
(`LCR-084` / `LCR-G146`). This campaign does not weaken that gate.
