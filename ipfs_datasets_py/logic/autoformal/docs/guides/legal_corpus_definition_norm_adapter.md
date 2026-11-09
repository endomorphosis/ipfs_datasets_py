# Explicit definition and unary norm to a candidate graph

`logic/autoformal/corpus_definition_norm_adapter.py` adapts the existing
`legal_source_definition_norm_bridge` profile into source-bound corpus records
and a candidate graph. It preserves an explicit caller interpretation after
regeneration by that unchanged owner. It does not extract definitions or norms
from legal text. Public module import is inert: native parser and lowering
owners are imported only when an adaptation or validation is requested.

## Independent inputs

```python
from ipfs_datasets_py.logic.autoformal.corpus_definition_norm_adapter import (
    adapt_definition_norm_bytes,
    export_definition_norm_candidate,
    validate_definition_norm_candidate,
)

inputs = dict(
    expected_report_sha256=independent_report_sha256,
    request_raw=original_request_bytes,
    expected_request_sha256=independent_request_sha256,
    raw_html=original_html_bytes,
    expected_raw_sha256=independent_html_sha256,
    expected_extracted_sha256=independent_document_text_sha256,
)
candidate = adapt_definition_norm_bytes(original_report_bytes, **inputs)
validate_definition_norm_candidate(candidate, original_report_bytes, **inputs)
manifest = export_definition_norm_candidate(
    candidate, fresh_graph_directory, report_raw=original_report_bytes, **inputs
)
```

Report and request hashes bind their exact original UTF8 JSON file bytes. They
are checked before parsing; duplicate keys, nonfinite values and oversize inputs
are refused. Expected commitments must originate outside the incoming records.
The API checks those commitments but does not authenticate their external owner.

The request's decoded `raw_html_base64` must equal the separately supplied raw
HTML bytes. The complete `document_text` has its own independently expected
SHA256. The existing owner then regenerates extraction, source declarations,
scoped symbols, native AST, parser receipts and generated Lean source. Raw HTML
must be nonempty and no larger than 8,000,000 bytes. The source version derives
its `release_id` as `govinfo-edition:<declared edition>`; this names the explicit
URL-bound edition and does not assert an authenticated government release.

Existing reports contain producer pins keyed by absolute source paths. Exact
regeneration may reject a report from another worktree even if source bytes are
otherwise identical. This adapter preserves original report bytes and pins; it
does not rewrite them or claim cross-tree portability.

## Supported declared meaning

The composition owner accepts exactly its
`section-local-defined-category-unary-norm/v1` profile in `deontic_fol` or
`tdfol`. Its nested definition request supports the existing unary FOL profile,
or that profile in TDFOL. The declared definition is a universal biconditional
between a unary category and caller-supplied Boolean `atom`, `not`, `all` or
`any` expressions. One untyped `Entity` carrier and variable `x` are retained.

The norm must cover a complete codified leaf paragraph of the exact form
`Each <category> shall|may|shall not <unary-action>.` The definition precedes the
norm in the same document, section and edition, with one literal section-scope
declaration. The full native AST preserves the declared definition conjoined
with `forall x, category(x) -> M(action(x))`. Category activation remains outside
the O/P/F modality. A category predicate is not replaced by a ground actor
constant, and O/P/F remain distinct parameters without additional deontic axioms.

The unchanged owner refuses objects, conditions, exceptions, temporal origins,
external definitions, additional norm text and multiple legal sorts. `includes`
and `deems` cannot be promoted to `means`. Boolean structure is declared by the
caller, not inferred from legal coordination. Full lexical coverage of the norm
paragraph is checked; full definition meaning or lexical coverage is not claimed.
Unsupported input is refused rather than rewritten into this profile.

## Source origins and scoped records

`source_occurrences` contains deduplicated physical records. Ordered
`source_bindings` retain every semantic role even when two roles share the same
geometry. Each binding names its occurrence CID and intersecting paragraph
indices. Definition symbol bindings also retain both the legacy source symbol
and the composition's rebound symbol.

| Role | Preserved origin |
| --- | --- |
| `definition_block` | Entire existing definition block, including descendants |
| `definition_paragraph` | Full paragraph named by the definition declaration |
| `scope_literal` | Exact section-scope phrase, including an ancestor paragraph origin |
| `definition_cue`, `definition_head` | Exact declared cue and category head |
| `definition_body/0000`, etc. | Every ordered body-atom occurrence, including duplicates |
| `norm_paragraph`, `norm_span` | Full physical norm paragraph and complete declared norm span |
| `norm_quantifier`, `norm_category`, `norm_modality`, `norm_action` | Exact ordered norm components |
| `physical_paragraph/<index>` | Every paragraph touched by those regions |

Definition-body atoms may occur in descendant paragraphs or cross paragraph
boundaries under the existing owner. All intersecting physical paragraphs are
retained. Repeated literals at different positions retain distinct identities;
shared geometry is stored once while keeping all role labels. Character and
UTF8 selectors address the normalized extracted view, never raw HTML offsets.
The complete original document remains inside the exact request custody record.

The companion retains exact original request/report JSON, source records,
composition scope, the full symbol table and rebinding, the variable binding,
bound definition AST, norm AST, full joint native AST and original generated
Lean body. Symbol identity uses the composition's edition-bound `scope_key` and
rebound symbols. Legacy definition symbols alone can coincide across editions
with identical HTML and are retained only as historical inputs to that rebinding.

The transport graph contains source-version and occurrence nodes, a declared
scope, interpretation custody, definition and norm assertions, a scoped head
`term_sense`, the full joint AST as an `expression`, and explicit issue nodes.
`DEFINES` connects the definition assertion to its category term; `USES_DEFINITION`
connects the norm assertion to that exact definition assertion. Source, scope,
custody and containment edges retain their content-addressed evidence. The first
profile emits no ground `HAS_ACTOR` or guessed condition/exception role edges.
Definition-body structure and variable/action bindings remain in the exact AST
and symbol records.

## Qualification, bounds and export

`declared_native_profile_encoded=true` means this bounded caller declaration
was regenerated and represented. It is separate from source fidelity or review.
Context may remain open. Source authenticity, source semantics, independent
review, admission, formalization, proof authority, backend execution, learned
translation and Lean compilation flags remain false. Issues preserve these gaps
and the absence of a general definition-coverage claim.

The existing corpus 1 MiB record, JSON depth and node bounds apply to each input
and the complete output companion. There are at most 256 unique source origins
and 512 role bindings. Original text, ASTs and graph envelopes may reach the
aggregate bound before these counts. Overflow refuses the operation without
dropping a paragraph, role, symbol or AST node.

Validation regenerates every nested record and graph edge from the independently
supplied original bytes. Resealing a changed outer record cannot authorize a
different source occurrence, modal scope, quantifier, symbol, issue or authority
flag. Parser/AST regeneration and emitted Lean text do not constitute a Lake
build or a proof.

Export delegates to the existing [candidate graph exchange](legal_corpus_graph_exchange.md)
after validation. The bundle transports graph envelopes only. Retain and
independently hash the full companion, original request/report and source bytes
separately: their payloads are not automatically embedded in `nodes.parquet` or
fetched through CIDs. No reviewed statutory corpus, complete Lean release or
publication is established by this export.
