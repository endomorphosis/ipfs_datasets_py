# Original Legal text round-trip scoring

The intended task is original legal text → predicted LegalIR → the same original legal text. The retained source-v2 decoder emits a single canonical rule. Its exact IR score and embedding loss do not measure original-wording reconstruction. The new detached `ir_legal_text_roundtrip.py` scorer keeps those tasks separate without changing the checkpoint, vectors, codec or pinned source-v2 implementation.

The concrete next cohort reuses `artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json` (614,534 bytes, SHA256 `6e3f4d731d798aa2732afc37bd74fec34da3267a323844975d2dab78f59f9c61`) and the original sibling `test.json` (529,323 bytes, SHA256 `ea7532abc3c2bcc27ce38dc6358a3898250f62e7cb8fd17af723dd1b85d65444`). This is the actual 384D donor inherited by the retained 768D initialization. The 60 test rows have no training/validation ID, source-hash or grid-group overlap, and their targets fit the donor's vocabulary. This authored composition split has already been evaluated historically; another replay is regression evidence and does not qualify a fresh independent teacher.

The scorer accepts explicit target-free captured inputs and an already captured source-v2 candidate report. It never invokes the numerical decoder or generates embeddings:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.ir_legal_text_roundtrip import (
    score_legal_original_text_roundtrip,
)

corpus_pin = {
    "path": "/home/barberb/lift_coding/artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/test.json",
    "bytes": 529323,
    "sha256": "ea7532abc3c2bcc27ce38dc6358a3898250f62e7cb8fd17af723dd1b85d65444",
}
# captured_inputs: ordered {id, source_text, embedding} rows from that exact cache.
# candidate_report: the target-free Runtime.infer result, saved before scoring.
ir_score = score_legal_original_text_roundtrip(
    corpus_pin, captured_inputs, candidate_report,
)
# Separately admitted canonical owners are needed for this explicit option.
canonical_text_score = score_legal_original_text_roundtrip(
    corpus_pin, captured_inputs, candidate_report, render_canonical=True,
)
```

Every selected input remains in the accuracy denominator. Missing, duplicate, malformed and unexpected output IDs are recorded; duplicates cannot receive credit by selecting a favorable occurrence. Each valid prediction must match its original source hash and declare no teacher forcing or target access. Invalid/incomplete candidates receive zero reconstruction credit. Canonical rendering failures remain per-row failures. Coverage and provenance validity are reported separately from exactness.

Text results distinguish exact UTF-8 bytes from equality after collapsing whitespace. Exact character and whitespace-token Levenshtein distances share a finite global cell budget; an exhausted distance is null with an explicit status, never a fabricated zero. Corpus source/vector digests and regular-file endpoint witnesses are rechecked. These are cooperative per-file checks, not an atomic multi-file snapshot or proof of producer execution, grammar qualification, model quality or a current serving head.

The opt-in built-in renderer receives only detached predicted IR and a fixed, non-source request ID. It is the deterministic canonical decompiler and contains no learned prose model. Raw source, gold IR, vectors, corpus locators and source identifiers remain on the scorer side. A caller-supplied renderer is explicitly identified and its behavior is not authenticated by this module. Neither canonical rendering nor retained-source restoration can establish that a learned source-free prose head exists.

Surface information is measured on the exact selected cohort. These 60 original rows have 30 semantic targets, each shared by two distinct wordings. A single-output inverse with only those semantic IRs and no style/residual/source side channel has an empirical 50% exact-original ceiling on this balanced cohort. This is not a limit on latent representations, a learned residual channel, later corpora or models generally. The scorer computes the collision groups and ceiling instead of hard-coding 30, two or 50%.

The original 8D donor's two retained training diagnostics remain useful compatibility checks, not heldout teacher evidence. The inherited 768D initializer remains reusable, but native 768D replay needs authentic same-source cached vectors and its exact source/interface capsule; 384D vectors cannot be padded or relabeled. Later retained 768D span/interface checkpoints do not establish compatibility with these 60 sources by their dimensions alone.

The next numerical admission must bind the exact checkpoint, captured cache rows, implementation generation and external/native dependencies. In particular, the original source-v2 checkpoint requires the historical UI decoder SHA `d7be6bff3a1f1464d4783567b90942258ef718bc1c2b7e02938698ed4e619e57`; its exact archived copy can be restored only into the new isolated capsule. The checkpoint's source-v2 runtime file remains unchanged. This change supplies the scorer and inert tests; it does not run inference, train a surface head, qualify a teacher or promote a model.
