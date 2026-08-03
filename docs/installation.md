# Installation Guide

| Field | Value |
| --- | --- |
| Interface | `InstallationGuide@1` |
| Task | `IPFSDOC-091` |
| Status | `canonical` |
| Owner | user-docs |
| Source of truth | `pyproject.toml`; `setup.py`; `requirements.txt`; `scripts/setup/install.py`; `docker/Dockerfile`; [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
| Last verified | 2026-08-03 |
| Audience | end-user, developer, operator |
| Related | [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md), [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md), [configuration.md](configuration.md), [PLATFORM_INSTALL.md](quickstart/PLATFORM_INSTALL.md) |

This page is the **short install route** for `ipfs_datasets_py`. Full extra tables, console scripts, native tools, lazy install policy, and capability probes live in [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md). Configuration precedence and security consequences live in [configuration.md](configuration.md) and [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md).

## 1. Requirements

| Requirement | Current packaging |
| --- | --- |
| **Python** | **Python 3.12+** (`requires-python = ">=3.12"` in `pyproject.toml`; `python_requires='>=3.12'` in `setup.py`) |
| Package manager | `pip` inside a virtual environment (recommended) |
| OS | Linux, macOS, Windows (platform markers differ for FAISS, magic, lazy ML helpers) |
| Disk / network | Base install needs network or a prepared wheelhouse; optional theorem provers, OCR models, and Playwright browsers need extra disk when provisioned |

**Not supported as the package baseline:** Python 3.7–3.11. Older docs that claim Python 3.7+ or 3.9+ are obsolete.

Base install is **not** every capability. Optional extras, system binaries, and native provers are separate layers; missing ones surface as **optional** / **unavailable**, not as silent success.

## 2. Base installation

### 2.1 Recommended: source checkout + project installer

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python scripts/setup/install.py --quick
# After install, keep using the activated .venv
```

`scripts/setup/install.py --quick` syncs `requirements.txt` into the target venv and installs the package editable. See the repository [README](../README.md) for installer options (`--venv-dir`, etc.).

### 2.2 Editable pip install only

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
python3.12 -m venv .venv && source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e .
```

Editable install resolves `ipfs_kit_py` / `ipfs_accelerate_py` from vendored checkouts when present, otherwise from GitHub `main` (see `setup.py`). Constrained builds can skip VCS optional deps:

```bash
export IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES=0
pip install -e .
```

### 2.3 Distribution name

Packaging metadata uses the distribution name **`ipfs_datasets_py`**:

```bash
pip install ipfs_datasets_py
# when published to the index you use; source install (§2.1–2.2) is the verified workspace path
```

### 2.4 Verify base install

```bash
python -c "import sys; assert sys.version_info >= (3, 12)"
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
# console scripts appear after install into the active env (setup.py entry points):
ipfs-datasets --help            # when setup.py scripts are installed
ipfs-datasets-install-provers --help
```

If a script is missing from `PATH`, reinstall with `pip install -e .` and confirm the venv is active.

## 3. Optional capabilities (real extras)

Install only the extras you need. Prefer the **declared** names below. Full matrix, platform markers, and recipes: [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md).

```bash
# Examples (editable source tree)
pip install -e '.[vectors]'
pip install -e '.[file_conversion,ocr]'
pip install -e '.[theorem-provers,logic]'
pip install -e '.[knowledge_graphs,web_archive,scraping]'
pip install -e '.[all,linux]'    # or windows / macos; still excludes full ml torch stack by design
```

| Extra (use these) | Role (summary) |
| --- | --- |
| `vectors` | FAISS / Qdrant / embeddings stack |
| `file_conversion` | MarkItDown / conversion path (Playwright browsers separate) |
| `theorem-provers` | Python bindings (`z3-solver`, `cvc5`, …)—**not** native CLIs |
| `knowledge_graphs` | spaCy, networkx, transformers, graph export |
| `web_archive` | WARC / archive tooling |
| `multimedia` / `ocr` / `scraping` / `api` / `lazy` / `test` | Media, OCR, scrape, HTTP/MCP, eager lazy-catalog, tests |
| `ml` | Heavy torch / LLM stack (**not** in `all`) |
| `all` | Large non-ML union |

### 3.1 Invalid or deprecated singular names (do not use)

| Invalid | Use instead |
| --- | --- |
| `vector` | `vectors` |
| `graphrag` | `knowledge_graphs` (+ app GraphRAG config) |
| `webarchive` / `web-archive` | `web_archive` |
| `theorem_prover` / `theorem-prover` | `theorem-provers` |
| Placeholder orgs (`your-organization`, `yourorga/…`) | `endomorphosis/ipfs_datasets_py` (or your real fork) |

### 3.2 System tools (not pip extras)

Python wheels do not replace host tools. Missing tools leave related features **unavailable**.

| Tool | Typical need |
| --- | --- |
| Kubo / `ipfs` | Local daemon workflows (CLI name overridable via `IPFS_DATASETS_PY_KUBO_CMD`) |
| FFmpeg | Multimedia conversion |
| Tesseract | `pytesseract` OCR |
| libmagic | `python-magic` on Linux/macOS |
| Playwright browsers | `python -m playwright install` after `file_conversion` |
| Cargo / Java / OPAM / elan | Groth16 builds and native theorem-prover portfolios |

Native provers install under a user-local root (default `~/.local/share/ipfs_datasets_py/theorem-provers`), not via `pip install` alone:

```bash
ipfs-datasets-install-provers --portfolio legal_ir_generation --yes --strict
```

Details: [lazy_theorem_prover_installation.md](security_verification/lazy_theorem_prover_installation.md).

### 3.3 GPU / CUDA note

Do **not** follow obsolete pin recipes (for example `torch==1.10.*+cu113` or blanket `faiss-gpu` one-liners from old docs). Current packaging:

- Prefer **`faiss-cpu`** via the `vectors` extra (platform-gated versions in packaging).
- Heavy GPU stacks come from the **`ml`** / accelerate paths and vendor wheel indexes for your OS/CUDA/driver set—select wheels that match **your** platform, then re-probe.
- Platform notes: [PLATFORM_INSTALL.md](quickstart/PLATFORM_INSTALL.md) and [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md).

## 4. Auto / lazy install, offline, and security

On import, if unset, `IPFS_DATASETS_AUTO_INSTALL` defaults toward allowing runtime `pip` for missing optional modules. That favors developer machines and is **unsafe** for immutable images without an explicit policy.

| Goal | Action |
| --- | --- |
| Production / CI (no surprise pip) | `export IPFS_DATASETS_AUTO_INSTALL=false` before import |
| Hermetic import | `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` or `IPFS_DATASETS_PY_BENCHMARK=1` |
| Offline / wheelhouse | `IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1` and `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/path/to/wheels` |
| Block native prover downloads | `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0` |
| Never grant sudo to prover install | Leave `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` unset (default deny) |

```bash
# Offline capability pre-provision example
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
pip install --no-index --find-links=/path/to/wheels -e '.[vectors,file_conversion,theorem-provers,lazy]'
```

Without a wheelhouse and without preinstalled binaries, optional features report **unavailable**—not proven, authorized, or healthy.

**Probe ≠ install ≠ capability ≠ authorization ≠ proof** (see [ADR-002](architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)).

```python
from ipfs_datasets_py.logic.common.feature_detection import is_module_available

if not is_module_available("faiss"):
    # degrade or skip vector path; do not claim production vector search
    ...
```

## 5. Docker (local build)

There is no verified public `yourorga/…` image in this tree. Build from the repository Dockerfile (`Dockerfile` → `docker/Dockerfile`, Python 3.12 base):

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
docker build -t ipfs_datasets_py:local -f docker/Dockerfile .
# compose samples under docker-compose.yml and deployments/ are environment-specific
```

Container images still need the same optional extras and system tools for full capabilities. Prefer `IPFS_DATASETS_AUTO_INSTALL=false` in production images and bake dependencies at build time.

Further deploy material: [deployment/](deployment/), [DOCKER_DEPLOYMENT_GUIDE.md](deployment/DOCKER_DEPLOYMENT_GUIDE.md) (verify against current manifests before production use).

## 6. Platform caveats (summary)

- **Windows:** FAISS pin and `python-magic-bin` differ; use `pip install -e '.[windows,…]'` when needed.
- **Linux / macOS:** `python-magic` needs system `libmagic`; Darwin skips some lazy `xformers` pins.
- **Architecture:** x86_64 and aarch64/arm64 are first-class for many tools; some ML/FAISS wheels are platform-gated.
- Full platform extras: [PLATFORM_INSTALL.md](quickstart/PLATFORM_INSTALL.md).

## 7. Uninstall / rollback (summary)

| Layer | Action |
| --- | --- |
| Python env | Recreate the venv, or `pip uninstall ipfs_datasets_py` |
| Optional extras | Reinstall without extras; shared base deps may remain |
| Native provers | Delete `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` intentionally (not removed by pip) |
| Playwright / NLTK data | Separate caches; clean with their own tools |

Keep capability installs in disposable virtualenvs when experimenting.

## 8. Troubleshooting (short)

| Symptom | Check |
| --- | --- |
| `ImportError` for optional stack | Install the matching **extra** (§3); probe with `is_module_available` |
| IPFS connection refused | Daemon/API not required for all paths; start Kubo or configure HTTP/kit backends (see [configuration.md](configuration.md)) |
| Prover / OCR / media fails | Missing **native** tool, not just a Python package |
| Surprise `pip` in CI | Set `IPFS_DATASETS_AUTO_INSTALL=false` before import |
| Wrong Python | Enforce 3.12+; recreate venv |

## 9. Next steps

| Need | Go to |
| --- | --- |
| Full extras, scripts, probes, offline matrix | [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
| Env vars, precedence, secrets | [configuration.md](configuration.md), [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
| First workflows | [getting_started.md](getting_started.md), [user_guide.md](user_guide.md) |
| Dependency / init architecture | [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) |
| Issues | [github.com/endomorphosis/ipfs_datasets_py/issues](https://github.com/endomorphosis/ipfs_datasets_py/issues) |
