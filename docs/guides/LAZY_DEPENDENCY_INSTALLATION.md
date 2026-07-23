# Lazy Dependency Installation

`ipfs_datasets_py` declares dependencies through `setup.py`,
`pyproject.toml`, and the requirements files. It can also resolve supported
Python dependencies when a feature first requests them.

## Behavior

The lazy resolver:

1. Tries a normal import.
2. Returns the installed module without invoking `pip` when it is available.
3. Maps the import name to its declared distribution, such as `fitz` to
   `pymupdf` or `PIL` to `pillow`.
4. Installs the reviewed requirement only when the requested module is
   missing and automatic installation is enabled.
5. Invalidates import caches and verifies the import after installation.

Imports that fail because an installed package has a missing transitive
dependency or raises another runtime error do not trigger a reinstall loop.
Parallel threads and supervisor worker processes share a per-distribution
single-flight lock, so only one worker invokes `pip`.

## Configuration

Set the policy before importing the package:

```bash
export IPFS_DATASETS_AUTO_INSTALL=true
```

The package currently enables this policy when it is unset. Set it explicitly
to `false` for immutable environments:

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
```

`IPFS_AUTO_INSTALL` remains a compatibility alias. Minimal-import and
benchmark modes always disable runtime installation:

```bash
export IPFS_DATASETS_PY_MINIMAL_IMPORTS=1
# or
export IPFS_DATASETS_PY_BENCHMARK=1
```

Useful controls:

| Variable | Purpose |
| --- | --- |
| `IPFS_DATASETS_PIP_TIMEOUT` | Per-`pip` timeout in seconds; bounded to 30-3600. |
| `IPFS_DATASETS_INSTALL_LOCK_TIMEOUT` | Maximum wait for another worker's install. |
| `IPFS_DATASETS_INSTALL_RETRY_SECONDS` | Cooldown after a failed installation. |
| `IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1` | Add `--no-index` to lazy `pip` calls. |
| `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE` | Add a local `--find-links` wheel directory. |
| `IPFS_INSTALL_VERBOSE=1` | Emit installer diagnostics. |

`IPFS_DATASETS_ENSURE_INSTALLER=1` controls repository/submodule bootstrap and
is intentionally separate. Enabling lazy Python dependencies does not run
repository setup helpers.

## API

Use `lazy_import` or `ensure_module` at a feature boundary:

```python
from ipfs_datasets_py import lazy_import

faiss = lazy_import("faiss")
if faiss is None:
    raise RuntimeError("The vector backend is unavailable")
```

The shared proxy provides cached attribute access:

```python
from ipfs_datasets_py._dependencies import dependencies

table = dependencies.pyarrow.Table.from_pylist([{"id": 1}])
```

Importing the proxy does not probe or install its modules. The first
`dependencies.pyarrow` access performs resolution.

Feature groups can be provisioned eagerly when runtime mutation is
undesirable:

```bash
pip install -e '.[ocr,multimedia,theorem-provers,lazy]'
pip install -r requirements-lazy.txt
pip install -r requirements-theorem-provers.txt
```

## Native Provers

Native theorem provers are not ordinary Python wheels. They continue to use
the checksum-aware prover installer and its separate
`IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS` policy. In particular, MathSAT is
installed through pySMT's solver installer rather than a `mathsat` PyPI
requirement.
