# Documentation Maintenance Workflow

## Overview

This GitHub Actions workflow provides **automated, weekly maintenance** of documentation across the `ipfs_datasets_py` repository. Unlike passive monitoring tools, this workflow **actively maintains** documentation by creating missing files, generating templates, and opening pull requests with fixes.

## Schedule

- **Frequency**: Every Monday at 9:00 AM UTC (with auto-fix enabled by default)
- **Manual Trigger**: Can be triggered manually via GitHub Actions UI with optional parameters

## What It Does

The workflow performs comprehensive documentation health checks **and automatically fixes issues**:

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
- **🔧 AUTO-FIX**: Creates missing documentation files with templates

### 4. Documentation Freshness Analysis
- Finds documentation files not updated in the last 90 days
- Helps identify potentially outdated or stale documentation
- Ensures documentation stays current with code changes

### 5. Documentation Consistency Checks
- Validates that main README references all major subdirectories
- Ensures documentation hierarchy is properly maintained
- Identifies documentation gaps and inconsistencies

### 6. Automated Fixes & Reporting
- **🤖 AUTO-FIX**: Creates missing README.md, TODO.md, and CHANGELOG.md files
- **📝 PULL REQUESTS**: Opens PRs with auto-generated documentation files
- Creates comprehensive health reports combining all audit results
- Generates actionable recommendations for improvements
- Creates or updates GitHub issues with findings
- Uploads detailed reports as workflow artifacts (retained for 30 days)

## Auto-Fix Capabilities

When auto-fix is enabled (default for scheduled runs), the workflow will:

### Missing README.md Files
Creates basic README files with:
- Module/directory name as title
- Overview section
- Contents section (to be filled in)
- Usage section (to be filled in)
- Links to related documentation

### Missing TODO.md Files
Creates task tracking files with:
- Pending tasks section with common documentation tasks
- Completed tasks section
- Last updated timestamp

### Missing CHANGELOG.md Files
Creates version history files with:
- Standard changelog format
- Unreleased section
- Initial structure with timestamps

**Note**: All auto-generated files include placeholder text marked for customization.

## Outputs

### Pull Requests (Auto-Fix Enabled)
When missing documentation is detected and auto-fix is enabled, the workflow creates a PR:
- **Branch**: `docs/auto-maintenance-{run_number}`
- **Title**: "docs: Auto-generate missing documentation files"
- **Labels**: `documentation`, `automated`, `maintenance`
- **Assignee**: Repository owner
- **Content**: All newly created documentation files with templates

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
- **auto_fix** (boolean, default: true) - Automatically create missing documentation files and open a PR

### To Run Manually:
1. Go to the repository's Actions tab
2. Select "Documentation Maintenance" workflow
3. Click "Run workflow"
4. Choose branch and set parameters:
   - Enable/disable `auto_fix` to control whether PRs are created
   - Enable/disable `full_scan` to control scan depth
5. Click "Run workflow" button

## Workflow Behavior

### Scheduled Runs (Weekly)
- **Auto-fix**: Enabled by default
- **Action**: Creates PR with missing documentation files
- **Notifications**: Creates/updates GitHub issue with report

### Manual Runs
- **Auto-fix**: Configurable (default: true)
- **Action**: Behavior depends on auto_fix parameter
- **Use Case**: Test changes or generate reports without creating PRs (set auto_fix=false)

### What Gets Fixed Automatically
✅ Missing README.md files  
✅ Missing TODO.md files  
✅ Missing CHANGELOG.md files  

### What Requires Manual Action
⚠️ Docstring improvements (identified in reports)  
⚠️ Stale documentation updates (flagged in reports)  
⚠️ Content quality improvements (templates need customization)  
⚠️ Consistency fixes (cross-references need manual validation)

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

This workflow is specifically designed to help AI agents (like Claude, GPT, etc.) **actively maintain** documentation:

### Key Features for AI Agents:
- **Automated Fixes**: Missing documentation files are created automatically
- **Pull Request Integration**: Changes are submitted via PR for review
- **Structured JSON Reports**: Machine-readable output for automated processing
- **Comprehensive Metadata**: Timestamps, paths, and quality metrics for decision-making
- **Issue Tracking**: Automated GitHub issues provide a queue of documentation tasks
- **Template-Based Generation**: Consistent structure across all auto-generated files

### Using the Workflow as an AI Agent:
1. **Monitor PRs**: Check for auto-generated documentation PRs
2. **Review Templates**: Examine auto-generated files and customize them
3. **Parse Reports**: Download and analyze JSON artifacts for insights
4. **Prioritize Tasks**: Use quality scores from reports to focus efforts
5. **Coordinate Work**: Reference PRs and issues for documentation improvements

## Maintenance and Evolution

### Completed Features:
- [x] ✅ Automatic creation of missing documentation file stubs
- [x] ✅ Automated PR creation for simple fixes
- [x] ✅ Template-based file generation with consistent structure
- [x] ✅ Weekly scheduled automated maintenance

### Future Enhancements:
- [ ] Link validation (checking for broken internal links)
- [ ] Code-to-documentation synchronization checks
- [ ] Documentation coverage metrics and trends over time
- [ ] Integration with code quality metrics
- [ ] Documentation diff analysis between versions
- [ ] Automated docstring generation for undocumented functions
- [ ] Smart content suggestions based on code analysis

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
