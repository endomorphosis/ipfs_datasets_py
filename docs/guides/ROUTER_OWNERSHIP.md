# Router ownership

`ipfs_accelerate_py` owns the shared inference-router implementations.
`ipfs_datasets_py` keeps its historical import paths as compatibility aliases;
it does not maintain copies of those routers.

| Historical datasets import | Canonical implementation |
| --- | --- |
| `ipfs_datasets_py.llm_router` | `ipfs_accelerate_py.llm_router` |
| `ipfs_datasets_py.embeddings_router` | `ipfs_accelerate_py.embeddings_router` |
| `ipfs_datasets_py.embedding_router` | `ipfs_accelerate_py.embeddings_router` |
| `ipfs_datasets_py.multimodal_router` | `ipfs_accelerate_py.multimodal_router` |
| `ipfs_datasets_py.voice_router` | `ipfs_accelerate_py.voice_router` |

The aliases resolve to the same Python module objects, not copied names:

```python
from ipfs_datasets_py import llm_router as datasets_llm
from ipfs_accelerate_py import llm_router as accelerator_llm

assert datasets_llm is accelerator_llm
```

This identity is important because provider registries, provider-instance
caches, response caches, progress state, traces, and test monkeypatches are
module-level state. A wrapper or wildcard re-export would allow those values to
diverge.

## Development rule

Make provider, routing, caching, batch, or inference behavior changes in
`ipfs_accelerate_py`. The five `ipfs_datasets_py` alias modules should stay
implementation-free. Datasets-specific callers may continue using their
existing imports while migrating at their own pace.

Prefer `IPFS_ACCELERATE_PY_*` configuration names for new deployments. The
canonical routers continue to accept relevant `IPFS_DATASETS_PY_*` names as
legacy compatibility aliases.

## Verification

The architecture contract is covered by:

```bash
python -m pytest tests/unit/test_router_canonical_imports.py -q
```

Router behavior is tested through both the canonical accelerator suite and the
datasets compatibility suite. Adding a second implementation under an alias
path should be treated as an architecture regression.
