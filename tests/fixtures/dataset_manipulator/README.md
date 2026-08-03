# Dataset Manipulator Characterization Fixtures (DSCON-G300)

Immutable fixtures for **freezing** observed dataset load / save / convert /
process contracts across direct Python, MCP tools, MCP client, HTTP, Swissknife
descriptor, and `ipfs_kit` integration surfaces.

## Policy

- **Characterization only.** Do not treat mock-success as a compatibility
  promise. Known defects are expected failures pending DSCON-G310 / DSCON-G320.
- **Side effects over shapes.** Assertions must observe persistence (or lack of
  it), fabricated counts, nondeterministic identities, and missing modules —
  not only `status` dictionary keys.
- **Safe vectors preserved.** Existing fail-closed security checks (dangerous
  op types, executable destinations, `.py` sources) remain required baselines.
- **No production edits** under DSCON-G300 / DSCON-005. Repair belongs to later
  packet goals (`dataset_contracts`, `DatasetManipulator`).

## Files

| File | Role |
| --- | --- |
| `manifest.json` | Fixture inventory, goal bindings, acceptance terms |
| `sample_dataset.json` | Hermetic offline sample used by live probes |
| `expected_behaviors.json` | Frozen failure/mock behaviors with drift links |
| `safe_vectors.json` | Security validations that must keep failing closed |
| `surface_inventory.json` | Entrypoint / package surface inventory |
| `digests.json` | SHA-256 digests of sibling fixture payloads |

Audit freeze companion:

`data/datasets_contract_analysis/audit/dataset-contract-baseline.json`

## Validation

```bash
python -m pytest -q ipfs_datasets_py/tests/contract/core_operations/test_dataset_manipulator_baseline.py
```

## Goal packet

`goal_packet/datasets_pilot/ipfs_datasets_py/c2f31d882e73`

- DSCON-G300 — freeze baselines (this directory)
- DSCON-G310 — canonical contracts / schema
- DSCON-G320 — real bounded `DatasetManipulator` core
