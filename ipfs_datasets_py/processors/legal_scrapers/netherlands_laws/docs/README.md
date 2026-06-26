# Netherlands Laws Submodule

This package holds Netherlands-law-specific:

- raw scraper outputs
- Hugging Face dataset packages
- IPFS/CID packaging outputs
- index builders and analysis artifacts

The goal is to keep these assets inside `ipfs_datasets_py.processors.legal_scrapers`
alongside the scraper, Bluebook-related tooling, and retrieval/indexing code.

## Runbook

Install the optional Netherlands packaging dependencies when working from a fresh environment:

```bash
pip install -e ".[legal_netherlands]"
```

Set a Hugging Face token in the environment before upload. Do not commit token values:

```bash
export HF_TOKEN="<token with write access to justicedao>"
```

The package-managed default raw source is `datasets/raw/nl_discovery_medium_100`, the latest validated 100-law medium scrape. It is intentionally not described as the full Dutch corpus.

Scrape the two current Netherlands law documents into the package-managed raw output directory:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --document-url "https://wetten.overheid.nl/BWBR0001854/" \
  --document-url "https://wetten.overheid.nl/BWBR0002656/" \
  --max-documents 2
```

Run discovery from official sources without explicit document URLs. Start with a 50-law validation run:
The scrape CLI also accepts underscore aliases such as `--use_default_seeds true` and `--max_seed_pages 10`.

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --use-default-seeds \
  --max-seed-pages 10 \
  --crawl-depth 1 \
  --max-documents 50 \
  --rate-limit-delay 0.2 \
  --skip-existing
```

Latest validated medium run:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --output-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_discovery_medium_100 \
  --use_default_seeds true \
  --max_seed_pages 25 \
  --crawl_depth 1 \
  --max_documents 100 \
  --rate_limit_delay 0.2 \
  --skip_existing true
```

The April 26, 2026 medium run is not a full corpus. It visited 25 seed pages, found 607 candidate links, accepted 593 unique official law documents, selected/fetched/parsed 100 laws, and had 0 document failures. The raw run produced 100 law records, 7,247 article records, and 7,347 search records. Two parsed law documents did not expose article-level rows in the current extractor, so article rows cover 98 distinct law identifiers.

## Scaling Beyond 100 Laws

For national-scale ingestion, use the persistent BWBR catalog and resumable queue.
This is the production path for the 42,956 unique BWBR identifiers found by the
official full SRU discovery inventory. Do not describe an output as the full
Dutch corpus until every catalog row is parsed, intentionally skipped, or failed
permanently with an explanation.

Import the official SRU discovery JSONL into the durable catalog. The catalog is
SQLite-backed and stores each BWBR identifier once, along with discovery source,
timestamps, scrape state, retry count, parser/article status, law status, and
version/checksum metadata as runs progress.

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws discover \
  --discovery-jsonl ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_full_bwb_discovery/netherlands_bwb_full_discovery_urls.jsonl
```

Queue identifiers in bounded batches:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws queue \
  --limit 500
```

Process queued work. This leases rows as `downloading`, writes explicit
transition events, retries only transient failures, and synchronizes parsed raw
rows back into the catalog.

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --from-catalog \
  --output-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_full_sru_sharded \
  --batch-size 50 \
  --rate-limit-delay 0.35 \
  --skip-existing true
```

If a run is interrupted, rerun:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws resume \
  --raw-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_full_sru_sharded \
  --batch-size 50 \
  --rate-limit-delay 0.35
```

Transient failures can be requeued separately:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws retry-failures \
  --limit 200
```

Write machine-readable completeness metrics after each run:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws coverage-report
```

Validate integrity before publishing:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws verify \
  --raw-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_full_sru_sharded
```

For changed-only operational deltas, emit affected law, article, CID, vector,
BM25 document, and graph rows without rebuilding global FAISS/BM25 artifacts:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws rebuild-huggingface \
  --incremental \
  --raw-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_full_sru_sharded
```

For a full published snapshot, rebuild packages and mark represented identifiers
as packaged:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws rebuild-huggingface \
  --raw-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_full_sru_sharded
```

Use cumulative, resumable scrape directories for larger runs. The scraper discovers official `BWBR...` URLs first, sorts them by identifier, applies `--max_documents` as a cumulative cap, and skips already persisted records when `--resume` or `--skip_existing true` is set. If a run is interrupted, rerun the same command with the same `--output-dir` and `--resume`.

After checking metadata and spot-checking records, increase to 500 laws in a larger-run directory:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --output-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_discovery_large \
  --use_default_seeds true \
  --max_seed_pages 75 \
  --crawl_depth 1 \
  --max_documents 500 \
  --rate_limit_delay 0.25 \
  --resume
```

To continue the same large-run directory in shards, raise the cumulative cap and keep `--resume`:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --output-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_discovery_large \
  --use_default_seeds true \
  --max_seed_pages 150 \
  --crawl_depth 1 \
  --max_documents 1000 \
  --rate_limit_delay 0.3 \
  --resume
```

Only after the 50-law, 100-law, and 500-law runs validate cleanly, run an uncapped discovered-corpus scrape. Keep a rate limit and use resume. Do not call the result a full Dutch corpus unless the run metadata confirms discovery actually covered all official `BWBR...` records you intend to include:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --output-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_discovery_full \
  --use_default_seeds true \
  --max_seed_pages 1000 \
  --crawl_depth 1 \
  --rate_limit_delay 0.35 \
  --resume
```

After any larger scrape, inspect these metadata fields before packaging:

- `total_unique_laws_discovered`
- `total_fetched`, `total_parsed`, `total_failed`, `total_skipped`
- `distinct_law_identifiers_in_outputs`
- `article_producing_laws_count`
- `non_article_producing_laws_count`
- `article_extraction_missing_count`
- `genuine_non_article_laws_count`

For a larger scrape, build from that explicit raw directory:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws build-normalized \
  --raw-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_discovery_large

python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws build-ipfs-package \
  --raw-dir ipfs_datasets_py/processors/legal_scrapers/netherlands_laws/datasets/raw/nl_discovery_large

python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws build-indexes
```

The latest 100-law no-article investigation found:

- `BWBR0001821`, `Loi concernant les Mines, les Minières et les Carrières`: parser miss caused by French `Article ...` headings; fixed by accepting French article/title/section headings.
- `BWBR0001958`, `Muziekauteursrecht`: appears to be an unnumbered/non-article ministerial document; it should be reported as `non_article_document` unless future source markup changes.

Build the normalized package and CID-addressed base dataset:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws build-normalized
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws build-ipfs-package
```

Build vector, BM25, and JSON-LD knowledge graph index datasets:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws build-indexes
```

Upload/update the Hugging Face datasets:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws upload \
  --namespace justicedao \
  --target all
```

Verify the remote datasets:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws verify-remote \
  --namespace justicedao \
  --target all
```

The `all` upload/verify target covers:

- `justicedao/ipfs_netherlands_laws`
- `justicedao/ipfs_netherlands_laws_vector_index`
- `justicedao/ipfs_netherlands_laws_bm25_index`
- `justicedao/ipfs_netherlands_laws_knowledge_graph`
