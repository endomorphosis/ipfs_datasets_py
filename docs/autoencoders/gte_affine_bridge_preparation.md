# Affine bridge preparation

The 768→384 affine adapter, exact-source pair handoff and frozen teacher gradient boundary are implemented. This preparation ran no optimizer or distillation steps. The target GTE assets remain absent, so real 768D embeddings and trained transfer results remain unavailable. The existing 8D and 384D workers keep their private runtime/checkpoint contracts.

See the [full migration plan](gte_multilingual_migration_plan.md) and [multilingual producer preparation](gte_multilingual_preparation.md). The first transfer branch can reuse the selected differentiable Torch sequence decoder; the sparse Legal and NumPy structured paths need exported alignment targets or separate differentiable replacements.

## Reused teacher contract

The selected Legal checkpoint is raw_ce-1729-checkpoint.json under artifacts/source-reconstruction-v2-20261001/run-01/legal_ir. Its SHA256 is 6e3f4d731d798aa2732afc37bd74fec34da3267a323844975d2dab78f59f9c61. The [teacher binding](../../../../artifacts/gte-affine-bridge-preparation-20261001/run-01/teacher-binding.json) verifies its 14 listed implementation files and 13 tensor shapes without loading a model.

This checkpoint uses identity input normalization: mode none, 384 zero means and scale 1. General center_rms checkpoints apply their saved training-only mean and scale **before** the residual projection. The bridge uses that exact convention:

~~~text
768D source vector → new affine adapter
→ (adapted384 − saved_mean384) / saved_scale
→ residual projection → conditioning → GRU → token logits
~~~

The teacher output codec is typed-json-lexical/v1, vocabulary size 32, with PAD=0, BOS=1 and EOS=2. Its saved generation budget is 512 output tokens. The target encoder's 8192-token input ceiling does not enlarge this decoder budget. Later training must enforce the saved output budget and exact vocabulary/prefix policy, not only the numerical helper's generic bounds.

The selected checkpoint's archived exposed tuning result is objective 0.13201065 with **0/60 exact targets**, 60/60 valid candidates and 84/240 correct varying leaves. These are archived diagnostic observations, not a new semantic evaluation. They keep the teacher qualification gate open. A low loss alone does not authorize its labels for KD.

## Implemented components

| Component | Contract |
| --- | --- |
| [Teacher binding](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_bridge_teacher.py) | Exact checkpoint/source pins, tensor geometry, codec, saved transform, split provenance and archived tuning observations |
| [Pair preparation](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_bridge_pairs.py) | Rechecks the complete 384D corpus and task manifest, binds exact-source 768D receipts, and preserves existing memberships |
| [Numerical bridge](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_affine_bridge.py) | Independent CPU float32 affine weights, frozen teacher logits with adapter gradients, and strict private checkpoint reload |
| [Offline CLI](../../scripts/ops/autoencoder/prepare_gte_bridge.py) | Preparation or an explicit local teacher gradient probe; no fitting command |

The adapter has new 384×768 weights and 384 biases. Seeded construction preserves CPU RNG and thread settings. Adapted outputs receive a distinct representation ID bound to adapter weights, the teacher checkpoint, teacher transform and both source representation IDs. They are never genuine GTE-small producer outputs; source_representation_id names the alignment reference coordinates. No prefix copying, vector padding, adapter L2 normalization or checkpoint relabeling is used.

The differentiable path calls the private teacher model directly with explicit decoder-prefix tokens. It freezes teacher parameters and keeps adapter autograd. Runtime.infer uses inference_mode and list conversion, so it cannot serve this gradient path. The diagnostic probe restores tensor state, existing gradients, per-module modes, requires_grad flags and CPU RNG. Neither eval alone nor a frozen sparse/NumPy runtime supplies a differentiable teacher.

Pair preparation exports vectors, source/group/split identities, reference hashes and receipt pins; it does not export reference target payloads. Teacher predictions and unlabeled rows cannot count as reference supervision. Only retained development train/validation tasks enter the selected-domain pair set. Source-vector geometry and declared IDs do not authenticate the original 384D encoder execution.

A second complete audit replaces only the coordinate payload with actual bound 768D receipts. It checks new identical-vector leakage, contradictory references and deduplication across domains and connected groups. Newly affected rows join the exclusion accounting; existing splits are not rewritten. Missing receipts never cause fallback vectors.

## Retained evidence

[Preparation run-01](../../../../artifacts/gte-affine-bridge-preparation-20261001/run-01/summary.json) is unavailable, with zero pairs. Of 2640 archived rows and 1920 retained source tasks, 480 Legal development tasks need receipts; the other 1440 retained tasks belong to the other three domains. All 720 archived cross-split quarantines remain excluded. The manifest SHA256 is 619a7eb83bd1a66d78857506072a0c102d172d00bc204457e994e661841ebe55.

The [native teacher probe](../../../../artifacts/gte-affine-bridge-preparation-20261001/probe-01/summary.json) loaded the actual pinned 384D teacher in a separate CPU process. Its input was explicitly synthetic: a fixed normalized sine vector with 768 coordinates and a BOS-only decoder prefix. It ran autograd.grad with no optimizer. Weight and bias gradient L2 norms were approximately 4.758727. Teacher and adapter states stayed unchanged; the untrained bridge checkpoint reloaded exactly. Its manifest SHA256 is 793641a2a43f6141f6cb9698ebd4609e365eb5e8dd4e784be1c10fcf2f02cac5.

This demonstrates local differentiability through the actual teacher weights. It does not demonstrate real target embeddings, useful learned alignment, IR fidelity, fitting, KD or teacher qualification. The untrained-bridge.json artifact is initialized adapter state, not a trained model.

The [verification record](../../../../artifacts/gte-affine-bridge-preparation-20261001/verification.json) binds preparation/probe outputs, inputs and code. Earlier numerical receipt files and model code remain unchanged. Prior planning documents were snapshotted before progress updates; the old multilingual preparation ledger describes that earlier documentation revision.

## Reproduce the bounded preparation

Run from the repository with fresh output/cache identities:

~~~bash
python scripts/ops/autoencoder/prepare_gte_bridge.py prepare \
  --config configs/autoencoders/gte_bridge_preparation_v1.json \
  --expected-config-sha256 2185d71d11db554bc88c7185cb7d87fccfdf1c706ae548fa4846dbe6766c0c20 \
  --output-directory /home/barberb/lift_coding/artifacts/gte-affine-bridge-preparation-20261001/run-02

python scripts/ops/autoencoder/prepare_gte_bridge.py probe-teacher \
  --teacher-checkpoint /home/barberb/lift_coding/artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json \
  --expected-teacher-sha256 6e3f4d731d798aa2732afc37bd74fec34da3267a323844975d2dab78f59f9c61 \
  --domain-id legal_ir \
  --output-directory /home/barberb/lift_coding/artifacts/gte-affine-bridge-preparation-20261001/probe-02 \
  --seed 1729 --threads 1 --memory-limit-mib 16384 --cpu-time-limit-seconds 120
~~~

Preparation exit code 1 means unavailable or partial pair coverage. The gradient probe applies offline environment settings and per-process CPU/address-space limits before model imports, uses a private adjacent cache directory, and returns local output files. It does not reserve aggregate resources across lanes.

Once qualified 768D receipts exist, bind a new receipt file by hash in a new preparation configuration. Keep the earlier zero-receipt snapshot immutable. Fit the adapter only on training pairs, tune on validation and preserve original gold/reference evidence. Teacher-transfer and KD branches still require frozen qualified donor scope and screened WP05 exports; independent reference/alignment work can proceed under its own declared gates.

## Validation and remaining work

All 494 focused checks passed: the earlier 324 plus 29 pair, 71 teacher-binding, 54 affine/gradient and 16 bridge CLI checks. Unit numerical and receipt tests use synthetic fixtures. The separate native probe is one real-teacher/synthetic-input case.

WP06 is in preparation. Actual fitting, paired-source loss measurements, semantic evaluation, masked KD, supervised comparisons and optimizer-resume support are still outstanding. WP04 still needs real target-encoder numerical and resource qualification. WP02/WP05 still govern teacher labels. No runtime default, donor checkpoint, registry publication or existing worker implementation was changed.

