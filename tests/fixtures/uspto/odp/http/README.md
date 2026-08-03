# ODP Patent File Wrapper HTTP fixtures

Compact recorded HTTP exchanges for `PATLAW-021` unit tests.

- Schema: `odp-http-fixture-v1`
- Loader: `ipfs_datasets_py.processors.domains.uspto.providers.base.load_recorded_exchanges`
- Client factory: `PatentFileWrapperClient.from_recorded_recipe`

Prefer extending `odp_http_recipe.json` with minimal envelopes over bulk
golden dumps that re-emit full upstream payloads per case.
