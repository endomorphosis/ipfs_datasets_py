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

Scrape the two current Netherlands law documents into the package-managed raw output directory:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape \
  --document-url "https://wetten.overheid.nl/BWBR0001854/" \
  --document-url "https://wetten.overheid.nl/BWBR0002656/" \
  --max-documents 2
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
