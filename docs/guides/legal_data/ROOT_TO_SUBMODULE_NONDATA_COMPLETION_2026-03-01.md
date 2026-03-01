# Root-to-Submodule Non-Data Migration Completion (2026-03-01)

This note records completion of the requested non-data migration scope.

## Completed

- `src/municipal_scrape_workspace/hybrid_legal_ir.py`
  - Canonical module moved to:
    - `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_legal_ir.py`
  - Root path retained as compatibility shim.

- Legal/formal `scripts/ops` entrypoints
  - Canonical implementations live in:
    - `ipfs_datasets_py/scripts/ops/legal_data/`
  - Root `scripts/ops/*` legal/formal files are compatibility wrappers only.

- Root docs compatibility pointers
  - `docs/HYBRID_LEGAL_IR_SPEC.md`
  - `docs/HYBRID_LEGAL_REASONING_EXECUTION_PLAYBOOK.md`
  - `docs/HYBRID_LEGAL_REASONING_IMPROVEMENT_PLAN.md`
  - `docs/HYBRID_LEGAL_REASONING_TODO.md`
  - `docs/REASONER_ARCHITECTURE.md`
  - Canonical documents live under:
    - `ipfs_datasets_py/docs/guides/legal_data/`

## Explicit Exclusion

- `data/state_laws/*`
  - No migration performed.
  - Artifacts remain in root workspace as requested while state-law workflows are still under active development.

## Traceability

- Scope manifests:
  - `ipfs_datasets_py/docs/guides/legal_data/ROOT_TO_SUBMODULE_SCOPE1_MANIFEST_2026-03-01.tsv`
  - `ipfs_datasets_py/docs/guides/legal_data/ROOT_TO_SUBMODULE_SCOPE2_MANIFEST_2026-03-01.tsv`
  - `ipfs_datasets_py/docs/guides/legal_data/ROOT_TO_SUBMODULE_SCOPE3_MANIFEST_2026-03-01.tsv`
