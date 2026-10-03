# Original decoder vocabulary compatibility and next steps

The new evaluation preflight authenticates an explicitly selected original checkpoint, package, cell inventory and ordered cached rows, then checks their canonical target encoding against that checkpoint's stored vocabulary and token limits. It reuses the original embeddings and weights without loading a model or fitting a vocabulary. This addresses the vocabulary gap identified in [the numerical replay](numerical_replay_handoff.md); it does not change the earlier reconstruction scores.

## Results on the retained caches

The complete census covers the original native-v3 train, validation, test and canary caches for LegalIR, SecurityIR and IntentIR at 384D: 1,980 rows in 33 explicit batches of at most 64 rows. Each family contributes 360 train, 120 validation, 120 test and 60 canary rows. No rows were dropped, transformed, re-embedded or passed to a model.

| Original 384D checkpoint | Frozen vocabulary | Retained rows checked | Canonical encodings covered | Rows with missing tokens | Rows over limit |
| --- | ---: | ---: | ---: | ---: | ---: |
| LegalIR | 37 | 660 | 0 | 660 | 0 |
| SecurityIR | 39 | 660 | 0 | 660 | 0 |
| IntentIR | 27 | 660 | 0 | 660 | 0 |

Legal targets require 16 tokens including BOS/EOS, Security targets 64 and Intent targets 31. Their stored target limits are respectively 64, 512 and 512. Longer encoder context or more epochs with the unchanged codec cannot repair these canonical missing-token failures. All twelve family/split combinations have the same uncovered result. Missing tokens include field-specific Legal atoms and whole quoted Intent/Security identifiers; the report preserves every missing position and facet.

These are **retained-cache lexical compatibility results**, not numerical reconstruction scores, independent teacher evaluation or failures on the checkpoints' own original training corpora. The published Domain checkpoints record earlier authored training manifests; the Legal head records 32 training and 8 tuning examples. A cache named `train` is not evidence that the selected checkpoint was trained on those rows. Preserve and reconcile those original training assets before continued fitting or loss comparisons.

The provenance audit located those earlier assets. Each Domain package retains its actual 16-row authored corpus: 12 training, 2 validation and 2 test rows. Its recorded training/validation manifests match the corpus exactly, and all 16 original targets have canonical vocabulary coverage. For each Domain family, none of the 660 native-v3 rows shares an ID, source digest, vector digest or full canonical target digest with that original corpus. The earlier two-row test reports still record 0/2 exact IR for each family; those historical accuracy reports are distinct from this metadata audit.

Legal's original development campaign retains 72 rows, including 32 extra training paraphrases. Use the original panel's explicit IDs to select the actual 32 fitting and 8 tuning rows; selecting every row tagged `training` would incorrectly include 64 rows. Its historical fit report records 32/32 exact training IR and 0/8 tuning IR. That reported training fit is not independent teacher quality, source-free wording recovery or a fresh numerical rerun. `training_cache_provenance.json` binds the discovered original assets and the exact association checks.

The check concerns the known canonical tokenization. It does not establish that every alternative JSON spelling is impossible. Native grammar validation, numerical checkpoint usability, source fidelity and proof remain unverified. The earlier genuine numerical replay still has 0/15 exact native IR matches and 0/5 exact original Legal text matches through the deterministic renderer.

## Calling the preflight

```python
from ipfs_datasets_py.logic.formalization.autoencoder.checkpoint_hub import (
    preflight_ir_cell_cached_targets,
)

report = preflight_ir_cell_cached_targets(
    directory_plan_pin,
    inventory_pins,  # Exactly twelve explicit family/dimension inventories.
    request,         # Family, dimension, dimension role, task, checkpoint SHA.
    package_manifest_pin=package_manifest_pin,
    cache_split="validation",
    row_ids=original_ordered_row_ids,
)
```

The public Hub entry is lazy and delegates to the stdlib evaluator. The existing cached model-opening path remains separate. A caller must inspect `counts`, row-level `canonical_encoding_representable`, `missing_tokens` and `over_limit`; this preflight does not automatically admit a model or teacher.

Only the explicit existing Legal/Security/Intent `384/input_embedding/source_to_native_ir` profiles are supported. Other cells, tasks and roles refuse before loading. A missing Legal formula head reports an unavailable capability for every selected row and uses no parser fallback. Malformed profiles, bindings, vocabularies, policy, targets or changed bytes raise an error rather than becoming successful coverage results.

Known codec generations are bound both to checkpoint-recorded implementation hashes and exact local source bytes, without importing numerical owners. Legal encoding preserves seven-facet order, typed atom identity, sorted unique qualifier lists and BOS/EOS. Domain encoding preserves compact sorted JSON, Unicode escapes, complete lexical strings and BOS/EOS. Simple Legal metadata checks include O/P/F, bounded exact strings and nonblank required facets, while permitting blank objects. Full native grammar checks are deliberately separate.

The evaluator has an explicit 512KiB selected-target bound; Domain additionally retains its authentic 128KiB codec bound. These are distinct from source token/span budgets. Legal's latent source vocabulary remains exactly PAD/UNK/latent; it is never applied to the original prose. Gold targets remain inside the evaluator and do not enter runtime preparation inputs, model loading or inference. Per-file reads and endpoint rechecks detect changed bindings without claiming an atomic or continuous repository snapshot.

## Validation and preserved evidence

The guarded control run passed 241 cases: 131 new compatibility cases plus 110 existing cached-runtime cases, with no failures, skips or deselections. All 723 setup/call/teardown reports passed. Tests use small private integrity fixtures with real routing/preparation and forbidden model loaders; their synthetic metadata does not qualify native grammar, core bindings, numerical tensors or reconstruction quality.

The original census used real cold package initializers and the public Hub wrapper in a finite isolated Python process, with numerical imports, model loading, network, databases, subprocess effects and writes outside the private run excluded. Both accepted runs recorded zero denied events, source endpoint equality and only the main thread. Independent reviews recomputed the entire census against original row/vector/target associations and token sequences. This is bounded Python observation, not native/shared-library or universal filesystem containment.

The copied admission files retained unused descriptive counts and Hub exclusions from the previous phase. `admission-metadata-correction.json` discloses this without rewriting executed inputs. The actual V3 selection is the two named test files and enforced 241 collected nodes; the actual census is 33 batches and 1,980 rows. The earlier 15-row V1 run predates the added Hub wrapper and is historical evidence only; V2 authenticates the final production sources.

The accompanying JSON records exact source, execution, input, review and preservation receipts. The artifact stage is `/home/barberb/lift_coding/artifacts/ir-target-compatibility-20261003`. Preservation checks authenticate all 2,484 inherited files, the original 26 assets and 13 inventory documents, plus all 542 sealed numerical-stage artifacts and its two committed handoff payloads. Previously sealed files were not rewritten. No training, weight change, new embedding generation, database creation, supervisor operation or publication occurred.

## Improvement sequence

1. **Reconcile checkpoint/corpus associations.** Keep each original checkpoint's own training and tuning manifests, source texts, targets, actual embeddings, producer revision and split exposure receipts. Record whether a selected cache is original fitting data, development replay or an independent evaluation cohort. Link the actual original donor corpora alongside the larger native-v3 caches in each appropriate inventory; do not relabel a later `train` file as the older checkpoint's training set. Add lexical compatibility as an explicit prerequisite for any candidate training/evaluation contract. Implement an explicit original-corpus replay lane using unchanged retained inputs before fitting a derivative; Legal raw-latent manifest recomputation requires its bound numerical source generation and remains a separate prerequisite.
2. **Create derivative output codecs while preserving donors.** Freeze the original vocabulary and all weights. For a bounded expanded codec, fit additions from declared training data only and record a semantic old-token-to-new-token mapping. Copy unchanged token embedding/output rows by token meaning, preserve compatible projection/conditioning/recurrent parameters, and initialize added rows by a declared donor rule. Map or explicitly reset the affected optimizer state. For unseen names, prefer a separately versioned grammar plus byte/subword or typed-reference channel over closed whole-string vocabularies. A source-reference/copy channel must declare source access and have separate metrics. Never add exposed validation/test/canary labels to a closed vocabulary and call the result generalization.
3. **Repair semantic conditioning before teacher admission.** Check source-disjoint holdouts for full IR equality, operators, types, modality, actors, actions, objects, conditions, exceptions and temporal facets. Include complete attempted denominators, invalid outputs, abstentions and truncation. Counterfactual source pairs must change the relevant prediction. Coverage alone cannot fix the previously observed repeated Security fragment or wrong Intent/Legal semantics. Keep embedding MSE and token loss visible alongside those task metrics.
4. **Add a separate learned Legal surface path.** The desired round trip is original text → predicted LegalIR → reconstructed original text. The existing semantic IR drops wording: in the retained Legal validation data, four distinct sources share each canonical target. Preserve semantic LegalIR v1 and introduce a versioned predicted surface channel and learned prose head. Evaluate it with predicted IR/channel only, withholding raw source, gold IR, caches and source-hash lookup. Measure exact UTF-8, normalized equality and edit distances separately. A stored lossless sidecar is restoration evidence and needs its own task label.
5. **Keep all twelve cells independent and align 768D derivatives.** Maintain CodebaseIR, SecurityIR, LegalIR and IntentIR × 8D, 384D and 768D inventories, decoder/schema/token/span profiles, DuckDB/DuckLake destinations and Hugging Face repositories. An 8D structural latent has its own role; it is not an eight-coordinate GTE source vector. Reuse each family's genuine compatible 8D/384D donors and vocabularies before training its 768D decoder. Keep original 384D vectors as teacher inputs. Inventory already-retained authentic 768D producer caches before considering any new vector generation. A native multilingual-GTE 768D connector requires separately authenticated native 768D vectors for the same source identities; padding or relabeling the old vectors cannot substitute. Align the connector first, then unfreeze inherited layers gradually. Qualify progressively larger spans per IR, including the requested 768D/8,192-source-token target. Encoder context capacity does not certify decoder target length or formalized span coverage; current Domain v1's 1,024-token hard cap requires a new qualified profile for longer targets. Teacher quality gates precede distillation.
6. **Bind CodebaseIR evidence to repository planning.** Capture the repository under test with source span, symbol, dependency and snapshot identities. Separate autoformalized candidates from checked proofs. A proof index needs typed premises and verified solver receipts, with invalidation on source/model/codec/assumption/solver changes. Match IntentIR to current CodebaseIR symbols/evidence before supervisor planning and reobserve affected dependencies before effects. On-the-fly training produces a bounded candidate tied to that repository snapshot, followed by evaluation and promotion checks. Independent cell store and release identities must survive this pipeline.
7. **Integrate reviewed consumers and asset bindings together.** Prepare an isolated current-origin comparison and reconcile all required worktree commits, manifests and authentic weight pointers. Keep historical decoder generations in explicit checkpoint-selected process/source capsules while retaining modern defaults. Verify the merged consumer loads the intended checkpoint and original cache, then run replay/regression and surface metrics. Publish immutable family/dimension releases and promote only validated candidates. This local branch and its review bundle do not themselves update GitHub `origin/main` or a serving head; cached remote refs are not a fresh remote observation.

The next concrete implementation is the explicit original-corpus replay contract, followed by the derivative codec and token-row inheritance mapping. Its acceptance requires authentic donor receipts, original embedding reuse, training-only additions and retained compatible weights before any training run or 768D distillation.
