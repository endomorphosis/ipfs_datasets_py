# Documentation Maintenance Workflow

## Overview

This GitHub Actions workflow provides automated, weekly maintenance of documentation across the `ipfs_datasets_py` repository to ensure that both human users and AI programming agents have access to current, complete, and consistent documentation.

## Schedule

- **Frequency**: Every Monday at 9:00 AM UTC
- **Manual Trigger**: Can be triggered manually via GitHub Actions UI with optional parameters

## What It Does

The workflow performs comprehensive documentation health checks including:

### 1. Documentation Discovery
- Scans the entire repository for documentation files (README.md, TODO.md, CHANGELOG.md)
- Records last modification times and file metadata
- Generates a complete inventory of documentation assets

### 2. Docstring Quality Audit
- Analyzes Python source files for docstring completeness
- Identifies classes and functions lacking comprehensive documentation
- Generates quality scores and recommendations
- Highlights high-priority files needing documentation enhancement

### 3. Missing Documentation Detection
- Identifies subdirectories lacking standard documentation files
- Reports which directories need README.md, TODO.md, or CHANGELOG.md
- Helps maintain consistent documentation structure across the project

### 4. Documentation Freshness Analysis
- Finds documentation files not updated in the last 90 days
- Helps identify potentially outdated or stale documentation
- Ensures documentation stays current with code changes

### 5. Documentation Consistency Checks
- Validates that main README references all major subdirectories
- Ensures documentation hierarchy is properly maintained
- Identifies documentation gaps and inconsistencies

### 6. Automated Reporting
- Creates comprehensive health reports combining all audit results
- Generates actionable recommendations for improvements
- Creates or updates GitHub issues with findings
- Uploads detailed reports as workflow artifacts (retained for 30 days)

## Outputs

### GitHub Issues
The workflow automatically creates or updates a GitHub issue titled:
```
Weekly Documentation Health Report - YYYY-MM-DD
```

This issue includes:
- Summary of findings
- List of directories missing documentation
- Stale documentation files
- Consistency issues
- Docstring quality analysis
- Actionable recommendations

Issues are tagged with: `documentation`, `automated`, `maintenance`

### Workflow Artifacts
The following artifacts are uploaded and retained for 30 days:
- `documentation_health_report.md` - Comprehensive HTML-formatted report
- `documentation_report.json` - Detailed JSON data from documentation finder
- `docstring_report.json` - Detailed docstring analysis results
- `missing_docs_report.md` - List of directories missing documentation
- `stale_docs_report.md` - List of outdated documentation files
- `consistency_report.md` - Documentation consistency findings

### Job Summary
A summary is automatically added to the GitHub Actions run summary page showing:
- Key metrics and statistics
- Major findings
- Links to detailed reports
- Recommendations

## Manual Execution

You can manually trigger this workflow from the Actions tab with optional parameters:

### Parameters:
- **full_scan** (boolean, default: true) - Perform a complete documentation scan
- **auto_fix** (boolean, default: false) - Automatically fix simple documentation issues (future enhancement)

### To Run Manually:
1. Go to the repository's Actions tab
2. Select "Documentation Maintenance" workflow
3. Click "Run workflow"
4. Choose branch and set parameters
5. Click "Run workflow" button

## Integration with Existing Tools

This workflow leverages existing adhoc tools:
- `adhoc_tools/find_documentation.py` - Discovers and catalogs documentation files
- `adhoc_tools/docstring_audit.py` - Analyzes docstring quality and completeness

These tools follow the standardized adhoc tool template and can also be run manually:

```bash
# Find all documentation files
python adhoc_tools/find_documentation.py --directory . --format json

# Audit docstring quality
python adhoc_tools/docstring_audit.py --directory ipfs_datasets_py --output report.json
```

## For AI Programming Agents

This workflow is specifically designed to help AI agents (like Claude, GPT, etc.) maintain documentation awareness:

### Key Features for AI Agents:
- **Structured JSON Reports**: Machine-readable output for automated processing
- **Comprehensive Metadata**: Timestamps, paths, and quality metrics for decision-making
- **Issue Tracking**: Automated GitHub issues provide a queue of documentation tasks
- **Consistency Validation**: Ensures documentation structure matches code structure

### Using Reports as an AI Agent:
1. Check the most recent workflow run artifacts
2. Download and parse JSON reports for structured data
3. Review the GitHub issue for human-readable summary
4. Prioritize documentation tasks based on:
   - Missing critical documentation (README.md)
   - Low docstring quality scores
   - Stale documentation (not updated in 90+ days)
   - Consistency issues with main documentation

## Maintenance and Evolution

### Future Enhancements:
- [ ] Automatic creation of missing documentation file stubs
- [ ] Link validation (checking for broken internal links)
- [ ] Code-to-documentation synchronization checks
- [ ] Documentation coverage metrics and trends
- [ ] Automated PR creation for simple fixes
- [ ] Integration with code quality metrics
- [ ] Documentation diff analysis between versions

### Contributing:
To improve this workflow:
1. Edit `.github/workflows/documentation-maintenance.yml`
2. Test changes using workflow_dispatch (manual trigger)
3. Review job summaries and artifacts
4. Submit PR with improvements

## Permissions

This workflow requires:
- `contents: write` - To checkout repository and potentially commit fixes
- `pull-requests: write` - To create PRs with documentation updates (future)
- `issues: write` - To create and update documentation health issues

## Dependencies

- Python 3.10+
- PyYAML (for YAML parsing)
- pathlib (for path manipulation)
- Standard library modules (os, sys, json, datetime, etc.)

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Worker coordination and documentation standards
- [TODO.md](../../TODO.md) - Project-wide task tracking
- [CHANGELOG.md](../../CHANGELOG.md) - Project history
- [adhoc_tools/README.md](../../adhoc_tools/README.md) - Adhoc tools documentation

## Support

For issues or questions about this workflow:
1. Check the most recent workflow run logs
2. Review generated issues for common problems
3. Open an issue with the `documentation` and `github-actions` labels
