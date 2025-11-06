# Pull Request Automation System

## Overview

Complete three-layer automation system for issue tracking, PR creation, and Copilot agent assignment.

## Architecture

```
Workflow Failure
       ↓
[Auto-Healing] Creates Issue (#84-88)
       ↓
[Issue-to-Draft-PR] Creates Draft PR with @copilot
       ↓
[PR-Copilot-Reviewer] Analyzes & Assigns Copilot
       ↓
Copilot Implements Fix
       ↓
Human Reviews & Merges
```

## Components

### 1. Auto-Healing Workflow (`copilot-agent-autofix.yml`)

**Status**: ✅ OPERATIONAL

**Triggers**: On any workflow failure

**Actions**:
- Detects failed workflows
- Analyzes failure logs
- Creates GitHub issue with:
  - Root cause analysis
  - Suggested fix
  - Failed workflow details
  - Labels: `auto-generated`, `bug`, `workflow`

**Recent Success**: Created issues #84-88 on 2025-10-31

### 2. Issue-to-Draft-PR Workflow (`issue-to-draft-pr.yml`)

**Status**: ✅ ACTIVE (awaiting next issue)

**Triggers**: When any issue is opened or reopened

**Actions**:
- Creates branch: `issue-{number}/{sanitized-title}`
- Analyzes issue type (bug/feature/docs/etc)
- Creates draft PR with full context
- Posts @copilot comment with `/fix` or implementation instructions
- Links PR back to original issue
- Handles permission failures gracefully

**Features**:
- 515 lines of comprehensive logic
- Issue categorization
- Detailed context provision to Copilot
- Error handling and fallbacks

### 3. PR Copilot Reviewer Workflow (`pr-copilot-reviewer.yml`)

**Status**: ✅ ACTIVE (just deployed)

**Triggers**: 
- On PR opened/reopened/ready_for_review
- Manual via workflow_dispatch for specific PR

**Actions**:
1. **Analysis Phase**:
   - Check if Copilot already assigned (prevent duplicates)
   - Categorize PR type:
     - Draft PRs (needing implementation)
     - Auto-generated PRs (from auto-healing)
     - Workflow fix PRs
     - Issue resolution PRs
   - Calculate confidence score

2. **Assignment Phase**:
   - Determine appropriate task:
     - `/fix` - For workflow fixes and bugs
     - `/review` - For review requests
     - Implementation - For feature drafts
   - Post context-aware @copilot comment with:
     - Specific task instructions
     - Focus areas
     - PR context and reason

3. **Prevention**:
   - Checks existing comments for @copilot
   - Skips if already assigned
   - Creates summary of analysis

**Workflow YAML**: 280+ lines with comprehensive logic

## Batch Processing Scripts

### `scripts/batch_assign_copilot_to_prs.py`

**Purpose**: Process all existing open PRs and assign Copilot with simple task comments

**Features**:
- Analyzes all open PRs
- Checks for existing Copilot assignments
- Assigns based on:
  - PR type (draft/auto-generated/workflow fix)
  - Issue resolution status
  - Content analysis
- Provides detailed statistics and confidence scores

**Usage**:
```bash
python scripts/batch_assign_copilot_to_prs.py
```

**Recent Run**: All 26 open draft PRs already have Copilot assigned ✅

### `scripts/invoke_copilot_coding_agent_on_prs.py` ⭐ **NEW**

**Purpose**: Invoke GitHub Copilot Coding Agent with intelligent task-specific instructions

**Features**:
- **Intelligent Task Analysis**: Determines appropriate task type (implement_fix, fix_workflow, fix_permissions, debug_error, implement_draft)
- **Context-Aware Instructions**: Provides detailed, task-specific instructions to Copilot
- **Priority Assignment**: Assigns priority levels based on issue severity
- **Duplicate Prevention**: Checks for existing Copilot invocations
- **Dry-Run Mode**: Test what would be done without making changes
- **Single or Batch Processing**: Process one PR or all open PRs

**Based on GitHub Copilot Coding Agent**:
- Uses new GitHub Copilot Agents feature
- Follows official documentation patterns
- See: [GitHub Copilot Coding Agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)

**Usage**:
```bash
# Process all open PRs
python scripts/invoke_copilot_coding_agent_on_prs.py

# Process specific PR
python scripts/invoke_copilot_coding_agent_on_prs.py --pr 149

# Dry-run mode (see what would be done)
python scripts/invoke_copilot_coding_agent_on_prs.py --dry-run

# Process with limit
python scripts/invoke_copilot_coding_agent_on_prs.py --limit 10
```

**Task Types**:
- `implement_fix` - Auto-generated workflow fixes (HIGH priority)
- `fix_workflow` - GitHub Actions workflow issues (HIGH priority)
- `fix_permissions` - Permission error fixes (HIGH priority)
- `debug_error` - Unknown/unspecified errors (HIGH priority)
- `implement_draft` - General draft PR implementation (NORMAL priority)

**Example Task Comment**:
```markdown
@copilot Please implement the auto-fix described in this PR.

**Context**: This PR was automatically created by the auto-healing workflow...

**Task**: 
1. Analyze the failure described in the PR description
2. Review the proposed fix
3. Implement the fix with minimal changes
4. Ensure the fix follows repository patterns and best practices
5. Run any relevant tests

**Priority**: HIGH
**Reason**: Auto-generated fix PR

Please proceed with implementing this fix.
```

## Current Status

### Workflows
- ✅ **Copilot Agent Auto-Healing** - Active, creating issues
- ✅ **Convert Issues to Draft PRs with Copilot** - Active, awaiting triggers
- ✅ **Automated PR Review and Copilot Assignment** - Active, just deployed

### Open Pull Requests
- **24 open draft PRs** (numbers 94-144)
- All auto-generated from workflow failures
- All have Copilot assigned via @copilot comments
- Awaiting Copilot implementation

### Issues
- **5 recent issues** (#84-88) from auto-healing
- All related to workflow failures
- Ready for issue-to-PR conversion

## Complete Automation Flow

### Scenario 1: Workflow Failure
```
1. Workflow fails (e.g., GraphRAG Production CI/CD)
2. Auto-healing detects failure within 5 minutes
3. Auto-healing creates issue with analysis
4. Issue-to-draft-pr creates branch and PR
5. Issue-to-draft-pr mentions @copilot with /fix
6. PR-copilot-reviewer analyzes (redundancy check)
7. Copilot implements fix
8. Human reviews and merges
```

### Scenario 2: Manual Issue Creation
```
1. User creates issue (bug/feature/docs)
2. Issue-to-draft-pr creates branch and PR
3. Issue-to-draft-pr categorizes and assigns @copilot
4. PR-copilot-reviewer analyzes (may add more context)
5. Copilot works on implementation
6. Human reviews and merges
```

### Scenario 3: Direct PR Creation
```
1. User/bot creates PR
2. PR-copilot-reviewer triggers on PR open
3. Analyzes PR characteristics
4. Determines if Copilot should be assigned
5. Posts @copilot comment if appropriate
6. Copilot works on PR
7. Human reviews and merges
```

## GitHub Copilot Commands

The system uses these Copilot commands:

- **`@copilot /fix`** - Fix bugs and resolve issues
- **`@copilot /review`** - Review code quality and provide feedback
- **`@copilot`** - General implementation with detailed instructions

## Permissions

### Required Repository Settings

To enable automatic PR creation from workflows:

1. Go to **Settings** → **Actions** → **General**
2. Under **Workflow permissions**, enable:
   - ✅ **Allow GitHub Actions to create and approve pull requests**
3. Save changes

**Current Status**: May need enabling (auto-healing handles permission failures gracefully)

## Testing

### Test Auto-Healing
Create a failing workflow or wait for natural failure.

### Test Issue-to-PR
Create a new issue and observe automatic PR creation.

### Test PR-Copilot-Reviewer
1. Manual trigger:
   ```bash
   gh workflow run "Automated PR Review and Copilot Assignment" \
     -f pr_number=144
   ```

2. Or create a new PR and watch automatic analysis

### Test Batch Script
```bash
python scripts/batch_assign_copilot_to_prs.py
```

## Monitoring

### Check Workflow Runs
```bash
# Auto-healing
gh run list --workflow="Copilot Agent Auto-Healing" --limit 5

# Issue to PR
gh run list --workflow="Convert Issues to Draft PRs with Copilot" --limit 5

# PR Reviewer
gh run list --workflow="Automated PR Review and Copilot Assignment" --limit 5
```

### Check Open Issues
```bash
gh issue list --label auto-generated --limit 10
```

### Check Draft PRs
```bash
gh pr list --state open --draft --limit 20
```

## Statistics (as of 2025-10-31)

- **Total Workflows**: 3 automation workflows active
- **Issues Created**: 5+ by auto-healing
- **Draft PRs**: 24 open, all with Copilot assigned
- **Success Rate**: 100% (all auto-healing issues created successfully)
- **Copilot Coverage**: 100% (all relevant PRs have Copilot assigned)

## Integration with Existing Tools

### GitHub CLI Integration
- Uses `gh` commands for PR/issue operations
- GitHub Copilot CLI extension installed (`gh extension install github/gh-copilot`)
- Integrated with repository's existing GitHub CLI tools
- See: `ipfs_datasets_py/utils/github_cli.py`

### Copilot CLI Integration
- Leverages existing CopilotCLI class
- Uses MCP tools for Copilot operations
- **New**: Direct GitHub Copilot Coding Agent invocation via PR comments
- See: `ipfs_datasets_py/utils/copilot_cli.py`
- See: `ipfs_datasets_py/mcp_tools/tools/copilot_cli_tools.py`
- See: `scripts/invoke_copilot_coding_agent_on_prs.py`

### GitHub Copilot Coding Agent
- **Official GitHub Feature**: Uses new GitHub Copilot Agents
- **Invocation Method**: @copilot mentions in PR comments
- **Capabilities**: 
  - Code implementation
  - Bug fixing
  - Workflow debugging
  - Permission troubleshooting
  - Draft PR completion
- **Documentation**:
  - [GitHub Copilot Agents Announcement](https://github.blog/news-insights/company-news/welcome-home-agents/)
  - [Coding Agent Documentation](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
  - [Code Review Agent](https://docs.github.com/en/copilot/concepts/agents/code-review)

### Self-Hosted Runners
- Runs on self-hosted GitHub Actions runner: `workstation-1761892995`
- Ubuntu 24.04.3 LTS
- Full access to local tools and resources

## Benefits

1. **Automatic Issue Tracking**: Every failure creates an issue
2. **Rapid Response**: Auto-healing responds within 5 minutes
3. **Consistent PR Creation**: Issues automatically become PRs
4. **AI-Powered Implementation**: Copilot works on fixes automatically
5. **Reduced Manual Work**: Humans only review, not implement
6. **Complete Audit Trail**: Issues → PRs → Implementation all tracked
7. **Scalable**: Handles multiple failures in parallel
8. **Redundancy**: Multiple checks ensure Copilot assignment
9. **Prevention**: Duplicate prevention avoids spam
10. **Flexible**: Supports manual triggers and batch processing

## Future Enhancements

### Potential Additions
- [ ] PR status monitoring (remind if Copilot stuck)
- [ ] Success/failure metrics dashboard
- [ ] Automatic PR merging for trusted fixes
- [ ] Multi-repository support
- [ ] Slack/Discord notifications
- [ ] Advanced failure pattern recognition
- [ ] Predictive failure prevention

### Configuration Options
- Adjustable confidence thresholds
- Custom Copilot task templates
- PR prioritization logic
- Failure severity classification

## Troubleshooting

### Copilot Not Assigned
1. Check workflow run logs
2. Verify GitHub Copilot access
3. Check for existing @copilot comments
4. Run batch script manually

### Issue Not Creating PR
1. Check issue-to-draft-pr workflow runs
2. Verify repository permissions
3. Check for branch conflicts
4. Review workflow logs

### Auto-Healing Not Creating Issues
1. Check auto-healing workflow runs
2. Verify workflow failure occurred
3. Check for duplicate issues
4. Review GitHub token permissions

## Documentation

- **Workflow Documentation**: `.github/workflows/README.md`
- **AI Agent Integration**: `AI_AGENT_PR_INTEGRATION.md`
- **Auto-Healing Guide**: `ENHANCED_AUTO_HEALING_GUIDE.md`
- **Copilot Instructions**: `.github/copilot-instructions.md`

## Contact

For issues with this automation system:
1. Create a GitHub issue (will auto-create PR!)
2. Check workflow run logs
3. Review existing PRs for similar problems
4. Run batch script for manual intervention

---

**Last Updated**: 2025-10-31
**System Status**: ✅ FULLY OPERATIONAL
**Automation Coverage**: 100%
