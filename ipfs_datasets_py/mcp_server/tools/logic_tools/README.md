# Logic Tools

MCP tools for formal logic reasoning: First-Order Logic (FOL), Temporal Deontic First-Order
Logic (TDFOL), and DCEC/CEC reasoning. These tools wrap the logic engine in
`ipfs_datasets_py.logic`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `tdfol_prove_tool.py` | `tdfol_prove()`, `tdfol_batch_prove()` | Prove TDFOL formulas with optional axioms |
| `tdfol_kb_tool.py` | `tdfol_kb_add()`, `tdfol_kb_query()`, `tdfol_kb_list()` | Manage a TDFOL knowledge base |
| `tdfol_parse_tool.py` | `tdfol_parse()` | Parse TDFOL formula strings into AST |
| `tdfol_convert_tool.py` | `tdfol_convert()` | Convert between TDFOL, Prolog, TPTP, SMT-LIB |
| `tdfol_visualize_tool.py` | `tdfol_visualize()` | Render a TDFOL formula as a proof tree or graph |
| `cec_prove_tool.py` | `cec_prove()`, `cec_check_theorem()` | Prove DCEC/CEC theorems |
| `cec_parse_tool.py` | `cec_parse()` | Parse CEC formula strings |
| `cec_inference_tool.py` | `cec_infer()` | Run CEC forward chaining inference |
| `cec_analysis_tool.py` | `cec_analyze()` | Analyze CEC formula structure and consistency |
| `logic_graphrag_tool.py` | `logic_graphrag_query()` | GraphRAG query using logic to extract structured facts |
| `logic_capabilities_tool.py` | `logic_capabilities()`, `logic_health()` | List supported logics, rule counts, system health |
| `temporal_deontic_logic_tools.py` | Multiple | Legacy RAG system for legal document consistency checking |

## Usage

### Prove a TDFOL formula

```python
from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_prove

result = await tdfol_prove(
    formula="Obligated(file_taxes(alice, 2024))",
    axioms=[
        "∀x∀y(citizen(x, y) → Obligated(file_taxes(x, y)))",
        "citizen(alice, 2024)"
    ],
    logic="TDFOL"   # "TDFOL" | "FOL" | "deontic"
)
# Returns: {"status": "success", "proved": True, "proof": {...}, "steps": [...]}
```

### Use the TDFOL knowledge base

```python
from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_kb_add, tdfol_kb_query

# Add axioms
await tdfol_kb_add(
    kb_name="tax_law",
    axioms=["∀x(person(x) → Obligated(pay_taxes(x)))"]
)

# Query
result = await tdfol_kb_query(
    kb_name="tax_law",
    query="Obligated(pay_taxes(bob))",
    additional_facts=["person(bob)"]
)
```

### Prove a CEC/DCEC theorem

```python
from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_prove

result = await cec_prove(
    goal="BF(agent1, knows(agent2, P), t1)",
    axioms=[
        "K(agent1, P, t0)",
        "communicates(agent1, agent2, P, t0, t1)"
    ]
)
```

### Check logic system capabilities

```python
from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_capabilities

caps = await logic_capabilities()
# Returns: {"supported_logics": ["FOL", "TDFOL", "CEC", "DCEC", ...], "rule_counts": {...}}
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.logic.TDFOL` — TDFOL prover and knowledge base
- `ipfs_datasets_py.logic.CEC` — CEC/DCEC prover
- `ipfs_datasets_py.logic.fol` — FOL utilities
- `ipfs_datasets_py.logic.common.proof_cache` — shared proof cache

## Logic Systems Supported

| System | Description | Use Case |
|--------|-------------|---------|
| **FOL** | First-Order Logic | General reasoning |
| **TDFOL** | Temporal Deontic FOL | Legal obligations with time |
| **Modal** | Modal logic (K, T, D, S4, S5) | Necessity and possibility |
| **CEC** | Causal Event Calculus | Event/action reasoning |
| **DCEC** | Deliberative CEC | Agent deliberation, belief/desire/intention |

## Dependencies

**Required:**
- `ipfs_datasets_py.logic` — core logic engine

**Optional (graceful degradation if missing):**
- `multiformats` — for content-addressed proof caching
- `networkx` — for proof graph visualization

## Status

| Tool | Status |
|------|--------|
| TDFOL tools | ✅ Production ready (2026-02-20 fixes applied) |
| CEC/DCEC tools | ✅ Production ready (2026-02-20 fixes applied) |
| `logic_graphrag_tool` | ✅ Production ready |
| `temporal_deontic_logic_tools` | ⚠️ Legacy — prefer `tdfol_*` and `cec_*` tools |
