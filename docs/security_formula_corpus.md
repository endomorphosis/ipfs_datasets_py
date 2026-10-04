# Decoder examples from complete CVE source

`security_formula_corpus.build_security_formula_corpus` consumes an existing
`security_cve_source_context` directory and its external manifest SHA-256 pin.
It replays native source admission offline, then joins each complete file to
its exact `CodeUnit` and source records. It makes no network requests and never
executes repository code.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formula_corpus import (
    build_security_formula_corpus, validate_security_formula_corpus,
)

report = build_security_formula_corpus(
    context=context_path, expected_manifest_sha256=context_manifest_sha256,
)
validate_security_formula_corpus(
    report, context=context_path, expected_manifest_sha256=context_manifest_sha256,
)
```

Every observed function has a provenance row in `functions`, including nested
scope, source location, original file hash, source and CodeUnit CIDs, and its
original repository split. The existing function-span adapter preserves
decorators and records every byte removed for indentation normalization. The
bridge independently verifies that each normalized byte maps back to the
admitted source. Unsupported functions and selection-bound omissions remain
explicit rows and frontiers.

`security_formula_grammar.parse_formula_source` determines whether each
normalized function belongs to the currently supported production grammar.
Teacher productions are obtained from source AST structure. CVE, CWE, and
fixed/vulnerable labels do not become formulas or per-function truth labels.
The underlying fixing-commit/parent polarity remains provenance only.

`supported_samples` retains every grammar-supported sample. Each sample has
only `id`, `split`, `source`, and `source_sha256`, matching the decoder trainer's
input contract. `samples` contains the eligible subset: every member of any
cross-split exact-body or alpha/literal-normalized shape collision is
quarantined. Splits are never reassigned. Collision groups, excluded sample
identities, and same-split duplicates are reported separately.

`training_input_contract_satisfied` checks nonempty train/validation/test
partitions and the current decoder's sample/node bounds. It is not a training,
semantic correctness, or held-out performance result. If the admitted corpus
has no supported train functions, that condition remains visible; source is
not silently replaced with authored examples. Any independently authored
supplement must be declared by its caller.

The report contains local source payloads. It grants no license or
redistribution permission; the upstream complete-source context's license
boundary still applies. There are no training steps, model-provider calls,
learned formula outputs, or proof/execution/mutation/completion authorities in
this preparation stage. Validation rebuilds the complete report, including
grammar and implementation hashes, from the pinned current source context.
