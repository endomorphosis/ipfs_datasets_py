# API documentation generation and freshness

| Field | Value |
| --- | --- |
| Interface | `APIGenerationAndFreshness@1` |
| Task | `IPFSDOC-082` |
| Status | `canonical` |
| Owner | api-reference |
| Source of truth | Domain pages under `docs/api/domains/`; `scripts/documentation/generate_optimizer_api_reference.py`; live ASTs under `ipfs_datasets_py/`; [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md); [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) lifecycle states; [DRIFT_AND_CLAIM_MATRIX.md](../maintenance/DRIFT_AND_CLAIM_MATRIX.md) |
| Last verified | 2026-08-03 |
| Audience | maintainer, developer, agent |
| Related | [README.md](README.md) (API index), [domains/](domains/), [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) |
| Review cadence | after generation-script changes, domain export changes, or bulk stub regeneration |

> **What this page is:** the honest lifecycle for **how** API docs are produced,
> what they cover, where they stop, and how to detect **signature drift**.
>
> **What this page is not:** a public API contract, a complete AST dump of the
> package, or authority for design rationale. Exhaustive internal AST output is
> a **discovery and verification input**, never the product public contract.

---

## 1. Purpose

This document answers:

1. **What is hand-maintained** vs **machine-generated** under the API surface.
2. **What inputs** generation and domain pages consume.
3. **Coverage and limitations** (what is deliberately omitted).
4. How to **verify freshness** after code changes.
5. How **legacy optimizer / TDFOL / stub** artifacts are classified.
6. How to **detect signature drift** between docs and the current tree.

Readers looking for callable maps should start at [README.md](README.md) and
the domain pages. Use this page when authoring, regenerating, or auditing.

---

## 2. Two production tracks

| Track | Artifacts | Authority for public API? | Lifecycle state |
| --- | --- | --- | --- |
| **A. Hand-maintained domain maps** | `docs/api/domains/*.md`, [README.md](README.md) | **Yes** (when grounded in ranks 1–2 of source authority) | `canonical` |
| **B. Generated / dump listings** | Optimizer dump, TDFOL Sphinx HTML, `*_stubs.md`, empty auto-stub tree | **No** — discovery and search only | `generated` or `historical` |

### Track A — domain maps (preferred contract)

Domain pages are **curated** inventories:

- Built from reviewed `__all__` / package exports, protocols, ABC method
  lists, and focused AST inspection.
- Label every listed surface with **Stability**, **Source**, **Optional**,
  **Side effects**, and sync/async where relevant.
- Explicitly **exclude** exhaustive internal listings with no stability
  promise (acceptance criterion for IPFSDOC-G091 / IPFSDOC-082).
- Cite architecture leaves for ownership; do not redefine domain boundaries.

**Inputs (evidence):**

| Input class | Examples | Role |
| --- | --- | --- |
| Package exports | `core_operations/__init__.py` `__all__`; package-root `__getattr__` / `__all__`; MCP server exports | Canonical name inventory |
| Module AST | Public methods on reviewed classes; Protocol/ABC definitions | Signature shape for listed symbols |
| Tests / schemas | Unit tests under `tests/unit/...`; IR/tool schemas | Rank-1 contracts |
| Architecture maps | `docs/architecture/DOMAIN_MAP.md`, domain leaves | Ownership and authority inequalities |
| Prior domain pages | Sibling `domains/*.md` cross-links | Avoid duplicate false contracts |

**Not inputs for public contract claims:** completion reports, session
summaries, marketing API guides, unchecked stub dumps.

### Track B — generated dumps (secondary)

Generated artifacts may list many symbols quickly. They:

- Help **discover** class and method names after large refactors.
- Do **not** assign public/reviewed/compatibility/internal stability.
- May lag the tree until regenerated.
- Must not be pasted wholesale into entry pages as “the API.”

---

## 3. Generation inventory (Track B detail)

### 3.1 Optimizers API dump

| Field | Value |
| --- | --- |
| Output | [OPTIMIZERS_API_REFERENCE.md](OPTIMIZERS_API_REFERENCE.md) |
| Generator | `scripts/documentation/generate_optimizer_api_reference.py` |
| Method | Static AST walk of selected module paths; type hints + first docstring line |
| Default modules | `optimizers/common/base_optimizer.py`; GraphRAG ontology generator/critic/mediator; `optimizers/agentic/cli.py` |
| Banner in file | “Auto-generated… Do not edit manually” |
| Classification | **`generated`** — secondary discovery dump |
| Canonical authority | [domains/KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) § optimizers |

**Regenerate (example):**

```bash
python scripts/documentation/generate_optimizer_api_reference.py \
  --output docs/api/OPTIMIZERS_API_REFERENCE.md
```

(Confirm flags with the script’s argparse help; paths above match the script’s
documented defaults at last verification.)

**Limitations:**

- Only modules passed to the script (default list is **not** the full
  `optimizers/` tree).
- No stability tags; private helpers may appear if present in the walked files.
- Docstring summaries can be empty or stale relative to tests.
- Does not prove optional dependencies or runtime backends are available.

### 3.2 TDFOL Sphinx tree

| Field | Value |
| --- | --- |
| Sources | `docs/tdfol/**/*.rst`, `docs/tdfol/conf.py`, `docs/tdfol/Makefile` |
| Build products | `docs/tdfol/_build/` (doctrees, HTML, module pages) |
| Subject | TDFOL / related modules under `ipfs_datasets_py/logic` (historical Sphinx set) |
| Classification | **`generated`** build output + hand-authored RST sources (domain-local) |
| Canonical authority | [domains/KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) for product-facing logic/prover contracts; live `logic` package for signatures |

**Rebuild (when Sphinx and deps are available):**

```bash
# From docs/tdfol when the environment has Sphinx configured
make html
```

**Limitations:**

- Tree is a **subsystem** documentation set, not the product-wide API index.
- `_build/` HTML can be stale relative to both RST and Python.
- Simulated ZKP / optional prover paths must still respect result-authority
  rules on the knowledge/logic domain page.
- Do not promote Sphinx autodoc of every internal symbol as a stable public
  contract for the whole package.

### 3.3 Stub markdown (`*_stubs.md`)

| Family | Location | Classification | Notes |
| --- | --- | --- | --- |
| Optimizer stubs | `docs/optimizers/*_stubs.md` | `generated` | Method/signature dumps for selected modules |
| Logic archive stubs | `docs/logic/archive/*_stubs.md` | `historical` / `generated` | Archived; not current authority |
| Auto-generated stubs home | `docs/auto_generated_stubs/` | `generated` policy | README describes lifecycle; active stub tree may be empty |
| Archived processor stubs | `docs/archived_stubs/` | `historical` | Bulk archive from processor cleanup; audit trail only |
| Package-local stubs | e.g. under package trees (see PACKAGE_LOCAL map) | `generated` | Same rule: signatures only, not behavior contracts |

**Rules for stubs:**

1. **Do not hand-edit** generated stubs to “fix” the product API; fix source
   docstrings/exports and regenerate, or update the **domain** page.
2. **Do not cite** stubs for return envelopes, side effects, or stability.
3. Prefer domain pages and tests when stubs and live AST disagree.

### 3.4 Superseded hand pages under `docs/api/`

| Path | Classification | Replacement |
| --- | --- | --- |
| [CORE_OPERATIONS_API.md](CORE_OPERATIONS_API.md) | `historical` / superseded for method accuracy | [domains/CORE_AND_DATA.md](domains/CORE_AND_DATA.md) |
| [OPTIMIZERS_API_REFERENCE.md](OPTIMIZERS_API_REFERENCE.md) | `generated` (kept navigable) | Stability from [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) |
| `docs/guides/reference/api_reference.md` | `review-needed` (known drift risk) | [README.md](README.md) + domain pages |

---

## 4. Coverage model (what domain pages include)

Domain pages aim for **intended public and reviewed surfaces**, not every
`.py` file in the package.

| Included | Excluded (by design) |
| --- | --- |
| Reviewed package / submodule `__all__` exports named on the page | Exhaustive listing of every private helper and test double |
| Protocol / ABC contracts that define extension points | Full autodoc of all mixin internals |
| Canonical import paths and known compatibility aliases | Marketing example methods that never existed on the class |
| Sync/async and side-effect notes for listed callables | Undeclared network/model behavior invented for tutorials |
| Optional extras, empty submodules, simulated paths **as availability** | Treating optional/simulated paths as production success |
| Explicit discrepancies and deferred items sections | Silent omission of known wrong legacy method names |

**Coverage is not 100% of the repository.** Large domains (`processors/`,
`logic/`, `mcp_server/tools/`) are mapped by **export and contract**, with
pointers to architecture leaves for depth. That is intentional: an exhaustive
AST dump would create a false public contract and go stale immediately.

---

## 5. Limitations (binding)

1. **Importability is not stability.** Domain pages mark this explicitly.
2. **Generated dumps lag.** Until regenerated, they may omit new classes or
   retain deleted ones.
3. **Docstrings are not rank-1.** Tests and schemas outrank docstring text when
   they conflict ([SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)).
4. **Optional capabilities.** Missing extras, empty git submodules, or absent
   prover binaries mean **unavailable**, not “domain missing from the map.”
5. **MCP tool discovery ≠ domain success.** Tool registration, health, policy
   allow, and engine execution are different facts
   ([MCP_AND_RUNTIME.md](domains/MCP_AND_RUNTIME.md)).
6. **No guarantee of hermetic examples.** Example verification is owned by
   tutorial/ledger tasks; this page only defines API doc freshness.
7. **MkDocs nav may lag.** Nav may still highlight generated dumps; the
   canonical entry is [README.md](README.md).

---

## 6. Freshness verification

### 6.1 When to re-verify

| Change type | Action |
| --- | --- |
| `__all__` or public export change in a mapped package | Update the owning domain page; refresh “Last verified” |
| Signature change on a **listed** public/reviewed method | Update domain page row; fix any tutorial examples that cite it |
| New optimizer module of interest | Optionally extend generator module list and regenerate dump; always update domain narrative if it is a product surface |
| TDFOL API change | Rebuild Sphinx if that corpus is still used; update knowledge/logic domain if product contract changes |
| Stub-only change with no export impact | Regenerate stubs if still maintained; **do not** treat as domain page refresh alone |
| Test/schema contract change | Prefer test citation on domain page over prose |

### 6.2 Recommended verification commands

**Spine presence (program gate for this task):**

```bash
test -s docs/api/README.md
test -s docs/api/GENERATION_AND_FRESHNESS.md
rg -n 'CORE_AND_DATA|PROCESSING_AND_RETRIEVAL|KNOWLEDGE_LOGIC_AND_PROOF|MCP_AND_RUNTIME' docs/api/README.md
test -s docs/api/domains/CORE_AND_DATA.md
test -s docs/api/domains/PROCESSING_AND_RETRIEVAL.md
test -s docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md
test -s docs/api/domains/MCP_AND_RUNTIME.md
test -s docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md
```

**Export inventory spot-check (example: core_operations):**

```bash
python - <<'PY'
import ast
from pathlib import Path
path = Path("ipfs_datasets_py/core_operations/__init__.py")
tree = ast.parse(path.read_text())
for node in tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "__all__":
                print(sorted(ast.literal_eval(node.value)))
PY
```

Compare the printed names to the eight-export table in
[CORE_AND_DATA.md](domains/CORE_AND_DATA.md) and the quick map in
[README.md](README.md).

**Method existence spot-check (example):**

```bash
python - <<'PY'
import ast
from pathlib import Path

def public_methods(module_path: str, class_name: str):
    tree = ast.parse(Path(module_path).read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            names = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not item.name.startswith("_"):
                        names.append(item.name)
            return names
    return None

print(public_methods(
    "ipfs_datasets_py/optimizers/common/base_optimizer.py",
    "BaseOptimizer",
))
PY
```

Compare against the domain page (and, for discovery only, against the
generated optimizers dump).

**Domain page self-checks:** each domain file ends with a **Validation
evidence** section; re-run those commands when refreshing that domain.

### 6.3 Freshness metadata

Every domain page and this file carry:

| Field | Expectation |
| --- | --- |
| `Last verified` | Date of last source-grounded review |
| `Source of truth` | Paths that must still exist and match claims |
| `Review cadence` | Event-driven triggers (export change, etc.) |

Stale `Last verified` alone is not a bug; **false signatures** are. Prefer
fixing wrong names over mass-updating dates without re-reading AST.

---

## 7. Detecting signature drift

**Signature drift** means documentation claims a callable shape (name, params,
asyncness, return contract) that the current tree does not implement—or the
tree exposes a reviewed export that maintained docs still omit or mislabel.

### 7.1 Drift classes

| Class | Example | Severity |
| --- | --- | --- |
| **Missing method** | Docs show `load_dataset`; class has `get_dataset` | High on entry/domain pages |
| **Wrong arity / keywords** | Docs omit required args or invent kwargs | High |
| **Sync/async mismatch** | Docs show sync call for `async def` | High for copy-paste users |
| **Wrong import path** | Docs use deleted or non-canonical module | Medium–high |
| **Stability mislabel** | Internal helper presented as public | Medium |
| **Generated dump lag** | Dump lists deleted class until regenerate | Low if dump is secondary |
| **Envelope fiction** | Docs invent success fields not returned | High (authority) |

Program-wide claim inventory (including API-signature rows):
[DRIFT_AND_CLAIM_MATRIX.md](../maintenance/DRIFT_AND_CLAIM_MATRIX.md).

### 7.2 Detection procedures

#### A. Manual / agent checklist (domain pages)

1. For each **Source** row on the domain page, open the module path.
2. Confirm the symbol exists (class/function name).
3. Confirm listed public methods exist on the class body (or Protocol).
4. Confirm `async def` vs `def` matches the page.
5. Confirm **canonical import** still resolves (`__all__` or documented export).
6. If the page names a return **envelope** (`status`, proof fields, etc.),
   confirm against implementation or tests—not against stubs.

#### B. Diff-assisted checklist (after a PR)

1. List changed Python files under `ipfs_datasets_py/`.
2. Map each file to a domain page via [README.md](README.md) conceptual routes.
3. Grep domain pages for the class or function name:

   ```bash
   rg -n 'ClassName|function_name' docs/api/domains/
   ```

4. Update matching rows or mark **Discrepancies** if deferred.
5. If the change is optimizers and the module is in the generator default list,
   regenerate [OPTIMIZERS_API_REFERENCE.md](OPTIMIZERS_API_REFERENCE.md).

#### C. Export-set drift

1. Extract `__all__` (or equivalent export table) from the package module.
2. Diff against the domain page inventory section.
3. New reviewed exports → add with stability labels.
4. Removed exports → remove or reclassify as compatibility/historical.

#### D. Generated-dump drift (secondary)

1. Regenerate the dump into a temporary file.
2. Diff against the committed dump:

   ```bash
   python scripts/documentation/generate_optimizer_api_reference.py \
     --output /tmp/OPTIMIZERS_API_REFERENCE.md
   diff -u docs/api/OPTIMIZERS_API_REFERENCE.md /tmp/OPTIMIZERS_API_REFERENCE.md | head
   ```

3. Non-empty diff means the dump is stale. Commit regeneration **or** document
   deferral; still update domain pages for any **product** contract change.
4. Never promote the dump diff alone as “API approved.”

#### E. Cross-check against known bad claims

When auditing entry guides, search for method names flagged in
DRIFT_AND_CLAIM_MATRIX (`CLAIM-api-*`) and confirm domain pages use the
corrected forms.

### 7.3 Disposition when drift is found

| Location of wrong claim | Disposition |
| --- | --- |
| Domain page (`domains/*`) | Fix in place; note in Discrepancies if partial |
| API index ([README.md](README.md)) | Fix route or export map |
| Generated dump | Regenerate; do not hand-patch large tables |
| Legacy `CORE_OPERATIONS_API.md` | Prefer leaving superseded; fix only if still navigated without banner—domain page wins |
| Tutorials / user guides | Fix or mark unverified; not owned by this task |
| Stubs / archive | Leave historical or regenerate; never sole fix for public contract |

---

## 8. Classification summary (legacy optimizer / TDFOL / stubs)

| Artifact class | Paths | Lifecycle | Public contract? | Drift response |
| --- | --- | --- | --- | --- |
| Domain API maps | `docs/api/domains/*.md` | `canonical` | **Yes** (curated) | Edit with AST/tests |
| API index | `docs/api/README.md` | `canonical` | Navigation + rules | Edit with domain spine |
| This provenance page | `docs/api/GENERATION_AND_FRESHNESS.md` | `canonical` | Process only | Edit when generators/process change |
| Optimizers AST dump | `docs/api/OPTIMIZERS_API_REFERENCE.md` | `generated` | **No** | Regenerate |
| Core ops legacy note | `docs/api/CORE_OPERATIONS_API.md` | `historical` / superseded | **No** | Prefer domain page |
| TDFOL Sphinx | `docs/tdfol/` | `generated` + local sources | Subsystem only | Rebuild / update logic domain |
| Optimizer stubs | `docs/optimizers/*_stubs.md` | `generated` | **No** | Regenerate or ignore |
| Auto-stub policy tree | `docs/auto_generated_stubs/` | `generated` policy | **No** | Keep policy accurate |
| Archived stubs | `docs/archived_stubs/` | `historical` | **No** | Do not revive as API |
| Marketing API guide | `docs/guides/reference/api_reference.md` | `review-needed` | **No** until refreshed | Defer to domain spine |

---

## 9. What agents must not do

1. **Do not** paste full package AST or entire generated dumps into public
   entry pages as the API contract.
2. **Do not** invent methods to make examples look complete.
3. **Do not** treat simulated proofs, mock workflows, or empty submodules as
   production authority.
4. **Do not** edit protected plan files or unrelated trees for this task.
5. **Do not** mark domain coverage “complete” solely because a generator ran.

---

## 10. Related documents

| Document | Role |
| --- | --- |
| [README.md](README.md) | Canonical API index and conceptual routes |
| [domains/CORE_AND_DATA.md](domains/CORE_AND_DATA.md) | Core / data / storage / archive / publication |
| [domains/PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) | Processors / embeddings / vectors / search |
| [domains/KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | Knowledge / optimizers / logic / proof |
| [domains/MCP_AND_RUNTIME.md](domains/MCP_AND_RUNTIME.md) | MCP and runtime surfaces |
| [domains/OPERATIONS_AND_INTEGRATIONS.md](domains/OPERATIONS_AND_INTEGRATIONS.md) | Audit / wallet / workflow / config / ops |
| [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) | Authority ranking |
| [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) | Lifecycle states including `generated` |
| [DRIFT_AND_CLAIM_MATRIX.md](../maintenance/DRIFT_AND_CLAIM_MATRIX.md) | Program-wide claim and signature drift |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Package-local docs disposition |

---

## 11. Validation evidence for this page

```bash
test -s docs/api/README.md
test -s docs/api/GENERATION_AND_FRESHNESS.md
rg -n 'CORE_AND_DATA|PROCESSING_AND_RETRIEVAL|KNOWLEDGE_LOGIC_AND_PROOF|MCP_AND_RUNTIME' docs/api/README.md
rg -n 'generate_optimizer_api_reference|signature drift|generated|TDFOL|stubs' docs/api/GENERATION_AND_FRESHNESS.md
test -f scripts/documentation/generate_optimizer_api_reference.py
```

Last verified against the live domain spine and generator path on 2026-08-03.
