# USPTO submission fixtures (PATLAW-033)

Compact synthetic generators and a recipe file for submission, amendment,
metadata, and receipt parsing tests.

## Design

- Prefer generators over bulk golden dumps.
- Canaries are synthetic markers, not real confidential filings.
- Signature fixtures include presence markers and deliberately include material
  that the processor must **suppress** (never reusable signing data).

## Layout

| Path | Purpose |
| --- | --- |
| `generators.py` | Text/field builders for amendments, receipts, DOCX/PDF pairs |
| `submission_recipe.json` | Compact case expectations |
| `__init__.py` | Re-exports for tests |

## Related gold corpus

Gold cases under `tests/fixtures/uspto/gold/cases/` (e.g.
`gold-amendments-current-claims`, `gold-filing-receipts`,
`gold-docx-pdf-difference`) provide higher-level truth labels; these fixtures
drive unit-level semantic extraction for `SubmissionProcessor`.
