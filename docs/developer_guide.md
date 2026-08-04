# Developer guide

| Field | Value |
| --- | --- |
| Interface | `DeveloperGuide@1` |
| Task | `IPFSDOC-074` |
| Status | `canonical` |
| Owner | developer-docs |
| Source of truth | Live packaging (`pyproject.toml`, `setup.py`); sibling guides under `docs/developer_guides/`; architecture hub; root `CONTRIBUTING.md`; maintenance authority docs |
| Last verified | 2026-08-03 |
| Audience | developer (primary); agent, maintainer |
| Related | [REPOSITORY_MAP.md](developer_guides/REPOSITORY_MAP.md), [EXTENSION_RECIPES.md](developer_guides/EXTENSION_RECIPES.md), [TESTING_AND_EVIDENCE.md](developer_guides/TESTING_AND_EVIDENCE.md), [FOR_AGENTS.md](developer_guides/FOR_AGENTS.md), [architecture/README.md](architecture/README.md), [DOCUMENTATION_CONTRIBUTING.md](developer_guides/DOCUMENTATION_CONTRIBUTING.md), [../CONTRIBUTING.md](../CONTRIBUTING.md) |
| Review cadence | after packaging surface changes, developer-guide tree moves, or removal of root entry scripts |

> **What this page is:** the **canonical contributor landing page**—prerequisites,
> a short safe setup, and **routes** into deeper guides.
>
> **What this page is not:** a repository inventory, extension cookbook, test
> selection matrix, agent contract, architecture design, security threat model,
> or documentation style manual. Those live in the linked leaves. Do not expand
> this page with duplicated leaf content.

---

## 1. Purpose

Use this guide when you need to:

1. Confirm **Python / packaging** prerequisites for local contribution.
2. Perform a **minimal editable install** that matches current packaging.
3. Find the **right next document** (map, recipes, tests, agents, architecture,
   contributing, security, docs).
4. Avoid **stale root scripts and imports** that older versions of this page
   advertised.

Authority when sources disagree
([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md)):

1. executable tests and schemas;
2. current implementation and packaging metadata;
3. accepted ADRs and architecture leaves;
4. this page and `docs/developer_guides/*`;
5. historical reports and archived scripts (lowest).

---

## 2. Prerequisites

| Requirement | Current fact | Notes |
| --- | --- | --- |
| **Python** | **Python 3.12+** (`requires-python = ">=3.12"` in `pyproject.toml`) | Do not target 3.7–3.11 for this package. |
| **Git** | Required for clone and patches | Submodules are optional and often unpopulated; see [INTEGRATION_BOUNDARIES.md](architecture/INTEGRATION_BOUNDARIES.md). |
| **Package identity** | `ipfs_datasets_py` **0.2.0** | Name and version from packaging metadata. |
| **IPFS daemon** | Optional | Needed only for live IPFS paths; not required for unit work. |
| **Optional stacks** | Extras under `[project.optional-dependencies]` | Lazy by design ([ADR-002](architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)). Prefer named extras over inventing a `dev` extra (not in `pyproject.toml`). |

---

## 3. Minimal contributor setup

Prefer **editable install via packaging**, not removed root helper scripts.

```bash
# From the repository root
python3 --version   # expect Python 3.12.x or newer

# Editable install + test tooling (recommended first gate)
pip install -e ".[test]"

# Optional: broader extras when your change needs them (examples)
# pip install -e ".[vectors,logic,api]"
# pip install -e ".[all]"   # heavy; not the default local step

# Smoke import (hermetic-by-default package surface)
python -c "import ipfs_datasets_py; print(getattr(ipfs_datasets_py, '__version__', 'ok'))"
```

**Tests (start nearest, not full-tree):**

```bash
# Selection rules and evidence classes → TESTING_AND_EVIDENCE
python -m pytest tests/unit/ -q --collect-only -q   # inventory only; optional

# Typical focused run after you locate nearest tests (paths from REPOSITORY_MAP)
python -m pytest path/to/nearest_test.py -q
```

**MCP server (module entry is current; root launchers are not):**

```bash
python -m ipfs_datasets_py.mcp_server --stdio
# HTTP mode: python -m ipfs_datasets_py.mcp_server --http --host 127.0.0.1 --port 3002
```

**Installer helper (when present):** `scripts/setup/install.py` is the in-tree
setup helper. There is **no** root `install.py`. Details and profiles belong in
installation/ops docs—not here.

**Do not use** these removed or non-root commands from older developer docs:

| Stale command / claim | Status |
| --- | --- |
| `python comprehensive_mcp_test.py` | **Removed** from root (archive only if present under `archive/`) |
| `python systematic_validation.py` | **Missing** at root |
| `python start_fastapi.py` | **Missing** at root — use MCP/HTTP entry or package FastAPI service paths in [RUNTIME_ENTRYPOINTS.md](architecture/RUNTIME_ENTRYPOINTS.md) |
| `python install.py` (repo root) | **Missing** — use `pip install -e ".[test]"` or `scripts/setup/install.py` |
| `python setup.py build` as primary workflow | **Legacy** — prefer `pip install -e …` against `pyproject.toml` |
| `from ipfs_datasets_py.ipfs_kit` / `libp2p_kit` as guaranteed in-tree modules | **Not** package-root modules; IPFS kit is an optional external/submodule boundary |

Branching, PR etiquette, and review process: root
[CONTRIBUTING.md](../CONTRIBUTING.md). Capability install depth:
[installation.md](installation.md) (treat Python version there as superseded by
**Python 3.12+** packaging until that page is refreshed).

---

## 4. Where to go next (routing table)

| Need | Go to | Owns |
| --- | --- | --- |
| **Repository layout**, ownership, hot files, nearest tests | [REPOSITORY_MAP.md](developer_guides/REPOSITORY_MAP.md) | Bounded first context set for trees and owners |
| **Architecture** (system, domains, ADRs, runtime) | [architecture/README.md](architecture/README.md) | Architecture hub → domain leaves |
| **How to extend** processors, vectors, MCP tools, logic, policy, docs | [EXTENSION_RECIPES.md](developer_guides/EXTENSION_RECIPES.md) | Invariant-preserving change workflows |
| **What to test** and how to report evidence | [TESTING_AND_EVIDENCE.md](developer_guides/TESTING_AND_EVIDENCE.md) | Proportional gates and evidence classes |
| **Agent / automation contract** (invariants, blockers, handoffs) | [FOR_AGENTS.md](developer_guides/FOR_AGENTS.md) | Implementation-agent decision contract |
| Agent companions | [TROUBLESHOOTING.md](developer_guides/TROUBLESHOOTING.md), [HANDOFF_CHECKLIST.md](developer_guides/HANDOFF_CHECKLIST.md) | Failure diagnosis; handoff templates |
| **Contributing process** (fork, branch, PR) | [CONTRIBUTING.md](../CONTRIBUTING.md) | Human contribution workflow |
| **Security** (threat model, secrets, wallet/trust) | [guides/security/README.md](guides/security/README.md), [THREAT_MODEL.md](guides/security/THREAT_MODEL.md), [WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md) | Security and trust surfaces |
| **Writing or changing documentation** | [DOCUMENTATION_CONTRIBUTING.md](developer_guides/DOCUMENTATION_CONTRIBUTING.md) | Docs workflow under information architecture |
| Creating MCP/tools patterns (legacy/specialized) | [CREATING_TOOLS.md](developer_guides/CREATING_TOOLS.md) | Tool-authoring notes; prefer EXTENSION_RECIPES for new work |
| Entry points and packaging drift | [RUNTIME_ENTRYPOINTS.md](architecture/RUNTIME_ENTRYPOINTS.md) | How to start CLI / MCP / API surfaces |
| Dependency and init behavior | [DEPENDENCY_AND_INITIALIZATION.md](architecture/DEPENDENCY_AND_INITIALIZATION.md) | Lazy extras, routers, init |
| Authority vocabulary | [GLOSSARY.md](GLOSSARY.md) | Shared terms (CID, proof, policy, adapter, …) |
| Doc maintenance / validation | [maintenance/INFORMATION_ARCHITECTURE.md](maintenance/INFORMATION_ARCHITECTURE.md), [VALIDATION_RUNBOOK.md](maintenance/VALIDATION_RUNBOOK.md) | Placement, lifecycle, validation |

### Suggested exploration order

1. This page (setup) → [REPOSITORY_MAP.md](developer_guides/REPOSITORY_MAP.md)
2. [DOMAIN_MAP.md](architecture/DOMAIN_MAP.md) or [architecture/README.md](architecture/README.md) for the domain you touch
3. [EXTENSION_RECIPES.md](developer_guides/EXTENSION_RECIPES.md) for the change kind
4. [TESTING_AND_EVIDENCE.md](developer_guides/TESTING_AND_EVIDENCE.md) before claiming done
5. If you are an agent: [FOR_AGENTS.md](developer_guides/FOR_AGENTS.md) **before** edits that touch protected or hot paths

---

## 5. Contributor ground rules (summary only)

These are **reminders**; full contracts live in the linked guides and ADRs.

1. **One owner domain** per behavior — place logic in the domain package, not a
   second parallel home ([DOMAIN_MAP.md](architecture/DOMAIN_MAP.md)).
2. **Optional capabilities stay lazy** — missing extras degrade fail-closed or
   feature-gated; do not hard-require heavy stacks at import time
   ([ADR-002](architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md),
   [ADR-004](architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).
3. **Evidence is proportional** — nearest unit/integration first; full-suite
   pytest is a broad/release option, not the default first step
   ([TESTING_AND_EVIDENCE.md](developer_guides/TESTING_AND_EVIDENCE.md)).
4. **Do not invent authority** — discovery ≠ approval; simulated proof ≠
   production soundness ([FOR_AGENTS.md](developer_guides/FOR_AGENTS.md),
   [SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md)).
5. **Docs follow IA** — one canonical home, honest lifecycle labels
   ([DOCUMENTATION_CONTRIBUTING.md](developer_guides/DOCUMENTATION_CONTRIBUTING.md)).
6. **Secrets and trust** — no credentials in tree; wallet and privacy rules are
   architecture, not afterthoughts
   ([guides/security/SECRETS_AND_CREDENTIALS.md](guides/security/SECRETS_AND_CREDENTIALS.md),
   [WALLET_TRUST_AND_PRIVACY.md](architecture/WALLET_TRUST_AND_PRIVACY.md)).

---

## 6. Explicit non-claims

- This page does **not** restate the full repository map, recipe steps, or test
  matrices.
- Commands above are **contributor-safe defaults** verified as *paths and
  packaging patterns* on the refresh date; they are not a guarantee that every
  optional extra or external service is provisioned in every environment.
- Historical “feature showcase” content formerly on this page (embedding product
  marketing, full MCP category catalogs, FastAPI route maps) is **not** current
  developer authority; use architecture, API, and runtime docs instead.
- Completion receipts and session summaries do not outrank tests or packaging.

---

## 7. Validation (for maintainers of this page)

When refreshing this guide, keep it a **routing entry** and re-check every link
and command path:

```bash
test -s docs/developer_guide.md
rg -n 'Python 3.12|REPOSITORY_MAP|EXTENSION_RECIPES|TESTING_AND_EVIDENCE|FOR_AGENTS' docs/developer_guide.md
# Linked leaves must exist and be non-empty (sample):
test -s docs/developer_guides/REPOSITORY_MAP.md \
  && test -s docs/developer_guides/EXTENSION_RECIPES.md \
  && test -s docs/developer_guides/TESTING_AND_EVIDENCE.md \
  && test -s docs/developer_guides/FOR_AGENTS.md \
  && test -s docs/architecture/README.md \
  && test -s docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md \
  && test -s CONTRIBUTING.md \
  && test -s docs/guides/security/README.md \
  && test -s docs/architecture/WALLET_TRUST_AND_PRIVACY.md
```
