# Knowledge Graph Load Harness (KGP-029)

Reproducible load harness for knowledge-graph production hardening.

## What it does

1. **Generates deterministic graph shapes** from `(seed, node_count, edge_count, shape)`.
2. **Replays corpus workloads** across:
   - Surfaces: `python`, `cli`, `mcp`, `mcp_plus`
   - Storage: `parquet`, `ipfs_ipld`, `ipfs_kit`, `hybrid`
   - Mixes: weighted **read / write / query**
3. **Records a versioned receipt** (`ipfs-datasets.knowledge-graphs.load-receipt.v1`) with:
   - environment, repository revision, seed, config
   - throughput and latency histogram (p50/p95/p99 + buckets)
   - queue / conflict / error counters
   - CPU / RSS / heap / open FDs
   - cache and IPFS bytes / fetches
   - shard fan-out
   - recovery timings

## Profiles

| Name | Size | CI | Notes |
|------|------|----|-------|
| `tiny` | 24n / 48e | **mandatory** | Correctness + matrix probe |
| `smoke` | 1k / 5k | opt-in | Plan smoke size |
| `corpus_211` | replay hook | opt-in | 211-AI corpus |
| `corpus_cvefixes` | replay hook | opt-in | CVEfixes corpus |
| `synthetic_large` | 1M / 10M | opt-in | Synthetic large |
| `concurrent_mixed` | 16 graphs | opt-in | Mixed concurrency |

Long profiles stay **opt-in**. Default CI runs only `tiny`.

`synthetic_large` has an additional fail-closed safety gate. It will not
materialize a graph unless `KG_LOAD_SYNTHETIC_LARGE=1` is set and the host
passes the available-memory, RSS, and free-disk preflight. Defaults can be
tuned for a labelled lab with `KG_LOAD_MIN_AVAILABLE_GIB`,
`KG_LOAD_ABORT_AVAILABLE_GIB`, `KG_LOAD_MAX_RSS_GIB`, and
`KG_LOAD_MIN_FREE_DISK_GIB`.

## Usage

```bash
# CI-mandatory tiny profile (matrix_mode=ci)
python -m benchmarks.knowledge_graphs --profile tiny --matrix-mode ci

# Storage matrix on python only
python -m benchmarks.knowledge_graphs --profile tiny --matrix-mode storage \
  --surfaces python

# List profiles
python -m benchmarks.knowledge_graphs --list-profiles
```

The 24-hour soak likewise requires `KG_SOAK_24H=1`, is rate-limited, and
enforces `KG_SOAK_{MIN_AVAILABLE,ABORT_AVAILABLE,MAX_RSS,MIN_FREE_DISK}_GIB`
resource limits. Run it only in a labelled, monitored environment:

```bash
KG_SOAK_24H=1 python -m benchmarks.knowledge_graphs.soak \
  --profile day --work-dir /path/to/evidence/soak
```

Generate a structured, content-addressed receipt for the isolated chaos suite:

```bash
python -m benchmarks.knowledge_graphs.chaos \
  --environment-id dev-host-linux-aarch64-py3.12 \
  --work-dir /path/to/evidence/chaos \
  --receipt /path/to/evidence/chaos/receipt.json
```

```python
from pathlib import Path
from benchmarks.knowledge_graphs import GraphLoadHarness, get_profile, validate_receipt

harness = GraphLoadHarness(Path("/tmp/kg-load"))
result = harness.run(get_profile("tiny"), matrix_mode="ci")
assert result.receipt is not None
assert not validate_receipt(result.receipt.to_json_dict())
```

## Tests

```bash
python -m pytest -q tests/load/knowledge_graphs/test_harness.py
```

## Module layout

| Module | Role |
|--------|------|
| `shapes.py` | Deterministic graph generation + fingerprints |
| `profiles.py` | Named workload profiles |
| `metrics.py` | Latency histogram + resource sampling |
| `receipt.py` | Versioned receipt build/validate/write |
| `surfaces.py` | Python/CLI/MCP/MCP++ adapters |
| `workloads.py` | Seed + read/write/query mixes |
| `harness.py` | Orchestrator + matrix expansion |
