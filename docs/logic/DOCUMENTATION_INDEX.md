# Logic Module Documentation Index

**Last Updated:** 2026-04-23  
**Status:** Current index for logic architecture/API docs and code-adjacent docs

---

## Quick Links

### Core Docs in `docs/logic/`

- [Architecture (code-aligned)](./logic_ARCHITECTURE.md)
- [API Reference (code-aligned)](./logic_API_REFERENCE.md)
- [Known Limitations](./KNOWN_LIMITATIONS.md)

### Primary Code-Adjacent Docs in `ipfs_datasets_py/logic/`

- [Logic package README](../../ipfs_datasets_py/logic/README.md)
- [FOL README](../../ipfs_datasets_py/logic/fol/README.md)
- [Deontic README](../../ipfs_datasets_py/logic/deontic/README.md)
- [Common utilities README](../../ipfs_datasets_py/logic/common/README.md)
- [TDFOL README](../../ipfs_datasets_py/logic/TDFOL/README.md)
- [CEC README](../../ipfs_datasets_py/logic/CEC/README.md)
- [F-logic README](../../ipfs_datasets_py/logic/flogic/README.md)
- [ZKP README](../../ipfs_datasets_py/logic/zkp/README.md)
- [External provers README](../../ipfs_datasets_py/logic/external_provers/README.md)
- [Types README](../../ipfs_datasets_py/logic/types/README.md)

---

## Documentation Scope

This index is focused on:

1. **Public logic architecture and API overviews** (`docs/logic/logic_*.md`)
2. **Code-adjacent module documentation** under `ipfs_datasets_py/logic/*/README.md`
3. **Current ZKP behavior and integration points**

---

## ZKP Documentation Navigation

- High-level architecture/API context:
  - [logic_ARCHITECTURE.md](./logic_ARCHITECTURE.md)
  - [logic_API_REFERENCE.md](./logic_API_REFERENCE.md)
- ZKP implementation docs:
  - [logic/zkp/README.md](../../ipfs_datasets_py/logic/zkp/README.md)

Notes:
- Default ZKP behavior is simulation-oriented and explicitly marked non-production for cryptographic assurance.
- Backend selection includes a Groth16 path with runtime/artifact gating.

---

## Validation Commands

Run from repository root:

```bash
python -m pytest -q tests/unit/logic
python -m pytest -q tests/unit_tests/logic
```

If `pytest` is not installed in the environment, install test dependencies first.

---

## Maintenance Checklist

When updating logic docs, verify against:

- `ipfs_datasets_py/logic/api.py`
- `ipfs_datasets_py/logic/__init__.py`
- submodule `__init__.py` exports (`fol`, `deontic`, `common`, `types`, `integration`, `TDFOL`, `CEC`, `flogic`, `zkp`)
- ZKP integration modules:
  - `ipfs_datasets_py/logic/TDFOL/zkp_integration.py`
  - `ipfs_datasets_py/logic/CEC/native/cec_zkp_integration.py`
  - `ipfs_datasets_py/logic/flogic/flogic_zkp_integration.py`
