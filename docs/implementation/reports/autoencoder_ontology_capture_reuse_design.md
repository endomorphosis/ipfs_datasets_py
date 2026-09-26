# Worker-scoped ontology capture reuse

Documentation-only design, source inspection completed before 2026-09-25 07:35:31 UTC. No capture cache is implemented or qualified by this report. Capture records remain non-admitted observations.

Implementation follow-up: [capture observations](autoencoder_ontology_observation.md)
now retain direct exceptions and native converter-result statuses in worker
receipts. Native owner qualification and exact capture parity pass. Observed
transitive fallback gaps keep `reuse_qualified=false`; no result cache is enabled.

## Measured work and corrected reuse opportunity

The [r3 diagnostic profile](evidence/autoencoder_control_plane_plan/warm-target-profile-20260925-r3.json) records 21.244971448 seconds of profiled training: three `_capture_ontology` calls consume 14.693794156 cumulative seconds; nine `triples_from_sample` calls consume 13.284772236 seconds, including nine `modal_ir_to_flogic_triples` calls at 13.008462352 seconds. These nested times must not be added together. Profiling overhead makes these diagnostic costs, not an unprofiled speed estimate.

The [paired ablation receipt](evidence/autoencoder_control_plane_plan/shared-target-ablation-20260925.json), at `paired_runs[0][0].ontology_captures` (reference) and `paired_runs[0][1].ontology_captures` (native), contains the same three ordered batches:

| Batch | Membership, in observed order | Meaning |
| --- | --- | --- |
| 0 | `us-code-22-4021a-fce42ca5c6a35f9d`; `us-code-7-4817-c0a689415be61f9b`; `us-code-4-101-b2aadd69bb073b70` | Initial validation evaluation |
| 1 | `us-code-38-102-505a7bed1f409aa4`; `us-code-5-8410-545e1e69d31abb65`; `us-code-43-391a-cbc16163ce5b351b` | Training-cache priming evaluation |
| 2 | Same validation IDs and order as batch 0 | Candidate validation evaluation |

The IDs are observed directly; stage labels follow the evaluator schedule in [modal_autoencoder.py](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py), including `before_holdout_evaluation` and `training_cache_prime`. **Nine captures cover six distinct samples.** The earlier hypothesis that all nine were validation captures was incorrect. Successful reuse removes three repeated captures in this schedule, reducing producer computations from nine to six. Their individual costs are not established by the aggregate profile. The receipt verifies identical complete capture records between reference and native runs.

The ablation receipt SHA-256 is `db7d972c3fd33573d53187b5524fc037bd96aa9db25fb137f51ad0fd6ebf7fed`; the r3 profile receipt SHA-256 is `5f8ca0a8d522386b5d9482b72ad09f1ef38a822058c45dbdbb7f0db7c8307114`.

## Current dependency and mutation contract

[capture_samples](../../../ipfs_datasets_py/logic/autoformal/ontology_capture.py) reads `sample_id`, exact `text`, and `modal_ir`. It obtains existing frame triples or invokes the much larger fallback triple projection before keeping at most 32 qualifying triples. Recipient and procedure extraction can each instantiate `DeonticConverter(use_ml=False, use_cache=False, enable_monitoring=False)` and parse the text. These capture paths do not consult the recipient/procedure law indexes or their blob stores.

Both evaluator classes assign mutable records to `last_ontology_captures` at evaluation completion. Captures are outside the serialized evaluation dictionary, so numeric evaluation parity alone cannot qualify reuse. Training callbacks can mutate nested IR between evaluations. Frozen dataclasses do not freeze their lists and dictionaries.

An exact key must include a versioned capture-producer identity plus raw `sample_id`, raw text, and every field of the native modal IR graph. Do not use object identity, rounded sample keys, normalized text alone, or `ModalIRDocument.canonical_hash()`. Its `to_dict()` sorts formulas and frame candidates; frame serialization sorts matched terms, while capture fallback iterates live fields. Serialize native dataclass fields with explicit type tags, preserving sequence and mapping iteration order, list/tuple distinctions, primitive types, and signed floating zero. Recompute the key at every capture boundary. Unsupported classes, cycles, custom containers, subclassed IR, or instance/class method overrides take the existing uncached path.

Producer qualification must cover direct and transitive capture dependencies, not only `capture_samples`. At minimum it includes recipient/procedure functions, the converter/parser, modal codec/decompiler, native IR methods, ontology helpers, and their defining modules. Source-file hashes alone do not detect in-memory callable replacement. Dynamic imports of recipient/procedure helpers must be checked at each reuse boundary. Codec fallback also reads mutable `DEFAULT_MODAL_REGISTRY`; its raw profile and family lookup contents need a content guard, not merely registry object identity or source hash. A registry snapshot may itself be material work and must be timed. Changes should disable reuse or reject the scoped job before publication. No attempt should silently rewrite module paths or restore another caller's modifications.

## First implementation slice: observable completion before reuse

First add an internal companion result for capture, preserving the current public list-of-records API and exact exception behavior. It should report ordered input identities, producer identity, stage timing, and per-record completion/failure markers. Record the stage and exception type for every currently suppressed error; do not invent a successful empty result.

This is required because `triples_from_sample` suppresses frame access and projection errors, and `capture_samples` suppresses recipient/procedure extraction errors. `_capture_ontology` additionally returns an empty batch for certain import or capture errors. A legitimate empty recipient/procedure and a temporary failed extraction currently look alike. Only a completed, error-free observation may become reusable; a partial observation must be recomputed on the next call even if its input key is unchanged. An outer batch failure must not publish newly computed cache entries from the partial batch.

After qualifying this protocol, implement an explicit worker-owned context around native training. Keep ordinary evaluator calls uncached. A task-local context permits the existing helper call sites to remain unchanged; a model-owned context is also viable but needs explicit installation/restoration and handling of subclassed evaluators. Neither option should become a process-global result cache or a durable target artifact.

Use lazy per-record misses, preserve requested order and duplicates, and deep-detach both retained and returned records. Compare input and dependency identities before and after a miss; changed identities prevent insertion. Proposed initial limits are 256 records, 64 MiB of retained key/result payloads, 4 MiB per input key, and 1 MiB per encoded result, with bounded traversal depth. These are proposed limits, not measured requirements. Oversized/unsupported entries bypass reuse without truncating capture. Retain immutable encoded keys/results where feasible so byte accounting is concrete; release everything at context exit. Measure temporary allocation and RSS separately from retained-byte accounting.

## Validation and acceptance

Before enabling reuse, cover nested metadata/formula/frame mutations, formula and frame reordering, text/ID changes, duplicate IDs with different content, signed zero, output mutation, unsupported/custom types, dependency replacement, source-tree drift, registry mutation, and extraction failure followed by recovery. Verify whole-batch failure semantics, capacity bypass, context cleanup, nested contexts, and isolation between independent workers. Compare every ordered capture field and all ordered triples, not just counts or `admitted` flags.

Run paired native/reference owner-dispatched jobs against one frozen source tree, exact same source-bound samples, target bundle, checkpoint, update configuration, and failure dispositions. Require equal complete evaluations, capture sequences, accepted epochs/patches, candidate bytes and logical state. Do not reuse historical targets to claim semantic parity: the [target-growth investigation](evidence/autoencoder_control_plane_plan/shared-target-growth-20260925.json) already establishes changed bridge coverage and losses across earlier preparations.

Report setup, identity serialization, registry/dependency guards, capture misses, detached replay, retained bytes, hits, misses, bypass/failure reasons, and total owner completion time. The observed one-epoch schedule should produce six successful misses and three hits only if all six records qualify. Require an end-to-end improvement including all guard costs; a lower profiled capture count alone is insufficient. Longer searches may offer more reuse, but require their own measured schedule.

## Opportunity cost and provenance

Capture reuse removes repeated deterministic work; Arrow feature-table storage addresses a different cost. Moving nested ontology graphs to Arrow would require a lossless schema for ordered triples, metadata, complete failure evidence, and Python consumer behavior. It would not by itself remove repeat projection or recipient/procedure parsing. Conversely, capture reuse does not remove target hydration, the first six capture computations, Python scalar access, or checkpoint serialization. Compare measured total costs before broadening Arrow beyond the existing feature/embedding tables. A hydration microbenchmark is not acceptance evidence when native end-to-end behavior regresses.

Reviewed source hashes below bind this design inspection, not a claim that the tree remains unchanged. They differ from the historical profile, whose ontology-capture hash is `54f6aa38553ed84154f6f701e53571126a12cbd43beb38b6d9142ee50e975106`. Concurrent changes were observed in ontology capture, the parser, and `autoformal.__init__`; compiler behavior now includes multi-clause processing. The parent subsequently reported another source-drift abort during target preparation, before owner dispatch: `autoformal.__init__` changed from the reviewed `d11fa0...` to `827c103...`, and the parser from `36cc9f...` to `25ba8...`. That attempt supplies no native benchmark result. Recheck the complete dependency/source identities before implementation, then requalify historical capture outputs and test expectations under a frozen producer. This document adds no production changes, tests, or timed jobs.

| File under `ipfs_datasets_py/` | SHA-256 at inspection |
| --- | --- |
| `logic/autoformal/ontology_capture.py` | `730deb53ac0e2c63d97c1b9fef0d971de917c7feea3953d2054995fdcf54d773` |
| `logic/autoformal/recipient_reference.py` | `4f180765d49b173772eaa17e7582e0de9185a700e52bb7c235f966c24d517217` |
| `logic/autoformal/procedure_slot.py` | `f0de735845451825858ae5b6cabc1fe5f76acf435d211f985aec6ec73ea7238b` |
| `logic/autoformal/__init__.py` | `d11fa0b5318b98dec123b23eae5c950940918e57bb96a992660b7d06743925b5` |
| `logic/deontic/utils/deontic_parser.py` | `36cc9fd4851ac642a4998d2a87536ffa3dacf74fc6725a5328bd5efbd6a2cad9` |
| `logic/modal/codec.py` | `ecd57906b6ca534caf29598c4c983d019b5021f3bc71a38257900e5b9361b5f3` |
| `logic/modal/decompiler.py` | `ecc13e624136d3f9a2d56b7c699d1d9b309847d1c1c8050ba422203f1b10a119` |
| `optimizers/logic_theorem_optimizer/modal_ir.py` | `697b8e183fb966f01a0b81e4241154c38d2785277739518cbdfcc8db37695743` |
| `optimizers/logic_theorem_optimizer/modal_registry.py` | `e8a79d5612f50d3a842b72e618fc1903094dc4dd225688d9cb2d67bb4b0cb00a` |
| `optimizers/logic_theorem_optimizer/modal_autoencoder.py` | `d8f35525ccb1d2db2124fc8b5988e6dc6db0f198e94c73e553844e13cfa5a172` |
| `optimizers/logic_theorem_optimizer/autoencoder_training_worker.py` | `90dfe43fbec34a18d97047734f2f3ce7008b7c9ecfe3961acc97bc2128b3cfab` |
