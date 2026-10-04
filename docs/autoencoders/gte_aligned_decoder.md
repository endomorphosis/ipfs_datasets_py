# Load a fitted connection into the inherited 768D student

The [dual-donor initializer](gte_decoder_reuse.md) already preserves learned 8D
and 384D decoder bodies. The [affine fitter](gte_affine_alignment.md) can fit the
new 768-to-384 input connection from real same-source vector pairs. This stage
joins those artifacts into a separately identified private student. It replaces
only the two adapter tensors and preserves all 26 learned donor tensors, both
codecs, the saved input transform and the auxiliary connector.

The implementation is ready for a completed fit. The October 2 production
preparation reports unavailable: multilingual model/code directories are absent,
there are zero vector pairs, and no fit has executed. It creates zero aligned
checkpoints and loads no numerical model. Learned decoder reuse remains the
default; supported distillation follows interface alignment and donor
qualification.

## Handoff and identity

The command authenticates the complete parent alignment manifest, all its input
and implementation receipts, and its exact output inventory. It replays teacher
admission against the archived implementation tree, checks the original donor
pins and initialization binding, and recomputes the plan from admitted pairs.
Mode, status, fit flags, partitions, candidate counts and coverage must agree.
A prepared or unavailable parent cannot become a fitted student, even when its
plan is ready. No substitute vectors or seeded boundary are presented as fitted.

For a fitted parent, require four external file hashes: initialization, fitted
bridge, plan and fit report. The dependency-free handoff inspector checks the
selected validation winner, declared ridge objective and diagnostics, exact
float32 bridge values, retained decoder weights, transform and profile bindings.
It checks consistency of recorded evidence; it does not prove execution merely
from a report. The CLI supplies authenticated file bytes and independently
checks the complete pair coverage retained by the parent manifest.

The aligned bundle has schema `gte-aligned-dual-decoder/v1`. It retains the
original initialization, bridge, plan and report as unchanged nested snapshots,
then derives its current weights and tensor provenance. The original
initialization identity remains historical. The current representation identity
comes from the fit report and identifies adapted coordinates, not genuine
GTE-small producer vectors. Historical flags inside nested initialization do
not describe the current student.

| Current tensor origin | Count | State after construction |
| --- | --- | --- |
| Learned 384D decoder | 13 | Exact copied values, frozen |
| Learned 8D grammar decoder | 13 | Exact copied values, frozen |
| Fitted 768-to-384 adapter | 2 | Analytically fitted values, trainable |
| Original shared-condition-to-8 connector | 2 | Unchanged initialized values, trainable and unfitted |

Construction creates private CPU float32 storage. No donor tensor or optimizer
state is shared. It preserves the inherited 512-token primary output budget and
64-token grammar budget; the 8192-token encoder input limit is independent.
The auxiliary loss still reaches the primary adapter through frozen inherited
bodies. Both heads keep separate vocabularies and reference prefixes.

The primary boundary is marked fitted only after an admitted fit. The auxiliary
connector remains unfitted, so `boundary_alignment_required` stays true. No
decoder gradient training, KD, semantic qualification, encoder execution or
optimizer-resume capability is asserted. A new optimizer will be required for
later interface training.

## Private APIs and command

The implementation files are
[handoff contract](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_aligned_decoder_contract.py),
[private constructor and loader](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_aligned_decoder.py),
and [preparation command](../../scripts/ops/autoencoder/prepare_gte_aligned_decoder.py).
Inspection uses the standard library. Numerical construction/loading imports
Torch only for an admitted fitted parent.

The private APIs are:

~~~python
inspect_alignment_handoff(initialization, bridge, plan, fit_report,
    expected_file_pins=file_pins, expected_donor_pins=donor_pins)
model, checkpoint = create_aligned_decoder(initialization, bridge, plan, fit_report,
    expected_file_pins=file_pins, expected_donor_pins=donor_pins)
inspect_aligned_decoder(checkpoint,
    expected_file_pins=file_pins, expected_donor_pins=donor_pins)
model = load_aligned_decoder(checkpoint,
    expected_file_pins=file_pins, expected_donor_pins=donor_pins)
~~~

Authenticate original JSON bytes before supplying decoded objects; these APIs
cannot reconstruct arbitrary original file serialization. Also authenticate the
saved aligned checkpoint bytes before loading it. The command performs those
checks, synthetic gradient checks and exact saved reload automatically.

The checked-in [configuration](../../configs/autoencoders/gte_aligned_decoder_preparation_v1.json)
binds the current unavailable alignment run and immutable donor initialization.
From the repository root, use a fresh output directory:

~~~bash
python scripts/ops/autoencoder/prepare_gte_aligned_decoder.py \
  --config configs/autoencoders/gte_aligned_decoder_preparation_v1.json \
  --expected-config-sha256 2be8aa4fa4f6eaa5ce40dfd22fcae44edaddfb2aea44db5272f5231786dc4dc5 \
  --output-directory /home/barberb/lift_coding/artifacts/gte-aligned-decoder-preparation-20261002/reproduction-01
~~~

Unavailable preparation writes only parent binding, summary and completion
manifest. With a fitted parent, a new pinned configuration instead produces the
aligned student, external parent-file pins, handoff/inspection receipts,
resource receipt and synthetic gradient/reload probe. It publishes the
completion manifest last, after rechecking all files. Existing input,
implementation, parent output and archived teacher source namespaces are
protected from writes. A fitted operation remains `constructed_unqualified`.

## Measured preparation and remaining work

Artifacts are under
~~~text
/home/barberb/lift_coding/artifacts/gte-aligned-decoder-preparation-20261002/
~~~
All 179 prior evidence bindings matched before this stage. Five prior planning
documents are preserved under inputs-01/previous-documents; immutable model,
initialization, pair-plan and source receipts remain bound separately.

The current run-01 completed in 0.95 seconds, created zero aligned checkpoints,
loaded no numerical model and executed no fit, encoder, optimizer or KD. Its
parent retains 480 missing eligible multilingual receipts and all 720 excluded
rows. The fresh asset inspection again found both local model/code directories
absent.

| Receipt | SHA256 |
| --- | --- |
| run-01/manifest.json | 3fbbbc68ff1c4da7afac0b33c4d0f52bc466ffb34589ccf75fef80ecbb33523d |
| run-01/summary.json | a602762fee0c33213781bf10733ab5d8e6782d11f7b8ffd2d74d29830a2e52a5 |
| Original donor initialization | 7443c8a60cb1f95e9a35017edcd394c0f47fd457c3733e0863d37bfc09a09a12 |

Tests cover strict handoff, independent storage, exact inherited weights,
fitted adapter replacement, both codecs, auxiliary gradient flow, private reload,
unavailable parents, forged evidence and file drift. Ready-fit cases use actual
ridge solving and model loading on explicitly synthetic fixtures. They do not
establish real multilingual embeddings, fitted production weights or student
fidelity. Test logs and the preservation ledger are saved beside run-01.

The full migration suite passed **1158 tests in 217.15 seconds**, including
958 retained checks and 200 new checks: 89 handoff contract, 57 private numerical
loader and 54 command checks. Compilation and document-link checks also passed.

First [reuse the existing assets and embedding caches](gte_embedding_reuse.md).
All archived 384D targets stay unchanged; admit matching 768D receipts before
encoding any missing sources. Next obtain the remaining authenticated multilingual receipts, run the declared
train-only fit, and bind its completed manifest in a new handoff configuration.
The [aligned-start interface trainer](gte_aligned_interface_training.md) now
consumes this completed handoff alongside the ready original-source native
batch. It starts from the fitted primary boundary, updates only four new
connection tensors with a fresh optimizer and preserves all 26 learned decoder
tensors. Its trained generation binds the original initialization and aligned
start separately and verifies actual post-training outputs after saved reload.
Current production parents remain unavailable with zero updates.

Then train the auxiliary connector on supported references or reproducible 8D
latents, qualify each donor scope and add screened per-head KD. Measure
free-running IR fidelity before selective unfreezing, direct conditioner
promotion or context expansion. The 8D, 384D and 768D paths retain independent
processes, optimizers, caches and checkpoint writers throughout.

## Compare the fitted start on source inputs

The [source-only comparison](gte_decoder_source_evaluation.md) includes the
fitted start as a separately identified arm alongside the original donors,
original 768D initialization and aligned-trained interfaces. It requires the
same native input profile and encoder asset generation used by the fit.
References are read only after generation; missing evaluation receipts remain
explicit. Current production has no fitted start and no native evaluation
receipts, so only the original cached-input donor baseline executes.
