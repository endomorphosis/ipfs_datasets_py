# Compact relational content for LegalIR

This profile prepares a small model-facing representation of the existing `syntax_core.ast.TypedExpression` relational fragment. It preserves operator placement, ordered predicate arguments, binder references and O/P/F distinctions. It adds transport for decoder development; it does not qualify any statutory interpretation as a training target.

## Separate content from identity and evidence

A predicted content tree contains constructors, predicate indices and lexical binder references. The decoder receives an independently supplied vocabulary of predicate identities and ordered role declarations. That vocabulary must come from permitted inference context; deriving it from a held-out target would expose answer information. Vocabulary preparation and exposure decisions remain the responsibility of the existing target/split owners.

An archival identity sidecar retains the original expression/signature/node/extension identifiers and binder names for exact reconstruction. It is used only to reproduce an already recorded expression. New prediction decoding creates deterministic content identities and must not consume this sidecar or an expected target tree. Generated identities identify content and context; they are not source-occurrence identities.

Source CIDs, occurrence/edition bindings, row identities, review evidence, eligibility masks and split assignments remain outside predicted content. Attach them through their existing owners after decoding and validation. A valid compact candidate has no legal, review, proof, training, gold or corpus authority.

## Supported syntax

The initial profile uses the existing relational owner: one arbitrary `Object` carrier; explicitly quantified bound variables; predicates with one to eight ordered variable arguments; binary `and`, `or`, `implies`, `iff`; unary `not`; one binder per `forall` or `exists`; and the existing exact `legacy.deontic/v1` O/P/F extension. It requires a closed expression, globally distinct nonshadowing binders and use of every declared predicate. All original sort/signature constraints still apply.

This includes relational approval formulas and authored unary definition-shaped formulas expressed as an `iff`, including an opaque body predicate versus a disjunction of predicates. The current definition owner emits native FOL with 65-character digest-derived predicate identifiers; the relational owner admits identifiers up to 64 characters. Exact current definition-owner intake therefore remains unsupported. Short-named fixture formulas qualify syntax only. Such transport does not establish that either definition body interprets its source correctly. Cardinality, dates, functions, constants, additional sorts and other extensions require separately qualified profiles.

## Validation and use

`project_request_v1(request_raw, expected_request_sha256=...)` validates an existing authored relational request and returns `content`, `context` and `identity_sidecar` separately. `prepare_context_v1(signature_raw, argument_roles_raw, expected_signature_sha256=..., expected_argument_roles_sha256=...)` prepares an independent signature/role context without an expression body.

`decode_prediction_v1(content_raw, context_raw, expected_content_sha256=..., expected_context_sha256=...)` constructs a fresh request using generated identities. It accepts no original target, target hash or identity sidecar. `reconstruct_request_v1` additionally requires the sidecar bytes, its independent hash and `expected_original_request_sha256` to restore the complete original request value. That original commitment hashes canonical JSON; the original raw-input hash is retained separately. Whitespace formatting is not restored.

The content wire is `{"schema":"legal-relational-compact-content/v1","tree":...}`. Trees are short arrays: `["predicate", predicate_index, argument_trees]`, `["variable", binder_index]`, `["forall", binder_index, body]`, binary `[operator, left, right]`, unary `["not", body]`, and `["extension", "P", body]` (or O/F). Binder indices follow global preorder and remain subject to lexical scope. Predicate indices follow the independently declared signature order; the role ledger fixes argument positions.

All wire-input SHA arguments commit to actual received bytes. The `compact_content_sha256`, `compact_context_sha256` and `compact_identity_sha256` helpers hash canonical ordinary JSON values. All wire inputs are bounded JSON with duplicate keys rejected. The existing typed AST and relational owner validate reconstructed expressions. Every declared predicate must occur; this initial contract does not implement selection from an unrestricted symbol catalog.

Measure compact bytes and explicitly declared lexical tokens before selecting a decoder output budget. These measurements are static transport diagnostics. They do not establish a checkpoint's tokenizer compatibility, free-running accuracy or eligibility for training. Encoder context, conditioning width, decoder vocabulary and output budget remain separate contracts.

The full source/span/entity joining, meaning review, exposure grouping and consumer binding gates in the source-to-Lean4 delivery plan remain required. Same-source interpretation alternatives remain alternatives; neither transport nor a successful Lean compilation selects a governing meaning.
