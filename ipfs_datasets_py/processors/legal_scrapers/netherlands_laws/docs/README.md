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

After checking metadata and spot-checking records, increase to 500 laws:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --use-default-seeds \
  --max-seed-pages 75 \
  --crawl-depth 1 \
  --max-documents 500 \
  --rate-limit-delay 0.25 \
  --resume
```

Only after the 50-law and 500-law runs validate cleanly, run an uncapped discovery scrape. Keep a rate limit and use resume:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --use-default-seeds \
  --max-seed-pages 1000 \
  --crawl-depth 1 \
  --rate-limit-delay 0.35 \
  --resume
```

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
