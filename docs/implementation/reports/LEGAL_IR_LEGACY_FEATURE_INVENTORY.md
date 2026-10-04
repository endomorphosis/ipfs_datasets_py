# LegalIR Legacy Feature-Transfer Inventory

- Task: `PORTAL-LIR-HAMMER-119`
- Track: `legacy-signal-migration`
- Inventory schema: `modal-autoencoder-legacy-feature-inventory-v1`
- Policy: fail closed; immutable audit evidence only
- Decision: verified

## Scope and trust boundary

The inventory independently reconciles the accepted legacy feature transfer. It
does not treat the transfer report's `accepted` flag or the evaluation
canary's `passed` decision as training labels. Neither the legacy tensors nor
the inventory are authorized production legal semantics. Promotion still
requires separate, trusted, source-free evaluation and proof evidence.

The JSON inventory contains counts, dimensions, activation frequencies, and
signed/absolute signal mass only. It contains no sparse row keys, source
samples, sample identifiers, prompts, decoded modal text, tensor rows, or
nested artifact payloads.

## Immutable artifact bindings

| Binding | SHA-256 |
| --- | --- |
| Legacy state | `sha256:7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be` |
| Accepted state | `sha256:1c615f7c622b46e1a3d7349b436bf5daefc3e26866e9458c0feacfe545bcb033` |
| Transfer report file | `sha256:5d6da2dca0c2ad5c74c16d9c47eee2fc43b18aabe5e53a6c1f55e3f6a14995e2` |
| Transfer report canonical payload | `sha256:7f33f7c55d37a8fcccc646452de21e3f8670a5982e4e68d6a614e2cc1896b4ed` |
| Evaluation canary file | `sha256:a71a67bf14b5740f9b52ef7ac3859b436df6406d4b60f0fc13e0e1e2125c2bb5` |
| Evaluation canary canonical payload | `sha256:83a894d019b368532122b598fd3ad71166df6406d4b60f0fc13e0e1e2125c2bb5` |
| Canary row-index set | `sha256:b45040bc5116a2661f74481b13bdf622eb40a34c3e5904a649ee81f106c357c7` |
| Architecture schema | `sha256:7351ce3e0b8e3c436b2eef6949fceb3e246c9ba887b7e8175c56963139ab0eda` |
| Tokenizer/parser source and canary configuration | `sha256:294ac801c57d8412ae415e14dbdd6744614e88d9d3e8a15766fd9a5cc390876a` |
| Compiler source and bridge configuration | `sha256:0ef2e3a17f2264431214fefc50020cf4319755cf8b4c72b4df0e21f7ca97c535` |

The generated inventory payload is
`sha256:2af5e26106dc5620498d571183164ba0e58bae6853c645c42a3b8de185d08060`.
This is the embedded canonical-payload digest, not the digest of its
pretty-printed JSON file.

## Accepted transfer lineage

The audit reproduces both the row disposition and the transfer provenance:

| Reconciliation | Rows |
| --- | ---: |
| Legacy generalizable rows | 1,205,336 |
| Accepted rows | 209,759 |
| Transferable, exact old values | 209,753 |
| Remapped logical rows | 0 |
| Target-preserved overrides | 6 |
| Omitted rows | 995,577 |
| Target-preserved provenance | 98,153 |
| Source-fill provenance | 111,606 |

The conservation equations hold exactly:

`209,753 exact + 0 remapped + 6 overridden = 209,759 accepted`

`209,759 accepted + 995,577 omitted = 1,205,336 legacy`

All six overrides are dimension-compatible scalar
`legal_ir_view_logits`. There are no accepted-only legacy-lineage gaps and no
incompatible shared dimensions. The transfer used capacity 32,768,
`target_exact_source_fill_v2`, deferred direct legacy embedding activation, and
reported source L1-signal coverage `0.984643314506242`.

## Semantic-family inventory

Activation frequency is the fraction of rows containing at least one nonzero
finite numeric leaf. Signed signal mass is `math.fsum` over finite leaves; it
preserves cancellation and is distinct from absolute/L1 signal.

| Tensor group | Legacy | Accepted | Exact | Override | Omitted | Omitted active frequency | Omitted signed mass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| compiler quality | 116 | 116 | 116 | 0 | 0 | 0 | 0 |
| decompiler plan | 39,950 | 33,645 | 33,645 | 0 | 6,305 | 0.855670103093 | -0.005829583340 |
| family | 8 | 8 | 8 | 0 | 0 | 0 | 0 |
| family × view | 42 | 42 | 42 | 0 | 0 | 0 | 0 |
| family × semantic slot | 70,470 | 8,192 | 8,192 | 0 | 62,278 | 0.795256751983 | 0.050177188564 |
| family × slot × view | 298,685 | 22,068 | 22,068 | 0 | 276,617 | 0.807249735193 | 0.109303595175 |
| sparse compiler/lexical feature | 544,979 | 41,804 | 41,804 | 0 | 503,175 | 0.981382222885 | 0.086832668243 |
| global LegalIR view | 19 | 19 | 13 | 6 | 0 | 0 | 0 |
| logic signature | 4,951 | 4,951 | 4,951 | 0 | 0 | 0 | 0 |
| predicate/argument | 26,895 | 22,796 | 22,796 | 0 | 4,099 | 0.911441815077 | -0.001525098268 |
| round trip/provenance | 338 | 338 | 338 | 0 | 0 | 0 | 0 |
| semantic slot | 42,093 | 35,358 | 35,358 | 0 | 6,735 | 0.711358574610 | 0.005154759837 |
| slot × LegalIR view | 176,790 | 40,422 | 40,422 | 0 | 136,368 | 0.932381497125 | 0.053643006037 |

Across all 995,577 omitted rows, 907,702 rows are active
(`0.911734602145`). The omitted tensors contain 7,997,902 finite numeric
leaves, of which 7,294,902 are nonzero (`0.912101948736`). Their signed signal
mass is `0.29775653624732634` and absolute signal mass is
`9.373148287794887`.

## Omitted transfer-risk ledger

Every omitted row is high risk under the current direct-transfer contract.
This is a transfer-risk classification, not a negative quality label.

| Omitted field | Rows | Risk basis |
| --- | ---: | --- |
| decompiler plan embeddings | 6,305 | Direct legacy embedding activation can regress held-out cosine. |
| family × semantic-slot embeddings | 62,278 | High-cardinality interaction tail; teacher-only until evidence-aware selection. |
| family × slot × view embeddings | 276,617 | High-cardinality interaction tail; teacher-only until factorized/evaluated. |
| feature embeddings | 164,268 | Sparse lexical/compiler tail; direct activation is excluded. |
| feature family logits | 246,040 | Capacity-pruned sparse tail requiring matched tokenizer/compiler evidence. |
| feature LegalIR-view logits | 92,867 | Compiler-facing calibration tail requiring a zero-influence baseline and canary. |
| predicate/argument embeddings | 4,099 | Direct embedding transfer risk. |
| semantic-slot embeddings | 6,735 | Direct embedding transfer risk. |
| slot × view embeddings | 49,504 | Direct interaction-embedding transfer risk. |
| slot × view family logits | 84,529 | Sparse factorization/calibration risk. |
| slot × view logits | 2,335 | Sparse factorization/calibration risk. |

The embedding omissions total 569,806 rows. The omitted logit tails total
425,771 rows. Their sum is the complete 995,577-row omission ledger.

## Fail-closed behavior

The audit rejects:

- a mismatched physical artifact digest or embedded report digest;
- unknown state, checkpoint-manifest, checkpoint-metadata, transfer-report,
  group-report, or canary fields;
- unsupported architecture, state, checkpoint, transfer, or canary schemas;
- non-finite or non-numeric tensor leaves;
- ragged embedding widths, shared vector-width changes, shared logit-label
  dimension changes, or scalar/mapping/sequence kind changes;
- accepted rows not present in the legacy lineage;
- a report, checkpoint, selection, or canary artifact-hash disagreement;
- nonzero incompatible/preservation-failure counts;
- a failed canary or non-target-preserving transfer;
- a changed source allowlist or direct legacy embedding activation; and
- any row, group, semantic-family, risk, or provenance reconciliation failure.

## Reproduction

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  scripts/ops/legal_ir/audit_legacy_autoencoder_features.py \
  --old-state /home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json \
  --new-state /home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-safe-legacy-port-v2-20260723T074055Z.state.json \
  --transfer-report /home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/test-logs/legal-ir-autoencoder-safe-legacy-port-v2-20260723T074055Z.report.json \
  --canary-report /home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/test-logs/legal-ir-autoencoder-safe-legacy-port-v2-20260723T074055Z.canary.json \
  --output workspace/test-logs/legal-ir-legacy-feature-inventory.json
```

The CLI refuses to overwrite an existing output. Remove or choose a fresh
destination before reproducing the audit.

Unit validation:

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  -m pytest \
  tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_feature_inventory.py \
  -q
```
