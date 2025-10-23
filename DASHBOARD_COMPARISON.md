# Dashboard Comparison: Caselaw, Finance, and Medicine

## Quick Reference

| Aspect | Caselaw | Finance | Medicine |
|--------|---------|---------|----------|
| **URL** | `/mcp/caselaw` | `/mcp/finance` | `/mcp/medicine` |
| **Title** | Caselaw Dashboard | Finance Dashboard | Medicine Dashboard |
| **Icon** | ⚖️ fa-gavel | 📈 fa-chart-line | ❤️ fa-heartbeat |
| **Domain Term** | Legal | Financial | Medical |
| **Scope Term** | Jurisdiction | Market | Specialty |
| **Rule Term** | Theorem | Rule | Guideline |

## Terminology Mapping

### Caselaw → Finance
- Legal → Financial
- Jurisdiction → Market
- Theorem → Rule
- Case Law → Finance
- Gavel icon → Chart-line icon

### Caselaw → Medicine
- Legal → Medical
- Jurisdiction → Specialty
- Theorem → Guideline
- Case Law → Medicine
- Gavel icon → Heartbeat icon

## API Endpoints

### Caselaw
```
GET  /mcp/caselaw
POST /api/mcp/caselaw/check_document
POST /api/mcp/caselaw/query_theorems
POST /api/mcp/caselaw/add_theorem
POST /api/mcp/caselaw/bulk_process
GET  /api/mcp/caselaw/bulk_process/<session_id>
POST /api/mcp/caselaw/bulk_process/<session_id>/stop
GET  /api/mcp/caselaw/bulk_process/<session_id>/download
GET  /api/mcp/caselaw/bulk_process/<session_id>/log
POST /api/mcp/caselaw/jsonrpc
GET  /api/mcp/caselaw/tools
```

### Finance
```
GET  /mcp/finance
POST /api/mcp/finance/check_document
POST /api/mcp/finance/query_theorems
```

### Medicine
```
GET  /mcp/medicine
POST /api/mcp/medicine/check_document
POST /api/mcp/medicine/query_theorems
```

## Shared Infrastructure

All three dashboards use the same backend components:

```python
# Shared components
from .logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
from .logic_integration.document_consistency_checker import DocumentConsistencyChecker
from .logic_integration.deontic_logic_core import DeonticOperator
```

The only difference in the backend is the default `legal_domain` parameter:
- Caselaw: `legal_domain="caselaw"` or `legal_domain="general"`
- Finance: `legal_domain="finance"`
- Medicine: `legal_domain="medicine"`

## Example Usage

### Starting the Server
```bash
ipfs-datasets mcp start
# or
ipfs-datasets mcp start --host 127.0.0.1 --port 8080
```

### Accessing Dashboards
- http://127.0.0.1:8080/mcp/caselaw
- http://127.0.0.1:8080/mcp/finance ⬅️ NEW
- http://127.0.0.1:8080/mcp/medicine ⬅️ NEW

### API Example: Check Finance Document
```bash
curl -X POST http://127.0.0.1:8080/api/mcp/finance/check_document \
  -H "Content-Type: application/json" \
  -d '{
    "document_text": "Company must disclose all financial risks in quarterly reports",
    "jurisdiction": "SEC",
    "legal_domain": "finance"
  }'
```

### API Example: Query Medical Guidelines
```bash
curl -X POST http://127.0.0.1:8080/api/mcp/medicine/query_theorems \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "patient consent requirements",
    "operator": "OBLIGATION",
    "legal_domain": "medicine",
    "top_k": 5
  }'
```

## Navigation

Each dashboard has a sidebar with links to the other dashboards:

```
Main Dashboard
├── MCP Dashboard
├── Caselaw Analysis (MCP) ⚖️
├── Finance Analysis (MCP) 📈
└── Medicine Analysis (MCP) ❤️
```

## Visual Differences

### Color Schemes
- All dashboards use the same purple gradient header
- Icons differ: gavel (⚖️) vs. chart-line (📈) vs. heartbeat (❤️)

### Labels
#### Document Input Section
- **Caselaw**: "Paste legal document text here..."
- **Finance**: "Paste financial document text here..."
- **Medicine**: "Paste medical document text here..."

#### Dropdown Filters
- **Caselaw**: "Jurisdiction" / "Legal Domain"
- **Finance**: "Market" / "Financial Domain"
- **Medicine**: "Specialty" / "Medical Domain"

#### Results Display
- **Caselaw**: "Theorems Found"
- **Finance**: "Rules Found"
- **Medicine**: "Guidelines Found"
