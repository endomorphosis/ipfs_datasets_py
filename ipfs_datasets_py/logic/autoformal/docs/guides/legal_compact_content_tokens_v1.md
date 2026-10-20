# Fixed tokens and prefixes for compact LegalIR content

This profile gives the existing compact relational content tree a fixed lexical vocabulary and an explicit next-token interface. A future learned decoder can call that interface with a separately supplied signature/role context. The profile does not run a numerical decoder or make an existing checkpoint compatible.

The owner is `logic/formalization/autoencoder/legal_compact_content_tokens_v1.py`. It uses `logic/autoformal/legal_compact_content_v1.py` for context and complete typed-expression validation. It retains the same constructors, ordered predicate arguments, lexical binders and exact O/P/F extension. No new AST or legal semantics is introduced.

## Separate the three transport contracts

The original relational byte codec serializes a complete authored request. The later `legal_relational_compact_codec_v1` replaces fixed request boilerplate but still predicts the full request, including its identities. Those codecs remain separate, qualified transport baselines.

This token profile emits only the semantic content object from `legal_compact_content_v1`. Signature and role context are supplied separately; archival node/expression/signature IDs and binder spellings remain in the existing identity sidecar. Neither prefix inspection nor prediction decoding receives an expected target, target lookup or sidecar. Source occurrence identity, cache membership, reviews, splits and eligibility remain with their existing owners.

A context hash commits to bytes; it does not establish permission to expose the context during inference. Deriving predicate names or role declarations from a held-out label can disclose the answer. The engineering A/B fixtures do exactly that to exercise transport and are not evidence of permitted held-out inference. All masks and authority remain zero/false.

## Vocabulary and budgets

The fixed vocabulary begins with `<pad>`, `<bos>`, `<eos>`, followed by sorted, unique JSON lexical tokens for the closed content schema, its existing constructors/modal letters, structural punctuation and integers 0 through 511. No target is consulted to build or fit this vocabulary. Integer tokens are available globally but each prefix restricts predicate and binder indices to the current context and lexical scope.

The vocabulary has **537 entries**, distinct from the output-length limit.

The output profile admits at most **512 IDs including BOS and EOS**. That is an explicit bounded subset of the existing AST owner's structural limits. Larger valid ASTs can remain unsupported by this output profile. No complete input is truncated, output cap silently raised, missing EOS inserted or PAD stripped.

Vocabulary layout uses the same special spellings and ordinary JSON lexical-token shape as the existing generic typed-JSON utilities. The codec schema and target validator are different. This does not qualify the older flat-rule trainer, its output head, saved tensors, token embeddings, optimizer state or checkpoint loader for these targets. Encoder context, conditioning width and numerical execution remain separate contracts.

## Prefixes and predictions

The prefix API checks canonical schema/key order, constructor shape, binary/unary arity, predicate arity, global quantifier preorder and lexical visibility of binder references. Completed content must use every declared predicate and satisfy the existing typed AST owner. Reordering predicate-keyed role rows preserves those rows; argument order is determined by the labels within each row.

Allowed next tokens describe local constraints for the supplied prefix. They do not promise that every admitted partial branch has a completion within the remaining token budget, prove general semantic equivalence or establish decoding speed. A future consumer must apply the returned mask explicitly; merely constructing this codec does not enable constrained generation in an existing model.

Generated output retains the entire bounded offered ID sequence, framing and failure disposition. Incomplete, rejected and budget-exhausted candidates remain observations. Malformed generated syntax is separate from invalid context commitments, changed producer source or disagreement with the authoritative owner; those operational failures propagate rather than being recorded as ordinary model rejection.


The public API is:

- `build_compact_content_token_codec_v1()` and `compact_content_token_codec_sha256(codec)`.
- `encode_compact_content_tokens_v1(content_raw, context_raw, *, expected_content_sha256, expected_context_sha256, codec, expected_codec_sha256)`.
- `compact_content_allowed_token_ids_v1(prefix_ids, context_raw, *, expected_context_sha256, codec, expected_codec_sha256)`.
- `decode_compact_content_tokens_v1(generated_ids, context_raw, *, expected_context_sha256, codec, expected_codec_sha256)`.

The prefix operation returns a report containing `offered_ids`, `allowed_token_ids`, state, reason and remaining slots. Its literal states are `empty`, `prefix`, `complete`, `rejected` and `budget_exhausted`; it is not a bare mask list. Decoding returns the entire offered `generated_ids` and framing, with an existing-owner prediction only for a valid complete candidate. All expected wire hashes commit to the actual received bytes; canonical content/context hashes remain separate.

The APIs and exact report schemas are specified in the source and [implementation evidence](../../../../../../../artifacts/legal-ir-compact-decoder-intake-20261017-01/README.md). Complete context and owner validation use the existing public compact-content APIs. Every successful decoded expression remains an unreviewed structural candidate.

## Remaining integration

A learned head still needs its own compatible target profile, explicit tensor-transfer/checkpoint rules, permitted source/context inputs and complete-population accounting. Preserve the source-separated example owner's physical grouping and pending null labels. Extend the existing batch owner for raw generated observations without creating a competing denominator. Actual statutory source/review/governing-dependency replay, exposure/split decisions and consumer binding remain required before numerical training or evaluation.

Exact current native definition-owner intake remains unsupported: its 65-character digest-derived predicates exceed the relational owner's unchanged 64-character bound. Counting, temporal syntax, additional sorts and functions also require separate profiles. No accepted semantic graph, legal meaning selection or Lean corpus admission follows from token validity.
