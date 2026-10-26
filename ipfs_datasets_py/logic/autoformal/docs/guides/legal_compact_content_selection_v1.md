# Compact content selection from complete logits

This opt-in single-step operation connects a complete vector of 537 finite scores to the existing public compact-content prefix constraints. It supplies the missing mask application between a numerical decoder's logits and its next output ID. The operation itself is pure Python: it does not run a model, fit weights or establish compatibility with a checkpoint.

The canonical owner is `logic/formalization/autoencoder/legal_compact_content_selection_v1.py`. Its public `select_compact_content_token_v1(logits, prefix_ids, context_raw, *, expected_context_sha256, codec, expected_codec_sha256)` delegates all syntax/context/mask decisions to the qualified `legal_compact_content_tokens_v1` owner. It introduces no second AST, grammar, vocabulary or legal meaning.

## Complete scores and deterministic decisions

Supply exactly 537 ordinary integer or finite floating-point scores in the fixed codec's ordered vocabulary. Booleans, custom numeric/container types, NaN, infinity, wrong lengths and integers beyond the declared exact bound are refused. The operation retains the complete detached score vector and its canonical commitment, including integer/float and signed-zero distinctions.

The raw argmax and the highest-scoring allowed ID both break ties by the lowest ID. The report retains the raw argmax, allowed set, selected ID and whether applying the mask changed the raw choice. An empty allowed set produces an explicit no-selection observation and leaves the offered prefix unchanged. The report includes the complete public prefix report and both offered and resulting prefixes.

A selection appends one newly chosen allowed token. It does not rewrite, strip or repair any ID already offered. Missing EOS and PAD within offered generated output remain subject to the existing token owner's disposition. The output limit remains 512 total IDs including BOS/EOS; vocabulary size and sequence length are separate constraints. Local next-token admissibility does not prove a branch can finish within its remaining budget.

Context, codec and changed-source failures propagate as operational errors. Invalid score containers or values are API errors, not semantic model errors. A bounded syntactically rejected prefix remains a no-selection observation through the existing prefix report. Named producer fences commit to the fixed raw sources and stable endpoint inputs; they are not a proof of a hermetic interpreter or authenticated model provenance.

## Integration boundaries

Score positions are interpreted using the exact supplied fixed codec. A caller must separately bind its actual numerical head, ordered vocabulary, dtype and checkpoint to that codec. Accepting 537 scores does not establish where they came from, and a same-sized head with a different token order is incompatible. This operation cannot infer a checkpoint's semantics from a list of numbers.

The older flat-rule trainer and inherited head/checkpoint contracts remain distinct. The source-separated compact-label companion and existing complete-population batch owner retain source, label, grouping, exposure and accounting responsibilities. Separate semantic-token batch and structural-target work can consume this selector without replacing those owners.

The engineering diagnostics program scores from two already exposed authored §7213 target alternatives, deliberately placing PAD above each intended allowed next token. Those controls exercise actual mask application and trace retention. They are not numerical generation, model accuracy, independent legal samples or permitted held-out inference. Their separately committed signature/role context is derived from the target. Authority remains false and training/evaluation gold masks remain zero.

Actual source/cache joins, source interpretation, governing definitions, independent review, context permission, exposure/splits and consumer eligibility remain necessary before statutory training or evaluation. Native digest-named definitions and counting remain outside the existing content profile. No graph or Lean corpus admission follows from selecting a syntactically allowed ID.

[Implementation evidence and qualification](../../../../../../../artifacts/legal-ir-compact-logits-selection-20261017-01/README.md) records the exact source/test generation and runtime limits.
