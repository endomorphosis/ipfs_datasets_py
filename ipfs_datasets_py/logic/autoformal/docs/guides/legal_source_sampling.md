# Whole-source sampling before formalization

`logic.autoformal.legal_source_sampling` prepares a deterministic complete input
population from independently pinned GovInfo HTML. It calls the existing
`legal_official_document_views` owner once per preparation or validation, then
uses `corpus_source` for source versions, exact character/UTF8 occurrences and
required-unavailable context declarations. It performs no network I/O or model,
training, native Lean, review, trust or publication action.

```python
from ipfs_datasets_py.logic.autoformal.legal_source_sampling import (
    prepare_source_sampling,
    source_sampling_report_sha256,
    validate_source_sampling,
)

# raw and the independent descriptor/content pins come from retained acquisition.
report = prepare_source_sampling(raw, **trusted_acquisition_inputs)
full_report_sha256 = source_sampling_report_sha256(report)
# Store that digest independently with the exact report and original raw body.
validate_source_sampling(
    report, raw, expected_report_sha256=full_report_sha256,
    **trusted_acquisition_inputs,
)
```

`trusted_acquisition_inputs` has `descriptor`, `expected_descriptor_sha256`,
`expected_raw_sha256` and `expected_raw_bytes`. The descriptor is the existing
closed `legal-official-source-acquisition/v1` contract, including actual HTTP
observations. Missing observations cannot be invented from a successful text
extraction. The optional `view_limits` belongs to the unchanged view owner;
`limits` may only lower the sampler's 2,048-unit/32-MiB whole-report caps.

The complete V2 document/view report stays in the result, with ordered blocks,
markup comments, table coordinates, classes, attributes and exact normalized
text. Every block produces one source occurrence, one context declaration and
one sealed sample unit, in original DOM order. The source-version record appears
first. Unit references bind full canonical record SHA256, CID and schema;
markup-block references bind its exact index, block ID and full canonical hash.
The complete normalized text is all block text joined by the retained LF
separators. Raw HTML and earlier V1/Parquet coordinates remain distinct.

The policy `complete-official-markup-block-population/v1` distinguishes three
input strata using existing markup observations:

- `candidate_statute_paragraph`: a whole paragraph in the declared statute field;
- `statute_structure_context`: other blocks in that field, including headings;
- `retained_context_control`: all remaining blocks, including metadata, source
  credits, tables, editorial/statutory notes and footnotes.

No block is removed, shortened to fit a grammar, sentence-split on a citation,
randomly selected or merged with another identical-text occurrence. A candidate
paragraph can contain several legal clauses, inline labels, a repeal marker or
an unresolved continuation. It is a source input, not a reviewed operative norm
or definition. Statutory notes can carry operative law and remain available.
Physical DOM order/classes do not resolve legal hierarchy, inherited scope or
continuation attachment. The full source view is available as context, while all
six dependency requirements stay open under the existing context owner.

A `br`, field boundary or nested block can split one physical paragraph into
several normalized blocks. Any statute paragraph with repeated DOM paths or
descendant block text is withheld from primary candidates. Its pieces remain
structure/context units, and `withheld_paragraph_contexts` retains the complete
parent range, source/context refs and explicit unsupported-assembly reason.
This prevents an action prefix from becoming a separate input without its
condition. The retained parent is not a resolved meaning unit. Such contexts can
add source/context records beyond the usual one version plus three per block.

All training/evaluation-gold masks are zero. Meanings, formal outputs and graph
assertions are empty; all authority/admission flags are false. The sampler does
not join existing span-cache rows, reinterpret the nine retained literal pilot
selectors, resolve a cross-section definition, or supply a statistical coverage
estimate. Add actual reviewed meanings and compatible downstream profiles later.

Missing raw bytes or unsupported markup retain the existing owner's explicit
disposition with no units. Invalid independent pins, corrupt bodies and exceeded
population/byte bounds raise with no partial result. Validation regenerates the
complete source/population and rejects rehashed or resealed omissions, reordered
units, changed source references or positive masks. A full report hash includes
its internal `sampling_report_sha256` payload digest; the two hashes have
different scopes.
Both public hashing and validation enforce the fixed hard report budget;
validation also checks the report's lowered byte limit before source replay.
