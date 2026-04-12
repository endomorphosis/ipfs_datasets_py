# Legal PDF Manifests

This guide documents the JSON manifest shapes supported by
`ipfs_datasets_py.processors.legal_data` and the `ipfs-datasets legal-pdf`
CLI.

## State Court Filing Packet Manifest

Use with:

```bash
ipfs-datasets legal-pdf \
  --action validate-manifest \
  --manifest-path /path/to/court_packet_manifest.json \
  --json
```

Then build with:

```bash
ipfs-datasets legal-pdf \
  --action build-court-filing-packet-from-manifest \
  --manifest-path /path/to/court_packet_manifest.json \
  --json
```

Minimal shape:

```json
{
  "$schema": "../schemas/legal_pdf/state_court_filing_packet_manifest.schema.json",
  "documents": [
    "motion.md",
    "memorandum.md",
    "declaration.md"
  ],
  "output_dir": "rendered_pdfs",
  "packet_output_path": "rendered_pdfs/filing_packet.pdf",
  "config": {
    "contact_block_html": "Party Name, pro se<br/>Party Role",
    "court_name": "IN THE [COURT NAME]",
    "state_name": "[STATE OR JURISDICTION]",
    "caption_left_html": "PLAINTIFF OR PETITIONER,<br/>v.<br/>DEFENDANT OR RESPONDENT.",
    "case_number_line": "Case No. __________________",
    "filed_date": "April 12, 2026",
    "signature_doc_keywords": ["motion", "memorandum", "certificate_of_service"],
    "declaration_doc_keywords": ["declaration"],
    "signature_names": ["Party One, pro se", "Party Two, pro se"],
    "declaration_name_by_stem_keyword": {
      "party_one": "Party One, Declarant"
    },
    "default_declarant_name": "Declarant"
  }
}
```

Field notes:

- `documents`: markdown files, relative to the manifest location
- `output_dir`: directory for individual rendered PDFs
- `packet_output_path`: merged output PDF
- `config`: serialized `StateCourtPleadingConfig`

Workspace example:

- [combined_state_court_packet_manifest.json](/home/barberb/HACC/workspace/combined_state_court_packet_manifest.json)
- Minimal reusable example: [state_court_filing_packet_manifest.example.json](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf/state_court_filing_packet_manifest.example.json)

## Exhibit Binder Manifest

Use with:

```bash
ipfs-datasets legal-pdf \
  --action validate-manifest \
  --manifest-path /path/to/exhibit_binder_manifest.json \
  --json
```

Then build with:

```bash
ipfs-datasets legal-pdf \
  --action build-exhibit-binder-from-manifest \
  --manifest-path /path/to/exhibit_binder_manifest.json \
  --json
```

Minimal shape:

```json
{
  "$schema": "../schemas/legal_pdf/exhibit_binder_manifest.schema.json",
  "family": "Core Exhibit Binder",
  "front_sheet_markdown": "covers/EXHIBIT_BINDER_FRONT_SHEET.md",
  "working_dir": "compiled_from_manifest",
  "output_pdf": "compiled_from_manifest/MASTER_Exhibit_Binder_Core_Set.pdf",
  "exhibits_root": "exhibits",
  "court_config": {
    "case_number": "Case No. __________________",
    "court_name": "IN THE COURT OF COMPETENT JURISDICTION",
    "state_name": "STATE / JURISDICTION",
    "contact_block_html": "Filing Party, pro se<br/>Party Role",
    "caption_left_html": "PLAINTIFF OR PETITIONER,<br/>v.<br/>DEFENDANT OR RESPONDENT."
  },
  "caption_config": {
    "court_lines": [
      "IN THE COURT OF COMPETENT JURISDICTION",
      "FOR THE APPROPRIATE COUNTY OR DISTRICT",
      "CIVIL / PROBATE / HOUSING DIVISION"
    ],
    "case_number": "Case No. __________________",
    "right_block_lines": [
      "In the Matter of:",
      "Protected Person / Party Name,",
      "Party / Subject."
    ],
    "left_block_label": "EXHIBIT VOLUME"
  },
  "exhibits": [
    {
      "code": "A",
      "title": "Sample Exhibit",
      "divider_markdown": "covers/Exhibit_A_tab_divider.md",
      "cover_markdown": "covers/Exhibit_A_cover_sheet.md"
    }
  ]
}
```

Field notes:

- `front_sheet_markdown`: front sheet markdown, relative to the manifest
- `working_dir`: output/intermediate directory
- `output_pdf`: final merged binder PDF
- `exhibits_root`: optional directory used to infer each exhibit source file by `Exhibit_<CODE>_*`
- `court_config`: optional binder caption/header override; defaults to the package binder court config
- `caption_config`: optional tab/cover exhibit-caption override for divider and cover-page renderers
- `exhibits[].source`: optional explicit source path; overrides inference
- `exhibits[].divider_markdown`: divider/tab markdown
- `exhibits[].cover_markdown`: cover sheet markdown

Workspace example:

- [exhibit_binder_manifest.json](/home/barberb/HACC/workspace/exhibit-binder-court-ready/exhibit_binder_manifest.json)
- Minimal reusable example: [exhibit_binder_manifest.example.json](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf/exhibit_binder_manifest.example.json)

## Full Evidence Binder Manifest

Use with:

```bash
ipfs-datasets legal-pdf \
  --action validate-manifest \
  --manifest-path /path/to/full_evidence_binder_manifest.json \
  --json
```

Then build with:

```bash
ipfs-datasets legal-pdf \
  --action build-full-evidence-binder-from-manifest \
  --manifest-path /path/to/full_evidence_binder_manifest.json \
  --lean-mode \
  --json
```

Minimal shape:

```json
{
  "$schema": "../schemas/legal_pdf/full_evidence_binder_manifest.schema.json",
  "submitted_by": "Filing Party, Pro Se",
  "exhibit_covers_root": "covers",
  "working_dir": "build",
  "generated_dir": "build/generated_pdfs",
  "build_manifest_output": "build/manifest.txt",
  "output_pdf": "build/full_binder.pdf",
  "lean_output_pdf": "build/full_binder_lean.pdf",
  "index_pdf": "binder_index.pdf",
  "caption_config": {
    "court_lines": [
      "IN THE COURT OF COMPETENT JURISDICTION",
      "FOR THE APPROPRIATE COUNTY OR DISTRICT",
      "CIVIL / PROBATE / HOUSING DIVISION"
    ],
    "case_number": "Case No. __________________",
    "right_block_lines": [
      "In the Matter of:",
      "Protected Person / Party Name,",
      "Party / Subject."
    ],
    "left_block_label": "EXHIBIT VOLUME"
  },
  "families": [
    {
      "name": "Primary Binder",
      "cover_dirs": ["primary"],
      "labels": ["Exhibit A", "Exhibit B"],
      "output_pdf": "build/primary_binder.pdf",
      "lean_output_pdf": "build/primary_binder_lean.pdf"
    }
  ],
  "lean_replacements": [
    {
      "family": "Primary Binder",
      "label": "Exhibit B",
      "lines": [
        "Lean binder replacement page.",
        "",
        "This exhibit is incorporated by reference from Exhibit A in the same binder."
      ]
    }
  ]
}
```

Field notes:

- `submitted_by`: text shown on the binder title page
- `exhibit_covers_root`: root directory containing family cover subdirectories
- `working_dir`: top-level build directory for regenerated artifacts
- `generated_dir`: optional explicit PDF generation directory inside the build
- `build_manifest_output`: optional text manifest emitted during assembly
- `output_pdf`: merged full binder output
- `lean_output_pdf`: alternate output path used when `--lean-mode` is set
- `index_pdf`: optional already-rendered index PDF inserted after the binder title page
- `index_command`: optional command run before reading `index_pdf`
- `caption_config`: optional caption override for title/divider/tab/cover pages
- `families[].cover_dirs`: one or more subdirectories searched for tab/cover markdown files
- `families[].labels`: exhibit labels in final merge order for that family
- `families[].output_pdf`: optional per-family merged binder output
- `lean_replacements`: optional cross-reference pages keyed by `(family, label)` for lean builds

Workspace example:

- [full_evidence_binder_manifest.json](/home/barberb/HACC/workspace/full_evidence_binder_manifest.json)
- Minimal reusable example: [full_evidence_binder_manifest.example.json](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf/full_evidence_binder_manifest.example.json)

## JSON Response Keys

When `--json` is used, the manifest builder actions return these top-level payload keys.

State-court filing packet:

- `action`: `build-court-filing-packet-from-manifest`
- `manifest_path`: source manifest path
- `packet_path`: merged filing packet PDF
- `rendered_paths`: individual rendered pleading PDFs
- `document_count`: number of rendered documents

Exhibit binder:

- `action`: `build-exhibit-binder-from-manifest`
- `manifest_path`: source manifest path
- `output_pdf`: merged exhibit binder PDF
- `front_pdf`: rendered front sheet PDF
- `table_pdf`: rendered table-of-exhibits PDF
- `packet_paths`: per-exhibit packet PDFs
- `exhibit_count`: number of exhibit packets

Full evidence binder:

- `action`: `build-full-evidence-binder-from-manifest`
- `manifest_path`: source manifest path
- `working_dir`: top-level build directory
- `generated_dir`: generated PDF directory
- `build_manifest_output`: emitted text build manifest
- `output_pdf`: merged full binder PDF
- `family_outputs`: mapping of family name to per-family merged PDF
- `family_count`: number of family sections processed
- `merged_input_count`: number of PDFs merged into the final binder
- `lean_mode`: whether lean replacements were used

## Config-Driven Default Builders

Some reusable builders are not manifest-based but support JSON config files via
`--config-path`:

- `build-court-ready-binder-index-default`
- `build-official-form-drafts-default`
- `build-filing-specific-binders-default`

Example config files:

- [courtstyle_packet_config.example.json](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf/courtstyle_packet_config.example.json)
- [court_ready_binder_index_config.example.json](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf/court_ready_binder_index_config.example.json)
- [official_form_drafts_config.example.json](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf/official_form_drafts_config.example.json)
- [filing_specific_binders_config.example.json](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf/filing_specific_binders_config.example.json)

## Practical Notes

- Relative paths resolve from the manifest file's directory.
- Schema files live under [docs/schemas/legal_pdf](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/schemas/legal_pdf).
- Copy-ready examples live under [docs/examples/legal_pdf](/home/barberb/HACC/complaint-generator/ipfs_datasets_py/docs/examples/legal_pdf).
- `validate-manifest` checks a manifest without rendering any PDFs.
- Filing packet manifests are best for motions, declarations, memoranda, and certificates.
- Exhibit binder manifests are best for front sheets, tables of exhibits, divider pages, cover sheets, and source exhibits.
- Full evidence binder manifests are best for multi-family exhibit volumes that also emit per-family merged binders and lean cross-reference builds.
- Binder manifest builds now prefer Python PDF merging before falling back to `pdfunite`.
