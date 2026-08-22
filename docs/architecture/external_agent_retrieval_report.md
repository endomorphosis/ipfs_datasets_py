# External-agent federated retrieval qualification (EAAEF-064)

This report records contract-level qualification of federated retrieval
relevance and trust. It is **not** live index-cluster evidence.

## Envelope

Every admitted retrieval item must carry:

| Field | Role |
| --- | --- |
| `cid` | Source content identity (`sha256:…`) |
| `revision` | Source revision / git binding |
| `trust` | Closed trust class; imported text is not authority |
| `mode` | Engine mode (ast, bm25, vector, …) |
| `score` | Rank score; cannot override repository truth |
| `path` | Source path |
| `span` | Byte or line span |
| `capsule` | ContextPack / capsule identity |
| `freshness` | Retrieval timestamp |
| `reason` | Why the item was selected |

## Trust

Untrusted similarity (`imported_claim` + `untrusted` / `imported_unverified`)
cannot override `repository_truth`. Similarity score is not authority.
Duplicate index systems are refused.

## Evidence mode

`contract_fail_closed`. `live_runtime_invoked`: false.
