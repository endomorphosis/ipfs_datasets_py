# GitHub Copilot Auto-Healing System

## Overview

The Auto-Healing System is an advanced workflow maintenance solution that automatically detects workflow failures, creates fix proposals, and uses GitHub Copilot Agent to implement the fixes without manual intervention.

## Key Differences from Auto-Fix

| Feature | Auto-Fix System | Auto-Healing System |
|---------|----------------|---------------------|
| **Detection** | Automatic | Automatic |
| **Analysis** | Automatic | Automatic |
| **Fix Proposal** | Automatic | Automatic |
| **Implementation** | Manual Review | **Copilot Agent** |
| **Label Required** | `copilot-ready` | **None** |
| **PR Creation** | Yes | Yes |
| **Auto-Implementation** | No | **Yes** |

## How It Works

```
┌─────────────────────┐
│  Workflow Fails     │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  Auto-Healing       │
│  System Detects     │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  Analyze Failure    │
│  - Download logs    │
│  - Pattern match    │
│  - Root cause       │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  Generate Proposal  │
│  - Fix strategy     │
│  - Code changes     │
│  - Confidence score │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  Create PR with     │
│  Copilot Task       │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  @copilot Mentioned │
│  in PR Comment      │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  Copilot Agent      │
│  - Reads analysis   │
│  - Implements fix   │
│  - Commits changes  │
│  - Runs tests       │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  Tests Validate     │
│  Fix                │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  Ready for Review   │
│  & Merge            │
└─────────────────────┘
```

## Features

### 🤖 Fully Automated
- No manual intervention required
- Copilot Agent implements fixes automatically
- Continuous healing loop for recurring issues

### 🎯 Intelligent Analysis
- Pattern-based error detection
- Root cause identification
- Confidence scoring
- Context-aware fix proposals

### 📝 Detailed Task Instructions
- Creates comprehensive task files for Copilot
- Includes failure analysis, logs, and context
- Provides step-by-step implementation guide
- Specifies success criteria

### 🔄 Self-Improving
- Learns from fix success/failure
- Adapts to new error patterns
- Maintains fix quality metrics

### 🔒 Safe by Default
- All fixes create PRs (no direct commits)
- Requires CI/CD validation
- Human review before merge
- Automatic rollback on failure

## Setup

### Prerequisites

1. **GitHub Copilot** must be enabled for your repository
2. **Copilot Agent** feature must be available (part of GitHub Copilot)
3. Repository must have proper permissions:
   - `contents: write`
   - `pull-requests: write`
   - `issues: write`
   - `actions: read`

### Installation

The auto-healing system is already configured in this repository:

1. **Workflow File**: `.github/workflows/copilot-agent-autofix.yml`
2. **Configuration**: `.github/workflows/workflow-auto-fix-config.yml`
3. **Scripts**: `.github/scripts/` directory

No additional setup required - it activates automatically when workflows fail.

### Configuration

Edit `.github/workflows/workflow-auto-fix-config.yml`:

```yaml
# Enable/disable auto-healing
enabled: true

# Copilot Agent settings
copilot:
  enabled: true
  use_agent_mode: true
  auto_mention: true
  create_task_file: true
  agent_timeout_hours: 24
```

## Usage

### Automatic Mode (Default)

The system runs automatically when any workflow fails:

```yaml
on:
  workflow_run:
    workflows: ["*"]
    types:
      - completed
```

**Process:**
1. Workflow fails
2. Auto-healing system detects failure
3. Analysis and fix proposal generated
4. PR created with Copilot task
5. Copilot Agent mentioned in PR comment
6. Copilot implements fix automatically
7. Tests run to validate fix
8. PR ready for review and merge

### Manual Trigger

You can manually trigger auto-healing for specific failures:

```bash
# Via GitHub CLI
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Docker Build and Test"

# For specific run ID
gh workflow run copilot-agent-autofix.yml \
  --field run_id="1234567890"

# Force create PR even with low confidence
gh workflow run copilot-agent-autofix.yml \
  --field workflow_name="Test Workflow" \
  --field force_create_pr=true
```

### Via GitHub UI

1. Go to **Actions** tab
2. Select **Copilot Agent Auto-Healing** workflow
3. Click **Run workflow**
4. Enter workflow name or run ID
5. Click **Run workflow**

## Copilot Agent Integration

### How Copilot is Invoked

1. **PR Creation**: System creates a PR with detailed failure information
2. **Task File**: Creates `.github/copilot-tasks/fix-workflow-failure.md` with instructions
3. **@copilot Mention**: Comments on PR mentioning @copilot
4. **Context Provision**: Provides analysis, logs, and fix proposal
5. **Implementation Request**: Asks Copilot to implement the fix

### Task File Structure

Each PR includes a Copilot task file with:

```markdown
# Fix Workflow Failure

## Problem Statement
[Description of the failure]

## Failure Analysis
- Error Type
- Root Cause
- Confidence Score

## Your Task
[Step-by-step instructions for Copilot]

## Fix Proposal
[Detailed fix suggestions]

## Expected Changes
[List of files and changes]

## Success Criteria
[How to validate the fix works]
```

### Copilot's Responsibilities

The Copilot Agent will:

1. **Analyze** the failure using provided logs and analysis
2. **Review** the fix proposal and validate approach
3. **Implement** the suggested fixes
4. **Test** changes locally (syntax validation)
5. **Commit** the implementation to the PR branch
6. **Document** any changes or deviations from proposal

## Supported Fix Types

### 1. Dependency Errors (90% confidence)
- Missing Python packages
- Import errors
- Version conflicts

**Auto-Healing Actions:**
- Add package to requirements
- Update install steps
- Pin versions if needed

### 2. Timeout Issues (95% confidence)
- Job/step timeouts
- Network timeouts
- Build timeouts

**Auto-Healing Actions:**
- Increase timeout values
- Add timeout parameters
- Optimize slow steps

### 3. Permission Errors (80% confidence)
- Access denied
- Token permissions
- Resource access

**Auto-Healing Actions:**
- Add permissions section
- Update token scopes
- Fix file permissions

### 4. Docker Errors (85% confidence)
- Build failures
- Daemon issues
- Registry problems

**Auto-Healing Actions:**
- Add Buildx setup
- Configure registry
- Fix Dockerfile syntax

### 5. Network Errors (75% confidence)
- Connection failures
- Download issues
- API timeouts

**Auto-Healing Actions:**
- Add retry logic
- Configure caching
- Use mirrors/fallbacks

### 6. Resource Exhaustion (90% confidence)
- Out of memory
- Disk full
- CPU limits

**Auto-Healing Actions:**
- Upgrade runner size
- Add cleanup steps
- Optimize resource usage

### 7. Test Failures (70% confidence)
- Assertion errors
- Test timeouts
- Environment issues

**Auto-Healing Actions:**
- Fix test configuration
- Update test data
- Adjust test timeouts

## Examples

### Example 1: Missing Dependency

**Scenario**: Workflow fails with `ModuleNotFoundError`

**Auto-Healing Process:**

1. **Detection**:
   ```
   ERROR: ModuleNotFoundError: No module named 'pytest-asyncio'
   ```

2. **Analysis**:
   - Error Type: Missing Dependency
   - Root Cause: pytest-asyncio not in requirements
   - Confidence: 90%

3. **PR Creation**:
   - Branch: `autofix/docker-build/add-dependency/20251029`
   - Title: "fix: Auto-fix Missing Dependency in Docker Build"

4. **Copilot Implementation**:
   - Adds `pytest-asyncio==0.21.0` to requirements.txt
   - Updates workflow install step
   - Adds comment explaining change
   - Commits to PR branch

5. **Validation**:
   - CI runs with new dependency
   - Tests pass
   - PR ready for merge

### Example 2: Timeout Issue

**Scenario**: Job exceeds time limit

**Auto-Healing Process:**

1. **Detection**:
   ```
   ERROR: Job exceeded timeout (5 minutes)
   ```

2. **Analysis**:
   - Error Type: Timeout
   - Root Cause: Insufficient time for build
   - Confidence: 95%

3. **Copilot Implementation**:
   - Increases `timeout-minutes: 30`
   - Adds timeout to long-running commands
   - Documents why change was needed

4. **Validation**:
   - Next run completes successfully
   - Timing metrics collected

### Example 3: Permission Error

**Scenario**: GitHub API returns 403

**Auto-Healing Process:**

1. **Detection**:
   ```
   ERROR: Resource not accessible by integration (403)
   ```

2. **Analysis**:
   - Error Type: Permission Error
   - Root Cause: Missing permissions section
   - Confidence: 80%

3. **Copilot Implementation**:
   - Adds permissions block to workflow
   - Includes required scopes
   - Tests token access

## Monitoring

### View Auto-Healing Activity

```bash
# List all auto-healing PRs
gh pr list --label "auto-healing"

# Check specific PR status
gh pr view 123 --json state,reviews,checks

# View auto-healing workflow runs
gh run list --workflow="Copilot Agent Auto-Healing"
```

### Check Copilot Agent Activity

```bash
# View Copilot's commits on PR
gh pr view 123 --json commits

# See Copilot's comments
gh pr view 123 --comments | grep "github-copilot"

# Check if Copilot implemented the fix
gh pr diff 123
```

### Success Metrics

Track auto-healing effectiveness:

```bash
# Get PR stats
gh pr list --label "auto-healing" --state closed --json number,state,mergedAt

# Calculate success rate
python .github/scripts/analyze_autohealing_metrics.py
```

## Troubleshooting

### GitHub CLI Authentication Failure (FIXED in v2.1.0)

**Symptom:**
- Auto-healing workflow completes in 1-2 seconds
- Steps using `gh` commands fail silently
- Error message: "To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable"
- No workflow details retrieved, no logs downloaded, no PRs created

**Root Cause:**
The workflow was setting `GITHUB_TOKEN` environment variable, but GitHub CLI in Actions workflows requires `GH_TOKEN`.

**Solution (Implemented in v2.1.0):**
All steps that use `gh` CLI commands now correctly set `GH_TOKEN`:
```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}  # Changed from GITHUB_TOKEN
```

**Affected Steps:**
- Get workflow run details (uses `gh run list`, `gh run view`)
- Download workflow logs (uses `gh run view`)
- Create Pull Request (uses `gh pr create`, `gh pr comment`)
- Add issue comment (uses `gh issue list`, `gh issue create`, `gh issue comment`)

**Verification:**
Check workflow logs for successful `gh` command execution. You should see:
- Workflow details being retrieved
- Logs being downloaded from failed jobs
- PRs being created successfully
- Copilot mentions being added to PRs

### Workflow Being Skipped (FIXED in latest version)

**Symptom:**
- Auto-healing workflow completes in 1-2 seconds
- No analysis or PR creation occurs
- Job appears to run but does nothing

**Root Cause (Historical):**
Prior to the fix, the workflow had an overly restrictive condition:
```yaml
github.event.workflow_run.event != 'workflow_run'
```

This prevented the auto-healing system from running when a failed workflow was itself triggered by a `workflow_run` event, which was too restrictive.

**Solution (Implemented):**
The condition has been updated to:
```yaml
!contains(github.event.workflow_run.name, 'Auto-Healing') &&
!contains(github.event.workflow_run.name, 'Auto-Fix')
```

This allows auto-healing to run for ANY failed workflow, while still preventing infinite loops by checking the workflow name instead of the event type.

**Verification:**
Check the workflow run summary for debug information showing:
- Event name and workflow details
- All condition check results
- Full event context in JSON format

If the workflow is still being skipped, check the debug output to see which condition is failing.

### Copilot Doesn't Respond

**Possible Causes:**
- Copilot not enabled for repository
- Task file not created properly
- PR too complex for automatic fix
- Copilot Agent quota exceeded

**Solutions:**
1. Verify Copilot is enabled in repository settings
2. Check `.github/copilot-tasks/` for task file
3. Review PR complexity (should be focused)
4. Try manual trigger with simplified fix
5. Check GitHub status for Copilot service

### Fix Doesn't Work

**Possible Causes:**
- Incorrect analysis
- Multiple root causes
- Environment-specific issue
- Missing context

**Solutions:**
1. Review failure analysis in artifacts
2. Check if fix confidence was low
3. Manually review and adjust PR
4. Close PR and investigate further
5. Update error patterns in analyzer

### PR Not Created

**Possible Causes:**
- Analysis confidence too low
- No applicable fix pattern
- Workflow excluded in config
- Permission issues

**Solutions:**
1. Check workflow run logs
2. Review confidence thresholds
3. Verify workflow not in excluded list
4. Check repository permissions
5. Try manual trigger with force option

### Multiple PRs Created

**Possible Causes:**
- Multiple workflow failures
- Retry logic triggered
- Rate limiting not working

**Solutions:**
1. Check rate limit settings in config
2. Review PR deduplication logic
3. Close duplicate PRs manually
4. Adjust configuration to prevent duplicates

## Best Practices

### 1. Review Before Merging

Even though Copilot implements fixes automatically:
- ✅ **Always review** Copilot's changes
- ✅ **Validate tests** pass successfully
- ✅ **Check for side effects**
- ✅ **Verify documentation** is updated if needed

### 2. Monitor Success Rate

Track how well auto-healing works:
- Monitor fix success rate
- Review failed auto-healing attempts
- Update patterns based on results
- Adjust confidence thresholds

### 3. Provide Feedback

Help improve the system:
- Report false positives
- Suggest new error patterns
- Share successful fixes
- Document edge cases

### 4. Configure Appropriately

Tune settings for your repository:
- Set appropriate confidence thresholds
- Exclude critical workflows if needed
- Configure rate limits
- Adjust timeout values

### 5. Maintain Patterns

Keep error detection up-to-date:
- Add new error patterns as discovered
- Update fix strategies based on experience
- Remove obsolete patterns
- Document pattern changes

## Security Considerations

### What the System Does

- ✅ Creates branches (non-protected)
- ✅ Commits fixes (via Copilot Agent)
- ✅ Creates PRs (requires review)
- ✅ Comments on issues (tracking)
- ✅ Analyzes logs (read-only)

### What the System Doesn't Do

- ❌ Auto-merge PRs
- ❌ Modify secrets or credentials
- ❌ Execute arbitrary code in main branch
- ❌ Bypass branch protection
- ❌ Access external systems
- ❌ Modify production environments

### Security Best Practices

1. **Branch Protection**: Maintain branch protection rules
2. **Required Reviews**: Require human review before merge
3. **CI/CD Validation**: Always run full test suite
4. **Audit Logs**: Monitor auto-healing activity
5. **Rate Limiting**: Prevent excessive PR creation
6. **Permissions**: Use minimal required permissions

## Advanced Configuration

### Custom Error Patterns

Add custom patterns in `analyze_workflow_failure.py`:

```python
'custom_error': {
    'patterns': [
        r'your custom pattern here',
        r'another pattern',
    ],
    'error_type': 'Custom Error Type',
    'fix_type': 'custom_fix',
    'confidence': 85,
}
```

### Custom Fix Generators

Implement custom fix logic in `generate_workflow_fix.py`:

```python
def _fix_custom_error(self) -> List[Dict[str, Any]]:
    """Generate custom fix for specific error."""
    return [{
        'file': '.github/workflows/target.yml',
        'action': 'custom_action',
        'description': 'What this fix does',
        'changes': {
            # YAML changes here
        },
    }]
```

### Workflow Exclusions

Exclude specific workflows from auto-healing:

```yaml
# In workflow-auto-fix-config.yml
excluded_workflows:
  - "Deploy to Production"
  - "Publish Release"
  - "Security Scan"
```

### Confidence Thresholds

Adjust when PRs are created:

```yaml
# Only create PR if confidence >= 80%
min_confidence_for_pr: 80

# Different thresholds per fix type
fix_types:
  add_dependency:
    confidence_threshold: 90
  fix_test:
    confidence_threshold: 60
```

## Limitations

### Current Limitations

1. **Pattern-Based**: Only detects known error patterns
2. **Single Fix**: One fix per PR (focused approach)
3. **YAML Focus**: Primarily fixes workflow files
4. **Limited Code Fixes**: Doesn't fix complex application logic
5. **No Multi-Repo**: Works within single repository
6. **Copilot Dependent**: Requires Copilot Agent access

### Planned Enhancements

- [ ] Machine learning for pattern detection
- [ ] Multi-fix PRs for related issues
- [ ] Application code fixes
- [ ] Cross-repository fix propagation
- [ ] Predictive failure prevention
- [ ] Fix success prediction
- [ ] Integration with external monitoring
- [ ] Custom Copilot models per project

## Comparison with Other Systems

### vs. Traditional Auto-Fix

| Feature | Traditional | Auto-Healing |
|---------|------------|--------------|
| Fix Implementation | Manual | Automatic |
| PR Review | Required | Optional* |
| Label Dependency | copilot-ready | None |
| Speed | Hours-Days | Minutes-Hours |
| Scalability | Limited | High |

*Human review still recommended for safety

### vs. Manual Fixing

| Feature | Manual | Auto-Healing |
|---------|--------|--------------|
| Speed | Slow | Fast |
| Consistency | Variable | High |
| Availability | Business Hours | 24/7 |
| Cost | High | Low |
| Learning | Yes | Yes (improves) |

## FAQ

**Q: Will Copilot automatically merge the fix?**  
A: No, all PRs require manual review and merge approval.

**Q: What if Copilot implements the wrong fix?**  
A: Close the PR, review manually, and provide feedback to improve patterns.

**Q: Can I disable auto-healing for specific workflows?**  
A: Yes, add workflows to `excluded_workflows` in config.

**Q: How accurate are the automatic fixes?**  
A: Accuracy varies by error type (70-95% confidence). Copilot adds an additional validation layer.

**Q: Does this work with private repositories?**  
A: Yes, requires Copilot license and appropriate permissions.

**Q: What if Copilot doesn't respond?**  
A: PR remains open with fix proposal. You can implement manually or close it.

**Q: Can I customize the Copilot task instructions?**  
A: Yes, modify the task file generation in the workflow.

**Q: How do I track auto-healing effectiveness?**  
A: Use the metrics script or check PR analytics with `auto-healing` label.

**Q: Is this safe for production workflows?**  
A: Yes, with proper branch protection and required reviews. No automatic merges.

**Q: Can Copilot fix complex issues?**  
A: Copilot works best with well-defined, focused fixes. Complex issues may require manual intervention.

## Support

### Documentation

- [Auto-Fix System](README-workflow-auto-fix.md)
- [Copilot Integration](COPILOT-INTEGRATION.md)
- [GitHub Actions Docs](https://docs.github.com/actions)
- [GitHub Copilot Docs](https://docs.github.com/copilot)

### Getting Help

1. Check workflow logs in Actions tab
2. Review artifacts for analysis details
3. Search existing issues
4. Create new issue with `auto-healing` label
5. Contact maintainers

### Reporting Issues

When reporting issues, include:
- Workflow run ID
- Failure analysis (from artifacts)
- PR URL (if created)
- Expected vs actual behavior
- Screenshots if applicable

## Contributing

Contributions welcome! Areas to help:

- Add new error patterns
- Improve fix generators
- Enhance Copilot task templates
- Write tests for auto-healing
- Improve documentation
- Share success stories

## License

Same as parent repository.

## Changelog

### Version 2.1.0 (2025-10-30)

**CRITICAL FIX: GitHub CLI Authentication**
- Fixed authentication issue causing auto-healing to fail silently
- Changed `GITHUB_TOKEN` to `GH_TOKEN` in all steps using `gh` CLI commands
- Resolves issue where workflow completed in 1-2 seconds without any actual work
- Enables proper workflow failure detection and PR creation

**Impact:**
This fix enables the auto-healing system to:
- Successfully authenticate with GitHub API
- Retrieve workflow run details and logs
- Create PRs for Copilot Agent to implement fixes
- Properly mention @copilot in PRs and comments

**Files Modified:**
- `.github/workflows/copilot-agent-autofix.yml` - 5 instances fixed

### Version 2.0.0 (2025-10-29)

- 🚀 Initial release of Auto-Healing system
- 🤖 Full Copilot Agent integration
- ✨ Automatic fix implementation
- 🎯 No manual label required
- 📝 Detailed task files for Copilot
- 🔄 Self-healing workflow loop
- 📊 Enhanced monitoring and metrics
- 🔒 Security-first design
- 📚 Comprehensive documentation

---

**Happy Auto-Healing!** 🤖✨🚀
