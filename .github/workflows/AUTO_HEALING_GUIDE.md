# Auto-Healing System - Complete Guide

## Overview

The Auto-Healing System automatically detects workflow failures across **ALL workflows** in the repository, creates detailed issue reports with logs, and generates draft Pull Requests that GitHub Copilot Coding Agent works on automatically.

**Key Feature**: Human intervention is only required for reviewing and merging the final PR - everything else is automated!

## How It Works

### 1. Automatic Failure Detection
- **Monitors**: ALL workflows in the repository (currently 16 workflows)
- **Triggers**: Automatically when any monitored workflow fails
- **Scope**: Every workflow except auto-healing workflows themselves

### 2. Issue Creation (Fully Automated)
When a workflow fails, the system automatically:
1. Downloads and analyzes the failure logs
2. Identifies error patterns and root causes
3. Creates a comprehensive issue with:
   - Workflow failure details
   - Run ID and links
   - Error analysis
   - Log excerpts
   - Fix recommendations

### 3. Draft PR Creation (Fully Automated)
After creating the issue, the system:
1. Creates a new branch for the fix
2. Generates a draft Pull Request linked to the issue
3. Includes detailed failure analysis in the PR
4. Mentions `@copilot` with `/fix` command to trigger the Coding Agent

### 4. Copilot Implementation (Fully Automated)
GitHub Copilot Coding Agent automatically:
1. Reads the issue and PR description
2. Analyzes the workflow failure
3. Implements fixes in the draft PR
4. Commits changes to the branch
5. Updates the PR when ready for review

### 5. Human Review (Only Manual Step)
You only need to:
1. Review the PR created by Copilot
2. Verify the fixes are correct
3. Merge the PR when satisfied

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Workflow Fails                           │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│         Copilot Agent Auto-Healing Workflow                 │
│         (copilot-agent-autofix.yml)                         │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
        ┌───────────────────┴───────────────────┐
        ↓                                       ↓
┌──────────────────┐                  ┌──────────────────┐
│ Check Duplicate  │                  │  Get Run Details │
│ Processing       │                  │  - Workflow name │
└────────┬─────────┘                  │  - Run ID        │
         ↓                             │  - Branch/SHA    │
    Skip if already                    └────────┬─────────┘
    processed                                   ↓
                                      ┌──────────────────┐
                                      │ Download & Parse │
                                      │ Failure Logs     │
                                      └────────┬─────────┘
                                               ↓
                                      ┌──────────────────┐
                                      │ Analyze Failure  │
                                      │ - Pattern match  │
                                      │ - Root cause     │
                                      │ - Confidence     │
                                      └────────┬─────────┘
                                               ↓
                                      ┌──────────────────┐
                                      │ Generate Fix     │
                                      │ Proposal         │
                                      └────────┬─────────┘
                                               ↓
                        ┌──────────────────────┴──────────────────────┐
                        ↓                                             ↓
              ┌──────────────────┐                          ┌──────────────────┐
              │  Create Issue    │                          │ Create Branch    │
              │  with Logs       │                          │ & Draft PR       │
              └────────┬─────────┘                          └────────┬─────────┘
                       │                                             │
                       └──────────────────┬──────────────────────────┘
                                          ↓
                                ┌──────────────────┐
                                │ @copilot /fix    │
                                │ Comment in PR    │
                                └────────┬─────────┘
                                         ↓
                      ┌──────────────────────────────────┐
                      │ GitHub Copilot Coding Agent      │
                      │ - Analyzes issue & PR            │
                      │ - Implements fixes               │
                      │ - Commits to branch              │
                      │ - Updates PR status              │
                      └────────┬─────────────────────────┘
                               ↓
                      ┌─────────────────┐
                      │ Human Reviews   │
                      │ & Merges PR     │
                      └─────────────────┘
```

## Monitored Workflows

The auto-healing system currently monitors **16 workflows**:

1. ARM64 Self-Hosted Runner
2. Comprehensive Scraper Validation with HuggingFace Schema Check
3. Docker Build and Test
4. Docker Build and Test (Multi-Platform)
5. Documentation Maintenance
6. GPU-Enabled Tests
7. GraphRAG Production CI/CD
8. MCP Dashboard Automated Tests
9. MCP Endpoints Integration Tests
10. PDF Processing Pipeline CI/CD
11. PDF Processing and MCP Tools CI
12. Publish Python Package
13. Scraper Validation and Testing
14. Self-Hosted Runner Test
15. Self-Hosted Runner Validation
16. Test Datasets ARM64 Runner

This list is **automatically updated** whenever workflows are added, removed, or renamed!

## Automatic List Updates

The `update-autohealing-list.yml` workflow automatically:
- Runs when workflow files change
- Scans for all workflows
- Updates the monitored list in `copilot-agent-autofix.yml`
- Commits changes on main branch
- Comments on PRs when changes are detected

**Manual update**: Run `python3 .github/scripts/update_autofix_workflow_list.py`

## Configuration

The system is configured via `.github/workflows/workflow-auto-fix-config.yml`:

### Key Settings
- **Auto-healing enabled**: `true`
- **Auto-create PR**: Automatic
- **Draft PRs**: Created automatically
- **Copilot integration**: Enabled via `@copilot` mention
- **Minimum confidence**: 70%

### Excluded Workflows
Some workflows are excluded from auto-healing:
- Copilot Agent Auto-Healing (itself)
- Workflow Auto-Fix System (legacy)
- Enhanced Auto-Healing (deprecated)

## How to Use

### For Failed Workflows (Automatic)
When a workflow fails:
1. **Do nothing** - the system detects it automatically
2. Wait for the issue to be created (usually within 2-5 minutes)
3. Wait for the draft PR to be created
4. Wait for Copilot to implement fixes
5. Review and merge the PR when ready

### Manual Trigger
You can manually trigger the auto-healing for a specific workflow:

```bash
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Your Workflow Name" \
  --field run_id="12345678"  # Optional: specific run ID
```

### Monitoring Progress
- Check the [Issues](../../issues?q=label%3Aauto-healing) page for auto-created issues
- Filter by labels: `automated`, `workflow-failure`, `auto-healing`
- Check [Pull Requests](../../pulls?q=label%3Aautomated-fix) for auto-generated PRs
- Filter by labels: `automated-fix`, `workflow-fix`, `copilot-ready`

## Files and Components

### Main Workflow
- `.github/workflows/copilot-agent-autofix.yml` - Main auto-healing workflow

### Support Scripts
- `.github/scripts/analyze_workflow_failure.py` - Analyzes logs and identifies errors
- `.github/scripts/generate_workflow_fix.py` - Generates fix proposals
- `.github/scripts/generate_workflow_list.py` - Lists all workflows
- `.github/scripts/update_autofix_workflow_list.py` - Updates monitored workflow list

### Configuration
- `.github/workflows/workflow-auto-fix-config.yml` - System configuration

### Automation
- `.github/workflows/update-autohealing-list.yml` - Auto-updates workflow list

## Troubleshooting

### Issue Not Created
- Check if the workflow is in the monitored list
- Verify the workflow actually failed (not cancelled or skipped)
- Check auto-healing workflow run logs
- Ensure it's not a duplicate (already has a PR)

### Copilot Not Responding
- Verify `@copilot` mention is in the PR comments
- Check that the PR is a draft
- Ensure the PR has the `copilot-ready` label
- Wait up to 24 hours for Copilot to respond

### Fix Not Appropriate
- The AI may not always generate the perfect fix
- Human review is always required before merging
- Close the PR and fix manually if needed
- Update the exclusion list if a workflow shouldn't be auto-fixed

## Best Practices

1. **Review all auto-generated PRs** before merging
2. **Update the exclusion list** for critical workflows that need manual attention
3. **Monitor the auto-healing workflow** for failures in the healing system itself
4. **Keep the workflow list updated** by running the update script after adding workflows
5. **Test fixes in a separate environment** if the failure is critical

## Differences from Other Systems

### vs. Enhanced Auto-Healing
- **Enhanced Auto-Healing**: Disabled (used unsupported `workflows: ["*"]`)
- **Copilot Agent Auto-Healing**: Active, uses explicit workflow list

### vs. Legacy Auto-Fix
- **Legacy Auto-Fix**: Requires manual PR review before Copilot
- **Copilot Agent Auto-Healing**: Copilot works automatically, human only reviews final result

## Metrics and Monitoring

Track auto-healing effectiveness:
- Issues created per month
- PRs successfully merged
- Average time to fix
- Fix success rate
- Workflows with recurring failures

Run `python3 .github/scripts/analyze_autohealing_metrics.py` for detailed metrics.

## Future Improvements

Planned enhancements:
- [ ] Machine learning for better error pattern detection
- [ ] Integration with external monitoring tools
- [ ] Slack/email notifications for critical failures
- [ ] Auto-merge for high-confidence fixes (>90%)
- [ ] Retry failed auto-healing attempts
- [ ] Custom fix templates per workflow type

## Support

For issues with the auto-healing system:
1. Check workflow run logs
2. Review existing issues and PRs
3. Open an issue with the `auto-healing` label
4. Tag maintainers if urgent

## License

This auto-healing system is part of the ipfs_datasets_py project.
