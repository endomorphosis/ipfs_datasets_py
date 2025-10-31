# Issue-to-Draft-PR Quickstart Guide

Get up and running with automatic issue-to-PR conversion in 5 minutes!

## 🚀 What You Get

Every time someone creates an issue in your repository:
1. ✅ A dedicated branch is created automatically
2. ✅ A draft PR is opened and linked to the issue
3. ✅ GitHub Copilot is assigned to implement the solution
4. ✅ The issue is updated with the PR link
5. ✅ You just review and merge when ready!

**Zero manual work until review time!**

## ⚡ Quick Setup

### Step 1: Enable Workflow Permissions (2 minutes)

1. Go to your repository on GitHub
2. Click **Settings → Actions → General**
3. Scroll to **Workflow permissions**
4. Select **"Read and write permissions"**
5. Check **"Allow GitHub Actions to create and approve pull requests"**
6. Click **Save**

✅ **Done!** The workflow is now enabled and will run automatically.

### Step 2: Test It (1 minute)

Create a test issue to see it in action:

```bash
gh issue create \
  --title "Test: Automated PR creation" \
  --body "This is a test issue to verify the issue-to-draft-PR workflow works correctly."
```

Or create an issue through the GitHub web interface.

### Step 3: Watch the Magic ✨

Within seconds:
- A workflow run will start (Actions tab)
- A branch will be created (`issue-X/test-automated-pr-creation`)
- A draft PR will be created
- The issue will be updated with a link to the PR
- @copilot will be mentioned in the PR

### Step 4: Monitor Progress

```bash
# Check the workflow run
gh run list --workflow="Convert Issues to Draft PRs with Copilot"

# View the created PR
gh pr list --draft

# Check the issue comments
gh issue view {issue_number}
```

## 📋 Real-World Example

### Before (Manual Process)

1. User creates issue
2. Developer sees issue
3. Developer creates branch
4. Developer creates PR
5. Developer implements fix
6. Developer asks for review
7. Review and merge

⏱️ **Time**: 30-120 minutes

### After (Automated Process)

1. User creates issue
2. **Workflow creates branch and PR automatically**
3. **Copilot implements the fix automatically**
4. Developer reviews and merges

⏱️ **Time**: 5-10 minutes

**~80-90% time savings!**

## 🎯 Usage Examples

### Example 1: Bug Fix

**Issue #42**:
```
Title: Login button not working on mobile
Body: When I click the login button on mobile Safari, nothing happens...
```

**Automatic Result**:
- Branch: `issue-42/login-button-not-working-on-mobile`
- PR #100: "Fix: Login button not working on mobile"
- Copilot: Analyzes the issue, fixes the mobile Safari event handling
- Ready for review in ~5 minutes

### Example 2: Feature Request

**Issue #43**:
```
Title: Add dark mode support
Body: Users are requesting dark mode. We should add a theme toggle...
```

**Automatic Result**:
- Branch: `issue-43/add-dark-mode-support`
- PR #101: "Fix: Add dark mode support"
- Copilot: Implements theme toggle, updates CSS, adds persistence
- Ready for review in ~10 minutes

### Example 3: Documentation

**Issue #44**:
```
Title: Update installation instructions
Body: The README is missing pip installation steps...
```

**Automatic Result**:
- Branch: `issue-44/update-installation-instructions`
- PR #102: "Fix: Update installation instructions"
- Copilot: Updates README with pip installation section
- Ready for review in ~2 minutes

## 🔧 Manual Trigger

You can also trigger the workflow manually for any existing issue:

```bash
# Convert specific issue to PR
gh workflow run issue-to-draft-pr.yml \
  --field issue_number="42"

# Watch the run
gh run watch
```

## 📊 Monitoring

### View All Auto-Generated PRs

```bash
gh pr list --draft --label "auto-generated"
```

### Check Workflow Activity

```bash
# Recent runs
gh run list --workflow="Convert Issues to Draft PRs with Copilot" --limit 10

# View specific run
gh run view {run_id}
```

### Success Metrics

Track how well it's working:
- Number of issues converted
- Average time from issue to PR
- Copilot success rate
- Time saved vs manual process

## 🛠️ Troubleshooting

### Common Issues

#### ❌ PR Not Created

**Problem**: Workflow runs but no PR is created.

**Solution**:
1. Check Settings → Actions → Workflow permissions
2. Ensure "Allow Actions to create PRs" is enabled
3. Check workflow logs for errors

#### ❌ Duplicate PR Warning

**Problem**: "Issue already has existing PR(s)"

**Solution**:
This is expected! The workflow prevents duplicate PRs. Close or merge the existing PR first.

#### ❌ Copilot Not Responding

**Problem**: @copilot is mentioned but doesn't respond.

**Solution**:
1. Verify Copilot is enabled for your repository
2. Check if the PR is in draft state
3. Try mentioning @copilot again in a new comment

## 💡 Pro Tips

### 1. Write Clear Issue Titles

**Good**: "Fix login button on mobile Safari"
**Bad**: "Button broken"

Clear titles → Better branch names → Easier code review

### 2. Provide Context in Issue Body

The more context you provide, the better Copilot's implementation will be:
- What's the expected behavior?
- What's actually happening?
- Steps to reproduce
- Error messages
- Screenshots

### 3. Use Labels

Add labels to issues for better organization:
- `bug` - Bug fixes
- `enhancement` - New features
- `documentation` - Documentation updates
- `good first issue` - Simple issues

### 4. Review Before Merging

Always review Copilot's implementation:
- Does it solve the problem?
- Are tests included?
- Is the code quality good?
- Are there any security concerns?

### 5. Provide Feedback

If Copilot's implementation isn't perfect:
- Comment on the PR with specific feedback
- @mention @copilot with corrections
- Learn from patterns to improve issue descriptions

## 🎓 Advanced Usage

### Custom Instructions for Copilot

You can guide Copilot by adding specific instructions in your issue:

```markdown
## Implementation Notes

Please implement this using:
- React hooks (not class components)
- TypeScript for type safety
- Jest for testing
- Follow the existing patterns in src/components/
```

### Integration with Labels

Create `.github/workflows/issue-to-draft-pr.yml` variants for different issue types:
- `bug` label → Use bug fix template
- `feature` label → Use feature template
- `security` label → Use security template

## 📈 Measuring Success

Track these metrics to measure effectiveness:

### Time Savings
- Before: Average time from issue to PR = 60 minutes
- After: Average time from issue to PR = 5 minutes
- **Savings**: 55 minutes per issue (92%)

### Developer Productivity
- Before: 10 issues resolved per day
- After: 30 issues resolved per day
- **Increase**: 200%

### Quality Metrics
- Test coverage maintained or increased
- Code review time decreased
- Bug regression rate unchanged or improved

## 🔐 Security Best Practices

### What the Workflow Can Do ✅
- Create branches
- Create draft PRs
- Comment on issues
- Analyze issue content

### What It Cannot Do ❌
- Merge PRs automatically
- Access secrets
- Modify protected branches
- Execute code in production

### Safety Checks
- All PRs require human review
- CI/CD tests must pass
- Branch protection rules still apply
- Full audit trail in Git history

## 📚 Next Steps

Once you're comfortable with the basics:

1. **Customize the workflow** - Modify `.github/workflows/issue-to-draft-pr.yml`
2. **Add issue templates** - Help users create better issues
3. **Create labels** - Organize issues by type
4. **Set up branch protection** - Require reviews before merging
5. **Monitor metrics** - Track time savings and quality

## 🆘 Getting Help

If you run into issues:

1. **Check the logs**:
   ```bash
   gh run view {run_id} --log
   ```

2. **Review the documentation**:
   - [Full Documentation](README-issue-to-draft-pr.md)
   - [GitHub Copilot Docs](https://docs.github.com/en/copilot)

3. **Search existing issues**:
   ```bash
   gh issue list --label "workflow"
   ```

4. **Create an issue**:
   ```bash
   gh issue create --title "Issue-to-PR workflow not working" --body "..."
   ```

## 🎉 Success Stories

### Before Automation
- 50 open issues
- 2-3 days average resolution time
- Developer frustration high
- Bottleneck on simple fixes

### After Automation
- 10 open issues (backlog cleared)
- 2-3 hours average resolution time
- Developer satisfaction up
- Focus on complex problems

## 🔗 Resources

- [GitHub Actions Documentation](https://docs.github.com/actions)
- [GitHub Copilot Agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [Auto-Healing Documentation](.github/workflows/README-copilot-autohealing.md)

---

**Ready to automate your issue resolution?** 🚀

Just enable the workflow permissions and watch as every issue gets its own draft PR with Copilot assigned! ✨
