# Original Legal text round-trip scoring

The intended task is original legal text → predicted LegalIR → the same original legal text. The retained source-v2 decoder emits a single canonical rule. Its exact IR score and embedding loss do not measure original-wording reconstruction. The existing detached `ir_legal_text_roundtrip.py` scorer keeps those tasks separate without changing the checkpoint, vectors, codec or pinned source-v2 implementation.

The retained cohort identifies `artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json` (614,534 bytes, SHA256 `6e3f4d731d798aa2732afc37bd74fec34da3267a323844975d2dab78f59f9c61`) and the original sibling `test.json` (529,323 bytes, SHA256 `ea7532abc3c2bcc27ce38dc6358a3898250f62e7cb8fd17af723dd1b85d65444`). This is the actual 384D donor inherited by the retained 768D initialization. The 60 test rows have no training/validation ID, source-hash or grid-group overlap, and their targets fit the donor's vocabulary. This authored composition split has already been evaluated historically; another replay is regression evidence and does not qualify a fresh independent teacher.

The [closed retrospective measurement](../autoformalization/evidence/legal-ir-source384-original-text-roundtrip-20261026.json) scored the retained 60 test predictions once, without loading the checkpoint or rerunning its decoder. All 60/60 predictions decoded and 60/60 canonical texts rendered. Exact semantic IR was 3/60; exact original UTF-8 and whitespace-collapsed exactness were 0/60 and 0/60. Joint exact IR plus original UTF-8 was 0/60; original UTF-8 exactness with a wrong IR was 0/60. 3 of the exact-IR predictions still rendered different original wording. This measures the selected canonical-rendering route, not a learned prose head, model convergence or saturation.

The existing scorer accepts detached captured inputs and candidate predictions. The closed worker used a retrospective, lossless projection of the historical evaluator-enriched report: exactly seven top-level metric/timing fields and each row's `exact_target` were removed; all remaining prediction fields, values, schema and order were preserved. The parent subtree and projection were committed before this new score, with explicit post-reference-evaluation provenance. This is not independent blind sealing. The single scoring call was:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.ir_legal_text_roundtrip import (
    score_legal_original_text_roundtrip,
)

# The admitted worker derives these exact rows from the pinned original cache.
# The committed candidate report is the retrospective prediction projection.
measurement = score_legal_original_text_roundtrip(
    corpus_pin, captured_inputs, candidate_report,
    render_canonical=True, max_edit_cells=4_000_000,
)
```

| Measure | Retained observation |
| --- | --- |
| Original semantic IR exact | 3/60 |
| Original UTF-8 exact | 0/60 |
| Whitespace-collapsed exact | 0/60 |
| Joint IR and UTF-8 exact | 0/60 |
| UTF-8 exact with wrong IR | 0/60 |
| Character edit distance | Mean 24.35; 60/60 rows scored |
| Whitespace-token edit distance | Mean 6.0666667; 60/60 rows scored |

The original evaluator's 3/60 exact IR and 97/240 varying-semantic-path matches remain historical parent metrics. The new scorer reports modality, actor, action, object, conditions, exceptions and temporal separately. The latter three qualifier slots are constant empty fields in this cohort; their matches must not be pooled with the old varying-field denominator or called improvement. The original owner witnesses record 1 scorer entry and 60 actual canonical-decompiler entries, with zero model, encoder or training calls. Original source, native-compute and storage closure were independently audited.

Every selected input remains in the accuracy denominator. Missing, duplicate, malformed and unexpected output IDs are recorded; duplicates cannot receive credit by selecting a favorable occurrence. Each valid prediction must match its original source hash and declare no teacher forcing or target access. Invalid/incomplete candidates receive zero reconstruction credit. Canonical rendering failures remain per-row failures. Coverage and provenance validity are reported separately from exactness.

Text results distinguish exact UTF-8 bytes from equality after collapsing whitespace. Exact character and whitespace-token Levenshtein distances share a finite global cell budget; an exhausted distance is null with an explicit status, never a fabricated zero. Corpus source/vector digests and regular-file endpoint witnesses are rechecked. These are cooperative per-file checks, not an atomic multi-file snapshot or proof of producer execution, grammar qualification, model quality or a current serving head.

The opt-in built-in renderer receives only detached predicted IR and a fixed, non-source request ID. It is the deterministic canonical decompiler and contains no learned prose model. Raw source, gold IR, vectors, corpus locators and source identifiers remain on the scorer side. A caller-supplied renderer is explicitly identified and its behavior is not authenticated by this module. Neither canonical rendering nor retained-source restoration can establish that a learned source-free prose head exists.

The measured 60-row cohort contains 30 semantic target groups. For one output per identical semantic IR with no style, residual or source side channel, its empirical exact-original ceiling is 30/60 (50%). The scorer derived these collision groups from the admitted corpus. This is a statement about the selected empirical corpus and information supplied to that inverse; it is not a global limit on latent representations, learned residuals, later corpora or models.

The original 8D donor's two retained training diagnostics remain useful compatibility checks, not heldout teacher evidence. The inherited 768D initializer remains reusable, but native 768D replay needs authentic same-source cached vectors and its exact source/interface capsule; 384D vectors cannot be padded or relabeled. Later retained 768D span/interface checkpoints do not establish compatibility with these 60 sources by their dimensions alone.

This completed operation read only the original saved predictions and the selected cache under original owned admission; it did not open the checkpoint, regenerate predictions, train a surface head, qualify a teacher or promote a model. A separate future numerical replay would still need the exact checkpoint, captured rows and source/interface capsule, including the historical UI decoder SHA `d7be6bff3a1f1464d4783567b90942258ef718bc1c2b7e02938698ed4e619e57` in an isolated capsule. That restore is unnecessary for reusing this saved measurement. Original-source byte recovery through retained surface data and learned source-free prose reconstruction remain different tasks.