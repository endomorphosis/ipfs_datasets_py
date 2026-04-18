# Docket Source Template Guide

This guide summarizes the public parser templates that are most useful for extending `ipfs_datasets_py` docket ingestion beyond normalized fixture inputs.

The current `legal_data` ingestion path already accepts normalized PACER- and Tyler Host-labeled JSON or directory inputs, CourtListener dockets, and local folders containing `.txt`, `.md`, `.json`, and `.pdf` files. This guide focuses on the next step: raw-source adapters.

## Currently Accepted Source Shapes

The current `ingest_docket_dataset(...)` flow is now regression-tested against these source shapes:

### PACER

- Normalized flat JSON with top-level docket fields and a `documents` array.
- Wrapped JSON where the usable docket payload is nested under envelopes such as `result` and `case`.
- Raw PACER docket HTML files.
- PACER HTML variants with extra columns, links, and multiline docket text cells.

### Tyler Host

- Normalized flat JSON with top-level docket fields and a `documents` array.
- Portal-style camelCase JSON using keys such as `caseNumber`, `caseTitle`, `courtName`, and `docketEntries`.
- Wrapped portal JSON where the usable case payload is nested under envelopes such as `result` and `case`.

### Auto-detection behavior

- `--input-type auto` detects raw PACER HTML by file suffix.
- `--input-type auto` detects PACER/Tyler wrapped JSON without `--source-type-hint` when nested `source_type` metadata is present under `result`, `case`, `data`, or `payload`.
- `--source-type-hint` is still useful when upstream JSON omits any source label.

## Recommended Sources

### 1. PACER HTML: `freelawproject/juriscraper`

Primary references:

- `juriscraper/pacer/docket_report.py`
- `tests/local/test_DocketParseTest.py`
- `tests/local/PacerParseTestCase.py`

Why this matters:

- It is the strongest public implementation for parsing raw PACER docket HTML into normalized metadata, party data, and docket entries.
- It includes fixture-backed tests that compare real checked-in HTML files against expected JSON outputs.
- It already handles docket-number parsing, document identifiers, party/counsel extraction, and docket-entry ordering concerns.

Use this as the model for any future `input_type=pacer_raw_html` adapter.

### 2. Portal-Style JSON: `freelawproject/juriscraper` ACMS parser

Primary references:

- `juriscraper/pacer/acms_docket.py`
- `tests/local/test_PacerParseACMSDocketTest.py`

Why this matters:

- ACMS is not Tyler Host, but it is the best public example of a hosted court portal JSON adapter.
- It shows a clean separation between upstream portal fields and downstream normalized output.
- It demonstrates how to normalize metadata, parties embedded as HTML, and structured docket-entry rows.

Representative upstream keys from the ACMS test fixture:

```json
{
  "caseDetails": {
    "caseId": "49d55502-744d-11ee-b5fa-e38eb4ba6cd2",
    "caseNumber": "23-1",
    "name": "Free Law Project v. People",
    "caseOpened": "2023-10-26",
    "partyAttorneyList": "<table>...</table>",
    "court": {"name": "Originating court name", "identifier": "OGC ID"},
    "feeStatus": "FLP"
  },
  "docketInfo": {
    "docketEntries": [
      {
        "endDate": "2023-10-28",
        "endDateFormatted": "10/28/2023",
        "entryNumber": 1,
        "docketEntryText": "<p>NEW PARTY...</p>",
        "docketEntryId": "19b65316-744e-11ee-a0a4-13890013fe63",
        "pageCount": 1
      }
    ]
  }
}
```

Use this as the model for any future `input_type=tyler_host_raw` or other portal-JSON adapter.

### 3. Downstream Normalization Contract: `freelawproject/courtlistener`

Primary references:

- `cl/recap/factories.py`
- `cl/recap/mergers.py`
- `cl/recap/tasks.py`

Why this matters:

- CourtListener provides the clearest public target contract for normalized docket data.
- Its factories and merge logic show which keys are expected at the docket level and which keys are expected on each docket entry.
- It is a better normalization target than any individual raw export shape.

Representative normalized fields:

### Docket-level fields

- `court_id`
- `case_name`
- `docket_number`
- `date_filed`
- `pacer_case_id`
- `federal_dn_office_code`
- `federal_dn_case_type`
- `federal_dn_judge_initials_assigned`
- `federal_dn_judge_initials_referred`
- `federal_defendant_number`

### Docket-entry fields

- `date_filed`
- `description`
- `short_description`
- `document_number`
- `pacer_doc_id`
- `pacer_seq_no`
- `document_url`
- `attachment_number`

## Tyler Host Research Result

I did not find a credible public GitHub repository that exposes Tyler Host or Tyler Odyssey docket export templates or parser code.

Searches for Tyler Host, Tyler Odyssey, court portal JSON, and related variants did not produce a reusable public contract.

Practical implication:

- Do not overfit a Tyler parser before you have a real sample export.
- Build the adapter shell around the ACMS-style pattern instead.
- Keep all Tyler-specific assumptions isolated to a source adapter layer.

## Recommended Normalized Contract For `ipfs_datasets_py`

For future raw-source adapters, normalize into the existing `ingest_docket_dataset(...)` flow and keep the contract stable.

Recommended minimum shape:

```json
{
  "docket_id": "1:24-cv-1001",
  "case_name": "Doe v. Example",
  "court": "D. Example",
  "source_type": "pacer",
  "case_number": "1:24-cv-1001",
  "documents": [
    {
      "id": "doc_1",
      "title": "Complaint",
      "text": "Extracted or provided document text.",
      "date_filed": "2024-01-10",
      "document_number": "1",
      "source_url": "file:///exports/complaint.pdf",
      "metadata": {
        "pacer_case_id": "123456",
        "pacer_doc_id": "987654",
        "source_path": "/exports/complaint.pdf"
      }
    }
  ],
  "plaintiff_docket": [],
  "defendant_docket": [],
  "authorities": []
}
```

Also accepted for wrapped portal exports:

```json
{
  "result": {
    "source_type": "tyler_host",
    "case": {
      "caseNumber": "TYLER-2025-099",
      "caseTitle": "In re Example Petition",
      "courtName": "Example County Probate Court",
      "docketEntries": [
        {
          "documentId": "entry_1",
          "documentTitle": "Petition for Appointment",
          "text": "Petition text.",
          "filedDate": "2025-01-07",
          "docNumber": "1",
          "documentUrl": "https://portal.example.gov/documents/1"
        }
      ]
    }
  }
}
```

The JSON importer unwraps envelopes like `result`, `case`, `data`, and `payload` before normalizing the docket.

Suggested mapping rules:

- Prefer `case_number` and `docket_id` to preserve the human docket reference.
- Store raw source identifiers such as `pacer_case_id`, `pacer_doc_id`, or portal row IDs under document metadata when they do not fit the top-level contract.
- Keep upstream raw payloads out of the top-level schema unless explicitly needed for provenance.
- Preserve source labels with `source_type`, for example `pacer`, `tyler_host`, `courtlistener`, or `directory_pdf`.

## Suggested Adapter Strategy

### PACER raw HTML

1. Parse raw HTML into a Juriscraper-like object model.
2. Normalize metadata, parties, and docket entries.
3. Emit the current `ingest_docket_dataset(...)`-compatible shape.
4. Add fixture-backed regression tests using checked-in HTML samples.

### Tyler Host raw export

1. Identify the real root object and docket-entry array from a sample export.
2. Map metadata, parties, and entries into the ACMS-style intermediate shape.
3. Normalize into the current `ingest_docket_dataset(...)`-compatible shape.
4. Add one checked-in raw sample plus one normalized fixture.

## Fixture Strategy

For each new raw adapter, keep both of these in the test suite:

- A raw-source fixture that matches the upstream format.
- A normalized fixture that matches the stable `legal_data` ingestion contract.

This keeps parser breakage separate from downstream ingestion breakage.

## Current Recommendation

- Use Juriscraper `DocketReport` as the canonical PACER raw parser template.
- Use Juriscraper `ACMSDocketReport` as the structural template for Tyler Host and other portal-style JSON exports.
- Use CourtListener recap factories and merger expectations as the normalization target.
- Treat Tyler Host field mappings as provisional until a real export sample is available, but the current importer already supports normalized, camelCase, and wrapped Tyler-style JSON variants.