# Source-package metadata intake

`ipfs_datasets_py.logic.autoformal.legal_source_package_intake_v1` validates
five supplied metadata files for `justicedao/ipfs_uscode`: `manifest.json`,
`release_metadata.json`, `dataset_configs.json`, `dataset_infos.json` and
`README.md`. It preserves their exact UTF-8 bytes, selection order and
descriptor or declaration discrepancies for later source/span/entity work.

The caller supplies the exact request bytes, an independent request SHA-256,
and a mapping from those five paths to bytes. The closed request fields are:

```text
schema = legal-source-package-intake-request/v1
repository_id = justicedao/ipfs_uscode
revision = immutable lowercase forty-hex Hub revision
expected_release_identity = independently expected release identity
expected_graph_population = independently expected graph descriptor population
files = [{path_in_repo, bytes, sha256}, ...]
```

All five paths must occur exactly once. Their order is caller-selected and
retained. The existing `legal_primary_graph_manifest` owner verifies the
supplied manifest against independent raw-byte, release and graph-population
expectations. The Hub revision and producer source revision remain separate;
their association is caller-supplied acquisition evidence.

The public functions are:

```python
prepare_source_package_intake(
    request_raw, metadata_bytes, *, expected_request_sha256
)
source_package_intake_sha256(report)
validate_source_package_intake(
    report, request_raw, metadata_bytes, *,
    expected_request_sha256, expected_report_sha256
)
```

Validation requires the independent report pin and regenerates the complete
report from the original inputs. Rehashing an altered report does not replace
that replay. The request is bounded to 256 KiB, each metadata file to 2 MiB,
aggregate metadata to 4 MiB and the complete report to 8 MiB. Exceeding a bound
refuses the operation.

The report distinguishes declared data-glob rows, routing-index rows, corpus
rows and advertised training examples. `unique_laws` remains unknown and
`rows_read` remains zero. Companion discrepancies are retained in `issues`;
`selected_metadata_verified_with_discrepancies` does not repair them. It opens
no corpus/graph table, database, model or network connection, and binds no
source occurrence or legal meaning. All authority flags remain false.

Owner file hashes are selected source observations. They do not establish
complete imported-byte identity, authenticate a remote revision or qualify
training targets or Lean proofs. The larger source/span/entity join is a
separate integration boundary.

The existing test owner is
`tests/unit/logic/autoformal/test_legal_source_package_intake_v1.py`. Its 45
synthetic cases previously passed within the October16 302-case join cohort;
the other 257 cases belong to their respective owners. Fresh clean-main
qualification and its original source/native/storage closure must be recorded
separately before crediting this integration.
