# Enhanced Auto-Healing System - Complete Guide

## Overview

The Enhanced Auto-Healing System automatically detects workflow failures, creates issues with detailed diagnostics, and initiates automated fixes through GitHub Copilot. This system uses a "VS Code-style" approach where draft PRs are created immediately with @mentions to trigger GitHub Copilot agents.

## Key Features

### 🤖 Automated Workflow Failure Detection
- Monitors all configured GitHub Actions workflows
- Detects failures in real-time
- Analyzes logs to identify root causes
- Generates fix proposals with high confidence scores

### 📝 Intelligent Issue Creation
- Creates detailed issues with:
  - Failure analysis and root cause
  - Complete log excerpts
  - Affected files
  - Recommended fixes
  - Quality metrics and diagnostics

### 🌿 Automatic Branch & PR Creation
- Creates feature branches automatically
- Generates draft PRs with comprehensive context
- Links issues and PRs automatically
- Assigns appropriate labels for tracking

### 🤖 GitHub Copilot Integration
- @mentions GitHub Copilot in draft PRs
- Provides structured context for AI analysis
- Enables automated fix implementation
- Supports iterative improvements

## Architecture

### 1. Comprehensive Scraper Validation Workflow
**File**: `.github/workflows/comprehensive-scraper-validation.yml`

**Triggers**:
- Manual dispatch (workflow_dispatch)
- Scheduled (weekly on Sundays at 3 AM UTC)
- On push to main/develop for scraper-related files

**Process**:
1. Runs scraper validation tests
2. Validates schema compliance
3. Checks HuggingFace dataset compatibility
4. Measures data quality scores
5. On failure:
   - Creates detailed issue with validation summary
   - Creates a new branch for fixes
   - Creates draft PR with @copilot mention
   - Uploads validation artifacts

**Key Validations**:
- ✅ Scraper execution success
- ✅ Data production (non-empty results)
- ✅ Schema validation (required fields present)
- ✅ HuggingFace compatibility
- ✅ Data quality score (>= 50/100)

### 2. Copilot Agent Auto-Fix Workflow
**File**: `.github/workflows/copilot-agent-autofix.yml`

**Triggers**:
- Automatically on workflow_run completion (for configured workflows)
- Manual dispatch for specific workflow runs

**Process**:
1. Detects workflow failures
2. Downloads and analyzes failure logs
3. Identifies error patterns and root causes
4. Generates fix proposals
5. Creates issue with detailed analysis
6. Creates branch and draft PR
7. @mentions GitHub Copilot with fix instructions

**Supported Error Types**:
- Dependency errors (missing packages)
- Syntax errors
- Test failures
- Timeout issues
- Permission errors
- Network errors
- Docker errors
- Resource exhaustion
- Missing environment variables

## Workflows Monitored

The auto-healing system monitors these workflows:
- ARM64 Self-Hosted Runner
- Docker Build and Test
- Documentation Maintenance
- GPU-Enabled Tests
- GraphRAG Production CI/CD
- MCP Dashboard Automated Tests
- MCP Endpoints Integration Tests
- PDF Processing Pipeline CI/CD
- Self-Hosted Runner Test
- And more...

## How It Works

### Example: Scraper Validation Failure

```mermaid
graph TD
    A[Scraper Validation Runs] --> B{All Validations Pass?}
    B -->|Yes| C[Workflow Success ✅]
    B -->|No| D[Create Issue with Details]
    D --> E[Create Fix Branch]
    E --> F[Create Draft PR]
    F --> G[@mention GitHub Copilot]
    G --> H[Copilot Analyzes Failure]
    H --> I[Copilot Implements Fix]
    I --> J[Auto Tests Run]
    J --> K{Tests Pass?}
    K -->|Yes| L[Ready for Review]
    K -->|No| H
    L --> M[Manual Review & Merge]
```

### Example: General Workflow Failure

```mermaid
graph TD
    A[Workflow Fails] --> B[Auto-Fix Triggered]
    B --> C[Download Logs]
    C --> D[Analyze Error Patterns]
    D --> E[Generate Fix Proposal]
    E --> F[Create Issue]
    F --> G[Create Branch & Draft PR]
    G --> H[@mention Copilot with Context]
    H --> I[Copilot Implements Fix]
    I --> J[Tests Verify Fix]
    J --> K[Manual Review & Merge]
```

## Configuration

### Excluding Workflows

To exclude specific workflows from auto-healing:

Edit `.github/workflows/workflow-auto-fix-config.yml`:

```yaml
excluded_workflows:
  - "Workflow Name to Exclude"
  - "Another Workflow to Skip"
```

### Required Permissions

The workflows require these GitHub permissions:

```yaml
permissions:
  contents: write        # For creating branches and commits
  pull-requests: write   # For creating PRs and comments
  issues: write          # For creating and updating issues
  actions: read          # For reading workflow run data
```

### Required Secrets

- `GITHUB_TOKEN` - Automatically provided by GitHub Actions

## Usage

### Manual Trigger for Scraper Validation

```bash
# Via GitHub CLI
gh workflow run comprehensive-scraper-validation.yml \
  -f domain=all

# For specific domain
gh workflow run comprehensive-scraper-validation.yml \
  -f domain=caselaw
```

### Manual Trigger for Auto-Fix

```bash
# Fix latest failure for a specific workflow
gh workflow run copilot-agent-autofix.yml \
  -f workflow_name="Docker Build and Test"

# Fix specific run
gh workflow run copilot-agent-autofix.yml \
  -f run_id=12345678
```

### Viewing Results

1. **Check Issues**: Look for issues tagged with:
   - `automated`
   - `scraper-validation` or `workflow-failure`
   - `auto-healing`

2. **Check Draft PRs**: Look for PRs tagged with:
   - `automated-fix`
   - `copilot-ready`
   - `scraper-validation` or `workflow-fix`

3. **Review Artifacts**: Download artifacts from workflow runs for:
   - Detailed validation reports
   - Log analysis
   - Fix proposals

## GitHub Copilot Integration

### How @mentions Work

When the auto-healing system creates a draft PR, it:

1. Creates a structured PR description with:
   - Issue reference
   - Failure analysis
   - Proposed fixes
   - Context and recommendations

2. Adds a comment with `@copilot /fix` followed by:
   - Specific instructions
   - Focus areas
   - References to artifacts

3. GitHub Copilot responds by:
   - Analyzing the issue and logs
   - Implementing proposed fixes
   - Running tests to verify
   - Updating the PR with changes

### Copilot Commands

The system uses these Copilot slash commands:

- `@copilot /fix` - Implements fixes based on analysis
- Context provided includes:
  - Root cause analysis
  - Error patterns
  - Recommended fixes
  - Affected files

## Monitoring & Maintenance

### Health Metrics

Track these metrics for system health:

- **Auto-fix success rate**: PRs successfully merged / total PRs created
- **Time to fix**: Time from failure detection to merge
- **Confidence scores**: Average confidence in generated fixes
- **False positives**: Issues created for non-fixable failures

### Log Locations

- **Workflow Summaries**: GitHub Actions summary page
- **Artifacts**: Downloaded from workflow run artifacts
- **Issues**: Repository issues with `automated` label
- **PRs**: Repository pull requests with `automated-fix` label

### Troubleshooting

**Issue: Draft PR not created**
- Check workflow permissions
- Verify GITHUB_TOKEN has necessary scopes
- Review workflow logs for errors

**Issue: Copilot not responding**
- Ensure @copilot mention is in PR comment
- Check that PR is in draft state
- Verify Copilot is enabled for repository

**Issue: Fixes not working**
- Review confidence score in analysis
- Check if error pattern is supported
- May require manual intervention for complex issues

## Best Practices

### For Repository Maintainers

1. **Review Auto-Generated PRs**: Always review before merging
2. **Update Patterns**: Add new error patterns to analysis scripts as needed
3. **Monitor Metrics**: Track success rates and improve patterns
4. **Test Changes**: Ensure auto-fix doesn't introduce regressions

### For Contributors

1. **Check Existing Issues**: Auto-healing may have already created an issue
2. **Review Draft PRs**: Copilot may have proposed fixes
3. **Provide Feedback**: Comment on auto-generated PRs to improve them
4. **Report Gaps**: If auto-healing misses a pattern, report it

## Examples

### Example 1: Scraper Validation Failure

**Scenario**: US Code scraper fails schema validation

**Auto-Healing Actions**:
1. Issue created: "🚨 Scraper Validation Failed - Action Required"
2. Details include: Missing required fields (title, text)
3. Branch created: `autofix/scraper-validation-20251030-060320`
4. Draft PR created with @copilot mention
5. Copilot analyzes and adds required fields to scraper
6. Tests run automatically
7. PR ready for review

### Example 2: Dependency Error

**Scenario**: Workflow fails with `ModuleNotFoundError: No module named 'datasets'`

**Auto-Healing Actions**:
1. Error pattern identified: Missing Dependency
2. Fix proposal: Add 'datasets' to requirements.txt
3. Issue created with analysis (90% confidence)
4. Branch and PR created
5. Copilot adds dependency
6. PR ready for review

### Example 3: Timeout Error

**Scenario**: Test workflow times out

**Auto-Healing Actions**:
1. Error pattern: Timeout
2. Fix proposal: Increase timeout-minutes to 30
3. Issue and PR created
4. Copilot modifies workflow YAML
5. PR ready for review

## Advanced Features

### Duplicate Detection

The system prevents duplicate processing:
- Checks for existing PRs referencing the same run ID
- Updates existing issues instead of creating duplicates
- Avoids redundant fix attempts

### Fix Confidence Scoring

Each fix proposal includes a confidence score:
- **90-100%**: High confidence, likely auto-mergeable
- **70-89%**: Good confidence, review recommended
- **50-69%**: Medium confidence, careful review needed
- **<50%**: Low confidence, manual fix likely needed

### Multi-Domain Support

Scraper validation supports multiple domains:
- **Caselaw**: Legal documents, statutes, case law
- **Finance**: Stock data, financial news
- **Medicine**: Research papers, clinical trials  
- **Software**: GitHub repositories, documentation

Each domain has specific schema requirements and validators.

## Future Enhancements

Planned improvements:
- [ ] Machine learning for error pattern recognition
- [ ] Auto-merge for high-confidence fixes
- [ ] Metrics dashboard for tracking system performance
- [ ] Integration with more CI/CD tools
- [ ] Support for custom fix patterns
- [ ] Rollback capabilities for failed auto-fixes

## Support

For issues or questions:
1. Check existing issues with `automated` label
2. Review workflow run logs and artifacts
3. Create an issue with details about the failure
4. Tag maintainers for assistance

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [GitHub Copilot Documentation](https://docs.github.com/en/copilot)
- [Workflow Configuration Guide](/.github/workflows/workflow-auto-fix-config.yml)
- [Analysis Scripts](/.github/scripts/)
