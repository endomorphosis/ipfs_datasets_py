# Backend representation limits from source inspection

This is a static source review prepared while capture-r3 was running. It is not a run result, test receipt, or claim that the current shared bundle contains any specific formula. The formal-validation receipt must establish the actual generated programs and outcomes. No additional validation process was launched for this note.

The current native compatibility check can qualify the exact generated program's syntax, deontic/temporal operator structure, and frame schema. It does not establish equivalence between a complete legal sentence and that program. A successful Lake build admits only its generated theorem.

- **Generic TDFOL norm projection:** `logic/bridge/fol_tdfol.py:_tdfol_formula_from_norm` builds a deontic wrapper around `action(actor)`. It may add `ALWAYS` when selected words (`before`, `after`, `when`, `until`) occur. This branch has no explicit duration-quantity or exception lowering. Neither a 10-day deadline nor a 20-day minimum can be inferred from this wrapper. Other guidance/export paths exist; inspect each actual frozen proof_input rather than generalizing this branch to every TDFOL target.
- **TDFOL serialization:** `DeonticFormula.to_string(pretty=False)` omits agent/context metadata. `TemporalFormula.to_string(pretty=False)` omits `time_bound`. A `Constant` and a `Variable` can serialize identically; the parser interprets an ordinary identifier term as a variable. Therefore matching serialized strings and operator AST paths cannot establish producer-object type, time-bound, or metadata equivalence. The helper records this limit instead of claiming a faithful object round trip.
- **Generic DCEC proof input:** `logic/bridge/cec_dcec.py:_proof_input_formula_text` renders `O/P/F(happens(actor,event,t0))`, or a selected state predicate. It takes actor/event/modality/state_kind parameters, with no explicit quantity, deadline relation, exception, or scoped condition arguments. An event symbol containing source words would still need an independently specified semantics. Separate event/state views may retain additional evidence; do not discard them or count their presence as native proof execution.
- **DCEC parser repair:** the reviewed balanced-prefix parser repair addresses actual generated-call compatibility and unary deontic operators. It does not add omitted legal semantics, resolve references, prove the resulting formulas, or admit a law.
- **Frame schema:** the existing adapter projects exact target triples into the frame contract. Required fields and role typing establish schema compatibility. They do not establish ontology entailment, legal interpretation, temporal/exception preservation, or ErgoAI proof execution.
- **Lean scope:** the supported minimum-duration gate supplies numeric threshold 20 to the JevOps renderer. The generated theorem checks the natural-number boundary at 19/20. It omits the actor, retention duty and time units. `within_duration` and a generic prohibition remain non-renderable in that path. A Lake success must retain this exact scope and must not mark any Constitution span formalized or roundtrip_ok.
- **Learned heads:** the trained heads produce embeddings/distributions/guidance. This helper validates deterministic source-derived shared targets and a canonical-rule-derived Lean fixture. It does not validate a symbolic program emitted by the learned checkpoint.

For publication, preserve source text, canonical rule and temporal/exception records, full shared target views, exact proof_input, parsed structure and validation errors, Lake command/source/artifact hashes, training/checkpoint lineage and separate false legal-authority fields. Do not collapse successful syntax/schema/Lake-fixture checks into legal-span admission.

Static source SHA-256 observations:

```json
{
  "ipfs_datasets_py/logic/CEC/native/dcec_integration.py": "3309196821c2ff357ecf587cba7b79bb997db3a0d003b2eec0b55126d8eab6b9",
  "ipfs_datasets_py/logic/TDFOL/tdfol_core.py": "67be350d1fb0422a64ab040349b2d51c4008fbeeb8b59a99b8901d681d7d71c7",
  "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py": "8e1f8885be6dc2a7d692ecdf0364ccc4d01692c38c81137775d9d222d8b8d9d3",
  "ipfs_datasets_py/logic/bridge/cec_dcec.py": "281a8f17579e21854d6aa2dc5ed013574c76e742117e7437ccc98098cb981cd8",
  "ipfs_datasets_py/logic/bridge/fol_tdfol.py": "0215d61cf61d82357ae0afc98590e1ab64fa465aa7cae53816c09f007a92480b",
  "ipfs_datasets_py/logic/integration/reasoning/legal_ir_view_contracts.py": "086997b67133df2437435b417324b11ede49b503ca92f5af6c67146c765fd875",
  "ipfs_datasets_py/logic/legal_ir/adapter.py": "9ca0036ec77f0e4a7676d31c932091f35dff5aff4bee73134e51bfe98ceb9180"
}
```
