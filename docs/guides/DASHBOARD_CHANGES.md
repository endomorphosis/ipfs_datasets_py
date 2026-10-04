# Dashboard Changes: Finance and Medicine Sub-Dashboards

## Overview
Added two new sub-dashboards based on the existing caselaw dashboard template:
- **Finance Dashboard** at `/mcp/finance`
- **Medicine Dashboard** at `/mcp/medicine`

## Changes Made

### 1. New Templates Created
- `ipfs_datasets_py/templates/admin/finance_dashboard_mcp.html`
  - Based on `caselaw_dashboard_mcp.html`
  - Customized terminology: Legal → Financial, Jurisdiction → Market, Theorem → Rule
  - Icon changed from gavel to chart-line

- `ipfs_datasets_py/templates/admin/medicine_dashboard_mcp.html`
  - Based on `caselaw_dashboard_mcp.html`
  - Customized terminology: Legal → Medical, Jurisdiction → Specialty, Theorem → Guideline
  - Icon changed from gavel to heartbeat

### 2. Backend Routes Added
Modified `ipfs_datasets_py/mcp_dashboard.py`:

#### New Route Setup Methods:
- `_setup_finance_routes()` - Registers finance dashboard routes
- `_setup_medicine_routes()` - Registers medicine dashboard routes

#### Finance Dashboard Routes:
- `GET /mcp/finance` - Main finance dashboard
- `POST /api/mcp/finance/check_document` - Check financial document consistency
- `POST /api/mcp/finance/query_theorems` - Query financial rules

#### Medicine Dashboard Routes:
- `GET /mcp/medicine` - Main medicine dashboard
- `POST /api/mcp/medicine/check_document` - Check medical document consistency
- `POST /api/mcp/medicine/query_theorems` - Query medical guidelines

### 3. Navigation Updates
All three dashboard templates now have cross-links in the sidebar:
- Caselaw dashboard links to Finance and Medicine
- Finance dashboard links to Caselaw and Medicine
- Medicine dashboard links to Caselaw and Finance

## Technical Details

### Backend Infrastructure
All three dashboards share the same underlying temporal deontic logic infrastructure:
- `TemporalDeonticRAGStore` - RAG storage for rules/theorems/guidelines
- `DocumentConsistencyChecker` - Document analysis engine
- `DeonticLogic` - Core logic reasoning system

The only differences between dashboards are:
1. Template styling and terminology
2. Default `legal_domain` parameter (caselaw, finance, or medicine)
3. UI labels and icons

### API Compatibility
The API endpoints follow the same interface pattern as caselaw.

**Important**: While the UI labels differ between dashboards (e.g., "Market" in Finance, "Specialty" in Medicine), the API parameter names remain consistent across all domains (`jurisdiction`, `legal_domain`). This design ensures:
- API consistency and backward compatibility
- Easy integration with existing tools
- Clear separation between UI presentation and backend logic

**Check Document Request:**
```json
{
  "document_text": "Document content...",
  "document_id": "optional_id",
  "jurisdiction": "Federal",
  "legal_domain": "finance|medicine|caselaw",
  "temporal_context": "2024-01-01T00:00:00"
}
```

**Query Theorems Request:**
```json
{
  "query_text": "Search query...",
  "operator": "OBLIGATION|PROHIBITION|PERMISSION",
  "jurisdiction": "optional_filter",
  "legal_domain": "finance|medicine|caselaw",
  "top_k": 10
}
```

## Testing

Run the test script to verify all routes and templates:
```bash
python3 test_dashboard_routes.py
```

## Starting the Server

Use the existing MCP dashboard start command:
```bash
ipfs-datasets mcp start
```

Then access the dashboards at:
- http://127.0.0.1:8080/mcp/caselaw
- http://127.0.0.1:8080/mcp/finance
- http://127.0.0.1:8080/mcp/medicine

## Future Enhancements

To further customize the dashboards, consider:
1. Domain-specific example data in each dashboard
2. Custom analysis tools specific to each domain
3. Separate RAG stores for each domain (currently shared)
4. Domain-specific visualizations
5. Different sidebar analysis tools per domain
