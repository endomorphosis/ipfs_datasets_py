# Capability Installation Guide

| Field | Value |
| --- | --- |
| Interface | `CapabilityInstallationGuide@1` |
| Task | `IPFSDOC-063` |
| Status | `canonical` |
| Owner | user-docs |
| Source of truth | `pyproject.toml`; `setup.py`; `requirements.txt`; `requirements-lazy.txt`; `requirements-theorem-provers.txt`; `ipfs_datasets_py/__init__.py`; `ipfs_datasets_py/auto_installer.py`; `ipfs_datasets_py/lazy_dependencies.py`; `ipfs_datasets_py/dependency_catalog.py`; `ipfs_datasets_py/logic/common/feature_detection.py`; `ipfs_datasets_py/logic/external_provers/lazy_installer.py` |
| Last verified | 2026-08-03 |
| Audience | developer, operator, CI owner |
| Related | [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md), [LAZY_DEPENDENCY_INSTALLATION.md](../LAZY_DEPENDENCY_INSTALLATION.md), [lazy_theorem_prover_installation.md](../../security_verification/lazy_theorem_prover_installation.md), [DEPENDENCY_AND_INITIALIZATION.md](../../architecture/DEPENDENCY_AND_INITIALIZATION.md), [ADR-002](../../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |

## 1. Purpose

This guide describes **how to install `ipfs_datasets_py` and enable optional capabilities** from current packaging and code. It replaces stale singular extras, placeholder organizations, and aspirational install recipes with names and behaviors that exist in the tree today.

**In scope:** Python/platform requirements, base install, real optional extras, console scripts, native/system tools, auto/lazy installation, capability probing, offline/unavailable behavior, and uninstall/rollback.

**Out of scope:** Runtime configuration precedence and security consequences of secrets (see [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md)); architecture of routers and trust boundaries (see architecture docs).

## 2. Python and platform requirements

| Requirement | Current packaging |
| --- | --- |
| Python | **Python 3.12+** (`requires-python = ">=3.12"` in `pyproject.toml`; `python_requires='>=3.12'` in `setup.py`) |
| Package manager | `pip` with a virtual environment strongly recommended |
| OS | Linux, macOS (Darwin), Windows (platform extras differ) |
| Architecture | x86_64 and aarch64/arm64 are first-class for many native tools; some FAISS/GPU/ML wheels are platform-gated |
| Disk / network | Base editable install needs network (or vendored submodules + wheelhouse). Theorem provers and OCR models need substantial additional disk when provisioned |

**Not supported as the package baseline:** Python 3.7–3.11. Older docs that claim Python 3.7+ or 3.9+ are obsolete relative to packaging.

### 2.1 Platform markers already in packaging

`setup.py` detects `IS_WINDOWS`, `IS_LINUX`, `IS_MACOS`, and bitness. Conditional pins include:

- **FAISS:** `faiss-cpu>=1.7.0` on Windows; `>=1.8.0` elsewhere (in `vectors`, `legal_netherlands`, and `all` where applicable).
- **python-magic:** pure `python-magic` on Linux/macOS; `python-magic-bin` on Windows.
- **lazy extra:** `xformers` skipped on Darwin; `torch-directml` only on Windows; `intel-extension-for-pytorch` only on Linux x86_64.
- **cfscrape:** constrained to `python_version < '3.12'` in base `install_requires` (not used on the supported 3.12+ line).

## 3. Base installation

### 3.1 From a source checkout (recommended for development)

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip setuptools wheel
pip install -e .
```

Editable install resolves `ipfs_kit_py` and `ipfs_accelerate_py` from the **vendored checkouts** when present (`file://…`), otherwise from GitHub `main` (see `setup.py` `_ipfs_kit_dependency` / `_ipfs_accelerate_dependency`).

Constrained container builds can skip VCS-based optional dependencies:

```bash
export IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES=0
pip install -e .
```

### 3.2 Requirements files

| File | Role |
| --- | --- |
| `requirements.txt` | Broad development/runtime pin set (includes tests, many processors, local `-e ./ipfs_kit_py` and `-e ./ipfs_accelerate_py` when present) |
| `requirements-lazy.txt` | Eager equivalent of the runtime lazy dependency catalog |
| `requirements-theorem-provers.txt` | Optional Python bindings for theorem-prover integrations |
| `requirements-docs.txt` | Documentation build tools only |

```bash
pip install -r requirements.txt
# optional:
pip install -r requirements-lazy.txt
pip install -r requirements-theorem-provers.txt
```

### 3.3 What base install does and does not include

**Typically pulled by `install_requires` (summary):** NumPy, datasets/Hugging Face hub, IPLD stack (`libipld`, `ipld-car`, …), IPFS HTTP client, PDF/OCR Python bindings (`pdfplumber`, `pymupdf`, `pytesseract`, …), markitdown/docx/yt-dlp/ffmpeg-python, OpenCV, NLTK, Click, Flask, pydantic-settings, JWT, scraping helpers, and (when VCS deps are enabled) kit/accelerate/libp2p-related packages. Several theorem-prover **Python** bindings (`z3-solver`, `cvc5`, `pysmt`, `beartype`) are also in base `install_requires` in `setup.py` while remaining available as the explicit `theorem-provers` extra for intentional environments.

**Not installed by base `pip install` alone:**

- Native theorem-prover **CLIs** (Lean, Tamarin, Maude, Apalache, Rocq/Coq, ProVerif, Vampire, …)
- System binaries (Tesseract, FFmpeg, Kubo `ipfs`, Cargo/Rust, Java, OPAM)
- Heavy optional stacks unless listed in `install_requires` or installed via extras (full vector stack with sentence-transformers, Selenium/Scrapy matrix, Neo4j, etc.)
- Empty/`legal` extra stub packages

### 3.4 Install-time side effects

| Hook | Env control | Default | Behavior |
| --- | --- | --- | --- |
| NLTK data download | `IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD` | on (`1`) | Best-effort `punkt` and related resources after install/develop |
| NLTK download dir | `IPFS_DATASETS_PY_NLTK_DOWNLOAD_DIR` / `NLTK_DATA` | unset | Prefer explicit dir or first `NLTK_DATA` entry |
| NLTK quiet | `IPFS_DATASETS_PY_NLTK_DOWNLOAD_QUIET` | on | Quiet downloads |
| Groth16 Rust backend | `IPFS_DATASETS_PY_AUTO_GROTH16_BUILD` | on | Uses bundled platform binary if present; else may run `build.sh` when `cargo` is on `PATH` |

Failures in these hooks **do not fail** the Python package install; they print diagnostics and leave the corresponding capability unavailable until fixed manually.

## 4. Real optional extras

Extras are declared in both `setup.py` (`extras_require`) and `pyproject.toml` (`[project.optional-dependencies]`). Prefer the names below. **Do not invent singular aliases.**

### 4.1 Canonical extra names (install with these)

```bash
pip install -e '.[vectors,file_conversion,theorem-provers]'
```

| Extra | Purpose | Notable packages / notes |
| --- | --- | --- |
| `ipld` | IPLD / CAR codecs | `libipld`, `ipld-car`, `ipld-dag-pb`, `dag-cbor`, `multiformats` (several also in base) |
| `knowledge_graphs` | Entity extraction, graph viz/export | `spacy`, `networkx`, `transformers`, `scipy`, viz stack, `rdflib`, `neo4j` (+ optional LLM clients in `setup.py`) |
| `logic` | Symbolic/logic bridge | `nltk`, `symbolicai` (import name `symai`) |
| `logic-api` | Logic HTTP API | `fastapi`, `uvicorn` (`setup.py`) |
| `theorem-provers` | Python bindings for prover integrations | `z3-solver`, `cvc5`, `pysmt`, `beartype`, `jsonschema`, `symbolicai` — **not** native CLIs |
| `file_conversion` | MarkItDown / conversion path | `markitdown`, `aiohttp`, `playwright`, `striprtf` (+ docx/yt-dlp/ffmpeg-python in pyproject variant) |
| `file_conversion_full` | Broader conversion formats | OCR/docx/xlsx/pptx/PDF helpers (`setup.py`) |
| `multimedia` | Media processing | `yt-dlp`, `ffmpeg-python`, `imageio-ffmpeg`, `pillow`, `moviepy` |
| `ocr` | OCR engines | `easyocr`, `opencv-python`, `pytesseract` (needs system Tesseract for pytesseract) |
| `vectors` | Vector stores / embeddings stack | `faiss-cpu` (platform-gated), `qdrant-client`, `elasticsearch`; pyproject also pins `sentence-transformers`, `scikit-learn` |
| `web_archive` | Archive / WARC tooling | `archivenow`, `ipwb`, `warcio`, HTML extractors (`setup.py`) |
| `legal_netherlands` | Netherlands legal dataset tooling | Arrow, HF datasets, FAISS, sklearn |
| `scraping` | Web scraping stack | BeautifulSoup, Selenium (pin range), Scrapy, autoscraper, CDX/Wayback/IA |
| `api` | HTTP services / MCP | FastAPI, uvicorn, Flask/MCP depending on packaging surface |
| `symai_router` | SymbolicAI + Copilot SDK path | OpenCV, `symbolicai`, `github-copilot-sdk` |
| `lazy` | Eager install of lazy-catalog modules | chardet, whisper, geo stack, caches, platform magic, … |
| `pdf` | PDF processing pin set | pdfplumber, pymupdf, PyPDF2/pypdf, pytesseract, tiktoken, pysbd |
| `ml` | Heavy ML | `torch`, `llama-index`, `openai` (**not** in `all`) |
| `accelerate` | Distributed AI via accelerate | git `ipfs_accelerate_py`, sentence-transformers, torch, transformers |
| `p2p` | libp2p networking | git `py-libp2p`, protobuf, multihash, dnspython |
| `security` | Crypto / keyring | `cryptography`, `keyring` |
| `audit` | Audit shipping | elasticsearch + cryptography |
| `provenance` | Provenance dashboards | plotly, dash, dash-cytoscape |
| `alerts` | Discord alerts | discord.py, aiohttp, PyYAML |
| `email` | HTML email parsing helper | beautifulsoup4 |
| `groth16` | ZKP schema helpers | `jsonschema` (Rust binary is separate) |
| `provekit` | ProveKit schema helpers | `jsonschema` (CLI binary is operator-provided) |
| `profile-f-zk` | Profile F ZK schema helpers | `jsonschema` (`pyproject.toml`; trusted setup not bundled by default) |
| `test` | Test runners | pytest ecosystem + hypothesis |
| `dev` | Lint/type/coverage helpers | mypy, flake8, coverage, Faker, reportlab, pyfakefs |
| `windows` / `linux` / `macos` | Platform magic/binaries | See §2.1 |
| `all` | Large non-ML union | See packaging; still **excludes** full `ml` torch stack by design in `setup.py` |

### 4.2 Nonexistent or deprecated singular names (do not use)

| Invalid name | Why | Use instead |
| --- | --- | --- |
| `vector` | No packaging extra | `vectors` |
| `graphrag` | Not an optional-dependencies key | `knowledge_graphs` (+ app-level GraphRAG config) |
| `webarchive` / `web-archive` | Not the declared key | `web_archive` |
| `theorem_prover` / `theorem-prover` | Singular not declared | `theorem-provers` |
| `file-conversion` | Underscore form is declared | `file_conversion` |
| Placeholder orgs (`your-organization`, `yourorga/…`) | Not this repository | `endomorphosis/ipfs_datasets_py` (or your real fork) |

The `legal` extra in `setup.py` is currently an **empty stub** and does not install a dependency set.

### 4.3 Capability-oriented install recipes

```bash
# Vectors / embedding stores
pip install -e '.[vectors]'

# File conversion (Playwright still needs browser install — see §6)
pip install -e '.[file_conversion]'
python -m playwright install   # when using Playwright backend

# Theorem-prover Python bindings only
pip install -e '.[theorem-provers]'
# or
pip install -r requirements-theorem-provers.txt

# Native solver portfolios (not pip extras)
ipfs-datasets-install-provers --portfolio legal_ir_generation --yes --strict

# Offline-friendly pre-provision of lazy catalog
pip install -e '.[lazy]'
# or
pip install -r requirements-lazy.txt

# Broad feature set without full torch ML extra
pip install -e '.[all,linux]'    # or windows / macos
```

## 5. Console scripts

Declared entry points (`setup.py` / `pyproject.toml`):

| Script | Module entry | Role |
| --- | --- | --- |
| `ipfs-datasets` | `ipfs_datasets_cli:cli_main` | Primary CLI |
| `ipfs-datasets-cli` | `ipfs_datasets_cli:cli_main` | Alias |
| `netherlands-laws` | `…netherlands_laws.cli:main` | Netherlands laws CLI |
| `ipfs-netherlands-laws` | same | Alias |
| `ipfs-datasets-sms-bridge` | `…messaging.sms_bridge:main` | SMS bridge service |
| `ipfs-datasets-install-provers` | `…prover_installer:main` | Managed native prover installer |
| `file-converter` | `…file_converter.cli:main` | File converter CLI |
| `fc` | same | Short alias |

```bash
ipfs-datasets --help
ipfs-datasets-install-provers --help
file-converter --help
```

Scripts appear on `PATH` only after the package is installed into the active environment.

## 6. Native and system tools

Python wheels do not replace these host tools.

| Tool | Needed for | Typical install | Probe / notes |
| --- | --- | --- | --- |
| **Kubo / `ipfs`** | Full local IPFS daemon workflows | Dist.ipfs binaries or package manager; CLI name overridable via `IPFS_DATASETS_PY_KUBO_CMD` | Router may fall back to HTTP API / kit / accelerate when enabled |
| **FFmpeg** | `ffmpeg-python`, moviepy, multimedia conversion | OS package or imageio-ffmpeg helper binary | Missing binary → media features unavailable |
| **Tesseract** | `pytesseract` OCR | OS package (`tesseract-ocr`) | Python package alone is insufficient |
| **libmagic** | `python-magic` on Linux/macOS | `libmagic` / Homebrew `libmagic` | Windows uses `python-magic-bin` |
| **Playwright browsers** | `file_conversion` Playwright path | `python -m playwright install` | Separate from pip |
| **Cargo / Rust** | Building Groth16 backend when no bundled binary | [rustup](https://rustup.rs) | Install hook skips with message if missing |
| **Java** | Apalache (JVM) | JDK | Managed prover installer documents platform support |
| **OPAM / OCaml** | Rocq/Coq, ProVerif builds | Managed under user-local prover root unless org command provided | No implicit `sudo` without explicit allow |
| **elan / Lean toolchain** | Lean kernel proofs | User-local elan bootstrap via installer | Not a PyPI package |
| **ProveKit CLI** | ProveKit circuits | Operator-provided content-addressed binary | Extra only installs schema helpers |
| **spaCy models** | `knowledge_graphs` NER | `python -m spacy download en_core_web_sm` | Package install does not download models |

### 6.1 User-local theorem-prover root

Native solvers install under (default):

```text
~/.local/share/ipfs_datasets_py/theorem-provers
```

Override with `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`. Managed install:

```bash
ipfs-datasets-install-provers --portfolio legal_ir_generation --yes --strict
ipfs-datasets-install-provers --check-updates
```

Importing `ipfs_datasets_py.logic.external_provers` **never** downloads a solver. Installation is tied to first **execution** (when lazy install is allowed) or explicit managed CLI use. See [lazy_theorem_prover_installation.md](../../security_verification/lazy_theorem_prover_installation.md).

## 7. Auto / lazy installation behavior

### 7.1 Python dependencies

On package import, if unset, `IPFS_DATASETS_AUTO_INSTALL` is set to `"true"` (and kit dep auto-install defaults on). Runtime resolution:

1. Try import.
2. If present, use it (no pip).
3. Map import name → distribution via the dependency catalog (e.g. `fitz` → `pymupdf`).
4. If missing and auto-install allowed, run a reviewed `pip` install with single-flight locking.
5. Re-import and return or report unavailable.

Disable for immutable images and CI:

```bash
export IPFS_DATASETS_AUTO_INSTALL=false
# or force hermetic modes:
export IPFS_DATASETS_PY_MINIMAL_IMPORTS=1
# or
export IPFS_DATASETS_PY_BENCHMARK=1
```

| Control | Role |
| --- | --- |
| `IPFS_DATASETS_AUTO_INSTALL` / `IPFS_AUTO_INSTALL` | Master switch for runtime pip |
| `IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1` | Prefer offline pip (`--no-index`) |
| `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE` | Local `--find-links` directory |
| `IPFS_DATASETS_PIP_TIMEOUT` | Pip timeout (bounded) |
| `IPFS_DATASETS_INSTALL_LOCK_TIMEOUT` | Wait for peer install |
| `IPFS_DATASETS_INSTALL_RETRY_SECONDS` | Cooldown after failure |
| `IPFS_DATASETS_ENSURE_INSTALLER` | Repo/submodule bootstrap (separate from feature lazy install) |

API:

```python
from ipfs_datasets_py import lazy_import
from ipfs_datasets_py._dependencies import dependencies

faiss = lazy_import("faiss")
if faiss is None:
    raise RuntimeError("vector backend unavailable")

# Proxy does not import until attribute access:
table = dependencies.pyarrow.Table.from_pylist([{"id": 1}])
```

### 7.2 Native provers (separate policy)

| Control | Effect |
| --- | --- |
| `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS` | Allow first-use native install |
| `IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>` | Per-prover override |
| `IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS` / portfolios | Preflight managed install |
| `IPFS_DATASETS_PY_LAZY_INSTALL_STRICT` / `…_PROVER_INSTALL_STRICT` | Raise on failure |
| `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS` | Permit interactive sudo (**default: never**) |
| `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE` | Explicit binary |
| `IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND` | Org-managed install command |

### 7.3 Heavy import-time stacks (opt-in)

Default package import stays hermetic. Opt-in flags:

- `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS`
- `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS`
- `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS`
- `IPFS_DATASETS_PY_ENABLE_FINANCE_DASHBOARD_IMPORTS`

## 8. Capability probing

Probes answer **importability / environment presence**, not production readiness, authorization, or proof.

| API | Behavior | Authority |
| --- | --- | --- |
| `feature_detection.is_module_available(name)` | `importlib.util.find_spec` only; respects minimal imports | Presence only |
| `feature_detection.require_module` | Raises `ImportError` with extra hints | Hard call-site requirement |
| `feature_detection.import_optional_module` | Best-effort import | Optional enablement |
| `lazy_import` / `ensure_module` | May install if policy allows | Module or `None` / error |
| Accelerate status helpers | Env + import diagnostics | Integration on/off |
| `ensure_prover_executable` phases | checking / available / installing / blocked / failed | Environment evidence only |
| Empty submodule directories | Path may exist without content | **Not** capability evidence |

```python
from ipfs_datasets_py.logic.common.feature_detection import is_module_available

if not is_module_available("faiss"):
    # degrade feature; do not claim vector search is production-ready
    ...
```

**Invariant (ADR-002):** probe ≠ install ≠ capability ≠ authorization ≠ proof.

## 9. Base, capability, offline, unavailable, and uninstall implications

### 9.1 Base-only environment

| Have | Missing | Expected behavior |
| --- | --- | --- |
| Editable/base package | Optional extras | Package import succeeds; optional features degrade or error at **use** |
| Hermetic flags on | Auto-install | No runtime pip; probes report unavailable |
| CLI scripts on PATH | Native provers | CLI works for non-prover commands; prover routes block/fail |

### 9.2 Capability-enabled environment

Install the matching extra **and** any system tool, then re-probe or run a real workload. Example for vectors:

```bash
pip install -e '.[vectors]'
python -c "from ipfs_datasets_py.logic.common.feature_detection import is_module_available; print(is_module_available('faiss'))"
```

Success of that probe is still not a load-test or security attestation.

### 9.3 Offline

```bash
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
# or allow offline pip only:
export IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1
export IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/path/to/wheels
pip install --no-index --find-links=/path/to/wheels -e '.[vectors,file_conversion,theorem-provers,lazy]'
```

Without a wheelhouse, lazy pip fails and features become unavailable. Native provers cannot be downloaded offline unless already present under the external prover root or on `PATH`.

### 9.4 Unavailable

| Situation | Feature path | Trust path |
| --- | --- | --- |
| Missing extra | Soft-disable / error / unavailable status | Must not imply verified capability |
| Missing system binary | Media/OCR/IPFS features off | Same |
| Missing prover + lazy off | Install phase blocked/disabled | Never “proven” |
| Missing prover + lazy on + fail | Phase failed; optional strict raise | Same |
| Empty git submodule | Integration wrappers report missing | Same |
| Accelerate disabled | Local fallback when coded | Does not authorize remote side effects |

### 9.5 Uninstall and rollback

| Layer | How to remove / roll back | Residual risk |
| --- | --- | --- |
| Python package | `pip uninstall ipfs_datasets_py` (and optional extras’ distributions as needed) | Does not remove `~/.local/share/ipfs_datasets_py` or NLTK data |
| Editable install | Deactivate venv or remove `.venv` | Cleanest isolation unit is the virtualenv |
| Optional extras only | Reinstall without extras; or uninstall specific distributions | Shared base deps may remain |
| Native provers | Delete or rename `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` (default under `~/.local/share/ipfs_datasets_py/theorem-provers`); remove elan/OPAM roots if provisioned | Managed installers do not auto-purge on `pip uninstall` |
| Playwright browsers | Playwright’s own uninstall/cache cleanup | Separate from pip |
| Groth16 build artifacts | Rebuild/remove under `processors/groth16_backend/bin/…` | Binary capability independent of Python wheel |
| Config / secrets | Remove `.env`, `~/.ipfs_datasets/cli.json`, and any tokens from the environment | Rotate secrets if they were exposed |

**Rollback recommendation:** keep capability installs inside disposable virtualenvs; treat the prover root as a separate artifact store that you version or wipe intentionally.

## 10. Quick validation checklist

```bash
python -c "import sys; assert sys.version_info >= (3, 12)"
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
ipfs-datasets --help
# optional capabilities you installed:
python -c "from ipfs_datasets_py.logic.common.feature_detection import is_module_available as a; print('faiss', a('faiss')); print('z3', a('z3'))"
```

## 11. Related documents

- [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) — environment/config precedence and security consequences
- [LAZY_DEPENDENCY_INSTALLATION.md](../LAZY_DEPENDENCY_INSTALLATION.md) — lazy Python installer details
- [lazy_theorem_prover_installation.md](../../security_verification/lazy_theorem_prover_installation.md) — native solvers
- [PLATFORM_INSTALL.md](../../quickstart/PLATFORM_INSTALL.md) — platform-specific extras notes
- [ADR-002 Lazy Optional Capabilities](../../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)
- [DEPENDENCY_AND_INITIALIZATION.md](../../architecture/DEPENDENCY_AND_INITIALIZATION.md)
