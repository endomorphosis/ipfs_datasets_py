# Lexical source nominations for compact LegalIR contexts

`ipfs_datasets_py.logic.autoformal.legal_compact_source_context_v1` bridges raw
source text and an explicitly supplied vocabulary to the existing compact
context API. It performs deterministic lexical nomination. It does not perform
autoformalization, infer legal roles or grant inference/training permission.

The fixed downstream owner is `legal_compact_content_v1.py`, SHA256
`de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e`.
The bridge calls its public `prepare_context_v1` for both the complete catalog
and the selected subset. Unused invalid declarations or roles still fail.
The bridge does not alter the decoder or any acceptance policy.

## Inputs and APIs

The source is exact nonempty, NUL-free UTF8 `bytes`, at most 65,536 bytes. The
catalog is exact UTF8 JSON `bytes`, at most 524,288 bytes, with these four fields:

```json
{
  "schema": "legal-compact-source-catalog/v1",
  "signature": "FULL EXISTING LogicSignature.to_dict() OBJECT, including signature_id",
  "argument_roles": [{"symbol": "Disclose", "roles": ["actor", "object"]}],
  "aliases": [{"symbol": "Disclose", "forms": ["disclose", "discloses"]}]
}
```

The quoted signature placeholder illustrates the field; a real input must use
the full existing signature object. There must be exactly one alias row per
predicate, one to 64 predicates and no more than 256 forms across all rows.
Each forms list is nonempty and contains nonblank exact strings; whitespace-only
aliases are rejected rather than nominating a predicate from spacing. Duplicate rows
or duplicate forms within a row fail. A shared form across different predicates
is retained and becomes ambiguous if that form actually occurs in the source.
No source normalization, case folding or whitespace trimming is performed.
Targets, ASTs and labels are not catalog fields. Unknown fields, duplicate JSON
keys, nonfinite values, all floats, custom JSON types and cycles are rejected.
Existing signature/role semantics remain those of the pinned context owner.

```python
import hashlib
import json
from ipfs_datasets_py.logic.autoformal.legal_compact_source_context_v1 import (
    prepare_source_context_v1, source_context_sha256, validate_source_context_v1,
)

# source_raw and catalog_raw are caller-supplied exact bytes. Their provenance,
# permissions and exposure time require independent evidence.
source_sha = hashlib.sha256(source_raw).hexdigest()
catalog_sha = hashlib.sha256(catalog_raw).hexdigest()
report = prepare_source_context_v1(
    source_raw, catalog_raw,
    expected_source_sha256=source_sha,
    expected_catalog_sha256=catalog_sha,
)
report_sha = source_context_sha256(report)
checked = validate_source_context_v1(
    report, source_raw, catalog_raw,
    expected_report_sha256=report_sha,
    expected_source_sha256=source_sha,
    expected_catalog_sha256=catalog_sha,
)
if checked["status"] == "nominated":
    context_raw = json.dumps(checked["context"], sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(context_raw).hexdigest() == checked["context_sha256"]
    # Context bytes can be supplied to the existing structural decoder API only
    # after the caller independently establishes the applicable use permission.
```

`source_context_sha256` hashes bounded canonical JSON; hashing alone does not
validate it. `validate_source_context_v1` requires the independent expected
report hash and both original raw inputs. It recomputes the complete report and
compares every field, then checks that the caller's mutable report stayed
unchanged during validation. It returns the fresh replayed report. All refusals
raise `ValueError`; successful reports are detached plain JSON dictionaries.

## Matching and dispositions

Matches are exact case-sensitive substring occurrences. If an alias starts with
a word character, its preceding character must be absent or non-word. If it ends
with a word character, the next character must be absent or non-word. Word
characters are Unicode letters, numbers, combining marks and connector
punctuation (categories `L`, `N`, `M`, `Pc`), plus the zero-width non-joiner and
joiner (`U+200C`, `U+200D`). Thus `retain` does not match the prefix of
`retain\u0301`, and underscore and joiner adjacency also prevent partial word
matches. This explicit boundary rule is not a general grapheme or
language-specific word segmenter. NFC and NFD spellings remain different;
normalization is never implicit. Punctuation-ended aliases have no word boundary
requirement on that end. All overlapping occurrences are retained,
including overlapping forms for different predicates. The search advances one
Unicode scalar position after each occurrence, never by the alias length.

Each match records `form`, `symbols`, `start_char`, `end_char`, `start_byte` and
`end_byte`. Ends are exclusive; character coordinates refer to the unchanged
decoded source and byte coordinates to its original UTF8 bytes. Every exact
`form` equals both corresponding slices. Symbol lists preserve signature order.
Matches sort by start byte, end byte and form. A shared form creates one
occurrence record listing all of its predicates. `ambiguities` records each
observed shared form once, in first source occurrence order.

- `nominated`: at least one match and no observed ambiguous form. `context`
  contains the existing validated compact context and `context_sha256` its
  canonical identity. Selected predicates retain signature order; roles retain
  their original validated order.
- `ambiguous`: an observed identical form belongs to multiple predicates.
  All occurrences remain available for inspection, but `context` and its hash
  are null. The bridge does not resolve ambiguity by priority or heuristics.
- `unavailable`: no alias occurs. Context and its hash are null.

`matched_symbols` always records every lexically observed predicate in signature
order. `selected_symbols` and `index_mapping` are populated only for a nominated
context. Mapping rows contain `symbol`, `catalog_index` and `selected_index`.
`excluded_symbols` is the signature-ordered complement of `selected_symbols`,
including the entire catalog when there is no context. The original alias-row
order is retained in `aliases`. `source_geometry` records encoding, source byte
length and Unicode scalar count. Raw source/catalog hashes, the producer source
hash and fixed context-owner hash bind the report's inputs and implementation.
`matching_policy` records case sensitivity, normalization, the boundary rule,
the runtime Unicode database version, overlap/ordering rules and ambiguity rule.

At most 4,096 occurrence records and a 1,048,576-byte canonical report are
allowed. The existing bounded JSON helper also enforces its depth/item limits.
Any bound overflow refuses the whole operation. No partial/truncated report or
context is returned. Extra alias evidence can cause the report bound to be
reached before the occurrence cap; these are independent upper limits.

## Scope of the result

Every report has origin `caller_supplied_unverified`. All authority fields are
false and `masks` is `{semantic: 0, training: 0, inference_permission: 0}`. The
explicit top-level `training_mask` and `evaluation_gold_mask` are also integer
zero, preserving the denial convention used by neighboring owners. A source
hash and byte offsets bind lexical observations; they do not verify a legal
interpretation, role meaning, permitted semantics, target independence or when
the catalog was created. Signature metadata and a caller's alias choices are
not independently verified provenance. In particular, this API cannot certify
that a vocabulary supplied by a caller was prepared without seeing a target.

The inherited compact grammar still requires **every selected predicate to
occur in the decoded output**. A lexical match may overselect predicates and
make a desired output inexpressible under that rule. Nomination establishes
neither optimal vocabulary selection nor decoder completability. A caller must
retain such failures and obtain better independently prepared context; it must
not silently remove unused predicates based on a target or predicted output.

This module invokes no model, training, native inference, solver or Lean build.
It adds no supervisor, authority store, policy promotion or catalog producer.
Semantic validation, corpus aggregation, legal applicability, independent use
permission and any later model/grammar qualification remain separate work.
