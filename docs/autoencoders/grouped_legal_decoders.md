# Experimental grouped Legal source decoders

The grouped heads contribute source-only, ordered 2–8-member deontic requests
alongside the existing Legal autoencoder and decoder owners. They predict
actor/action character occurrences, O/P/F, member count and the caller's supplied
modal scope. V2 adds two masked byte convolutions and a learned profile-support
gate. Both published checkpoints remain experimental.

This contribution was reconciled against datasets main
`795d960170214d03e2eaf4c0a13ad4eb922c5c08` and workspace main
`b0ba1aaa9c8a3f1d0e42bca31aa710f1108c686e`. The earlier sixteen study reports
remain present with identical bytes. Recent
[normative wording](normative_wording_training.md) and
[contextual reconstruction](contextual_legal_reconstruction_runtime.md) work
remains intact. The concurrent [working-copy and twenty-study reconciliation](progress_reconciliation_20261006.md)
adds recovery, evidence and retention planning to this same effort; its grouped
interface is the renderer used by these learned heads. Their overlapping test
populations remain separate measurements. No historical 8D teacher, selected vector decoder, source-AE
checkpoint, native768 span model, or default runtime is replaced.

## Owners and compatibility

| Owner | Contract |
| --- | --- |
| `logic/formalization/autoencoder/legal_grouped_span_decoder.py` | Original grouped head and strict v1 model/Adam checkpoint |
| `logic/formalization/autoencoder/legal_grouped_span_decoder_v2.py` | Ordered local byte features, learned support, strict v2 checkpoint |
| `logic/deontic/coordination_decoder.py` | Closed ordered semantic request, native AST, normalized text and Lean renderer |
| `logic/autoformal/legal_coordination_evaluation.py` | Complete reference/output denominators and semantic IR field accounting |
| `optimizers/logic_theorem_optimizer/autoencoder_runtime_registry.py` | Explicit opt-in `legal_ir:source_conditioned_grouped_v2` reader |

Paths are relative to `ipfs_datasets_py/`. The four new model/renderer/evaluator
files retain their published bytes, so the published checkpoints keep their
producer identities. V1 and v2 schemas mutually reject one another. The new
registry adapter owns discovery and opt-in loading; it does not change a model
or checkpoint format and exposes no generic training or promotion capability.

Input is raw `source_text` plus explicit `modal_scope`, chosen from
`modal_over_actions` and `disjunction_of_norms`. Missing or unknown scope abstains.
Output is `legal-coordination-decode-request/v1`: an inclusive alternative,
universal actor predicate binding and ordered actor/modality/action members.
Only the current `deontic_fol` profile is supported. The eight-family Legal
requirement remains unmet by this head.

There is no 8D/384D/768D vector input or latent bottleneck. The historical 8D
teacher, vector formula sidecars, native768 single-rule span decoder and
registered `source_conditioned_formula_v1` have distinct producer, grammar and
checkpoint contracts. The existing 384D grouped source-training recipe also
rejects identical source inputs with conflicting targets. These new scope-paired
examples deliberately have different explicit scope inputs; they cannot be
silently fed to that recipe as identical input rows.

## Published checkpoint and loading

The selected v2 checkpoint has 306,317 parameters at epoch 3 / 480 AdamW updates.
Its complete recipe ran 2,400 updates and 38,400 balanced row presentations. The
[immutable release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/726386d3cb0ef068f275d4ded97fef71fdfeebf0/experiments/grouped-span-head-v2-20261006/run-02)
includes weights, target/split evidence, every final output and limitations.
The checkpoint SHA-256 is
`efd7f7e71159592672769c7f580112917381e9a854f021a72f8de1613d299b95`.
The [v1 release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/80087f53b1dff4811623079dd7d642347d6232bb/experiments/grouped-span-head-20261006/run-03)
remains separately available.

These are finite CPU PyTorch JSON checkpoints, not Transformers AutoModels.
Loading requires a local file, its exact expected SHA-256, the matching producer
files and the recorded Torch version (`2.13.0+cu130` for this checkpoint). It
downloads no weights and selects no version from vector width. For the CPU
prototype, set `CUDA_VISIBLE_DEVICES=''` before starting Python.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import (
    open_runtime,
)

runtime = open_runtime(
    "legal_ir", "source_conditioned_grouped_v2",
    checkpoint_path="checkpoint.json",
    checkpoint_sha256="efd7f7e71159592672769c7f580112917381e9a854f021a72f8de1613d299b95",
)
result = runtime.decode_formal_logic(
    "The Registrar shall publish notice or shall retain records.",
    modal_scope="modal_over_actions",
)
```

The sentence illustrates the API, rather than a correctness assertion about
unseen text. Retain status, blockers, support probability and null requests.
`formal_output` is `None` for refused/blocked predictions. A nonnull artifact is
syntax/rendering evidence: this call does not run Lake or verify legal meaning.
The adapter retains `source_interpretation_unreviewed`, `requires_validation`
and false authority flags.

## Evidence and remaining failures

The [machine-readable findings](../implementation/reports/evidence/grouped-legal-decoders-20261006/summary.json)
bind producer hashes, publication, original reports and the main-based replay.

| Measurement | Result | Scope |
| --- | ---: | --- |
| Selected v2 training fit | 2537/2560 | In-sample exact positive requests plus learned negative refusal |
| V2 positive selection | 64/64 | Separate authored selection sources |
| V2 negative selection | 64/64 | Learned profile refusal at fixed threshold 0.5 |
| Fresh v2 positive outputs | 64/64 | All 305 ordered actor/action occurrences exact |
| Fresh v2 learned refusals | 55/64 | Seven additional validation blocks; two unsupported requests emitted |
| Published v1 on same fresh positives | 40/64 | Training recipes differ; not a controlled architecture ablation |
| Known short-modal perturbations | 27/27 refused | Preserved diagnostic cases, not fresh legal gold |
| Seven retained 2024 official paragraphs | 14/14 refused | Two supplied scope probes; no reviewed targets or formalization coverage |

The 128 final cases derive from 38 correlated source-parent clusters. Their
references were sealed before fit and scored after checkpoint selection. They
are now exposed and cannot serve as the next untouched final benchmark.
Negative labels mean unsupported by this narrow grouped profile, not legally
false: single duties and qualified clauses can be valid law.

Main-based replay restored both model/Adam checkpoints byte-exactly and
reproduced all 256 selected-v2 selection/final predictions without new fitting.
Actual generated eight-member selection outputs render identically through
main's existing native owners. `lake build legal` accepts the constructed scope
witness and rejects a false narrow-scope claim. That witness does not establish
the statute's meaning or grant proof authority to every model output.

Two Conv3 layers and pooling distinguish the tested short spelling permutations
but still collide on some longer tokens with identical local neighborhoods.
Negative-only training leaves structural-head gradients/moments idle while the
shared/support trunk changes. Shared changes can still affect structural
predictions. Support confidence is not a legal-truth probability.

## Combine with the main training effort

Reuse admitted source/context targets and occurrence/attachment declarations
from `canonical_statement_scope`; use `alignment_lane_bundle` for future
raw/latent/reconstructed view identities. Preserve the existing review intake,
relation masks, numerical training/cache and native-family validation owners.
Implemented synthetic contracts do not supply independently reviewed legal
labels; retained admitted semantic pair counts remain zero.

Existing normative TRAIN wording can inform a new group-compatible fixture bank
after its provenance, scope, object boundaries and leakage groups are checked.
It does not automatically widen this head's input profile or establish reviewed
gold. Compare raw/PCA/AE/source-only conditions under matched architecture,
initialization, admitted targets, update and decoding budgets, with new final
source groups. Report unsupported emissions, learned refusal and incidental
validation blocks separately from exact IR, individual fields and vector loss.

The older source-bound group compiler and its parser/readiness changes require
a separate dependency port: twenty reachable definitions are absent from main
and six differ. They are retained in the reconciliation inventory, rather than
overwriting current parser/default behavior in this additive contribution.
Qualifiers, nested/exclusive alternatives, broader families, legal scope
interpretation and actual latent conditioning remain further work.
