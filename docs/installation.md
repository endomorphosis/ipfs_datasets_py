# Installation Guide

| Field | Value |
| --- | --- |
| Interface | `InstallationGuide@1` |
| Task | `IPFSDOC-091` |
| Status | `canonical` (root user entry) |
| Owner | user-docs |
| Source of truth | `pyproject.toml`; `setup.py`; detailed [CAPABILITY_INSTALLATION](guides/installation/CAPABILITY_INSTALLATION.md) |
| Last verified | 2026-08-03 |
| Audience | end-user, operator, developer |
| Related | [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md), [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md), [configuration.md](configuration.md), [PLATFORM_INSTALL.md](quickstart/PLATFORM_INSTALL.md) |

This page is the **short root route** for installing `ipfs_datasets_py`. Full extras tables, lazy/auto-install policy, native prover install, capability probing, and uninstall/rollback live in [CAPABILITY_INSTALLATION](guides/installation/CAPABILITY_INSTALLATION.md). Runtime env and secrets precedence: [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md) and the root [configuration guide](configuration.md).

## Requirements

| Requirement | Current packaging |
| --- | --- |
| Python | **Python 3.12+** (`requires-python = ">=3.12"`). Python 3.7–3.11 are **not** supported. |
| Package manager | `pip` inside a virtual environment (strongly recommended) |
| OS | Linux, macOS, Windows — platform extras and native wheels differ (see CAPABILITY_INSTALLATION §2 / PLATFORM_INSTALL) |
| Disk / network | Base install needs network or a wheelhouse; theorem provers, OCR models, and Playwright browsers need extra disk when provisioned |

**Not claimed here:** specific CUDA toolkit pins or GPU wheel URLs. Install matching `torch` / FAISS builds from current vendor docs when you need GPU; the `ml` extra pulls `torch` generically and is **not** included in `all`.

## Base installation

### From PyPI (when published for your target)

```bash
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip setuptools wheel
pip install ipfs-datasets-py
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
```

### From source (development / current tree)

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e .
```

Editable install resolves vendored `ipfs_kit_py` / `ipfs_accelerate_py` when present; otherwise packaging may pull GitHub `main`. For constrained builds:

```bash
export IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES=0
pip install -e .
```

Requirements files (broader pin sets): `requirements.txt`, `requirements-lazy.txt`, `requirements-theorem-provers.txt` — see CAPABILITY_INSTALLATION §3.2.

### What base does **not** install

- Native theorem-prover **CLIs** (Lean, Tamarin, Maude, …)
- System binaries (Tesseract, FFmpeg, Kubo `ipfs`, Cargo, Java, OPAM)
- Heavy **optional** stacks not listed in base `install_requires` (full vector stack, Selenium matrix, Neo4j, full `ml` torch, …)
- Empty stub extras (e.g. `legal` is an empty stub in packaging)

Missing pieces surface as **unavailable** features at use time, not as a failed base import.

## Optional capabilities (real extras)

Use **declared** extra names only. Prefer:

```bash
pip install -e '.[vectors,file_conversion,theorem-provers]'
# or broader non-ML union + platform magic:
pip install -e '.[all,linux]'    # windows / macos as appropriate
```

| Goal | Extra / action |
| --- | --- |
| Vector stores / embeddings | `vectors` |
| Knowledge graphs / entity extraction | `knowledge_graphs` |
| Web archive / WARC | `web_archive` |
| File conversion | `file_conversion` (+ `python -m playwright install` when using Playwright) |
| Theorem-prover **Python** bindings | `theorem-provers` or `requirements-theorem-provers.txt` |
| Native solver portfolios | `ipfs-datasets-install-provers --portfolio …` (not a pip extra) |
| Eager lazy-catalog modules | `lazy` or `requirements-lazy.txt` |
| Heavy ML (torch, …) | `ml` (**excluded** from `all` by design) |

### Do not use (nonexistent or wrong names)

| Invalid | Use instead |
| --- | --- |
| `vector` | `vectors` |
| `graphrag` | `knowledge_graphs` (+ app GraphRAG config) |
| `webarchive` / `web-archive` | `web_archive` |
| `theorem_prover` / `theorem-prover` | `theorem-provers` |
| Placeholder orgs (`your-organization`, `yourorga/…`) | `endomorphosis/ipfs_datasets_py` (or your real fork) |

Full extra catalog: [CAPABILITY_INSTALLATION §4](guides/installation/CAPABILITY_INSTALLATION.md).

## Native and system tools

Python wheels do not replace host tools. Common needs:

| Tool | Typical need |
| --- | --- |
| Kubo / `ipfs` | Local daemon workflows (`IPFS_DATASETS_PY_KUBO_CMD` overrides the binary name) |
| FFmpeg | Multimedia conversion |
| Tesseract | `pytesseract` OCR |
| libmagic | `python-magic` on Linux/macOS (Windows uses `python-magic-bin`) |
| Playwright browsers | After `file_conversion` extra |
| Cargo / JDK / OPAM / elan | Building or managing selected provers / Groth16 when no bundled binary |

Managed provers default under `~/.local/share/ipfs_datasets_py/theorem-provers` (override with `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`). Importing prover modules **never** downloads a solver by itself—execution or the managed CLI does, when policy allows. Details: CAPABILITY_INSTALLATION §6 and [lazy theorem prover installation](security_verification/lazy_theorem_prover_installation.md).

## Auto / lazy install, offline, and unavailable

| Mode | What to set | Expected behavior |
| --- | --- | --- |
| Base-only | default install; no extras | Import works; optional features degrade or error at **use** |
| Capability-enabled | matching extras + system tools | Feature path can run; probe ≠ production attestation |
| Hermetic / CI | `IPFS_DATASETS_AUTO_INSTALL=false` and/or `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` | No surprise runtime `pip` |
| Offline | `IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1` + wheelhouse; disable prover lazy install | Missing wheels/binaries → **unavailable**, not silent success |

Default-on auto-install favors developers. Production and immutable images **should** disable it before import. Full policy and security consequences: [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md) and CAPABILITY_INSTALLATION §7–9.

Probe example (importability only):

```bash
python -c "from ipfs_datasets_py.logic.common.feature_detection import is_module_available as a; print('faiss', a('faiss'))"
```

If a module is missing, treat the feature as **optional/unavailable**—never as verified or authorized.

## Console scripts (after install)

| Script | Role |
| --- | --- |
| `ipfs-datasets` / `ipfs-datasets-cli` | Primary CLI |
| `ipfs-datasets-install-provers` | Managed native prover installer |
| `file-converter` / `fc` | File converter CLI |
| `netherlands-laws` / `ipfs-netherlands-laws` | Netherlands laws CLI |

```bash
ipfs-datasets --help
```

## Docker and deployment

Container images and compose samples are **deployment-owned** and may lag packaging. Prefer building from this repository’s Dockerfiles when you need a known tree, and set hermetic install flags in images. See [deployment](deployment.md) and [Docker deployment](deployment/DOCKER_DEPLOYMENT_GUIDE.md). Do not use placeholder registries such as `yourorga/…`.

## Quick validation

```bash
python -c "import sys; assert sys.version_info >= (3, 12)"
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
ipfs-datasets --help   # if console scripts are on PATH
```

## Troubleshooting (short)

| Symptom | Check |
| --- | --- |
| Wrong Python | Use 3.12+; recreate the venv |
| `ImportError` for optional stack | Install the real extra name; re-probe |
| IPFS connection refused | Daemon running; API address; firewall; backend env (configuration guide) |
| GPU / CUDA import failures | Install a **current** torch/FAISS build for your CUDA/driver; do not follow obsolete pin recipes |
| Offline install fails | Provide wheelhouse; disable auto-install; pre-provision provers |

## Next steps

- [Configuration guide](configuration.md) — precedence routes and safe operator defaults
- [CAPABILITY_INSTALLATION](guides/installation/CAPABILITY_INSTALLATION.md) — complete install surface
- [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md) — env catalog and security
- [Getting started](getting_started.md) · [FEATURES](FEATURES.md) · [FAQ](faq.md)
