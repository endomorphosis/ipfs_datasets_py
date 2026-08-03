# Installation

| Field | Value |
| --- | --- |
| Interface | `RootInstallationPage@1` |
| Task | `IPFSDOC-091` |
| Status | `canonical` (route page) |
| Owner | user-docs |
| Source of truth | `pyproject.toml`; `setup.py`; [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
| Last verified | 2026-08-03 |
| Audience | end-user, operator, developer |
| Related | [configuration.md](configuration.md), [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md), [FEATURES.md](FEATURES.md), [ADR-002](architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |

This page is the **short install route** for `ipfs_datasets_py` **0.2.0**. Full extras tables, native tooling, auto/lazy install, probes, offline recipes, and uninstall/rollback live in the detailed guide:

→ **[Capability Installation Guide](guides/installation/CAPABILITY_INSTALLATION.md)** (`CAPABILITY_INSTALLATION`)

Runtime env, file precedence, and security consequences live in:

→ **[Configuration Reference](guides/installation/CONFIGURATION_REFERENCE.md)** (`CONFIGURATION_REFERENCE`) and the root [configuration](configuration.md) page.

---

## 1. Requirements

| Item | Current packaging |
| --- | --- |
| **Python** | **Python 3.12+** (`requires-python = ">=3.12"`). Python 3.7–3.11 are **not** supported. |
| Package manager | `pip` inside a virtual environment |
| OS | Linux, macOS, Windows (platform extras and FAISS/magic pins differ) |
| Architecture | x86_64 and aarch64/arm64 are first-class for many tools; some ML/GPU wheels are platform-gated |

**Disk / network:** base editable install needs network (or a wheelhouse + vendored submodules). Theorem provers, OCR models, and Playwright browsers need substantial extra disk when provisioned.

---

## 2. Base installation

### From source (recommended for development)

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip setuptools wheel
pip install -e .
```

Constrained builds can skip VCS optional dependencies:

```bash
export IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES=0
pip install -e .
```

### Requirements files (optional bulk pins)

| File | Role |
| --- | --- |
| `requirements.txt` | Broad development/runtime pin set |
| `requirements-lazy.txt` | Eager equivalent of the lazy dependency catalog |
| `requirements-theorem-provers.txt` | Python bindings for theorem-prover integrations |
| `requirements-docs.txt` | Documentation build tools only |

### Quick check

```bash
python -c "import sys; assert sys.version_info >= (3, 12)"
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
ipfs-datasets --help
```

Base install does **not** include native theorem-prover CLIs, system binaries (Tesseract, FFmpeg, Kubo `ipfs`), or every optional ML stack. Missing optional pieces stay **unavailable** until you install them—package import should still succeed.

---

## 3. Capability (optional) installation

Extras are declared in `pyproject.toml` / `setup.py`. Use the **real plural/underscore names** below. Do **not** use stale singular aliases.

```bash
# Vectors / embeddings
pip install -e '.[vectors]'

# Knowledge graphs / entity extraction
pip install -e '.[knowledge_graphs]'

# File conversion (Playwright browsers are a separate step)
pip install -e '.[file_conversion]'
python -m playwright install   # when using Playwright

# Theorem-prover Python bindings (not native CLIs)
pip install -e '.[theorem-provers]'
# or: pip install -r requirements-theorem-provers.txt

# Media / OCR / web archive / scraping / API
pip install -e '.[multimedia,ocr,web_archive,scraping,api]'

# Eager lazy-catalog modules (offline-friendly pre-provision)
pip install -e '.[lazy]'

# Broad non-ML union (still excludes full torch `ml` stack by design)
pip install -e '.[all]'
```

| Valid extra (examples) | Invalid / obsolete name | Use instead |
| --- | --- | --- |
| `vectors` | `vector` | `vectors` |
| `knowledge_graphs` | `graphrag` | `knowledge_graphs` |
| `web_archive` | `webarchive` / `web-archive` | `web_archive` |
| `theorem-provers` | `theorem_prover` / `theorem-prover` | `theorem-provers` |
| `file_conversion` | `file-conversion` | `file_conversion` |

Full extra inventory, console scripts, and native tool matrix: [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md).

### Native / system tools (not pip wheels)

| Tool | Needed for |
| --- | --- |
| Kubo / `ipfs` | Full local IPFS daemon workflows (`IPFS_DATASETS_PY_KUBO_CMD` overrides CLI name) |
| FFmpeg | Multimedia conversion |
| Tesseract | `pytesseract` OCR |
| Playwright browsers | `file_conversion` Playwright path |
| Cargo / Rust | Groth16 backend when no bundled binary |
| Managed provers | Lean, Tamarin, Maude, Apalache, … under user-local prover root |

```bash
# Managed native provers (separate from pip extras)
ipfs-datasets-install-provers --portfolio legal_ir_generation --yes --strict
```

Default prover root: `~/.local/share/ipfs_datasets_py/theorem-provers` (override with `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`).

### GPU / CUDA

There is **no** package-pinned “CUDA 10/11 + torch==1.10 + faiss-gpu” recipe in current packaging. Vector support is primarily **`faiss-cpu`** via the `vectors` extra (platform-gated versions). If you need GPU-accelerated PyTorch or FAISS:

1. Install a **current** CUDA toolkit matching your driver and OS.
2. Install torch/FAISS wheels from the **vendor** index for that CUDA version (PyTorch Get Started / FAISS docs)—not historical `cu102`/`cu113` pins from older docs.
3. Keep GPU installs out of immutable CI images unless the image is purpose-built for them.

Optional env hints used by some deploy samples: `CUDA_VISIBLE_DEVICES`, `ENABLE_GPU` (see configuration reference). Presence of those variables alone does not install CUDA software.

---

## 4. Docker and containers

Use first-party Docker assets under `docker/` and root `Dockerfile` / `docker-compose.yml` when containerizing. Do **not** pull placeholder images such as `yourorga/ipfs-datasets-py`.

```bash
# Example: build from this repository
docker build -t ipfs-datasets-py:local .
```

Set `IPFS_DATASETS_AUTO_INSTALL=false` (and prover lazy-install off) in production images so first-use `pip` or solver downloads do not mutate the container. Pre-install extras and system tools at **build** time.

---

## 5. Platform, offline, security, and unavailable behavior

### Platform

- **Windows:** `python-magic-bin`; FAISS pin differs; some lazy extras use `torch-directml`.
- **Linux:** `python-magic` + system `libmagic`; optional `intel-extension-for-pytorch` on x86_64 in the `lazy` extra.
- **macOS:** `xformers` skipped in the `lazy` extra on Darwin.

### Offline / air-gapped

```bash
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
# optional offline pip against a wheelhouse:
export IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1
export IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/path/to/wheels
pip install --no-index --find-links=/path/to/wheels -e '.[vectors,file_conversion,theorem-provers,lazy]'
```

Without a wheelhouse and pre-provisioned prover root, optional features become **unavailable**—not silently “proven.”

### Security (install-time)

| Risk | Mitigation |
| --- | --- |
| Default-on runtime `pip` after import | Set `IPFS_DATASETS_AUTO_INSTALL=false` before import in CI/production |
| Native prover download / optional sudo | Keep `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` unset; use managed installer with reviewed portfolios |
| Secrets in env | Never commit `.env`; see [CONFIGURATION_REFERENCE](guides/installation/CONFIGURATION_REFERENCE.md) § security |

**Invariant (ADR-002):** probe ≠ install ≠ capability ≠ authorization ≠ proof. Soft-disable optional media/vector helpers when missing; **fail closed** on authz, admissibility, and proof paths.

### Probe (presence only)

```bash
python -c "from ipfs_datasets_py.logic.common.feature_detection import is_module_available as a; print('faiss', a('faiss')); print('z3', a('z3'))"
```

---

## 6. What this page replaced

| Stale content | Current guidance |
| --- | --- |
| Python 3.7 / 3.9 minimum | **Python 3.12+** |
| Extras `vector`, `graphrag`, `webarchive` | `vectors`, `knowledge_graphs`, `web_archive`, … |
| `your-organization` / `yourorga` Docker and clone URLs | `https://github.com/endomorphosis/ipfs_datasets_py` |
| CUDA 10/11 + torch 1.10 install blocks | Vendor-current CUDA/torch; package vectors via `faiss-cpu` |
| Incomplete env coverage on root page | Short route here; full catalog in CONFIGURATION_REFERENCE |

---

## 7. Next steps

| Goal | Go to |
| --- | --- |
| Full extras, scripts, native tools, lazy install, uninstall | [CAPABILITY_INSTALLATION.md](guides/installation/CAPABILITY_INSTALLATION.md) |
| Env precedence, secrets, production profiles | [configuration.md](configuration.md) · [CONFIGURATION_REFERENCE.md](guides/installation/CONFIGURATION_REFERENCE.md) |
| Capability status labels | [FEATURES.md](FEATURES.md) |
| Lazy dependency detail | [LAZY_DEPENDENCY_INSTALLATION.md](guides/LAZY_DEPENDENCY_INSTALLATION.md) |
| Native provers | [lazy_theorem_prover_installation.md](security_verification/lazy_theorem_prover_installation.md) |
| Architecture / init order | [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) |

**Help:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues) · [Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)
