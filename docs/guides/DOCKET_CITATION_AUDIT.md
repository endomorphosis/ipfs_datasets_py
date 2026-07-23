# Docket Citation Audit Payloads

This guide documents the citation audit payloads emitted by the docket dataset pipeline, including the EU/member-state citation audit.

## Audit Sources

- **Docket dataset audit**: `audit_docket_dataset_citation_sources(...)`
- **Packaged docket audit**: `audit_packaged_docket_citation_sources(...)`
- **EU-only audit**: `audit_docket_dataset_eu_citation_sources(...)`

These calls return a JSON-compatible dictionary. The top-level audit for docket datasets includes Bluebook citation resolution results and (optionally) a nested EU/member-state audit.

## Top-Level Audit (Docket Dataset)

```json
{
  "dataset_id": "docket_dataset_1_24_cv_1010",
  "docket_id": "1:24-cv-1010",
  "source": "docket_dataset_citation_source_audit",
  "citation_count": 7,
  "matched_citation_count": 6,
  "unmatched_citation_count": 1,
  "citation_resolution_ratio": 0.857,
  "unresolved_documents": [
    {
      "document_id": "doc_2",
      "unmatched_citations": [
        {
          "citation_text": "Minn. Stat. § 999.999",
          "normalized_citation": "minn stat 999 999",
          "metadata": {
            "recovery_supported": true
          }
        }
      ]
    }
  ],
  "eu_citation_audit": { "...": "See schema below" }
}
```

### Notes
- The `eu_citation_audit` field is included when `include_eu_audit=True` (default).
- The audit is suitable for embedding into `dataset.metadata["citation_source_audit"]`.

## EU/Member-State Citation Audit

```json
{
  "dataset_id": "docket_dataset_1_24_cv_1010",
  "docket_id": "1:24-cv-1010",
  "source": "docket_dataset_eu_citation_audit",
  "document_count": 12,
  "documents_analyzed": 12,
  "documents_with_citations": 3,
  "citation_count": 6,
  "unique_citation_count": 5,
  "citations_by_scheme": {
    "CELEX": 2,
    "ECLI": 3
  },
  "citations_by_member_state": {
    "DE": 2,
    "FR": 1,
    "NL": 1
  },
  "lookup_action_count": 5,
  "lookup_handlers": {
    "eurlex_registry": 2,
    "ecli_registry": 3
  },
  "documents": [
    {
      "document_id": "doc_1",
      "title": "EU Filing",
      "citation_count": 2,
      "schemes": ["CELEX", "ECLI"],
      "member_states": ["DE"]
    }
  ],
  "citations": [
    {
      "raw_text": "CELEX 32016R0679",
      "normalized_text": "32016R0679",
      "scheme": "CELEX",
      "citation_type": "legislation",
      "jurisdiction": "EU",
      "canonical_uri": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
      "member_state": null,
      "identifiers": [],
      "metadata": {}
    }
  ],
  "lookup_actions": [
    {
      "dataset_id": "eurlex",
      "handler_key": "eurlex_registry",
      "query_text": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
      "action_type": "eu_legislation_lookup",
      "parameters": {
        "language": "en",
        "member_state": null
      }
    }
  ]
}
```

### Notes
- `citations` and `lookup_actions` are de-duplicated across documents.
- Use `lookup_actions` to drive resolver execution later (for example, in an asynchronous enrichment step).
- EU audits can be stored separately under `dataset.metadata["eu_citation_audit"]` for quick access.

## Summary Fields

These are surfaced across summaries, inspection payloads, and dashboards:

- `eu_citation_count`
- `eu_unique_citation_count`
- `eu_documents_with_citations`

## CLI Flags

```bash
ipfs-datasets docket --citation-source-audit \
  --eu-citation-language en \
  --eu-citation-max-documents 200 \
  --json
```
