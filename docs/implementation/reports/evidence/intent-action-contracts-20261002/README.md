# Learned explicit Intent action contracts — 2026-10-02

A new experimental 384-dimensional Intent readout reconstructs explicit native
preconditions and effects from a bounded authored language. Its 24 held-out
compositions reconstructed exactly. A separate live replay then passed those
actual learned contracts through the supervisor's optional advice consumer and
Lean checks against **one** unchanged SecurityIR prediction for an addition
function. All 24 contracts were checked; their outcomes were one satisfied,
eight refuted, and fifteen with no enabled inputs.

This exercises learned advice and finite contract checking, not a complete
supervisor-daemon or Terminal Bench lifecycle. The earlier permission-only
instruction `the agent may delete the report.` did not declare an effect. The
new profile requires explicit `requires` and `ensures` clauses rather than
inventing effects for that instruction. It is distinct from the earlier local
paired-text Intent checkpoint.

## Training and held-out reconstruction

The [training plan](training-plan.json) fixes seed `42017` and 144 authored
combinations: six actors, two operand orders, four thresholds, and three
operators (`+`, `-`, `*`). It assigns **96 training, 24 validation, and 24 test**
compositions. Vocabulary, scalar classes, and grammar are shared across these
partitions. This is a composition holdout, not unseen-vocabulary evaluation,
general SkillCenter accuracy, or independently reviewed semantic gold.

Targets are native IntentIR documents with a fixed, explicitly unbound source
reference. Its hash identifies a placeholder declaration; the model does not
predict per-instruction hashes. Numerical inference produces the raw native
target. A separate complete-source audit permits replacement of only the source
reference with the exact original instruction identity. Raw and bound documents
remain separately recorded; source disagreement never repairs the prediction.

The shared structured head uses cached GTE-small embeddings and inherits the
Legal projection unchanged. Training fits scalar classifiers, while validation
selects the ridge value. The [fit seal](fit-seal.json) records the checkpoint
before test texts, targets or embeddings are materialized. Test data is not used
to fit weights or select the model.

| Held-out test condition | Exact native targets | Native-valid semantic variable-leaf accuracy |
| --- | ---: | ---: |
| Actual trained head and matching embeddings | 24/24 | 100% |
| Zero head | 0/24 | 29.17% |
| Shuffled embeddings | 0/24 | 34.03% |

The [training summary](training-summary.json) also records 24/24 complete source
agreements, **0.2546 seconds** of fitting and **5.5805 seconds** for the complete
CPU training/evaluation script. These are correctness-run timings, not a
comparative throughput result. The frozen embedding projection was not trained
to improve reconstruction. Later supervisor and Lean work is outside those
timings.

The new Intent checkpoint is
`4f3fd17ea2d908fe36c57a444517f3cc0a983cab26f0f67f2e32371e25def3cd`.
Its original Legal parent is
`969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62`.
The existing Security checkpoint is
`2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5`.
[checkpoint-references.json](checkpoint-references.json) records these identities;
parent and Security weights remain unchanged. No model weights are copied into
this Git evidence directory.

## Actual supervisor and Lean replay

The [native summary](native-summary.json) retains all 24 instructions and all
216 bounded instruction/input combinations: the same nine code inputs are
checked for each instruction. There is **one distinct Security source**, not
24 coding tasks:

```python
def derive(capacity: int, threshold: int) -> int:
    return capacity + threshold
```

Both integer parameters range independently from −1 through 1. The caller
explicitly maps Intent `left` to `capacity` and `right` to `threshold`; the system
does not infer a correspondence between arbitrary instruction and code names.

| Contract outcome | Instructions | Meaning of successful Lake check |
| --- | ---: | --- |
| Satisfied | 1 | Every enabled finite transition satisfies the declared effects, with an enabled witness |
| Refuted | 8 | A real initial-state transition and matching ProgramIR outcome witness a false effect |
| No enabled cases | 15 | Preconditions exclude every input in the selected bounds; no positive satisfaction claim |
| Unsupported or omitted | 0 | All supplied instructions remain in the denominator |

There are **33 enabled cases** and **24 counterexample cases**. Thresholds that
exclude the chosen input bounds explain the no-enabled outcomes. Successful
reconstruction of a requested subtraction or multiplication contract does not
make addition satisfy it. A compiled counterexample remains a refutation; an
empty enabled population remains unsatisfied.

The replay consumes the actual new Intent checkpoint and the existing published
Security checkpoint. It recomputes embeddings from original text on CPU and
passes no stored targets or embeddings into inference. The Security source is
inferred once, then its unchanged candidate is reused for the 24 contracts.
The supervisor independently replays Intent inference and preserves raw versus
provenance-bound identities. Associations lower only the source-audited declared
predicates, with an explicit parameter mapping. The existing live gate checks
the resulting complete finite state/ProgramIR relation and all condition values.

[input-references.json](input-references.json),
[source-only-instructions.json](source-only-instructions.json), and
[execution-environment.json](execution-environment.json) record the exact input
selection and CPU correctness scope. [producer-sources.json](producer-sources.json)
captures 184 datasets modules, four supervisor modules, the script, and input
file identities. Runtime direct disk pins are limited inventories; native gate
receipts separately check their imported producers and selected Lake/Lean
binaries. Neither claims a complete Python/dependency/toolchain capsule.

## Tests and documentation checks

There are **391 distinct passing tests**: 210 datasets and 181 supervisor tests.

| Saved log | Result | Counting rule |
| --- | --- | --- |
| [Initial datasets suite](datasets-initial-tests.log) | 194 passed, 2 skipped | Preserve the original result |
| [Native gate rerun](datasets-native-gate-tests.log) | 17 passed | Adds the two previously skipped native cases; fifteen overlap |
| [Live replay script tests](datasets-smoke-script-tests.log) | 5 passed | Five additional tests |
| [Immutable Hub resolver tests](hub-resolver-tests.log) | 9 passed | Nine additional isolated loader tests |
| [Supervisor suite](supervisor-tests.log) | 181 passed | Includes actual checkpoint replay and optional task-context boundaries |

The two initially skipped native tests passed when rerun with the native checker
available. They are not counted twice. The tests cover strict source grammar,
permission-only abstention, ordered/repeated operands, explicit old-state
references, raw/bound provenance replay, wrong or missing effects, type and
identity mutations, explicit parameter maps, all three finite dispositions, and
supervisor fail-open behavior.

The separate [publisher validation](publisher-validation.log) checks the complete
release file allowlist, all 24 source/prediction joins, recomputed disposition
and case counts, captured source identities, and deterministic archive contents.
[Thirteen publisher helper controls](publisher-hardening-tests.log) passed;
these artifact-publication controls are recorded separately and are not added
to the 391-test implementation total.

All four required supervisor documentation commands passed locally: primary-doc
vocabulary, maintained relative links, packaging version alignment, and closeout
navigation markers. Their [exact log](documentation-gates.log) is retained. This
does not imply a green remote CI result. The remote documentation job
for the tested supervisor commit is
[infrastructure-blocked](https://github.com/endomorphosis/ipfs_accelerate_py/actions/runs/36954030333/job/110672898146):
GitHub reports that the account is locked due to a billing issue. It executed
zero steps. This is not a code-test failure or a passing remote check.

## Reproduction, implementation and publication

The [implementation guide](../../../../autoencoders/intent_action_contract_training_384.md)
documents training, inference, the source codec, explicit association APIs and
the opt-in supervisor configuration. Reproduce the training with the exact
parent and pinned local embedding assets, using a fresh output directory. The
subsequent repository command is:

```bash
CUDA_VISIBLE_DEVICES='' python scripts/ops/autoencoder/check_learned_intent_action_effects_384.py \
  --intent-config /path/to/intent-config.json \
  --security-config /path/to/security-config.json \
  --tests-file /path/to/training-01/test-rows.json \
  --source-inputs /path/to/source-inputs.json \
  --lake /path/to/native/lake \
  --left-parameter capacity --right-parameter threshold \
  --output /path/to/fresh-native-output
```

The script extracts a source-only view before inference; it does not send the
test file's labels or stored embeddings to either advisor. Local artifact paths
in configurations must resolve to the exact checkpoint and embedding bytes.
[run-artifacts.json](run-artifacts.json) provides a complete hash inventory of
the training and native runs, including the checkpoint identity without copying
its weights. Exact tested code commits and the reviewed Hugging Face publication
receipt are recorded separately from inference claims.

The tested datasets implementation is
[`79e8261611518e8f02c7dbbd33f20b77ba3bce5b`](https://github.com/endomorphosis/ipfs_datasets_py/commit/79e8261611518e8f02c7dbbd33f20b77ba3bce5b),
preserving concurrent upstream `144030faa` in its ancestry. The tested supervisor
implementation is
[`2ea2edbe4ba1406b82c5e5e41b198ce0073b7afc`](https://github.com/endomorphosis/ipfs_accelerate_py/commit/2ea2edbe4ba1406b82c5e5e41b198ce0073b7afc).
Both implementation commits are pushed. The reviewed checkpoint is published as
an experimental version, with immutable identities and download verification
recorded below.

A separately added datasets Hub resolver validates immutable manifest and raw
checkpoint identities, with local-cache-only resolution by default. It was not
imported by the original native proof run and does not change that run's tested
producer identity. Its separately tested, pushed implementation is
[`54cbb4800110c983ae6202984a04b5db3d6fcf19`](https://github.com/endomorphosis/ipfs_datasets_py/commit/54cbb4800110c983ae6202984a04b5db3d6fcf19).
The post-publication downloaded-checkpoint replay is recorded separately from
the original 24-contract native run.

## Published checkpoint and downloaded inference

The [release manifest](publication/manifest.json) and
[upload receipt](publication/receipt.json) are copied exactly from the reviewed
package. The checkpoint, manifest, and evidence archive were uploaded to
`Publicus/intent-ir-autoencoder` at immutable revision
`d12dd68fcc54441ded09ed217526e02b7bdfd9e3`:

- [Experimental checkpoint](https://huggingface.co/Publicus/intent-ir-autoencoder/resolve/d12dd68fcc54441ded09ed217526e02b7bdfd9e3/experiments/action-contracts-384/v1/5dd54fae01f9a5faa543195e5455b28a5c8cbdcf543cf024ae535aacabea3032/checkpoint.json)
- [Release manifest](https://huggingface.co/Publicus/intent-ir-autoencoder/blob/d12dd68fcc54441ded09ed217526e02b7bdfd9e3/experiments/action-contracts-384/v1/5dd54fae01f9a5faa543195e5455b28a5c8cbdcf543cf024ae535aacabea3032/manifest.json)
- [Complete evidence archive](https://huggingface.co/Publicus/intent-ir-autoencoder/resolve/d12dd68fcc54441ded09ed217526e02b7bdfd9e3/experiments/action-contracts-384/v1/5dd54fae01f9a5faa543195e5455b28a5c8cbdcf543cf024ae535aacabea3032/evidence.tar.gz)

The manifest SHA-256 is
`5dd54fae01f9a5faa543195e5455b28a5c8cbdcf543cf024ae535aacabea3032`.
The archive contains 199 members, is 2,696,550 bytes, and has SHA-256
`9a34675aae60af80537e265fc302bce94edb52d0a7f408233df1bfd5fc4557bb`.
The upload verifies downloaded manifest, checkpoint and archive bytes. The
published archive retains full training/evaluation and native-run evidence;
neither the archive nor checkpoint weights are copied into this Git directory.
The default release and model selection remain unchanged.

The [exact Hub reference](hub-reference.json) selects that revision and checkpoint
hash. A fresh [downloaded-checkpoint verification](hub-consumer-verification.json)
resolved it through the datasets Hub loader, then consumed the downloaded bytes
through the actual supervisor advisor. Numerical replay passed, and both the raw
prediction and source-bound document matched native-run case `000`. This is a
separate one-instruction inference replay; it does not claim to rerun all 24
Lean builds after downloading.

The [full advice](hub-consumer-advice.json),
[verification script](verify_hub.py), and
[exact log](hub-consumer-verification.log) preserve that execution. Downloaded
checkpoint bytes remained unchanged, with no default promotion or proof
authority. [artifact-manifest.json](artifact-manifest.json) binds every copied
file except itself by relative path, byte size and SHA-256.

## Remaining scope

This demonstrates a learned explicit contract readout and bounded correspondence
checks under the declared mathematical-integer source model. It does not prove
Python runtime equivalence, arbitrary natural-language intent, whole-goal
completion, security-policy compliance, or LegalIR/UIUXIR constraint composition.
Freeform SkillCenter instructions, further grammar constructors, branches,
loops and independent corpus evaluation remain outside this profile. No source
Python execution, proof/admission authority, automatic model promotion, full
daemon run, Terminal Bench score, token-saving result or comparative throughput
improvement is claimed.
