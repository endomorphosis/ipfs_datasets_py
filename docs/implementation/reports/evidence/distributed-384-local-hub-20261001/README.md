# Four-domain local training and Hugging Face exchange, 2026-10-01

All four published structured 384d heads completed a real local threaded training round, uploaded disjoint updates, and were reconstructed by an independent DuckDB owner using Hugging Face discovery. Exact downloaded checkpoint and inference replay passed. The inherited Legal projection was unchanged.

This is a full-corpus ridge-head refit over the frozen published projection and target vocabulary, using the original authored composition controls and their previously computed CUDA GTE-small embeddings. It is not neural gradient training, a new embedding benchmark, a fresh holdout evaluation, or training on the full CVEfixes/SkillCenter/US Code corpora.

| Domain | Training rows | Shards | Active threads | Tuning exact IR | Worker phase rows/s | Checkpoint patch / full bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| intent_ir | 360 | 4 | 3 | 120/120 | 251.1 | 127,095 / 447,990 |
| security_ir | 360 | 4 | 3 | 120/120 | 266.8 | 171,029 / 493,355 |
| ui_ux_ir | 180 | 2 | 2 | 120/120 | 370.5 | 130,297 / 383,180 |
| legal_ir | 360 | 4 | 3 | 120/120 | 275.1 | 126,927 / 447,408 |

Worker-phase timing includes local registration, input checks, scheduling, and durable update completion, and excludes Hub uploads and the coordinator solve. These single bounded runs do not establish a speedup over a serial run. Four threads were requested; the short jobs used two or three.

Checkpoint postimages were 65.3–71.6% smaller than complete checkpoint files. The factored shard updates contain dense projected features and sparse label indices; their aggregate size exceeded sending one full head per shard for these small heads. This run does not demonstrate total bandwidth savings.

## Correctness and scope

- The distributed head weights matched the original centralized fits within a maximum absolute difference of 6.48e-10; tuning predictions were unchanged.
- A separate local coordinator downloaded the same immutable input bundle and discovered every update through Hugging Face. It did not read the worker DuckDB.
- Fourteen unique shard updates, four merged checkpoint patches, four complete input bundles, and a standalone SecurityIR anchor were uploaded. All checkpoint downloads reproduced the exact local bytes and inference. Repeated publication returned the same acknowledged receipt.
- One physical machine was used. Automated tests also exercise two isolated host profiles, separate databases, real worker threads, missing shards, replay, interrupted work, and CLI execution.
- Final relevant suite: **486 passed, 5 skipped** after integration with main at `4f7ce5f6bee49c28f83c9589516e655c0fbe20ea`. Numerical producer pins and old published runtime files remain unchanged.

## Projection results

Projection reports are generated from actual target-free checkpoint predictions and are bound to candidate/source/head/projection identities. All default native families are attempted and their individual outcomes retained.

- SecurityIR: 120/120 source-bound program projections; eight additional families require context.
- UI/UX IR: 120/120 frame-logic structural projections; seven additional families require context. The supported route does not prove all UI facets.
- LegalIR: 120/120 deontic projections; five additional families require context.
- IntentIR: 60 supported cases each for Datalog, DCEC, deontic, first-order, frame, higher-order, Horn CHC, program, TDFOL, and temporal routes; other cases or families require richer contextual declarations.

Every full-family gate remains incomplete. These typed projection reports do not themselves run Lake or establish source semantics; they grant no qualification or promotion. Any separate Lake run is reported separately with its narrower scope.

## Reproduce and continue

See the [training guide](../../../../autoencoders/distributed_384_training.md). The [machine-readable receipt](results.json) includes immutable input, update, checkpoint, and anchor references, source pins, byte counts, timings, and family coverage. The four `*-inputs-reference.json` files can be passed directly to `fetch --reference`, followed by `work` and `merge --discover`. Each new host owns its own DuckDB and artifact directory.

To start a changed corpus or a new round from a downloaded candidate, use a new directory and `prepare --base <checkpoint>`. Supply the full intended corpus; prior sufficient statistics cannot be recovered from weights alone. The public defaults remain the previously reviewed experimental parents.

## Separate real SecurityIR Lake check

The merged SecurityIR weights produced 120/120 source-bound candidates that passed one real `lake build SecuritySourcePrograms` under Lean 4.34.1. The source-only inference run took 0.82 s; compilation and live issued-handle verification took 17.02 s. A source/candidate drift control was rejected. This checks the emitted bounded program definitions and types, not Python equivalence or a security specification. The eight other Security families remain unresolved.

See the [summary](security-lake-summary.json), [full evidence archive](security-lake-evidence.tar.gz), and [artifact hashes](security-lake-artifacts.json). A recorded successful receipt is historical evidence; it does not recreate the original live backend handle.

## Published evidence

- [intent_ir training and projection evidence](https://huggingface.co/Publicus/intent-ir-autoencoder/tree/3f8198aeae8858c3ae65f5e576dc6be2d1620f45/training/structured384/fd9d9b655650583be0d76972ac3b9c67905628294ba2df38ef59fb6d1c8b1fc5/evidence/fbc2a9179f0977e07d18fe52d8df19b12b894882bff209631f1e5dbeb3524664).
- [security_ir training and projection evidence](https://huggingface.co/Publicus/security-ir-autoencoder/tree/56f6cbc8ca17ad515d4294479b128e19a3ad5d5c/training/structured384/fcab87ade962350c30a3e80d2f7bd3385d60bcfc666e0ba74955ca8e4008074c/evidence/914c1915d62745c33d6b2696a67163902f09a855611da2041181e59d088103d1).
- [ui_ux_ir training and projection evidence](https://huggingface.co/Publicus/ui-ux-ir-autoencoder/tree/b03ca5bf66b3574d9d347b2863d90d6cea7a292c/training/structured384/20c621da5b717eb7fb8174df991efb593bcd846e0d68a3edd62f3151ae041157/evidence/4b489de453cda01638a1abdf76baf2325016f6515b4ea9a10ff38ee4d84903ad).
- [legal_ir training and projection evidence](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/27e9239241a49386f8576485d4f14caf9b523029/training/structured384/0a70e2ca59bb14791ae52ba8cd5253dc66bf7b2ae20fa23908a3bd1f9410d1e5/evidence/ac5c95baae7f8d1fc4c146e5930d41d5ad3340bbf3d899267feb34f99bfb820c).
