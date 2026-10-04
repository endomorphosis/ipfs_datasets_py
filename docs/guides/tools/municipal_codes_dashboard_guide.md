# Municipal Codes Scraper Dashboard Integration - Visual Guide

## Overview

The Municipal Codes Scraper has been fully integrated into the MCP Dashboard with a professional UI, JavaScript SDK integration, and comprehensive testing.

## Dashboard Navigation

### Location in Sidebar
The Municipal Codes Scraper is located in the **Legal & Logic Systems** section of the sidebar navigation:

```
📊 MCP Server Dashboard
├── Overview
├── Tools
├── Legal & Logic Systems
│   ├── Caselaw Analysis
│   ├── 🆕 Municipal Codes Scraper  ← NEW!
│   ├── Text to First-Order Logic
│   ├── Legal Text to Deontic Logic
│   └── Permission Checker
└── Settings
```

## User Interface

### Form Layout

The Municipal Codes Scraper section includes three main panels:

#### Panel 1: Jurisdiction Selection
```
┌─────────────────────────────────────────┐
│ 🗺️  Jurisdiction Selection              │
├─────────────────────────────────────────┤
│ Jurisdictions:                          │
│ [Seattle, WA; Portland, OR; Austin, TX] │
│ Enter one or more jurisdictions         │
│                                         │
│ Provider: [Auto-detect ▼]              │
│ Legal code provider                     │
│                                         │
│ Output Format: [JSON ▼]                │
└─────────────────────────────────────────┘
```

#### Panel 2: Scraping Options
```
┌─────────────────────────────────────────┐
│ ⚙️  Scraping Options                    │
├─────────────────────────────────────────┤
│ Rate Limit (seconds): [2.0      ]      │
│ Delay between requests                  │
│                                         │
│ Max Sections: [              ]          │
│ Limit sections per jurisdiction         │
│                                         │
│ Scraper Backend: [Playwright (Async)▼] │
│                                         │
│ ☑ Include Metadata                     │
│ ☑ Include Full Text                    │
└─────────────────────────────────────────┘
```

#### Panel 3: Execute Scraping
```
┌─────────────────────────────────────────┐
│ ▶️  Execute Scraping                    │
├─────────────────────────────────────────┤
│ Custom Job ID (Optional):              │
│ [                        ]              │
│ Auto-generated if empty                 │
│                                         │
│ ☐ Resume from Previous Job             │
│                                         │
│ ┌───────────────────────────────────┐  │
│ │   📥 Start Scraping               │  │
│ └───────────────────────────────────┘  │
│                                         │
│ ┌───────────────────────────────────┐  │
│ │   🔄 Clear Form                   │  │
│ └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Information Panel

Below the form panels, there's an informational panel:

```
┌──────────────────────────────────────────────────────────────┐
│ ℹ️  About Municipal Codes Scraping                           │
├──────────────────────────────────────────────────────────────┤
│ This tool integrates with the scrape_the_law_mk3 system to  │
│ collect municipal legal codes from US cities and counties.   │
│                                                              │
│ • Coverage: ~22,899+ US municipalities                       │
│ • Providers: Municode (~3,528), American Legal (~2,180),   │
│   General Code (~1,601), LexisNexis (~3,200)               │
│ • Job Management: Auto-generated job IDs with resume        │
│   capability for long-running operations                     │
│ • Output: Structured data with full metadata and citation   │
│   information                                               │
└──────────────────────────────────────────────────────────────┘
```

### Results Display

After clicking "Start Scraping", results are displayed in a terminal-style panel:

```
┌──────────────────────────────────────────────────────────────┐
│ Scraping Results                                             │
├──────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────────┐  │
│ │ ✓ Scraping Job Initialized                             │  │
│ │                                                         │  │
│ │ Job ID: municipal_codes_20251017_022500                │  │
│ │ Status: success                                         │  │
│ │ Jurisdictions: 3                                        │  │
│ │ Provider: municode                                      │  │
│ │ Output Format: json                                     │  │
│ │ Scraper: playwright                                     │  │
│ │                                                         │  │
│ │ Municipal code scraping job initialized                │  │
│ │                                                         │  │
│ │ Jurisdictions to scrape:                               │  │
│ │   1. Seattle, WA                                        │  │
│ │   2. Portland, OR                                       │  │
│ │   3. Austin, TX                                         │  │
│ │                                                         │  │
│ │ Metadata:                                              │  │
│ │   Jurisdictions Count: 3                               │  │
│ └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## JavaScript SDK Integration

### Function: scrapeMunicipalCodes()

This function is called when the "Start Scraping" button is clicked:

```javascript
async function scrapeMunicipalCodes() {
    // 1. Gather form data
    const jurisdictions = document.getElementById('municipal-jurisdictions').value
        .split(',').map(j => j.trim()).filter(j => j);
    
    const params = {
        jurisdictions: jurisdictions,
        provider: document.getElementById('municipal-provider').value,
        output_format: document.getElementById('municipal-output-format').value,
        rate_limit_delay: parseFloat(document.getElementById('municipal-rate-limit').value),
        // ... other parameters
    };
    
    // 2. Call MCP API
    const response = await fetch('/api/mcp/tools/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            tool_name: 'scrape_municipal_codes',
            parameters: params
        })
    });
    
    // 3. Display results
    const data = await response.json();
    displayResults(data);
}
```

### Function: clearMunicipalForm()

Resets all form fields to their default values:

```javascript
function clearMunicipalForm() {
    document.getElementById('municipal-jurisdictions').value = '';
    document.getElementById('municipal-provider').value = 'auto';
    document.getElementById('municipal-output-format').value = 'json';
    // ... reset other fields
    
    document.getElementById('municipal-results').innerHTML = `
        <div class="result-header">Form cleared</div>
        <div class="result-item">Ready to configure a new scraping job.</div>
    `;
}
```

## Testing with Playwright

### Test Execution Flow

The Playwright test (`tests/e2e/test_municipal_codes_functional.py`) performs these steps:

1. **Navigate to Dashboard**
   - Opens http://localhost:8899/mcp
   - Waits for page to load
   - Takes screenshot: `01_dashboard_loaded.png`

2. **Click Municipal Codes Tab**
   - Locates tab using `data-target="municipal-codes-scraper"`
   - Clicks the tab
   - Takes screenshot: `02_municipal_codes_tab.png`

3. **Verify Form Elements**
   - Checks for presence of all 10+ form elements
   - Validates input types and select options
   - Confirms all elements are interactive

4. **Fill Form with Test Data**
   - Enters jurisdictions: "Seattle, WA"
   - Selects provider: "municode"
   - Configures other parameters
   - Takes screenshot: `03_form_filled.png`

5. **Test Validation**
   - Clears jurisdictions field
   - Clicks "Start Scraping"
   - Verifies error message appears
   - Takes screenshot: `04_validation_error.png`

6. **Test Successful Submission**
   - Fills form with valid data
   - Clicks "Start Scraping"
   - Verifies results are displayed
   - Takes screenshot: `05_scraping_results.png`

7. **Test Clear Form**
   - Clicks "Clear Form" button
   - Verifies all fields are reset
   - Takes screenshot: `06_form_cleared.png`

### Running the Tests

```bash
# Install Playwright
pip install playwright
playwright install chromium

# Run the functional test
python tests/e2e/test_municipal_codes_functional.py

# Expected output:
# ======================================================================
# Municipal Codes Scraper Dashboard Integration Test
# ======================================================================
# 
# 🌐 Launching browser...
# 📍 Navigating to http://localhost:8899/mcp...
# ✓ Screenshot: Dashboard loaded
# 
# 🔍 Checking for Municipal Codes Scraper tab...
# ✓ Municipal Codes Scraper tab found
# 🖱️  Clicking Municipal Codes Scraper tab...
# ✓ Screenshot: Municipal Codes Scraper tab opened
# 
# ... (additional test output) ...
# 
# ✅ ALL TESTS COMPLETED SUCCESSFULLY
# 📸 Screenshots saved to: test_screenshots/
```

## API Integration

### MCP Tool Call Endpoint

The JavaScript makes requests to the MCP API endpoint:

```
POST /api/mcp/tools/call
Content-Type: application/json

{
    "tool_name": "scrape_municipal_codes",
    "parameters": {
        "jurisdictions": ["Seattle, WA", "Portland, OR"],
        "provider": "municode",
        "output_format": "json",
        "rate_limit_delay": 2.0,
        "scraper_type": "playwright",
        "include_metadata": true,
        "include_text": true
    }
}
```

### Expected Response

```json
{
    "status": "success",
    "result": {
        "status": "success",
        "job_id": "municipal_codes_20251017_022500",
        "message": "Municipal code scraping job initialized",
        "jurisdictions": ["Seattle, WA", "Portland, OR"],
        "provider": "municode",
        "scraper_type": "playwright",
        "output_format": "json",
        "scraper_path": "ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3",
        "note": "scrape_the_law_mk3 integration ready...",
        "data": [],
        "metadata": {
            "job_id": "municipal_codes_20251017_022500",
            "jurisdictions_count": 2,
            "parameters": { ... }
        }
    }
}
```

## Error Handling

### Validation Errors

When no jurisdictions are provided:

```
┌──────────────────────────────────────────┐
│ ✗ Error                                  │
│                                          │
│ Please specify at least one jurisdiction │
│ to scrape.                               │
└──────────────────────────────────────────┘
```

### API Errors

When the MCP server returns an error:

```
┌──────────────────────────────────────────┐
│ ✗ Error                                  │
│                                          │
│ scrape_the_law_mk3 module not available │
└──────────────────────────────────────────┘
```

### Network Errors

When the request fails:

```
┌──────────────────────────────────────────┐
│ ✗ Request Failed                         │
│                                          │
│ Error: Failed to fetch                   │
│ Please check the console for details.    │
└──────────────────────────────────────────┘
```

## Summary

The Municipal Codes Scraper is now fully integrated into the MCP Dashboard with:

✅ **Professional UI** - Matches existing dashboard design and patterns
✅ **Complete Form** - 11 configurable parameters with validation
✅ **JavaScript SDK** - Clean integration with MCP API
✅ **Real-time Results** - Structured display with success/error handling
✅ **Information Panel** - Educational content about coverage and capabilities
✅ **Playwright Tests** - Automated UI testing with screenshots
✅ **Error Handling** - Comprehensive validation and error messages

The integration follows all MCP dashboard conventions and provides a seamless user experience for scraping municipal legal codes from US cities and counties.
