# Historical LegalIR and autoencoder audit

The repository at `ddf6b79467b68159650df81befc288c8553df664` contains
documented working typed compiler/decompiler results. The recent poor outputs
from fragmented US Code spans do not erase that evidence. The historical
results also do not establish that the legacy autoencoder independently
generated legal formulas or outperformed the current student.

This audit read immutable Git objects on 2026-09-30 and compared them with
`485adbbe7032a1445b6b2322eab539c448094b22` (the complete comparison revision
is authoritative in the evidence JSON). No historical package was imported,
no compiler or model inference was rerun, and no weights were downloaded.
The requested commit was made on September 19 and added SAWM trace/program
view modules; it is a useful repository snapshot, not the introducing commit
of either model architecture. Source hashes and exact comparison results are
in [history-audit.json](../implementation/reports/evidence/legal-lineages-20260930/history-audit.json).

## What worked in the historical evidence

The checked-in July 26 pilot reports five cases, 24 adjudicated rules, and a
closed vocabulary containing gold atoms plus distractors. Typed deontic
compilation had 5/5 nonempty round trips, mean forward score **0.915**, and
mean cycle score **1.000**. These are weighted structural scores, not a claim
that every extracted rule was correct. The report identifies lost deadlines
and condition/exception attachments in the more difficult cases.

For the actual pilot input:

> Company A shall submit backup report within 10 days unless emergency.

the recorded typed compiler output and recompiled output both contain this
exact structured rule:

```json
{
  "action": "submit",
  "actor": "company_a",
  "conditions": [],
  "exceptions": ["emergency"],
  "modality": "O",
  "object": "backup_report",
  "temporal": ["within_10_days"]
}
```

The deterministic realization preserved the original sentence while the
source was withheld from the realizer. Forward and cycle scores were both
1.0 for this case. Its L1 and L2 CID was
`baguqeeradpjcplbnxaoxi2hjrm4q3jaalfrxuen6s5lsibhptvpxvxuz3wua`.
This is the recorded structured IR, not a newly invented rendering or a new
successful run. The historical Lean check concerned canonical rule-CID list
identity. This audit does not turn that into `lake build <Lib>` admission.

Sources at the requested commit:

- [Audited report and actual case output](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/workspace/benchmarks/semantic-logic-roundtrip/2026-07-26-audited-v2/semantic-roundtrip-report.json)
- [Pilot snapshot](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/docs/performance_snapshots/2026-07-26_semantic_logic_roundtrip_pilot.json)
- [Method, scores, and known failures](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/docs/benchmarks/semantic_logic_roundtrip.md)

The same pilot recorded zero nonempty semantic round trips for its DCEC
projection and regex-modal arms. Its spaCy-modal arm had forward 0.8325 and
cycle 0.920833333. These different arms should remain separate evidence.

## What the historical autoencoder actually did

Historical `AdaptiveModalAutoencoder` describes itself as a diagnostic and
advisor. Its `encode()` returns family distributions, frame/sample metadata,
and an embedding projection. Its `decode()` returns `list[float]`. Formula
production belongs to the deterministic compiler and bridge adapters.
See historical [class and output contracts](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L3514),
[`encode`](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L4291),
and [`decode`](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L4360).

Historical reconstruction is also a different measurement from the current
raw-decoder objective: `_decoded_for()` passes the known source embedding
into `_reconstruction_safe_projection()`, which can return that target vector
exactly. A good projected cosine is therefore insufficient evidence of a
good independently reconstructed representation. Preserve projected and raw
metrics under different names in any comparison. The relevant historical
[projection call and function](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L7910)
are bound in the evidence JSON.

The historical
[causal autoencoder guidance qualification](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json)
was explicitly `not_measured` / `terminal_unsupported`, because a reviewed
causal L1 adapter was unavailable. Its checkpoint was the separate 25.9 MB
restart12 state (`1446cb…`), not the 398 MB legacy teacher (`7236de…`). Neither
this receipt nor the typed pilot is an old-versus-new autoencoder ablation.
The historical eight-row integrated smoke likewise reports equal baseline
and candidate family metrics, rather than evidence of improvement.

## What changed and what survived

The core state dataclass has **41 annotated fields in both revisions**:
38 public fields and three internal bookkeeping fields. Names and order are
identical. Both snapshots default to `proof_aware_auxiliary_heads_v2` and
support `legacy_dense_v1`; both use `modal-autoencoder-state-v1`.

No `AdaptiveModalAutoencoder` methods were removed. Four were added for raw
decoder evaluation, and eight changed: evaluation, decode preparation,
projection training/update, hard-example selection, embedding nudges, and
the sample training objective. This is a source comparison, not a claim that
all runtime behavior is identical.

These modules are byte-identical between the compared commits:

- `modal_autoencoder_legacy_distillation.py`
- `modal_autoencoder_feature_transfer.py`
- `modal_autoencoder_factorized_heads.py`
- `modal_autoencoder_legacy_view_calibration.py`
- `legal_ir_grammar_decoder.py`

The seven metric families also survive: deontic, frame logic, TDFOL, KG,
CEC, external provers, and decompiler. Having a family head or metric slot
does not establish successful formula serialization or semantic coverage.
The parser and canonical compiler/decompiler did change, so using an old
checkpoint with the current runtime is a compatibility experiment, not an
exact replay of historical behavior.

The older
[feature inventory](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/docs/implementation/reports/LEGAL_IR_LEGACY_FEATURE_INVENTORY.md)
provides a concrete reason to retain the full teacher. It binds legacy
checkpoint SHA-256 `7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be`:

| Inventory item | Rows |
| --- | ---: |
| Legacy reusable rows | 1,205,336 |
| Accepted transfer rows | 209,759 |
| Omitted rows | 995,577 |
| Active omitted rows | 907,702 |

The accepted transfer reports 98.46% L1 signal coverage but deferred direct
legacy embedding activation because bulk transfer reduced held-out cosine.
Omission is a capacity/transfer decision, not evidence that the remaining
legacy features are useless. The inventory's accepted state (`1c615f…`) is
another distinct artifact, not automatically the current training state.

## Two lineage boundaries

Keep an immutable **legacy teacher** lineage with the original checkpoint
digest, raw architecture declaration, embedding contract, runtime revision,
and parser/compiler/bridge provenance. Keep the **current student** lineage
with its own state, representation/profile, optimizer, and storage/publication
namespace. A current runtime reading legacy weights must say so explicitly;
it must not claim historical replay.

The existing historical distillation implementation already provides a
useful boundary: separate bounded low-rank `C @ B` adapters per reusable
embedding head, no mutation of teacher/student dense maps, no sample-memory
transfer, and zero runtime influence until held-out promotion passes. Its
gate defaults to three seeds and checks declared required-family evidence
(the lower-level configuration accepts a minimum of two). Reuse that
contract instead of overwriting either lineage with a bulk weight merge.

A matched comparison should bind one held-out corpus and record both
lineages' raw vector metrics, compiler-produced formulas, source-grounded
semantic scores, emitted-family coverage, and resource cost. An 8-dimensional
legacy diagnostic vector and a 384-dimensional semantic representation
require an explicit adapter/embedding contract; truncation or padding is not
an architecture comparison. Neither lineage grants legal admission without
the required Lake build.

The unit tests listed in the evidence JSON were **inspected, not executed
today**. They cover bounded nonmutating distillation, exact zero influence,
isolated optimizer state, lineage-bound checkpoints, no-regression promotion,
target-preserving transfer, and nonvacuous semantic scoring. A historical
runtime replay remains a separate, explicitly pinned task; importing the
editable HACC tree or silently switching parser trees is not an acceptable
substitute.
