# Typed relational reconstruction diagnostics

`legal_relational_reconstruction_v1` compares two independently pinned, valid authored relational declarations through the existing [relational norm owner](legal_relational_norm_v1.md). It supplies the structural diagnostic needed before richer decoder outputs can be compared. The existing seven-facet formula scorer remains useful for its own schema; flattening typed predicates into those facets would lose argument order, lexical binding, quantifiers and modal placement.

This is a paired diagnostic, with no aggregate accuracy score. It refuses invalid or unsupported requests. It does not evaluate a batch containing missing outputs, malformed predictions or abstentions, and must not be used to hide those failures from an accuracy denominator. Neither input is assumed to be a reviewed target or a model prediction.

## Inputs and replay

Use `prepare_relational_reconstruction_comparison_v1(reference_report, candidate_report, *, reference_request_raw, candidate_request_raw, expected_reference_request_sha256, expected_candidate_request_sha256, expected_reference_report_sha256, expected_candidate_report_sha256)`. Both original request transports and both complete canonical report hashes are independent caller commitments. The adapter detaches bounded ordinary inputs before lazy operation imports, then replays both reports through the public `validate_relational_norm_v1` owner. A self-hash does not authenticate a caller commitment.

`relational_reconstruction_comparison_sha256` commits the complete comparison report. `validate_relational_reconstruction_comparison_v1(..., expected_comparison_sha256=...)` regenerates every diagnostic from the independently pinned originals. Changed flags, omitted paths, altered features or elevated eligibility cannot be authorized by resealing the result.

Public import loads standard-library modules only. Each request is bounded by the existing 524,288-byte profile, each original report by eight MiB and the complete output by four MiB. Complete overflow refuses. The adapter checks its own and trusted operation-source hashes across replay, projection and serialization. It starts no resource owner; callers retain their existing admission and process lifecycle contracts.

## Three different comparisons

| Result | Preserved distinctions |
| --- | --- |
| Exact typed expression | Complete serialized expression, including node/expression/signature IDs and derived content digest |
| Declared ordered structure | All supported structure and binder names; only artifact IDs and the derived digest are omitted; signature declaration order and role-row order are normalized explicitly |
| Lexical alpha structure | The existing bounded expression-algebra comparison allows consistent bound-variable renaming; actual signature, family/profile and ordered-role agreement remain required |

Fresh artifact IDs alone change exact identity while preserving the other two comparisons. Renaming a binder and every reference to it changes declared spelling while preserving lexical alpha agreement. Predicate identities, ordered predicate arguments and role values, quantifier kinds, implication direction, connectives, O/P/F operators, modal placement and extension payload/features remain distinct. No commutative reordering, predicate renaming, deontic axiom or legal-equivalence rule is inferred.

Alpha comparison reuses `syntax_core.algebra.LogicExpressionAlgebra.alpha_equivalent` on complete validated roots. The adapter does not introduce a new AST or invoke the algebra's `semantic_identity` as a legal judgment. Its one-`Object` carrier, closed variables and restricted extensions come from the unchanged relational profile; broader formulas require their own supported profile.

## Complete path diagnostics

The flat feature ledger retains every authoritative `structural_mapping` path, including explicit binder and modal-extension rows. Its ordered union lists reference paths first, followed by candidate-only paths in candidate order. Missing sides remain explicit nulls with `reference_only` or `candidate_only` presence. The report never aligns a favorable subtree to a different path.

Features expose ordered children, lexical binding quantifier paths, predicate argument positions and declared roles, and modal/connective ancestry. `binding_quantifier_path` names the quantifier node, such as `/root`; the binder row itself remains `/root/binders/0`. Artifact-ID differences are reported separately from declared feature differences. These features describe the existing validated syntax, not independently established denotation or source meaning.

## Use in decoder work

Use these comparisons alongside exact original UTF8, normalized source text, complete graph reconstruction, fixed-view CE and embedding MSE/cosine; each measures a different outcome. Reuse the existing [batch evaluator](legal_relational_batch_evaluation_v1.md) for the complete requested population, duplicate and missing IDs, invalid outputs and abstentions. Its UTF-8 request intake still needs a separately qualified bridge from the [relational decoder codec](legal_relational_decoder_target_contract_v1.md): preserve original generated IDs/bytes, invalid UTF-8, framing and incomplete outcomes without inventing requests or abstentions. Source/partition and actual generation/target-access evidence remain separate commitments. A successful pair must not stand in for complete coverage.

Reviewed source/version/applicability, legal interpretation and formal targets remain prerequisites for semantic training claims. The [association-bound definition review](../../../../../docs/autoencoders/legal_sampled_primary_definition_review_v2.md) and [typed source correspondence](legal_source_typed_norm_join_v1.md) keep their separate domains. The existing review APIs do not directly express a source-equivalence verdict for the association-bound envelope; an additional unsigned declaration alone would not establish gold eligibility.

Every authority flag stays false and both training and evaluation-gold masks stay integer zero. This operation performs no model inference, training, graph admission, human review or Lean build. The [comprehensive plan](../../../../../docs/autoencoders/legal_ir_uscode_corpus_improvement_plan_20261015.md) tracks the remaining review, connected-target and matched 8D/384D/768D milestones.

## Native qualification and retained declarations

The final native qualification passed **187 unique cases** with no failures, errors or skips: 84 new reconstruction cases, all 70 relational cases and all 33 shared-algebra cases. Collection, successful calls and JUnit identities agree. The request froze 240 source pins; 89 product origins executed checked buffers. Its receipt records 4.84 seconds. The ten legacy preflight inputs/assertions are unchanged; explicit descriptive parameter IDs keep the oversized byte-bound input from producing a 524 KB JUnit name.

A separately admitted fresh interpreter consumed the two original retained §7213 authored typed requests, totaling 33,548 bytes, and their independently sealed producer export copies. It prepared new current-root relational reports and compared AA, BB, AB and BA. Both self pairs have all six agreement booleans true and 19 complete feature rows. Both cross pairs retain matching family/profile, signature declarations and ordered role ledgers while exact identity, declared structure and lexical alpha agreement are false. Their ordered union has 31 rows: seven shared paths, twelve reference-only paths and twelve candidate-only paths, with one shared path reporting declared feature differences. These are two competing hypotheses about one paragraph, not four legal examples or decoder predictions.

Seven named artifact checks completed, including two required refusal operations for a wrong independent request pin and resealed promotion of a modal disagreement. These checks are separate from the 187 pytest cases. The consumer froze 243 source/config pins and executed 86 checked-buffer product origins; its receipt records 0.80 seconds. Six local payload outputs total 335,738 bytes. Saved-comparison validation runs in that same consumer interpreter; a separate later consumer of the new outputs is not claimed.

Selected original request, export-copy and metadata bytes and physical identities were checked before/after. The old producer main, source HTML, scope and join owners were not rerun, and the complete old producer tree was not inventoried. The comparison neither closes source-context issues nor resolves the source-only pending §7214 provision. Both current native jobs completed durable output sealing, stopped-group checks and storage/lease release under a two-GiB memory budget; qualification storage was one GiB and comparison storage 256 MiB.

Earlier failed import-closure qualifications, the all-tests-pass/JUnit-name closeout failure and a scheduler refusal before child attachment remain separate history. Only this phase's four own failed storage claims were explicitly reconciled through the existing public recovery API, retaining all outputs. The final roster preserves every case and strict evidence bound. These repeated runs do not supply additive legal-example or test coverage.

The curated evidence index (`../autoencoders/evidence/legal-typed-reconstruction-20261016/publication-copy-roster.json`; historical reference unavailable in this checkout) contains source, frozen requests, native receipts/parent captures and independent audits, plus selected failure/recovery metadata. Original request, relational and comparison payloads remain local. The published subset is not a self-contained replay corpus.
