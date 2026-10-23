# country-laws-ir

Malta-first packager that turns `endomorphosis/ipfs_<country>_laws`
(`laws.parquet` + `articles.parquet`) into a CID-keyed SkillCenter-style
sparse GraphRAG release (`country-laws-ir-graphrag/v1`, layout family
`skillcenter-huggingface-release/v3` / Publicus/skillcenter-ir).

**Research snapshot. Not legal advice.** Official gazettes prevail.
No legal text is invented. This tree does **not** upload to Hugging Face
and does **not** read or store an HF token. Source datasets are public.

## Setup

```bash
cd /workspace/country-laws-ir
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# torch CPU wheel if needed:
# pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## Build Malta (local)

```bash
cd /workspace/country-laws-ir
PYTHONPATH=. python -m country_laws_ir build \
  --source-repo endomorphosis/ipfs_malta_laws \
  --out /workspace/country-laws-ir/releases/ipfs_malta_laws_ir
```

Equivalent: `python scripts/build_country_laws_ir.py --source-repo endomorphosis/ipfs_malta_laws --out ...`

## Query smoke test

```bash
REL=/workspace/country-laws-ir/releases/ipfs_malta_laws_ir
PYTHONPATH=. python scripts/query_country_laws_hf.py --local-dir "$REL" bm25 "constitution" --top-k 5
PYTHONPATH=. python scripts/query_country_laws_hf.py --local-dir "$REL" vector "money laundering" --top-k 5
# pick an entry_cid from bm25 output:
PYTHONPATH=. python scripts/query_country_laws_hf.py --local-dir "$REL" graph neighbors <entry_cid>
```

## CID payload

`entry_cid` is CIDv1 codec=raw (0x55) hash=sha2-256 (0x12) base32 (`bafkrei...`)
over the UTF-8 bytes of `json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`.
The identity object is versioned (`country-laws-entry/v1`). Same payload → same CID.
Integer `document_index` is only a compact shard pointer.

Vectors: `thenlper/gte-small` 384-d, sentence-transformers mean pool, L2 / cosine.
Shard assignment: recursive spherical k-means (binary split until ≤4096 rows),
rows sorted by cosine to the shard centroid.

## Batch / other countries

Catalog: `catalog/countries.json` and `catalog/batch_slugs.txt`.
`python -m country_laws_ir catalog`

Normalize only:

```bash
PYTHONPATH=. python -m country_laws_ir normalize --source-repo endomorphosis/ipfs_germany_laws
```

Belgium, Portugal, and Lithuania are incomplete Wayback harvests and are
excluded from indexing.

## Later publish (operator only — not this run)

```bash
export HF_TOKEN=...   # never commit / never echo
hf upload-large-folder justicedao/ipfs_malta_laws_ir \
  /workspace/country-laws-ir/releases/ipfs_malta_laws_ir \
  --repo-type dataset --no-private --num-workers 8 \
  --exclude "**/__pycache__/**" --exclude "**/*.pyc"
```
