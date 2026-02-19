# Architecture Validation Quick Start Guide

**Purpose:** Guide for running architecture validation and interpreting results

---

## 📁 Validation Artifacts

### Generated Files

| File | Type | Size | Purpose |
|------|------|------|---------|
| `architecture_validation_script.py` | Script | 15K | Automated validator |
| `architecture_validation_report.json` | Data | 15K | Machine-readable results |
| `architecture_validation_detailed.json` | Data | 202K | Per-tool analysis |
| `ARCHITECTURE_VALIDATION_REPORT.md` | Doc | 17K | Comprehensive report |
| `CLI_MCP_ALIGNMENT_ANALYSIS.md` | Doc | 16K | Interface analysis |
| `PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | Doc | 18K | Executive summary |

**Total Artifacts:** 6 files, 283K of validation documentation

---

## 🚀 Running the Validator

### Basic Usage

```bash
# Run from repository root
cd /home/runner/work/ipfs_datasets_py/ipfs_datasets_py

# Execute validation
python architecture_validation_script.py
```

### Expected Output

```
🔍 Starting architecture validation for Phase 2...
   Scanning ipfs_datasets_py/mcp_server/tools/

Scanning 311 tool files...
✓ JSON report saved to architecture_validation_report.json
✓ Detailed results saved to architecture_validation_detailed.json

================================================================================
ARCHITECTURE VALIDATION REPORT - PHASE 2
================================================================================

📊 OVERALL STATISTICS
   Total tools analyzed: 311
   Compliance score: 20.3%
   ✓ Compliant: 63
   ⚠ Needs attention: 248
   
[... detailed output ...]
```

### Exit Codes

- `0` - Validation passed (compliance ≥60%)
- `1` - Validation failed (compliance <60%)

---

## 📊 Interpreting Results

### Compliance Levels

| Level | Icon | Meaning | Action Needed |
|-------|------|---------|---------------|
| **Exemplary** | ⭐ | Perfect thin wrapper | None - use as template |
| **Compliant** | ✓ | Acceptable with minor issues | Low priority fixes |
| **Needs Review** | ⚠️ | Approaching limits | Medium priority |
| **Needs Refactoring** | ❌ | Exceeds standards | High priority |

### Compliance Score Interpretation

| Score | Status | Meaning |
|-------|--------|---------|
| **90-100%** | 🟢 Excellent | Phase 2 complete |
| **70-89%** | 🟡 Good | Close to completion |
| **50-69%** | 🟠 Marginal | Significant work needed |
| **0-49%** | 🔴 Poor | Major refactoring required |

**Current Score:** 20.3% 🔴 (Major refactoring required)

### Issue Severity

**Critical Issues (Must Fix):**
- Exceeds maximum line count (>200 lines)
- Missing imports from core modules
- No error handling

**Important Issues (Should Fix):**
- Exceeds acceptable line count (>150 lines)
- Missing module docstring
- High complexity score

**Minor Issues (Nice to Fix):**
- Docstring doesn't explain core module usage

---

## 📖 Reading the Reports

### 1. JSON Report (`architecture_validation_report.json`)

**Structure:**
```json
{
  "summary": {
    "total_tools": 311,
    "compliance_score": 20.26,
    "by_level": { ... },
    "compliant_count": 63,
    "needs_attention_count": 248
  },
  "category_statistics": { ... },
  "top_issues": [ ... ],
  "thick_tools": [ ... ],
  "exemplary_tools": [ ... ]
}
```

**Use Cases:**
- Automated CI/CD checks
- Trend analysis over time
- Dashboard visualization
- Script integration

### 2. Detailed JSON (`architecture_validation_detailed.json`)

**Structure:**
```json
[
  {
    "file_path": "ipfs_datasets_py/mcp_server/tools/graph_tools/graph_create.py",
    "category": "graph_tools",
    "line_count": 33,
    "has_core_imports": true,
    "core_modules_used": ["ipfs_datasets_py.core_operations"],
    "has_docstring": true,
    "docstring_mentions_core": true,
    "has_error_handling": true,
    "complexity_score": 15.2,
    "compliance_issues": [],
    "compliance_level": "exemplary"
  },
  ...
]
```

**Use Cases:**
- Per-tool analysis
- Tracking individual tool improvements
- Identifying patterns in violations
- Targeted refactoring

### 3. Architecture Report (`ARCHITECTURE_VALIDATION_REPORT.md`)

**Sections:**
1. Executive Summary - High-level findings
2. Compliance Statistics - Numbers and trends
3. Top 20 Thick Tools - Priority refactoring targets
4. Top 10 Exemplary Tools - Best practice examples
5. Category Performance - Category-level analysis
6. ADRs - Architectural decisions
7. Recommendations - Actionable next steps

**Audience:** Developers, architects, project managers

### 4. CLI/MCP Alignment (`CLI_MCP_ALIGNMENT_ANALYSIS.md`)

**Sections:**
1. Interface Overview - MCP vs CLI comparison
2. Coverage Analysis - Gap identification
3. Parameter Mapping - Consistency issues
4. Core Module Verification - Shared usage
5. Error Handling - Format differences
6. Recommendations - Alignment improvements

**Audience:** CLI developers, integration teams

### 5. Executive Summary (`PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md`)

**Sections:**
1. Overall Compliance Score - 20.3%
2. Key Findings - Top issues and patterns
3. ADRs - Architectural decisions
4. Refactoring Roadmap - 8-week plan
5. Success Metrics - Tracking progress
6. Phase 3 Readiness - Blockers and requirements

**Audience:** Management, architects, stakeholders

---

## 🎯 Common Workflows

### Weekly Compliance Tracking

```bash
# Run validation
python architecture_validation_script.py

# Extract score
SCORE=$(grep '"compliance_score"' architecture_validation_report.json | awk '{print $2}' | tr -d ',')

# Log to tracking file
echo "$(date +%Y-%m-%d),$SCORE" >> compliance_tracking.csv

# Generate trend chart (requires matplotlib)
python scripts/generate_compliance_trend.py
```

### Finding Tools to Refactor

```bash
# List all tools needing refactoring
python -c "
import json
with open('architecture_validation_detailed.json') as f:
    data = json.load(f)
    needs_refactor = [t for t in data if t['compliance_level'] == 'needs_refactoring']
    for tool in sorted(needs_refactor, key=lambda x: x['line_count'], reverse=True)[:20]:
        print(f\"{tool['line_count']:4d} lines - {tool['file_path'].split('/')[-1]}\")
"
```

### Checking a Specific Category

```bash
# Get compliance for a specific category
python -c "
import json
category = 'graph_tools'
with open('architecture_validation_detailed.json') as f:
    data = json.load(f)
    tools = [t for t in data if t['category'] == category]
    compliant = len([t for t in tools if t['compliance_level'] in ['exemplary', 'compliant']])
    print(f'{category}: {compliant}/{len(tools)} ({compliant/len(tools)*100:.1f}%)')
"
```

### Validating a Single Tool

```bash
# Quick check of a specific tool
python -c "
import json
import sys
tool_name = sys.argv[1]
with open('architecture_validation_detailed.json') as f:
    data = json.load(f)
    tool = next((t for t in data if tool_name in t['file_path']), None)
    if tool:
        print(f\"Tool: {tool['file_path'].split('/')[-1]}\")
        print(f\"Lines: {tool['line_count']}\")
        print(f\"Level: {tool['compliance_level']}\")
        print(f\"Issues: {', '.join(tool['compliance_issues']) if tool['compliance_issues'] else 'None'}\")
    else:
        print(f'Tool {tool_name} not found')
" graph_create.py
```

---

## 🛠️ Integration with CI/CD

### GitHub Actions

```yaml
name: Architecture Validation

on:
  pull_request:
    paths:
      - 'ipfs_datasets_py/mcp_server/tools/**'
  schedule:
    - cron: '0 0 * * 1'  # Weekly on Monday

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run Architecture Validation
        run: python architecture_validation_script.py
        
      - name: Check Compliance Score
        run: |
          SCORE=$(grep '"compliance_score"' architecture_validation_report.json | awk '{print $2}' | tr -d ',')
          echo "Compliance Score: $SCORE%"
          
          # Fail if score drops below threshold
          if (( $(echo "$SCORE < 60" | bc -l) )); then
            echo "❌ Compliance score below 60%"
            exit 1
          fi
          
      - name: Upload Reports
        uses: actions/upload-artifact@v3
        with:
          name: validation-reports
          path: |
            architecture_validation_*.json
            ARCHITECTURE_*.md
            CLI_MCP*.md
```

### Pre-commit Hook

```bash
# .git/hooks/pre-commit
#!/bin/bash

# Only run if tool files changed
if git diff --cached --name-only | grep -q "ipfs_datasets_py/mcp_server/tools/"; then
  echo "🔍 Running architecture validation on changed tools..."
  python architecture_validation_script.py --quiet
  
  if [ $? -ne 0 ]; then
    echo "❌ Architecture validation failed. See report for details."
    exit 1
  fi
  
  echo "✅ Architecture validation passed"
fi
```

---

## 📈 Tracking Progress

### Compliance Trend Over Time

Create `compliance_tracking.csv`:
```csv
date,score
2024-02-19,20.3
2024-02-26,35.2
2024-03-04,52.8
2024-03-11,68.5
2024-03-18,82.1
2024-03-25,91.3
```

### Key Metrics to Track

1. **Overall Compliance Score**
   - Target: 95%+
   - Current: 20.3%
   - Weekly improvement: +10-15%

2. **Tools by Level**
   - Exemplary: 15 → 250+
   - Needs refactoring: 152 → <15

3. **Category Performance**
   - 0% compliance categories: 5 → 0
   - 100% compliance categories: 1 → 30+

4. **Issue Counts**
   - Line count violations: 152 → <15
   - Missing core imports: 139 → 0
   - Missing docstrings: 75 → 0

---

## 🔧 Customizing the Validator

### Adjusting Thresholds

Edit `architecture_validation_script.py`:

```python
# Line count thresholds
self.IDEAL_LINE_COUNT = 100      # Change to 80 for stricter
self.ACCEPTABLE_LINE_COUNT = 150  # Change to 120 for stricter
self.MAX_LINE_COUNT = 200         # Change to 150 for stricter

# Complexity threshold
if complexity_score > 30:  # Change to 20 for stricter
    issues.append(...)
```

### Adding Custom Checks

```python
def check_custom_pattern(self, content: str) -> bool:
    """Check for custom architectural pattern."""
    # Example: Check for async/await usage
    has_async = 'async def' in content
    has_await = 'await ' in content
    return has_async and has_await

# In analyze_tool_file:
has_async_await = self.check_custom_pattern(content)
if not has_async_await:
    compliance_issues.append("Missing async/await pattern")
```

---

## 🎓 Best Practices

### For Tool Developers

1. **Run validation before committing:**
   ```bash
   python architecture_validation_script.py
   ```

2. **Use exemplary tools as templates:**
   - Copy from `graph_tools/graph_*.py`
   - Follow the thin wrapper pattern
   - Keep under 100 lines

3. **Always reference core modules:**
   ```python
   """
   This is a thin wrapper around CoreModule.
   Core implementation: ipfs_datasets_py.module.class
   """
   ```

4. **Check your tool's compliance:**
   ```bash
   grep "your_tool.py" architecture_validation_detailed.json
   ```

### For Code Reviewers

1. **Check compliance in PR:**
   - Run validator on PR branch
   - Compare score to main branch
   - Reject if score decreases

2. **Verify new tools are compliant:**
   - <150 lines
   - Has core module imports
   - Has proper docstring
   - Has error handling

3. **Prioritize refactoring:**
   - Focus on >500 line tools first
   - One category at a time
   - Use exemplary tools as targets

---

## 📚 Additional Resources

### Documentation
- `ARCHITECTURE_VALIDATION_REPORT.md` - Full analysis
- `CLI_MCP_ALIGNMENT_ANALYSIS.md` - Interface parity
- `PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` - Executive overview

### Example Code
- `ipfs_datasets_py/mcp_server/tools/graph_tools/` - Exemplary thin wrappers
- Pattern: Import → Delegate → Return with error handling

### Related Scripts
- `architecture_validation_script.py` - Main validator
- CI/CD workflows in `.github/workflows/`

---

## 🆘 Troubleshooting

### Script Fails to Run

**Error:** `ModuleNotFoundError: No module named 'ipfs_datasets_py'`

**Solution:** Run from repository root:
```bash
cd /home/runner/work/ipfs_datasets_py/ipfs_datasets_py
python architecture_validation_script.py
```

### Low Compliance Score

**Problem:** Score is 20.3%, expected higher

**Explanation:** This is the baseline. Refactoring campaign needed.

**Solution:** Follow the 8-week roadmap in `PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md`

### Tool Shows Wrong Category

**Problem:** Tool in wrong category in report

**Solution:** Move tool file to correct category directory:
```bash
mv ipfs_datasets_py/mcp_server/tools/tool.py \
   ipfs_datasets_py/mcp_server/tools/correct_category/
```

---

## ✅ Validation Checklist

Before committing tool changes:

- [ ] Run `python architecture_validation_script.py`
- [ ] Check your tool in `architecture_validation_detailed.json`
- [ ] Verify compliance level is "exemplary" or "compliant"
- [ ] Confirm line count <150 (ideally <100)
- [ ] Has imports from `ipfs_datasets_py.*`
- [ ] Has module docstring referencing core module
- [ ] Has proper error handling
- [ ] No embedded business logic

---

**Quick Start Guide Version:** 1.0  
**Last Updated:** February 19, 2024  
**Maintained By:** Architecture Team
