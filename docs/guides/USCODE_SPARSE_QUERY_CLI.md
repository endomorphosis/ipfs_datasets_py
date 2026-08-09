# US Code Sparse GraphRAG Query CLI (USCIR-028)

Direct Hugging Face query entry point for the sealed US Code sparse GraphRAG
release. The CLI maps each subcommand onto `UscodeQueryClient` without optional
accelerators.

## Offline fixture mode

```bash
python scripts/ops/legal_data/query_uscode_hf.py \
  --local-root /path/to/release \
  --fixture-mode \
  --json --trace \
  bm25 "5 U.S.C. § 552"
```

`--local-root` uses `LocalRootTransport` (no network). Live Hub queries require
an immutable `--revision` pin (not `main`/`latest`).

## Subcommands

| Command | Python API |
|---------|------------|
| `bm25` | `UscodeQueryClient.bm25_search` |
| `vector` | `UscodeQueryClient.vector_search` |
| `hybrid` | `UscodeQueryClient.hybrid_search` |
| `neighbors` | `UscodeQueryClient.neighbors` |
| `graph-walk` | `UscodeQueryClient.graph_walk` |
| `semantic-graph-walk` | `UscodeQueryClient.semantic_graph_walk` |

## Shared flags

- `--repo-id`, `--revision`, `--cache-dir`, `--local-root`
- Budget caps: `--max-bytes`, `--max-shards`, `--max-rows`, `--max-nodes`, `--max-edges`, `--max-depth`, `--max-time-ms`
- Legal filters: `--title`, `--section`, `--citation`, `--version`, `--legal-id`
- Output: `--json`, `--trace`

Secrets (`HF_TOKEN`, etc.) are never printed. Passing token-like values on the
command line is rejected.
