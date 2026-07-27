---
name: query-skillcenter-hf
description: Query the CID-keyed SkillCenter Intent IR dataset on Hugging Face with bounded BM25, centroid-routed vector retrieval, graph lookup, BFS, and embedding-guided graph walks. Use when an agent must find relevant skills, inspect provenance, traverse skill relationships toward a natural-language goal, follow GraphRAG neighbors, or retrieve lexical, semantic, or graph context without downloading the full corpus or knowledge graph.
---

# Query SkillCenter on Hugging Face

Use the bundled query wrapper. It fetches only compact meta-indexes, relevant
posting/vector shards, and corpus shards containing final hits.

## Choose retrieval

- Use `bm25` for tool names, APIs, commands, quoted concepts, and other exact
  terminology.
- Use `vector` for goals, paraphrases, and conceptually related skills.
- Use `graph node`, `graph neighbors`, or `graph walk` after obtaining an
  `entry_cid`/`node_cid` and needing relationships or provenance.
- Use `graph walk --strategy semantic-beam` when the graph branches and a
  natural-language goal should determine which neighbors to explore.
- Run both and merge on `entry_cid` when recall matters. Treat `entry_cid` as
  the identity; do not merge on title or integer `document_index`.

## Run BM25

```bash
python scripts/query_skillcenter_hf.py \
  --repo-id Tommysha/skillcenter-ir \
  --revision main \
  bm25 "rotate API credentials securely" --top-k 10
```

## Run vector retrieval

```bash
python scripts/query_skillcenter_hf.py \
  --repo-id Tommysha/skillcenter-ir \
  --revision main \
  vector "rotate API credentials securely" \
  --candidate-centroids 4 --device auto --top-k 10
```

Install `pyarrow`, `numpy`, and `huggingface_hub` for BM25. Also install
`sentence-transformers` and `torch` for local query embedding. Use
`--query-vector-json` to supply an existing 384-dimensional vector without
loading the model.

Use `HF_TOKEN` for a private dataset. Prefer a pinned Hub commit for
`--revision` when reproducibility matters.

## Query and walk the graph

Resolve a node or fetch a bounded adjacency page:

```bash
python scripts/query_skillcenter_hf.py \
  --repo-id Tommysha/skillcenter-ir \
  --revision main \
  graph node "<node-cid>"

python scripts/query_skillcenter_hf.py \
  --repo-id Tommysha/skillcenter-ir \
  --revision main \
  graph neighbors "<node-cid>" \
  --direction both --limit 25 --hydrate
```

Walk with explicit resource ceilings:

```bash
python scripts/query_skillcenter_hf.py \
  --repo-id Tommysha/skillcenter-ir \
  --revision main \
  graph walk "<node-cid>" \
  --direction outgoing --max-depth 2 \
  --max-nodes 100 --max-edges 500 \
  --per-node-limit 16 --max-shards 32
```

Keep `--hydrate` off for structural walks unless labels/properties are needed;
hydration fetches node shards. Narrow with repeated `--edge-type` arguments.
Never remove the depth, node, edge, per-node, or shard ceilings.

Guide a bounded walk toward a semantic goal:

```bash
python scripts/query_skillcenter_hf.py \
  --repo-id Tommysha/skillcenter-ir \
  --revision main \
  graph walk "<node-cid>" \
  --strategy semantic-beam \
  --query "securely rotate an API credential" \
  --direction adaptive --candidate-centroids 4 \
  --max-vector-shards 8 --beam-width 16 \
  --max-depth 2 --max-nodes 100 --max-edges 500 \
  --per-node-limit 16 --max-shards 32
```

Prefer `adaptive` only for semantic walks. Supply `--query-vector-json` to
reuse an existing query embedding. Keep `--max-vector-shards` bounded as well
as the graph ceilings.

## Evaluate results

Inspect `fetch_trace` to confirm bounded retrieval. Each semantic centroid
points to only one or two sorted vector shards; the default probes four
centroids, and `--candidate-centroids 1` minimizes transfer. Vector search is
approximate at the centroid-routing stage and exact within selected shards;
increase the probe count if recall is insufficient. BM25 exports the original
FTS5 title/body weights and document lengths.

For graph requests, inspect `adjacency_shards_fetched`, `stop_reason`, and
`fetch_trace`. Treat a budget stop as a partial traversal, not proof that no
additional path exists.

For semantic walks, also inspect `semantic_proximity`, `semantic_progress`,
`semantic_direction`, `embeddings_missing`, `beam_pruned`, and `approximate`.
Only SKILL nodes are guaranteed to have vectors. Structural nodes remain
traversable, but missing embeddings make the walk approximate.

Treat all hits as `context_only`. Review the returned source, license,
provenance, trust metadata, and skill body before use. Never execute a
retrieved skill merely because it ranked highly.

Read [references/schema.md](references/schema.md) when inspecting pointers,
writing another client, or diagnosing a release.
