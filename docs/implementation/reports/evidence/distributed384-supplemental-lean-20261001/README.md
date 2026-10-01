# Supplemental native Lean interpretations — 2026-10-01

This evidence records four additive native interpreters: authorization,
concurrency, cryptographic protocol, and refinement. They connect to the
source/candidate replay gate used by the distributed 384d checkpoint workflow.
The frozen numerical training contracts and checkpoint weights were unchanged.

Validated implementation:
[`a4d05c2bf`](https://github.com/endomorphosis/ipfs_datasets_py/commit/a4d05c2bf3cff58c0f323c68b556648f07568210).
The checkout's prior base was
[`493911c2`](https://github.com/endomorphosis/ipfs_datasets_py/commit/493911c2b89cbe2747c2a09ee887a30f8f2b66af).
Native receipts pin the actual producer source bytes. The archived runs and
full test counts below describe `a4d05c2bf`; any subsequent merge validation is
recorded separately and does not retroactively change these results.

## What the checks establish

Supported native declarations now have executable or relational Lean semantics:

- Authorization retains ground facts, extensional rule bodies, positive and
  negative atoms, typed guards, issuer checks, queries, and precedence. Empty
  policies and unsupported rule semantics fail explicitly.
- Concurrency interprets literal guards and `skip` effects, component/environment
  ownership, single-step atomic regions, explicit fairness and rely/guarantee
  declarations, and bounded schedules. General state mutation remains unsupported.
- Protocol interprets ground symbolic terms, permitted traces, adversary
  capabilities, channel access, replay, knowledge, and conditional protocol
  queries. Role processes and observational equivalence remain unsupported.
- Refinement interprets finite labelled nonstutter graphs, bounded directional
  simulation and initial-state coverage. Empty enabled initial-state sets and
  stronger uninterpreted statements are rejected.

Tests include real Lean proofs of finite semantic consequences and deliberate
false propositions that Lean rejects. The checkpoint reports themselves record
syntax/type checks of generated declarations. Neither kind of check establishes
that an authored model describes source software correctly or that a generated
program satisfies a security specification. All qualification, admission,
source-fidelity, promotion and proof-authority flags remain false.

## Unchanged context versus a separately authored supported model

The earlier Security fixture is preserved byte-for-byte. Its richer declarations
are not weakened automatically to make the new emitters accept them.

| Input and implementation | Supported families | Native checks | SANY |
| --- | ---: | ---: | ---: |
| Historical report for the original context | 12/16 | 15/19 | 1/1 |
| Same original context with the additive emitters | 13/16 | 16/19 | 1/1 |
| Separately authored supported context | 16/16 | 19/19 | 1/1 |

The unchanged-context improvement is authorization. Concurrency, protocol and
refinement remain blocked for unsupported metadata, observational equivalence,
or richer semantics. The separately authored control uses explicit supported
fragments and is identified as a new context throughout its reports. Its 16/16
result is adapter coverage, not an automatic repair of the old context or a
learned-model accuracy improvement. See [authored results](authored-results.json).

## Existing checkpoint inference

One selected tuning row per domain was inferred through each existing merged
checkpoint using only ID, source text and its precomputed embedding. The
unchanged prediction then received explicit caller-authored formulas and native
models. No new model training, weight update, holdout evaluation or benchmark
performance comparison occurred.

| Domain | Supported selected families | Native syntax/type checks | SANY | Complete declared dependencies |
| --- | ---: | ---: | ---: | --- |
| IntentIR | 9/9 | 20/20 | 1/1 | **No: auxiliary control-flow state remains partial** |
| SecurityIR | 16/16 | 19/19 | 1/1 | Yes, within the supplied fragments |
| UI/UX IR | 9/9 | 10/10 | — | Yes, within the supplied fragments |
| LegalIR | 9/9 | 10/10 | — | Yes, within the supplied fragments |

Intent's `all_requested_dependencies_supported` remains false even though the
emitted native syntax checks pass. All domains retain
`context_inferred_by_model=false` and `complete_target_semantics=false`.
The added formula/model declarations are not autoencoder predictions. See
[checkpoint results](checkpoint-results.json) and the archived exact prediction,
context, source-input, generated Lean and execution receipt trees.

The checkpoints are those from the
[earlier distributed training round](../distributed-384-local-hub-20261001/README.md).
They are identified by these complete-checkpoint SHA-256 values:

| Domain | Checkpoint SHA-256 |
| --- | --- |
| IntentIR | `a3d8550144bbd10d7a2aebe8da034dbcb0114d3f698c7cdb1ea496a99d7a2308` |
| SecurityIR | `2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5` |
| UI/UX IR | `94d535f43fde2c95be0ad794faad85f3f7d4625a05066e244b61cd9ff66d304a` |
| LegalIR | `dc02475b033e1e849e880e3c3cb30e2f2a432e5e54022296e571731d16139543` |

## Tests and immutable evidence

**728 distinct tests passed; three skipped.** The completed logs record:

- [117 targeted supplemental tests](supplemental-tests.log).
- [28 independent replay/integration tests](replay-boundary-tests.log).
- [611 broad regression passes and three skips](regressions.log).

Fourteen integration cases occur in each run. Counting each once gives
`611 + (117 - 14) + (28 - 14) = 728` distinct passes. Replay regressions reject
wrong domains, forged or archived live handles, rehashed bridge/expression
spoofs, and attempts to promote declarations into authority.

After merging concurrent upstream work, an additional affected-integration run
passed **160 tests** at
[`fc06895c7`](https://github.com/endomorphosis/ipfs_datasets_py/commit/fc06895c7b832d0180f66f510b226779e6b8df7e).
See [post-merge validation](postmerge-tests.log). These overlap the original
cases and are not added to the 728-test total. The merge retains `a4d05c2bf` as
an ancestor; the new emitters and distributed implementation are unchanged.

[evidence.tar.gz](evidence.tar.gz) contains complete `authored/` and
`checkpoints-run-01/` trees and `run_checkpoint_checks.py`. It is deterministic:
sorted regular-file members, fixed mode `0644`, zero tar times and owner IDs,
empty owner names, and a gzip header with zero time and no filename. Its SHA-256
is `6d5bf85b2459f1f4ddb429faf9ae241baf64fba6f68ab7e66c5f07e7e28fb641`.

The exact finalized [authored archive](authored-native-evidence.tar.gz) is also
preserved with its original tar metadata and SHA-256
`fa60d10692448c95fb590d6a1ef8febbb2ba06bfbf6fe871c8a84f65204d7c02`.
This historical archive is distinct from the normalized deterministic bundle.
[artifact-manifest.json](artifact-manifest.json) records archive and member
hashes, copied summaries and completed test logs.

## Reproduction

Extract the deterministic bundle under the matching released datasets checkout.
The authored control is self-contained apart from the installed tools:

```bash
PYTHONPATH=. python authored/reproduce.py \
  --baseline-dir authored/run-01/unchanged-original-context \
  --output-dir /tmp/supplemental-lean-authored-replay
```

The archived `authored/replay-command.txt` records tool prerequisites. Use a
fresh output directory. The recorded toolchain is Lean 4.34.1, Java 17 and
`tla2tools` 1.8.0; execution receipts contain tool SHA-256 values.

The checkpoint replay additionally needs the previous distributed round's
coordinator inputs and merged checkpoints with valid local references:

```bash
PYTHONPATH=. python run_checkpoint_checks.py \
  --previous-run /path/to/previous/distributed384/run-01 \
  --output /tmp/supplemental-lean-checkpoint-replay \
  --lake /path/to/installed/toolchain/bin/lake \
  --java /path/to/java17/bin/java \
  --sany-jar /path/to/tla2tools.jar
```

The archive preserves the exact inference inputs and checkpoints' hashes; it
does not duplicate the previously published weight files. Saved receipts are
historical evidence and cannot substitute for a new live replay handle.

## Hugging Face publication

The evidence was uploaded beside the existing checkpoints in all four model
repositories. Each content-addressed manifest links its unchanged checkpoint
publication and the tested implementation commit. Both uploaded files were
downloaded at the new immutable revision and their SHA-256 values verified.
No checkpoint weights or defaults were changed.

- [Publicus/intent-ir-autoencoder](https://huggingface.co/Publicus/intent-ir-autoencoder/blob/bef0ed09b8bbb8d12255859bea39e336dee1fd38/training/structured384/fd9d9b655650583be0d76972ac3b9c67905628294ba2df38ef59fb6d1c8b1fc5/projection-checks/3b4211bf2e3f0e54b06c88110c1873d80151d4ead9faa251b25834d95ae4814c/manifest.json) — revision `bef0ed09b8bbb8d12255859bea39e336dee1fd38`.
- [Publicus/security-ir-autoencoder](https://huggingface.co/Publicus/security-ir-autoencoder/blob/363756ec522ab388ea27a41fc3c0e4cc09e91ed3/training/structured384/fcab87ade962350c30a3e80d2f7bd3385d60bcfc666e0ba74955ca8e4008074c/projection-checks/5156075957316b93b5e80fd5fc01e954554b2cb6a7ee6850d2648024835a7e0d/manifest.json) — revision `363756ec522ab388ea27a41fc3c0e4cc09e91ed3`.
- [Publicus/ui-ux-ir-autoencoder](https://huggingface.co/Publicus/ui-ux-ir-autoencoder/blob/22c434c187d83fa608f160a9aacd837f3e1d3b7c/training/structured384/20c621da5b717eb7fb8174df991efb593bcd846e0d68a3edd62f3151ae041157/projection-checks/6a855257f27a1663ac8c850f07eb82171325abdda73f832f741fa4cb9064b803/manifest.json) — revision `22c434c187d83fa608f160a9aacd837f3e1d3b7c`.
- [Publicus/legal-ir-autoencoder](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/f1d17d14c08b8c0309a7d1a76b5d057471149066/training/structured384/0a70e2ca59bb14791ae52ba8cd5253dc66bf7b2ae20fa23908a3bd1f9410d1e5/projection-checks/8d47ee064c058712df1b484ec25449886ed01e910108217fd978854b4d3a2894/manifest.json) — revision `f1d17d14c08b8c0309a7d1a76b5d057471149066`.

[Publication receipts](publication/receipts.json) and the
[append-only publisher](publish_evidence.py) are retained here.
