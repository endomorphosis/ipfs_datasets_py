# Reconcile autoencoder work before further text-to-logic training

This October 6 review joins the existing published autoencoder work with the new normative-wording fits. The package review pins `795d960170214d03e2eaf4c0a13ad4eb922c5c08`; the workspace source review pins `b0ba1aaa9c8a3f1d0e42bca31aa710f1108c686e`. Later unrelated workspace supervisor commits are preserved when publishing this integration. Git histories, effective main blobs and current working files are separate observations.

## Published work and actual working files

The branch inventory covers 423 package refs and 19 registered package worktrees, plus 338 workspace refs and 35 worktrees, as recorded at their respective snapshots. Live origin advertisements and local patch-equivalence checks supplement history reachability. There is no additional scoped branch-only file that needs a broad cherry-pick. Earlier restoration paths still match main; older branches must not replace newer files merely because they contain familiar decoder code.

Some published main files were absent from the shared canonical checkout. Recovery authenticated every selected main Git blob, refused differing existing files and created only absent paths: 89 source/schema files, 82 dedicated tests, one test dependency and three guides. Another 42 contextual replay evidence files were restored. Two existing owners received exact bounded main changes: lazy training-reference import for cached LegalIR inference, and an immutable source-local line index for function-span extraction. Their preimages are retained. The final audit verifies 219 reviewed main paths are present and byte/mode identical in the canonical tree.

The main contextual LegalIR384/768 runtime is now available in the source-of-truth tree. Its codec, cached source/context inputs, original selected state and frozen projection buffers remain bound; teacher/runtime/native/proof authority remains false. This is the opt-in [contextual replay interface](contextual_legal_reconstruction_runtime.md), not a default ModelManager promotion.

During final integration, another agent published `a3f16f2870a80a7e985b35bed3334512c47d9dc3`, clarifying the contextual runtime input boundary and completed-training documentation. Paragraph vectors bind to caller-pinned asset bytes and width/finite/unit-norm checks; the saved inventory has no paragraph-vector producer receipt or digest. Explicitly repinned replacement vectors therefore do not inherit authenticated encoder provenance. The retained original 44-asset replay still uses its exact original vectors. This metadata correction adds no model fitting or qualification. The earlier 219-path recovery audit remains pinned to the reviewed `795d960` snapshot.

The restored codebase APIs preserve the current dirty resource scheduler. Three new routes still need the published timeout/resource-profile contract reconciled with that owner: `bounded_header_checker`, `codebase_header_context` and `codebase_source_units_384`. Missing timeout functions are not replaced with guessed constants. Other changed existing registry, scanner, source-derivation and process owners remain untouched; this review does not claim every restored route has executed numerically.

## Keep the evidence populations separate

The workspace `artifacts/autoencoder-progress-reconcile-20261006/evidence/evidence-review.json` catalogs twenty studies and verifies 56 primary Git source/report identities. It preserves the earlier sixteen studies and adds the source/recurrent observation, contextual replay, new wording fits and the observer loss-definition review; twelve declarative family/width plans are cataloged separately. Checkpoint serialization, actual tensor, donor, codec, embedding producer, corpus and source/context identities remain explicit.

| Study | Supported observation | Limit for the next experiment |
| --- | --- | --- |
| Historical 8D linguistic teacher | Original feature decoder/training lineage remains separate | Parser/source omissions and general teacher fidelity require their own checks |
| Learned 8D formula sidecar | Different experimental decoder from the linguistic teacher | Its poor exposed formula scores cannot describe the teacher |
| Native 384D normative fit | Sealed wording development improves 55/60 to 60/60, token CE falls 69.92% | Original meanings were already exposed; original DEV CE slightly worsens |
| Native 768D normative fit | Both arms are 60/60; auxiliary CE rises 2.45% | Retain width-specific controls; no uniform auxiliary benefit is established |
| Contextual LegalIR replay | Original cohort is 48/48 semantic IR and canonical-contract exact; prose is 0/48 exact | Different source/checkpoint population; no learned prose decoder was loaded |
| Source-only and PCA/AE studies | Vector reconstruction and conditioner controls have actual measurements | Identity MSE, vector loss and structural proposals are distinct from generated formula/source fidelity |
| 4096D heads and family/width plans | Actual short TRAIN fitting exists; twelve family/width plans are declarative | Capacity and a plan do not establish wider semantic convergence |

The normative states are four unique selected tensors. Selected/last-attempt aliases within each arm are not independent replications. The contextual replay uses the same original selected parents as the normative training; it is not the same candidate endpoint or wording cohort. Tiny inherited identity-projection MSE values are not learned source reconstruction. Native 384D and 768D encoders differ in architecture, so comparisons do not isolate dimensionality.

## Contribute the grouped semantic decoder interface

Two newly reviewed source-only modules from local agent work are included: `logic/deontic/coordination_decoder.py` and `logic/autoformal/legal_coordination_evaluation.py`. Their two dedicated suites pass 161 tests against twelve byte-authenticated main dependencies and in the canonical tree. Negative-control fixtures guard both module lookup and existing parent attributes, so absent optional source-parser helpers do not become test dependencies.

The deterministic decoder accepts only an explicit closed semantic request with two through eight ordered actor/modality/action members, inclusive disjunction, a declared modal scope and universal actor-predicate binding. `modal_over_actions` requires one normalized actor and modal operator and produces one modal formula over an action disjunction. `disjunction_of_norms` retains each member's modal formula and branch order/multiplicity. The request must choose scope; no original text or teacher output fills missing slots.

It renders deontic first-order formulas, strict native TDFOL AST payloads and Lean bodies through existing owners. The declared lexical profile rejects explicit source/provenance fields and recognized modal or qualifier cues in member labels. Five temporal/qualifier boundary probes refuse before rendering, including `within_duration`; no threshold or qualifier is silently discarded. The evaluator counts every missing, extra or invalid output and compares semantic IR separately from exact request/formula equality.

The deterministic renderer is a target/output interface, not a learned decoder or a source parser. Rendering, syntax validation and `structure_compiled` grant no admission: source-semantic verification, semantic-equivalence verification, admission, formalization and proof readiness remain false.

The separate [grouped source-only v1/v2 heads](grouped_legal_decoders.md) and opt-in `legal_ir:source_conditioned_grouped_v2` registry reader are now published and integrated in [PR #1271](https://github.com/endomorphosis/ipfs_datasets_py/pull/1271). Their immutable Hugging Face weights, source producer identities, 256 exact retained prediction replays and actual native scope controls are documented there. V2's fresh authored panel has 64/64 exact positive requests, 55/64 learned refusals, seven incidental blocks and two unsupported emissions. Seven official paragraphs yield only refusals, so real-law formalization coverage is not established. These heads consume source text and explicit caller scope; they are separate from 8D/384D/768D latent conditioning. The wider source-parser/qualifier port and broader family support remain pending. The published test populations overlap and must not be added as independent evidence.

## Prevent another history/working-tree mismatch

The existing workspace tool now has an opt-in working-copy check while preserving its original v1 behavior:

```bash
python3 scripts/review_autoencoder_progress.py \
  --repository external/ipfs_datasets \
  --source 795d960170214d03e2eaf4c0a13ad4eb922c5c08 --target origin/main \
  --path ipfs_datasets_py/logic/formalization/autoencoder/contextual_legal_ir_runtime.py \
  --working-tree --fail-on-missing --fail-on-working-tree-missing \
  --output /tmp/contextual-working-copy-review.json
```

The result keeps history reachability and source/target blob retention, adding current regular-file SHA256, size, mode and status. When the target lacks an ancestor path, the working comparison explicitly identifies the source reference; target absence is still counted. Reads reject symbolic/nonregular aliases, size overflow and observed metadata/path replacement, support stable hardlinks and leave Git HEAD/index unchanged. This is a sequence of fenced file observations, not an atomic whole-tree snapshot. Twenty-nine real temporary-Git tests cover the optional mode and unchanged default behavior.

## Validation and next bounded work

The selected twelve recovered interface/source-indexing suites pass 621 tests. The working-copy tool adds 29 tests, and the grouped interface adds 161, for 811 distinct targeted integration tests. Restored suites that actually fit models, execute native checks or transfer Hub data were not broadly invoked. The canonical tree-pin check loads compiler, decompiler and parser from `external/ipfs_datasets`, never the editable HACC tree.

The next prepared observation checks the four new normative selected tensors on the earlier exposed-v3 48-paragraph/180-rule panel. Both zero controls must exactly reproduce their archived M2 token/status/EOS outputs. All four same-pass traces and predictions must become durable before the v3 reference body is parsed. Full formula, seven-facet, full-vocabulary CE and all 180-rule/720-scalar-site denominators are retained. This is retention on previously exposed development, with no new fitting or fresh semantic holdout claim.

Only after retention should additional fitting use independently reviewed natural source/formal pairs, fresh source groups and a codec capable of complete nonempty qualifiers. Preserve domain-specific projections, output contracts and solver eligibility rather than applying the Legal scalar grammar to Intent/Security/UI. The existing target, sparse-update, Arrow, DuckDB/Quack, DuckLake and Hub owners remain separate from inference, training and semantic/proof qualification.

Temperature remains 0; encoder context and decoder output limit remain 512; no weights are downloaded. The retention run uses verified warm caches, one CPU worker, no bridges/provers and disabled metric disk cache; it is not a bridge-on Legal-IR speed benchmark. Only an applicable actual `lake build <Lib>` may grant Lean admission. No integration test, rendered Lean body, compiler output, database row, vector loss or source census does so. The Constitution remains unformalized and no span receives `roundtrip_ok` from this review.
