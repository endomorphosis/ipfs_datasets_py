# Declared-context embedding sensitivity

| Field | Value |
| --- | --- |
| Status | canonical |
| Owner | formalization / autoencoder development |
| Source of truth | `alignment_context_embeddings.py`, `alignment_context_assay.py`, `alignment_context_experiment.py`, and `alignment_context_development_v1.json` |
| Last verified | 2026-10-03 |
| Audience | developer |

This exposed-development experiment checks numerical sensitivity to separately
declared assumptions in the richer 34-item source/context panel. It compares
saved raw-source vectors with two fresh, role-marked input arms. Forwarding
context into an encoder is an input-delivery fact. A changed vector does not
establish that the encoder resolved the assumption correctly, formalized the
source faithfully or produced a useful proof.

The earlier [source-only experiment](alignment_richer_embedding_retrieval.md)
encoded the same text for the two contextual interpretations and obtained the
same vectors. Their separate evidence identities retained the available
assumptions, but those assumptions were not forwarded to the encoders. This
stage changes the input profile while preserving that earlier generation and
its receipts.

## Run a separate evidence generation

From the datasets repository root, use the pinned
[configuration](../../configs/autoencoders/alignment_context_development_v1.json)
and a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_context_experiment.py \
  --config configs/autoencoders/alignment_context_development_v1.json \
  --output-directory /tmp/context-embedding-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_context_experiment.py) accepts
`--workspace-root` for the enclosing evidence workspace. Its configuration
binds the completed source-only embedding report and the richer review-admission
report by file digest. It also retains the installed spaCy backend, pinned
GTE-small snapshot, complete multilingual GTE assets and a bounded deadline.
Input, implementation and predecessor bindings are checked before publication.
The dependency bindings cover listed source files; they are not a complete
interpreter or dependency manifest.

The source-only receipts are reused rather than re-encoded. A complete run has
102 saved raw-source receipts, plus 68 new receipts in each of the three lanes,
or 204 new receipts in total. These are expected accounting counts; use the
actual report for observed availability and completion. This workflow fits no
ridge head, autoencoder, projection, contrastive objective or generation model.

## Input arms and the formatting control

Both fresh arms use the same compact JSON shell:

~~~json
{
  "schema": "role-marked-source-context/v1",
  "source": {"role": "source", "text": "<exact source text>"},
  "assumptions": {
    "role": "declared_assumptions",
    "text": "<separately supplied context text, or empty string>",
    "bindings": {}
  }
}
~~~

The example illustrates roles, not a suggested interpretation. Actual rendering
preserves the original strings as JSON values and uses the profile's exact
serialization recipe. Its transport digest binds the UTF-8 text actually sent
to the model, including JSON escaping and formatting.

| Representation | Encoder text |
| --- | --- |
| Saved raw source | Original source text, from the previous profile. |
| `source_frame_only` | Role-marked source, with empty assumption text and bindings. |
| `declared_context` | The same shell, with the exact supplied context text and bindings when present. |

The arm ID stays outside the encoded text. For the 32 items without explicit
assumptions, both fresh arms therefore send identical text. Those rows are
negative controls for changes caused by the arm label or transport machinery.
For the two contextual items, the full arm includes the supplied definition of
the designated official; the frame-only arm withholds it.

Compare raw source against the frame-only arm to measure formatting sensitivity.
Compare the full arm against the frame-only arm to isolate the additional
declared-context text and bindings together. This design does not separately
isolate the effects of the prose and the literal binding values. Comparing only
raw source against the full arm would combine formatting and context changes.
The two same-source contextual items remain distinct
outer identities even when their frame-only transport text is identical.

No authored target, expected handling, partition, original item ID, compiler
result or retrieval suggestion is added to the encoder text. The separately
supplied context is available input; it is not inferred from the authored
reference. Context-sensitive source fidelity still requires independent review
of whether that input was interpreted correctly.

## Preserve representation and evidence identities

The new [input and transport wrapper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_context_embeddings.py)
retains the original source SHA-256, the full available source/context input
SHA-256 and the rendered encoder-text SHA-256 separately. Every outer receipt
also identifies its arm and the frozen producer's transport input. Do not
overwrite an original source digest with a rendered-text digest or reuse the
earlier raw-source profile ID for the new representation.

The frozen native producers encode the rendered text under their existing
recipes. The 8D lane is a spaCy lexical/POS/dependency/modal-cue feature hash,
with its disclosed whitespace preprocessing and six-decimal output rounding.
The 384D GTE-small lane uses pinned mean pooling and L2-normalized CPU float32
output. The 768D multilingual GTE lane uses its pinned complete checkpoint,
CLS hidden state and L2-normalized CPU float32 output. All expected encoder
and classifier weights are loaded for that checkpoint; classifier logits are
not the embedding. Overlong input is rejected under each producer's token
limit rather than silently truncated.

The outer context profile and the inner native representation identity are
both needed to interpret a cache entry. The 8D, 384D and 768D source spaces
remain independent. These source producers are distinct from the corresponding
trained autoencoders and their formal decoders. Width labels do not establish
shared coordinates, formal-rule preservation or readiness to fuse the lanes.

## Read numerical assays within their scope

The [assay](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_context_assay.py)
compares the saved raw, frame-only and declared-context vectors with finite-value
and L2 checks. The declared L2 tolerance is `1e-5`; it is a numerical validation
tolerance rather than a semantic agreement threshold. Report vector equality,
cosine or distance changes according to the assay's explicit recipe.

Separate the 32 unchanged-text controls from the two contextual items. New
context vectors can differ because extra tokens were supplied, including the
literal actor names in the assumptions. That sensitivity does not demonstrate
correct reference resolution, qualifier attachment, exception handling, timing
or inference. Equality after supplying different assumptions can expose a
representation limitation, but it does not identify the cause by itself.

This assay consumes no authored references or source partitions to measure
meaning, train a model, choose an arm, score retrieval or select a checkpoint.
It introduces no new statement construction, proof checking or formal-family
qualification. `context_forwarded` can be true while
`context_semantics_applied` remains false. The latter records that successful
interpretation has not been established.

The [runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_context_experiment.py)
writes `context_inputs.json`, `{lane}_context_embeddings.json`,
`{lane}_assay.json` and `report.json`. Context embedding artifacts bind both
outer receipts and the untouched native transport evidence. The report retains
the reused raw-source bindings, the richer review-admission binding and the
observed lane availability. An unavailable or incomplete lane cannot acquire
invented vectors or successful sensitivity measurements.

## Review and downstream gates remain pending

The bound richer admission report records a prepared packet with 34 pending
items and zero authenticated independent reviews. See the
[review-admission runbook](alignment_richer_review_admission.md) for collecting
actual source/context annotations and preserving reviewer blinding. Forwarding
those assumptions to an encoder does not update the review status.

All fidelity, qualification, production admission and proof-authority flags
remain false. Context semantics and independent source fidelity are unverified,
native useful proof coverage is unrun, and this stage runs no Leanstral model,
autoencoder training, generator or prover. A successful numerical assay supports
a later context-aware interpretation experiment; its downstream behavior needs
new independently reviewed evidence.

Focused validation from the datasets root:

~~~bash
python -m pytest -q tests/unit/logic/formalization/autoencoder/test_alignment_context_experiment.py
~~~
