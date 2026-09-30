# Preserve two legal autoencoder lineages

The legacy teacher and current legal students now have separate identities in
[`legal_autoencoder_lineages.json`](../../configs/autoencoders/legal_autoencoder_lineages.json).
Keep both. An architecture tag, a compatibility load, or a faster execution
backend does not change a checkpoint's ancestry.

## The two lines

| Identity | Code reference | Weights and role |
| --- | --- | --- |
| `legacy_hub_v1` | Branch `autoencoder/legacy-v1`; immutable source tag `autoencoder/legacy-v1-ddf6b794` at `ddf6b79467b68159650df81befc288c8553df664` | Complete 398,209,746-byte June Hub checkpoint, 1,205,336 reusable rows; frozen teacher |
| `current_legal_v2` | `main`; catalog baseline `485adbbe7032a1445b6b2322eab539c448094b22` | Explicit student checkpoint and parent chain; current legal feature training, including raw reconstruction and parallel sparse updates |

These are artifact/runtime lineages, not claims of two unrelated neural
architectures. Both legal paths use `AdaptiveModalAutoencoder`, an additive
sparse residual model. The native UI/Security/Intent bottleneck is separate.
The historical runtime already includes proof-aware heads, constrained grammar
utilities, and legacy distillation adapters. The
[historical source audit](historical_ddf6b794_audit.md) records what changed and
what was already present.

The teacher's [Hub manifest](https://huggingface.co/datasets/justicedao/legal-ir-autoencoder-checkpoints/resolve/94ca549d102e3e31781370aec1247f91365440eb/checkpoints/20260630T221836Z/manifest.json)
pins SHA-256 `7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be`.
Its checkpoint preparation commit is **`4f8ec909…`**, not `ddf6b794…`.
The requested September commit is a later historical runtime reference.
It needs a separate compatibility/parity replay before being treated as a
compatible historical runtime. Even a passing replay cannot establish that it
produced the June weights. The ten constituent training runs do not each have
verified producer commits.

The full teacher is distinct from restart12 (25,895,338 bytes, `1446cb18…`) and
from the July accepted port (`1c615f7c…`). That port retained 209,759 rows and
omitted 995,577. The complete teacher remains available; omitted rows have not
been restored to students merely by recording this catalog.

## What worked historically

The committed compiler pilot reported five nonempty text roundtrips and
forward 0.915 / cycle 1.000 against 24 adjudicated rules and a closed vocabulary.
Its Company A case retained the backup-report action, ten-day deadline and
emergency exception in the reported typed IR. These are actual compiler results
worth retaining. They are not measurements of an independent learned formula
decoder, whole-corpus semantics or Lake admission.

Historical autoencoder reconstruction used a target-aware safety projection
that could return the supplied target embedding. Current feature training uses
`raw_decoder`. Compare both under the same independent evaluation; old projected
cosines and new raw cosines are different measurements.

## Check identity before any model loader

The current compatibility loader can accept an untagged legacy checkpoint and
return a state labeled `proof_aware_auxiliary_heads_v2`. It also has a historical
missing-file fallback to an empty state. The new preflight reads and hashes the
actual file before any model import, so a missing file, wrong teacher, or implicit
legacy-as-student selection fails visibly.

From the canonical dataset checkout, verify the existing local teacher:

```sh
python3 scripts/ops/legal_ir/check_autoencoder_lineage.py \
  --lineage legacy_hub_v1 \
  --checkpoint /home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json
```

Verify an actual retained newer student from the six-row parallel feature smoke:

```sh
python3 scripts/ops/legal_ir/check_autoencoder_lineage.py \
  --lineage current_legal_v2 \
  --checkpoint /home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/feature-pretraining-20260929T162033Z/native-r4/feature-training/artifacts/4f/4fe1c0038018dec32e6a92aa76f90607039b8f86b7740a1719f15d1cb50619e8 \
  --expected-sha256 4fe1c0038018dec32e6a92aa76f90607039b8f86b7740a1719f15d1cb50619e8
```

`--output-receipt /path/to/new-lineage-receipt.json` optionally writes an exclusive,
non-overwriting identity receipt. The command is offline, imports no model and
streams weight bytes. It does not copy, deserialize, adapt, train, or save weights.
The receipt binds the catalog hash, checkpoint hash/size and historical source
reference. It reports runtime compatibility as **not checked** and grants no
qualification. It verifies opaque bytes, not student architecture, embedding
compatibility, or ancestry. A reserialized legacy checkpoint has a different hash
and still needs a separate ancestry review; an explicit SHA alone cannot detect
that history. This is a standalone operator preflight; existing runners have not
silently acquired a new mandatory gate.

The retained student above has 384-dimensional rows and verified local
GTE-small input evidence. Its source capsule, sparse candidate and training
receipt are linked in the [checkpoint audit](../implementation/reports/evidence/legal-lineages-20260930/checkpoint-audit.json).
It is a historical smoke exemplar, not a promoted or automatically selected
campaign head. Its two tuning rows were repeatedly consulted; the independent
canary was not evaluated.

## Run and store each lineage independently

Use separate state directories and `--model-variant` values for the legal
incremental runner, including the lineage and input-space identity, for example
`current_legal_v2-gte-small384`. The existing DuckDB/Quack registry derives its
variant from this value and its other contract fields. Existing version-parent
and run-base guards reject cross-variant ancestry. A teacher can be referenced
in a distillation receipt without becoming a student's resumable parent.

Keep sparse updates bound to their exact parent state, variant, parameter schema,
source generation and embedding contract. Do not merge teacher and student
updates into one mutable weight head. Preserve the full teacher as an immutable
artifact; any compatibility conversion is a new hash and a separately recorded
experiment. The catalog's `artifact_namespace` values specify distinct paths
for future local/Hub outputs; creating the catalog does not create Hub branches,
move files, or rewrite a shared live database.

The current legacy CUDA census uses the full legacy checkpoint through the
**current compatibility runtime**. This is a legacy-weight/current-runtime
experiment, not execution of the `ddf6b794` snapshot. Its existing producer hashes
remain authoritative. We did not restart it or edit package source for this
lineage preservation change.

Do not switch the live checkout to the legacy branch. Historical replay needs
an explicitly isolated source generation through the existing
[source integration workflow](../implementation/reports/AUTOENCODER_SOURCE_INTEGRATION_20260929.md).
Keep the canonical import pin and record the runtime's full source identity;
never substitute HACC or a mixed historical/current parser.

## Distill with explicit alignment and promotion evidence

The existing `modal_autoencoder_legacy_distillation.py` already supports separate
bounded low-rank adapters for 13 reusable embedding fields. It excludes sample
memory, leaves student tables intact, and defaults runtime influence to zero.
The catalog requires at least three seeds for held-out promotion, matching the
module default. The lower-level API permits a two-seed minimum when configured,
so callers must retain the catalog's three-seed policy explicitly. That adapter
implementation was already present at the historical commit.

The legacy checkpoint uses eight-dimensional vectors with no recorded semantic
encoder. The verified newer feature example uses 384 dimensions. Existing
legacy adapters **do not learn an 8-to-384 mapping**: their runtime returns a zero
adjustment when the requested dimension differs. Padding/truncating or relabeling
vectors would not fix this. Distillation between these input spaces needs an
explicit learned mapping or a shared, well-defined prediction target, trained
on aligned source examples with disjoint evaluation.

Every distillation artifact must bind teacher and student hashes, both runtimes,
constructor scales, input model/dimensions, split, seeds, target provenance,
objective and adapter digest. Use the existing infrastructure for same-space
adapters; evaluate a cross-space design separately before enabling influence.
Neither a successful load nor a copied architecture tag is promotion evidence.

Compiler-generated targets and guided outputs remain labeled as such. Their
known fallback/semantic errors must not become gold targets by agreement alone.
The [readable output audit](formal_logic_visibility_audit.md) preserves failures
for repair work. Lake's source-bound `lake build <Lib>` remains the only Lean
admit. The Constitution is not formalized.

## Scope of this preservation

This change pins source references, preserves checkpoint identity, adds an
offline identity guard, and records verified existing evidence. It does not
claim historical/runtime parity, architecture superiority, a completed
cross-dimension distillation, or new semantic qualification. No weights were
downloaded, rewritten or bulk-transferred.

The new identity guard passed **23 tests**. An offline smoke verified the full
legacy teacher and both retained newer student files, and rejected the teacher
when selected as `current_legal_v2`. The [identity smoke](../implementation/reports/evidence/legal-lineages-20260930/identity-smoke.json)
and [remote source-reference verification](../implementation/reports/evidence/legal-lineages-20260930/source-preservation.json)
record that scope. These checks performed no inference or training.
