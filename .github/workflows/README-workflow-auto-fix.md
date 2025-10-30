# Workflow Auto-Fix System

## Overview

The Workflow Auto-Fix System is an automated GitHub Actions solution that detects workflow failures, analyzes their root causes, generates fix proposals, and creates pull requests for GitHub Copilot to review and implement.

## Features

- **🔍 Automatic Failure Detection**: Monitors all workflows and triggers on failure
- **📊 Intelligent Analysis**: Identifies root causes using pattern matching
- **🔧 Fix Generation**: Creates targeted fixes based on error types
- **🤖 Copilot Integration**: Prepares PRs for GitHub Copilot review
- **📝 Detailed Reports**: Provides comprehensive failure analysis
- **🏷️ Smart Labeling**: Automatically tags PRs with relevant labels

## Architecture

### Components

1. **Workflow Trigger** (`.github/workflows/workflow-auto-fix.yml`)
   - Listens for workflow failures via `workflow_run` event
   - Can be manually triggered for specific failures
   - Coordinates the entire auto-fix process

2. **Failure Analyzer** (`.github/scripts/analyze_workflow_failure.py`)
   - Downloads and parses workflow logs
   - Identifies error patterns using regex
   - Determines root cause with confidence scoring
   - Generates actionable recommendations

3. **Fix Generator** (`.github/scripts/generate_workflow_fix.py`)
   - Creates fix proposals based on analysis
   - Generates PR title, description, and labels
   - Suggests specific code changes

4. **Fix Applier** (`.github/scripts/apply_workflow_fix.py`)
   - Applies proposed fixes to repository files
   - Handles YAML modifications safely
   - Creates review notes for complex fixes

### Workflow Diagram

```
Workflow Failure
      ↓
workflow_run trigger
      ↓
Download Logs
      ↓
Analyze Failure ──→ Pattern Matching
      ↓             ├─ Dependency errors
      ↓             ├─ Timeout issues
      ↓             ├─ Permission problems
      ↓             ├─ Network failures
      ↓             └─ Resource exhaustion
      ↓
Generate Fix Proposal
      ↓
Apply Changes
      ↓
Create Branch
      ↓
Create Pull Request ──→ GitHub Copilot Review
      ↓
Link to Issue
```

## Supported Fix Types

### 1. Dependency Errors
**Detection**: Missing Python packages, import errors
**Fix**: 
- Adds package to `requirements.txt`
- Adds pip install step in workflow
**Confidence**: 90%

### 2. Timeout Issues
**Detection**: Step or job exceeds time limit
**Fix**:
- Increases `timeout-minutes` in workflow
- Adds timeout parameters to commands
**Confidence**: 95%

### 3. Permission Errors
**Detection**: Access denied, forbidden errors
**Fix**:
- Adds required permissions to workflow
- Updates GITHUB_TOKEN scopes
**Confidence**: 80%

### 4. Network Errors
**Detection**: Connection failures, download issues
**Fix**:
- Adds retry logic using `nick-invision/retry@v2`
- Adds `continue-on-error` for non-critical steps
**Confidence**: 75%

### 5. Docker Errors
**Detection**: Docker daemon issues, build failures
**Fix**:
- Adds Docker Buildx setup
- Adds container registry login
**Confidence**: 85%

### 6. Resource Exhaustion
**Detection**: Out of memory, disk full
**Fix**:
- Changes runner to larger instance
- Adds cleanup steps
**Confidence**: 90%

### 7. Missing Environment Variables
**Detection**: Undefined env var references
**Fix**:
- Adds env section to workflow
- Creates placeholder for secret
**Confidence**: 95%

## Usage

### Automatic Mode (Default)

The workflow automatically triggers when any workflow fails:

```yaml
on:
  workflow_run:
    workflows: ["*"]
    types:
      - completed
```

No manual intervention required. The system will:
1. Detect the failure
2. Analyze logs
3. Generate fix
4. Create PR
5. Link to tracking issue

### Manual Mode

Manually trigger for specific workflow failures:

```bash
# Via GitHub CLI
gh workflow run workflow-auto-fix.yml \
  --field workflow_name="Docker Build and Test" \
  --field create_pr=true

# Via GitHub UI
# Go to Actions → Workflow Auto-Fix System → Run workflow
# Enter workflow name or run ID
```

### Testing Mode

Test the system without creating PRs:

```bash
gh workflow run workflow-auto-fix.yml \
  --field workflow_name="Docker Build and Test" \
  --field create_pr=false
```

## Configuration

### Workflow Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `workflow_name` | string | No | - | Name of failed workflow to analyze |
| `run_id` | string | No | - | Specific workflow run ID |
| `create_pr` | boolean | No | true | Create PR for the fix |

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GITHUB_TOKEN` | GitHub API token | Yes (auto-provided) |
| `PYTHON_VERSION` | Python version for scripts | No (default: 3.10) |

### Permissions

The workflow requires these permissions:

```yaml
permissions:
  contents: write       # Create branches and commits
  pull-requests: write  # Create PRs
  issues: write        # Create/comment on issues
  actions: read        # Read workflow logs
```

## Output

### PR Structure

Each auto-generated PR includes:

1. **Title**: `fix: Auto-fix [Error Type] in [Workflow Name]`
2. **Description**:
   - Summary of failure
   - Detailed analysis
   - Proposed fixes
   - Recommendations
   - Affected files
   - Link to failed run
3. **Labels**: 
   - `automated-fix`
   - `workflow-fix`
   - `copilot-ready`
   - Type-specific labels
4. **Branch**: `autofix/[workflow]/[fix-type]/[timestamp]`

### Artifacts

Each run creates artifacts:
- `workflow-autofix-[run_id]/`
  - `workflow_logs/` - Downloaded logs
  - `failure_analysis.json` - Analysis results
  - `fix_proposal.json` - Fix proposal
  - Retention: 30 days

## GitHub Copilot Integration

### How It Works

1. PR is created with `copilot-ready` label
2. GitHub Copilot automatically reviews the PR
3. Copilot suggests improvements or validates the fix
4. Developer reviews Copilot's suggestions
5. PR is merged if tests pass

### Copilot Review Points

Copilot will check:
- ✅ Syntax correctness of YAML changes
- ✅ Consistency with workflow patterns
- ✅ Security implications
- ✅ Best practices compliance
- ✅ Potential side effects

## Examples

### Example 1: Missing Dependency

**Failure**:
```
ModuleNotFoundError: No module named 'pytest-asyncio'
```

**Auto-Fix**:
1. Detects missing package: `pytest-asyncio`
2. Adds to `requirements.txt`
3. Updates workflow install step
4. Creates PR with confidence: 90%

### Example 2: Timeout

**Failure**:
```
Error: The operation was canceled.
Job ran for 6 minutes (timeout: 5 minutes)
```

**Auto-Fix**:
1. Identifies timeout issue
2. Increases `timeout-minutes` to 30
3. Creates PR with confidence: 95%

### Example 3: Permission Error

**Failure**:
```
Error: Resource not accessible by integration
403 Forbidden
```

**Auto-Fix**:
1. Detects permission issue
2. Adds required permissions section
3. Creates PR with confidence: 80%

## Testing

### Unit Tests

```bash
# Test analyzer
python .github/scripts/analyze_workflow_failure.py \
  --run-id 12345 \
  --workflow-name "Test Workflow" \
  --logs-dir /tmp/test_logs \
  --output /tmp/analysis.json

# Test fix generator
python .github/scripts/generate_workflow_fix.py \
  --analysis /tmp/analysis.json \
  --workflow-name "Test Workflow" \
  --output /tmp/proposal.json

# Test fix applier
python .github/scripts/apply_workflow_fix.py \
  --proposal /tmp/proposal.json \
  --repo-path .
```

### Integration Tests

Create a test workflow that intentionally fails:

```yaml
name: Test Auto-Fix
on: [push]
jobs:
  test-fail:
    runs-on: ubuntu-latest
    steps:
      - run: exit 1  # Intentional failure
```

Trigger the auto-fix workflow manually:

```bash
gh workflow run workflow-auto-fix.yml \
  --field workflow_name="Test Auto-Fix"
```

Verify:
1. PR is created
2. Analysis is correct
3. Fix is appropriate
4. Labels are applied

## Monitoring

### Workflow Summary

Each run creates a step summary showing:
- Workflow details
- Failure analysis
- Fix proposal
- PR status
- Artifact locations

### Artifacts

Download artifacts for detailed review:

```bash
gh run download [RUN_ID] -n workflow-autofix-[RUN_ID]
```

### Logs

Check workflow logs for debugging:

```bash
gh run view [RUN_ID] --log
```

## Troubleshooting

### GitHub CLI Authentication Failure (FIXED in v1.0.1)

**Symptom:**
- Auto-fix workflow completes in 1-2 seconds
- Steps using `gh` commands fail silently
- Error message: "To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable"
- No workflow details retrieved, no logs downloaded

**Root Cause:**
The workflow was setting `GITHUB_TOKEN` environment variable, but GitHub CLI in Actions workflows requires `GH_TOKEN`.

**Solution (Implemented in v1.0.1):**
All steps that use `gh` CLI commands now correctly set `GH_TOKEN`:
```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}  # Changed from GITHUB_TOKEN
```

**Affected Steps:**
- Get workflow run details
- Download workflow logs
- Generate fix proposal
- Create Pull Request
- Add issue comment

**Verification:**
Check workflow logs for successful `gh` command execution. You should see workflow details, logs being downloaded, and PRs being created.

### Workflow Being Skipped (FIXED in latest version)

**Symptom:**
- Auto-fix workflow completes in 1-2 seconds
- No analysis or PR creation occurs
- Job appears to run but does nothing

**Root Cause (Historical):**
Prior to the fix, the workflow had an overly restrictive condition:
```yaml
github.event.workflow_run.event != 'workflow_run'
```

This prevented the auto-fix system from running when a failed workflow was itself triggered by a `workflow_run` event, which was too restrictive and caused many legitimate failures to be ignored.

**Solution (Implemented):**
The condition has been updated to:
```yaml
!contains(github.event.workflow_run.name, 'Auto-Healing') &&
!contains(github.event.workflow_run.name, 'Auto-Fix')
```

This allows auto-fix to run for ANY failed workflow, while still preventing infinite loops by checking the workflow name instead of the event type.

**Verification:**
Check the workflow run summary for debug information showing:
- Event name and workflow details
- All condition check results
- Full event context in JSON format

If the workflow is still being skipped, check the debug output to see which condition is failing.

### Issue: No PR Created

**Causes**:
- Analysis confidence too low
- No changes to commit
- Permission issues

**Solution**:
- Check workflow logs
- Review failure analysis
- Verify permissions

### Issue: Wrong Fix Applied

**Causes**:
- Pattern matching incorrect
- Multiple error types present
- Unclear logs

**Solution**:
- Review analysis JSON
- Adjust patterns in analyzer
- Run manually with specific fix type

### Issue: Copilot Not Reviewing

**Causes**:
- Label not applied
- Copilot not enabled for repo
- PR too large

**Solution**:
- Verify `copilot-ready` label
- Check repository settings
- Split into smaller PRs

## Limitations

### Current Limitations

1. **Pattern-Based**: Only detects known error patterns
2. **Single Fix**: Applies one fix per run
3. **YAML Only**: Primarily fixes workflow files
4. **No Code Fixes**: Doesn't fix application code
5. **Manual Review**: Complex fixes require review

### Future Enhancements

- [ ] Machine learning for pattern detection
- [ ] Multi-fix proposals
- [ ] Application code fixes
- [ ] Automated testing of fixes
- [ ] Fix success rate tracking
- [ ] Custom pattern configuration
- [ ] Integration with external analysis tools

## Security Considerations

### What The System Does

- ✅ Creates branches (read-only repo)
- ✅ Commits changes (automated account)
- ✅ Creates PRs (requires review)
- ✅ Comments on issues (tracking)

### What The System Doesn't Do

- ❌ Auto-merge PRs
- ❌ Modify secrets
- ❌ Execute arbitrary code
- ❌ Access external systems
- ❌ Bypass branch protection

### Best Practices

1. **Review All PRs**: Never auto-merge
2. **Check Changes**: Verify fixes are correct
3. **Test Locally**: Run tests before merging
4. **Monitor Usage**: Track fix success rate
5. **Update Patterns**: Add new error patterns

## Contributing

### Adding New Fix Types

1. Add pattern to `analyze_workflow_failure.py`:
```python
'new_error_type': {
    'patterns': [r'your regex here'],
    'error_type': 'Display Name',
    'fix_type': 'your_fix_type',
    'confidence': 85,
}
```

2. Add fix generator to `generate_workflow_fix.py`:
```python
def _fix_your_fix_type(self) -> List[Dict[str, Any]]:
    return [{
        'file': 'target/file',
        'action': 'your_action',
        'description': 'What the fix does',
        'changes': 'YAML changes',
    }]
```

3. Add fix applier to `apply_workflow_fix.py`:
```python
elif fix['action'] == 'your_action':
    self._apply_your_action(fix)
```

### Testing New Patterns

1. Create test logs with the error
2. Run analyzer manually
3. Verify pattern matches
4. Check confidence score
5. Validate generated fix

## FAQ

**Q: Will this auto-merge fixes?**
A: No, all PRs require manual review and approval.

**Q: Can I disable auto-fix for specific workflows?**
A: Yes, add condition to the workflow trigger or exclude workflow names.

**Q: How accurate are the fixes?**
A: Accuracy varies by error type (70-95% confidence). Always review.

**Q: Can I customize fix proposals?**
A: Yes, modify the generator scripts to customize fixes.

**Q: What if the fix doesn't work?**
A: Close the PR and manually fix. Consider updating patterns.

**Q: Does this work with private repositories?**
A: Yes, requires appropriate permissions and GitHub Copilot access.

## Support

### Resources

- [GitHub Actions Documentation](https://docs.github.com/actions)
- [GitHub Copilot](https://github.com/features/copilot)
- [Workflow Syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)

### Getting Help

1. Check workflow logs
2. Review artifacts
3. Create an issue
4. Tag maintainers

## License

Same as parent repository.

## Changelog

### Version 1.0.1 (2025-10-30)

**CRITICAL FIX: GitHub CLI Authentication**
- Fixed authentication issue causing workflows to fail silently
- Changed `GITHUB_TOKEN` to `GH_TOKEN` in all steps using `gh` CLI commands
- Affects both `workflow-auto-fix.yml` and `copilot-agent-autofix.yml`
- Resolves issue where workflows completed in 1-2 seconds without doing any work

**Files Modified:**
- `.github/workflows/copilot-agent-autofix.yml` - 5 instances fixed
- `.github/workflows/workflow-auto-fix.yml` - 5 instances fixed

### Version 1.0.0 (2025-10-29)

- Initial release
- Support for 9 common error types
- Automatic PR creation
- GitHub Copilot integration
- Comprehensive analysis and reporting
