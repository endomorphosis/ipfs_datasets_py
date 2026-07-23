# Portland, Oregon Current City Code

This folder contains a current-origin scrape of the Portland City Code from
`https://www.portland.gov/code`, prepared for the JusticeDAO American Municipal
Law CID-indexed schema.

## Contents

- `raw/pages.parquet`: raw section scrape with extracted text, source HTML,
  source URLs, Portland metadata, and document/text/source CIDs.
- `raw/manifest.json`: scrape manifest. The scrape discovered 34 title pages,
  404 chapter pages, and 3,052 section pages, with 3,052 rows written and 0
  errors.
- `canonical/STATE-OR.parquet`: canonical municipal law rows for Portland
  current code sections.
- `canonical/STATE-OR_embeddings.parquet`: `thenlper/gte-small` embeddings
  generated through `embeddings_router` with `embedding_device=cuda`.
- `canonical/STATE-OR.faiss`: FAISS vector index for the embeddings.
- `canonical/STATE-OR_faiss_metadata.parquet`: FAISS row metadata keyed by
  `ipfs_cid`.
- `canonical/STATE-OR_cid_index.parquet`: CID lookup/index table.
- `canonical/STATE-OR_bm25.parquet`: lexical retrieval documents.
- `canonical/STATE-OR_knowledge_graph_entities.parquet`: JSON-LD-derived
  knowledge graph entities.
- `canonical/STATE-OR_knowledge_graph_relationships.parquet`: JSON-LD-derived
  knowledge graph relationships.
- `canonical/STATE-OR_knowledge_graph_summary.json`: knowledge graph and corpus
  quality summary.
- `logic_proofs/STATE-OR_logic_proof_artifacts.parquet`: machine-generated
  formalization candidates for every Portland code section, keyed by
  `ipfs_cid`, including first-order logic, deontic temporal first-order logic,
  deontic cognitive event calculus, frame logic, and zero-knowledge proof
  certificate metadata.
- `logic_proofs/manifest.json`: logic/proof artifact build manifest.

## Build Summary

- Source: `https://www.portland.gov/code`
- Jurisdiction: City of Portland, Oregon
- GNIS: `2411471`
- Canonical rows: 3,052
- Embedding backend: `embeddings_router`
- Embedding model: `thenlper/gte-small`
- Embedding device: `cuda`
- Embedding dimension: 384
- Logic/proof rows: 3,052
- Logic/proof scope: machine-generated candidate formalizations
- ZKP backend: simulated educational certificates, not cryptographically secure
