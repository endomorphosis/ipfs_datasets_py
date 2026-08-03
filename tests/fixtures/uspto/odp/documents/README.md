# ODP document sync fixtures

Compact inventory + download recipes for `PATLAW-023` unit tests.

- Schema: `odp-document-sync-fixture-v1`
- Loader: `ipfs_datasets_py.processors.domains.uspto.document_sync_processor.load_document_sync_recipe`
- Processor helper: `processor_from_recipe_case`

Prefer extending `odp_document_sync_recipe.json` with minimal document envelopes
and small synthetic PDF bodies (base64) over bulk golden dumps.
