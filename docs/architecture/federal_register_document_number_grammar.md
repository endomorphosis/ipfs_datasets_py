# ADR: Federal Register document-number grammar and identity preservation

| Field | Value |
| --- | --- |
| Interface | `FederalRegisterSparseGraphRagReleaseSchema@2` |
| Task | `LCR-049`, `LCR-050` |
| Status | accepted |
| Date proposed | 2026-08-11 |
| Date accepted | 2026-08-11 |
| Decision owners | legal-ir / federal-foundation-completeness / federal-foundation-schema |
| Consulted | FederalRegister.gov API; NARA `federalregister-api-core`; Federal Register Sparse GraphRAG v2 schema ADR |
| Source of truth | `ipfs_datasets_py/processors/legal_data/federal_register_source_policy.py`; `ipfs_datasets_py/processors/legal_data/federal_register_release_schema.py` |
| Last verified | 2026-08-11 |
| Supersedes | [Federal Register Sparse GraphRAG v2 schema and identity-bound release contract](federal_register_sparse_graphrag_schema.md) |
| Superseded by | none |
| Origin | Repair of the predecessor ADR's incomplete `YYYY-NNNNN` document-number grammar |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The predecessor ADR represented every Federal Register document number as
`YYYY-NNNNN`. That shorthand excludes identifiers retained as canonical bytes
by FederalRegister.gov, including historical two-character series such as
`94-184`, `00-1`, `E9-9`, and `Z9-9`, and corrected or republished identifiers
such as `C1-2010-31877` and `R2-2023-00490`.

NARA's `federalregister-api-core` source tests enumerate a finite set of known
two-character series. The same source implementation treats a leading `C` or
`R` followed by one digit as an identity-bearing correction/republication
prefix. A generic alphanumeric fallback would admit unrelated identifiers such
as `CDC-2024-0015`, while applying the short historical tail rule to modern
years would admit non-canonical short shapes such as `2024-123`.

This successor incorporates every other decision and invariant from the
predecessor ADR unchanged. The only changed decision is the predecessor's
document-number grammar and examples.

## Decision

Federal Register document numbers use this closed ASCII grammar:

```text
historical_series := 0[0-9] | 20 | 9[2-9] | C[0-9] | E[13-9]
                   | R[0-9] | X[019] | Z[4-9]

modern             := [0-9]{4}-[0-9]{4,6}
historical         := historical_series-[0-9]{1,6}
revision           := [CR][0-9]-[0-9]{4}-[0-9]{4,6}
document_number    := modern | historical | revision
```

The four-digit year token in modern and revision forms must be between 1936
and 2100 inclusive. Document-number bytes are uppercase and are preserved
exactly; the LCR-049 and LCR-050 boundary validators do not strip revision
prefixes, pad tails, fold case, or replace a canonical API value with a lookup
alias.

`document_number` and `publication_date` remain the required segments of
`legal_id`:

```text
fr:<document_number>:<publication_date>[:qualifier...]
```

The `legal_id` segments must exactly equal the corresponding `CorpusRecord`
fields. Correction/republication records remain separate durable rows. Their
source-provided relationship is represented by `correction_relation` and
`related_document_number`; neither the prefix nor the related document may be
discarded or substituted for the correcting/republished row's identity.

## Consequences

- LCR-049 completeness and acquisition can retain every admitted canonical
  historical identifier without opening the prefix grammar to arbitrary
  letters or digits.
- LCR-050 release records, graph rows, locators, and receipts can use the same
  historical and revision identities without disagreement at schema borders.
- Modern and three-part revision forms keep their four-digit minimum tail, so
  short plain-year and short revision aliases remain invalid durable identity.
- The grammar is intentionally duplicated at the LCR-049 and LCR-050 trust
  boundaries; tests must exercise identical positive and negative matrices to
  prevent drift.

## Validation

The sealed unit suites must include:

- canonical one-, two-, and three-digit historical tails;
- modern, historical, correction, and republication examples;
- exact `legal_id` and `CorpusRecord` preservation;
- correction relationship and target preservation for a prefixed record;
- rejection of unknown series, lowercase or repeated prefixes, short modern or
  revision tails, implausible years, and overlong tails.

Validation commands:

```bash
python -m pytest tests/unit/processors/legal_data/test_federal_register_completeness.py -q
python -m pytest tests/unit/processors/legal_data/test_federal_register_release_schema.py -q
```
