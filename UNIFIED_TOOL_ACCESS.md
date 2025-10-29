# Unified Medical Research Tools - Access Methods

## Overview

All medical research tools are exposed through three consistent interfaces:
1. **CLI** - Command-line interface
2. **MCP Server Tools** - Model Context Protocol server tools
3. **Python Package** - Direct Python imports

All three methods call the same underlying MCP tool functions, ensuring consistent behavior and code paths regardless of access method.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Access Methods                           │
├───────────────┬──────────────────┬─────────────────────────┤
│     CLI       │   MCP Server     │    Python Package       │
│  (mcp_cli.py) │  (server.py)     │  (direct import)        │
└───────┬───────┴─────────┬────────┴──────────┬──────────────┘
        │                 │                   │
        │                 │                   │
        └─────────────────┼───────────────────┘
                          ↓
         ┌────────────────────────────────────┐
         │   MCP Tool Functions (Core Layer)  │
         │                                    │
         │  • scrape_pubmed_medical_research  │
         │  • scrape_clinical_trials          │
         │  • discover_protein_binders        │
         │  • discover_enzyme_inhibitors      │
         │  • discover_biomolecules_rag       │
         │  • etc.                            │
         └────────────────────────────────────┘
                          ↓
         ┌────────────────────────────────────┐
         │     Implementation Layer           │
         │                                    │
         │  • PubMedScraper                   │
         │  • ClinicalTrialsScraper           │
         │  • BiomoleculeDiscoveryEngine      │
         │  • MedicalTheoremFramework         │
         └────────────────────────────────────┘
```

## Dashboard Integration

The medicine dashboard uses a JavaScript MCP SDK to call tools through the same code paths:

```
Dashboard (JavaScript)
    ↓
MCP Client SDK (mcp_client_sdk.js)
    ↓
API Route (/api/mcp/medical_research_scrapers/scrape_pubmed_medical_research)
    ↓
MCP Tool Function (scrape_pubmed_medical_research)
    ↓
Implementation (PubMedScraper)
```

This ensures the dashboard always uses the same code as CLI and Python API calls.

## Usage Examples

### 1. CLI Interface

```bash
# Scrape PubMed
mcp_cli.py medical_research_scrapers scrape_pubmed_medical_research \
    --query "COVID-19 treatment" \
    --max-results 100 \
    --email user@example.com

# Discover protein binders
mcp_cli.py medical_research_scrapers discover_protein_binders \
    --target-protein "SARS-CoV-2 spike" \
    --interaction binding \
    --min-confidence 0.7

# Scrape clinical trials
mcp_cli.py medical_research_scrapers scrape_clinical_trials \
    --condition diabetes \
    --intervention metformin \
    --max-results 50
```

### 2. Python Package Import

```python
from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers import (
    scrape_pubmed_medical_research,
    scrape_clinical_trials,
    discover_protein_binders,
    discover_enzyme_inhibitors,
    discover_biomolecules_rag
)

# Scrape PubMed
result = scrape_pubmed_medical_research(
    query="COVID-19 treatment",
    max_results=100,
    email="user@example.com"
)

# Discover protein binders
candidates = discover_protein_binders(
    target_protein="SARS-CoV-2 spike",
    interaction_type="binding",
    min_confidence=0.7,
    max_results=50
)

# Scrape clinical trials
trials = scrape_clinical_trials(
    condition="diabetes",
    intervention="metformin",
    max_results=50
)
```

### 3. MCP Server / Dashboard (JavaScript SDK)

```javascript
// Initialize MCP client
const mcpClient = new MCPClient('/api/mcp');
const medicalTools = new MedicalResearchTools(mcpClient);

// Scrape PubMed
const pubmedResult = await medicalTools.scrapePubMed({
    query: "COVID-19 treatment",
    max_results: 100,
    email: "user@example.com"
});

// Discover protein binders
const binders = await medicalTools.discoverProteinBinders({
    target_protein: "SARS-CoV-2 spike",
    interaction_type: "binding",
    min_confidence: 0.7,
    max_results: 50
});

// Scrape clinical trials
const trials = await medicalTools.scrapeClinicalTrials({
    condition: "diabetes",
    intervention: "metformin",
    max_results: 50
});

// Generic MCP call (alternative)
const result = await mcpClient.callTool(
    'medical_research_scrapers',
    'scrape_pubmed_medical_research',
    {
        query: "COVID-19 treatment",
        max_results: 100
    }
);
```

## Available Tools

All tools are accessible through all three methods:

### Medical Research Scraping
- `scrape_pubmed_medical_research` - PubMed medical literature
- `scrape_clinical_trials` - ClinicalTrials.gov trial data
- `scrape_biochemical_research` - Biochemical research queries
- `scrape_population_health_data` - Population demographics

### Theorem Framework
- `generate_medical_theorems_from_trials` - Auto-generate theorems
- `validate_medical_theorem_fuzzy` - Fuzzy logic validation

### Biomolecule Discovery (RAG)
- `discover_protein_binders` - Find protein binders
- `discover_enzyme_inhibitors` - Find enzyme inhibitors
- `discover_pathway_biomolecules` - Find pathway components
- `discover_biomolecules_rag` - Unified discovery interface

## Code Path Verification

All three access methods ultimately call the same MCP tool functions:

```python
# This is the SAME function called by:
# - CLI (via mcp_cli.py)
# - Dashboard (via MCP Client SDK)
# - Python imports (direct call)

def scrape_pubmed_medical_research(
    query: str,
    max_results: int = 100,
    email: Optional[str] = None,
    research_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Scrape medical research from PubMed.
    
    This function is the single source of truth for PubMed scraping,
    called by all access methods.
    """
    # Implementation here
    pass
```

## Benefits

1. **Consistency** - Same behavior regardless of access method
2. **Maintainability** - Single implementation to maintain
3. **Testing** - Test once, works everywhere
4. **Documentation** - Single set of docs for all methods
5. **Security** - Centralized validation and error handling

## API Routes

The dashboard API routes are wrappers that call MCP tool functions:

```python
@app.route('/api/mcp/medicine/scrape/pubmed', methods=['POST'])
def api_scrape_pubmed():
    """Dashboard API endpoint - calls MCP tool function."""
    from .mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import scrape_pubmed_medical_research
    
    data = request.json
    # Call the MCP tool function (same code path as CLI and Python API)
    result = scrape_pubmed_medical_research(**data)
    return jsonify(result)
```

Generic MCP router also available:

```python
@app.route('/api/mcp/<category>/<tool_name>', methods=['POST'])
def api_call_mcp_tool(category, tool_name):
    """Generic MCP tool router - dynamically calls any tool."""
    # Dynamically import and call tool function
    # Ensures same code path for all tool calls
    pass
```

## Dashboard SDK Integration

The dashboard template includes the MCP Client SDK:

```html
<!-- Load MCP Client SDK -->
<script src="{{ url_for('static', filename='js/mcp_client_sdk.js') }}"></script>

<script>
    // Initialize MCP client
    const mcpClient = new MCPClient('/api/mcp');
    const medicalTools = new MedicalResearchTools(mcpClient);
    
    // All form handlers use the SDK
    document.getElementById('pubmedForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const result = await medicalTools.scrapePubMed({
            query: document.getElementById('query').value,
            max_results: parseInt(document.getElementById('maxResults').value)
        });
        // Display results
    });
</script>
```

## File Structure

```
ipfs_datasets_py/
├── mcp_server/
│   └── tools/
│       ├── medical_research_scrapers/
│       │   ├── __init__.py                    # Package exports
│       │   ├── pubmed_scraper.py              # Implementation
│       │   ├── clinical_trials_scraper.py     # Implementation
│       │   ├── biomolecule_discovery.py       # Implementation
│       │   └── medical_research_mcp_tools.py  # MCP tool functions (CORE)
│       └── cli/
│           ├── __init__.py
│           └── medical_research_cli.py        # CLI wrappers
├── mcp_dashboard.py                            # API routes
├── static/
│   └── js/
│       └── mcp_client_sdk.js                  # JavaScript SDK
└── templates/
    └── admin/
        └── medicine_dashboard_mcp.html        # Dashboard UI
```

## Testing

All three access methods can be tested to ensure they produce identical results:

```python
# Test CLI
cli_result = subprocess.run([
    'mcp_cli.py', 'medical_research_scrapers', 'scrape_pubmed_medical_research',
    '--query', 'test', '--max-results', '10'
], capture_output=True)

# Test Python import
from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers import scrape_pubmed_medical_research
python_result = scrape_pubmed_medical_research(query='test', max_results=10)

# Test API/Dashboard
api_result = requests.post('/api/mcp/medicine/scrape/pubmed', json={
    'query': 'test',
    'max_results': 10
})

# All three should produce identical results
assert cli_result == python_result == api_result.json()
```

## Summary

This unified architecture ensures that:
- ✅ CLI calls use MCP tool functions
- ✅ MCP server exposes MCP tool functions
- ✅ Python imports use MCP tool functions
- ✅ Dashboard uses JavaScript SDK → API → MCP tool functions
- ✅ Same code path for all access methods
- ✅ Consistent behavior and testing
- ✅ Single source of truth for all functionality
