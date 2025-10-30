# Auto-Healing System Enhancements

## Overview

This document describes the enhancements made to the GitHub Actions auto-healing system to ensure all workflows run on Docker containers with self-hosted runners, and to improve the automatic issue creation and GitHub Copilot integration.

## Changes Made

### 1. New Enhanced Auto-Healing Workflow

**File**: `.github/workflows/enhanced-autohealing.yml`

This new workflow provides comprehensive automated healing for failed workflows with the following features:

#### ✅ Docker Container Execution
- Runs on self-hosted runners: `[self-hosted, linux, x64]`
- Uses Docker container: `python:3.12-slim`
- All operations execute inside isolated containers for consistency and security

#### ✅ Automatic Issue Creation
- **Detects workflow failures** automatically via `workflow_run` trigger
- **Creates tracking issues** for each failed workflow
- **Reuses existing issues** if they already exist for the same workflow
- **Updates issues** with new failure information

#### ✅ GitHub Copilot Integration
- **Creates fix branches** with detailed instructions for Copilot
- **Generates Pull Requests** with explicit `@copilot` mentions
- **Provides task files** in `.github/copilot-instructions/` for Copilot to follow
- **Adds PR comments** to trigger Copilot agent
- **Links issues to PRs** for full traceability

#### ✅ Comprehensive Workflow Analysis
- Downloads and analyzes failed job logs
- Identifies root causes of failures
- Generates detailed failure reports
- Creates actionable fix proposals

### 2. Updated Scraper Validation Workflow

**File**: `.github/workflows/scraper-validation.yml`

Updated to run on self-hosted Docker containers:

#### Changes:
- **All jobs** now run on `[self-hosted, linux, x64]` runners
- **Docker containerization**: Uses `python:3.12-slim` container
- **Simplified execution**: Runs tests directly in container (no nested Docker)
- **Consistent environment**: All matrix jobs use same container image

#### Jobs Updated:
1. **test-scrapers-docker**: Matrix testing across 4 domains
2. **generate-report**: Consolidated test reporting
3. **notify-on-failure**: Failure notifications

## Enhanced Auto-Healing Features

### Automatic Issue Creation

When a workflow fails, the system automatically:

1. **Detects the failure** via `workflow_run` event
2. **Creates a tracking issue** with:
   - Descriptive title: "🔧 Auto-Healing: Workflow Failure - [Workflow Name]"
   - Detailed failure information
   - Links to failed run
   - Status tracking
3. **Updates existing issues** if one already exists
4. **Labels issues** appropriately: `automated`, `workflow-failure`, `auto-healing`

### GitHub Copilot Assignment

The system automatically assigns GitHub Copilot to fix issues:

1. **Creates a fix branch** with a unique name
2. **Generates Copilot instructions** in `.github/copilot-instructions/`
3. **Creates a Pull Request** with:
   - Explicit `@copilot` mention in title and description
   - Detailed task description
   - Links to failure analysis
   - Clear success criteria
4. **Adds PR comment** to trigger Copilot agent
5. **Links PR to tracking issue** for full traceability

### Docker Container Benefits

All workflows now run in Docker containers, providing:

✅ **Consistency**: Same environment across all runs
✅ **Isolation**: No conflicts between workflows
✅ **Reproducibility**: Exact Python version and dependencies
✅ **Security**: Isolated execution with controlled permissions
✅ **Self-hosted compatibility**: Works on self-hosted runners

## Workflow Trigger Methods

### Automatic Triggers

The Enhanced Auto-Healing workflow triggers automatically when:
- **Any workflow fails**: via `workflow_run` with `completed` type
- Excludes auto-healing workflows to prevent loops

### Manual Triggers

Can be triggered manually via `workflow_dispatch` with inputs:
- `workflow_name`: Name of the failed workflow to analyze
- `run_id`: Specific workflow run ID to analyze
- `force_create_issue`: Force create a new issue even if one exists

## Self-Hosted Runner Requirements

### System Requirements

The workflows require self-hosted runners with:
- **Labels**: `self-hosted`, `linux`, `x64`
- **Docker installed**: For running containers
- **Git and GitHub CLI**: For repository operations
- **Network access**: For downloading dependencies and accessing GitHub API

### Container Configuration

All workflows use:
- **Image**: `python:3.12-slim`
- **User**: `root` (for installing system dependencies)
- **Resources**: Default container resources

## Usage Examples

### Viewing Auto-Healing Issues

1. Go to repository Issues tab
2. Filter by labels: `workflow-failure`, `auto-healing`
3. Issues are automatically created/updated when workflows fail

### Monitoring Auto-Healing PRs

1. Go to repository Pull Requests tab
2. Filter by labels: `automated-fix`, `workflow-fix`, `copilot-task`
3. PRs have `@copilot` mentions and detailed instructions

### Manual Trigger Example

To manually trigger auto-healing for a specific failure:

```bash
# Via GitHub CLI
gh workflow run enhanced-autohealing.yml \
  -f workflow_name="Scraper Validation and Testing" \
  -f run_id="12345678"

# Via GitHub UI
# Actions → Enhanced Auto-Healing → Run workflow
# Enter workflow name or run ID
```

## Integration with Existing Workflows

The Enhanced Auto-Healing system integrates seamlessly with:

✅ **Scraper Validation**: Automatically fixes scraper test failures
✅ **MCP Dashboard Tests**: Handles dashboard test issues
✅ **Docker CI**: Fixes container build problems
✅ **Documentation Maintenance**: Resolves doc generation issues
✅ **All other workflows**: Universal coverage

## Monitoring and Metrics

### Artifacts

Each auto-healing run creates artifacts:
- **Name**: `autohealing-logs-[run_id]`
- **Contents**: Failure analysis, logs, proposals
- **Retention**: 30 days

### Summary Reports

Each run generates a summary showing:
- 🔍 **Analysis Status**: Whether failures were detected and analyzed
- 📝 **Issue Status**: Issue number created/updated
- 🌿 **Branch Status**: Fix branch name
- 🔀 **PR Status**: Whether PR was created
- 🤖 **Copilot Status**: Whether Copilot was assigned

## Troubleshooting

### Auto-Healing Not Triggering

**Symptoms**: Workflow fails but no auto-healing runs

**Solutions**:
1. Check workflow name doesn't contain "Auto-Healing" or "Auto-Fix"
2. Verify workflow actually failed (not cancelled or skipped)
3. Check self-hosted runner availability
4. Manually trigger using `workflow_dispatch`

### Issues Not Creating

**Symptoms**: Auto-healing runs but no issue created

**Solutions**:
1. Check repository permissions: `issues: write`
2. Verify GitHub token has correct permissions
3. Use `force_create_issue: true` in manual trigger
4. Check workflow logs for error messages

### Copilot Not Responding

**Symptoms**: PR created but Copilot doesn't act

**Solutions**:
1. Ensure `@copilot` is mentioned in PR description
2. Check Copilot is enabled for repository
3. Verify PR has correct labels
4. Add manual comment with `@copilot` mention

## Best Practices

### For Self-Hosted Runners

1. **Keep Docker updated**: Ensure latest Docker version
2. **Monitor resources**: Watch CPU/memory usage
3. **Clean containers**: Regularly prune unused images
4. **Update runner**: Keep GitHub Actions runner updated

### For Workflow Failures

1. **Review issues promptly**: Check auto-created issues regularly
2. **Validate Copilot fixes**: Don't blindly merge PR fixes
3. **Provide feedback**: Comment on PRs if fix is incorrect
4. **Close resolved issues**: Close issues once fixed and verified

### For Development

1. **Test locally first**: Use Docker to test changes
2. **Small changes**: Make incremental improvements
3. **Document fixes**: Add comments explaining complex changes
4. **Update tests**: Ensure tests reflect fixes

## Future Enhancements

Potential improvements for the auto-healing system:

- [ ] Machine learning for better failure prediction
- [ ] Automated test generation for new code
- [ ] Integration with external monitoring tools
- [ ] Slack/email notifications for failures
- [ ] Auto-merge for high-confidence fixes
- [ ] Metrics dashboard for healing success rate
- [ ] Cost tracking for runner usage
- [ ] Priority queue for critical failures

## Security Considerations

The auto-healing system is designed with security in mind:

✅ **Isolated execution**: All operations in containers
✅ **Limited permissions**: Workflows only have necessary permissions
✅ **Code review required**: PRs need manual approval before merge
✅ **Audit trail**: All changes tracked via Git
✅ **Token security**: Uses GitHub-provided tokens
✅ **No credentials in logs**: Sensitive data excluded

## Conclusion

The enhanced auto-healing system provides:

1. ✅ **Automated failure detection and analysis**
2. ✅ **Automatic issue creation for tracking**
3. ✅ **GitHub Copilot integration for fixes**
4. ✅ **Docker container execution on self-hosted runners**
5. ✅ **Comprehensive logging and reporting**

This ensures faster incident resolution, better tracking, and consistent execution across all workflows.

---

**Last Updated**: 2025-10-30  
**Version**: 1.0  
**Status**: Production Ready
