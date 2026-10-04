# Draft PR Spam Prevention and Cleanup

## Problem

The auto-healing system created 100+ draft PRs overnight due to a feedback loop:

1. **copilot-agent-autofix.yml** detects workflow failures → creates issues
2. **issue-to-draft-pr.yml** triggers on ALL issues (including auto-generated ones) → creates draft PRs
3. This created 2+ PRs per workflow failure
4. Multiple workflow failures overnight = 100+ draft PRs asking for completion

## Solution

### 1. Prevent Auto-Generated Issue PRs

**File**: `.github/workflows/issue-to-draft-pr.yml`

**Changes**:
- Added detection for auto-generated issues from auto-healing system
- Skips creating PRs for issues with titles like "Fix:" or containing "auto-healing" in body
- This prevents the feedback loop where auto-healing creates issues that trigger more PRs

### 2. Rate Limiting

**File**: `.github/workflows/issue-to-draft-pr.yml`

**Changes**:
- Added rate limiting: maximum 10 draft PRs per hour
- Prevents spam even if detection fails
- Workflow will skip PR creation if rate limit is reached

### 3. Automatic Stale PR Cleanup

**File**: `.github/workflows/close-stale-draft-prs.yml`

**Purpose**: Automatically close abandoned draft PRs

**Schedule**: Runs every 6 hours

**Behavior**:
- Finds draft PRs created by github-actions[bot]
- Closes PRs with no activity for 48+ hours
- Posts explanatory comment before closing
- Only affects auto-generated PRs

### 4. Manual Cleanup Script

**File**: `scripts/close_stale_draft_prs.py`

**Purpose**: Manually close existing stale draft PRs

**Usage**:

```bash
# Dry run - see what would be closed (RECOMMENDED FIRST)
python scripts/close_stale_draft_prs.py --dry-run

# Close PRs older than 24 hours
python scripts/close_stale_draft_prs.py --max-age-hours 24

# Close all auto-generated draft PRs (use to clean up the 100+ PRs)
python scripts/close_stale_draft_prs.py --max-age-hours 0

# Close specific PR numbers
python scripts/close_stale_draft_prs.py --pr-numbers 123,124,125
```

## Quick Fix for Current 100+ PRs

To clean up the existing 100+ draft PRs:

```bash
# Step 1: Dry run to see what would be closed
python scripts/close_stale_draft_prs.py --dry-run

# Step 2: Review the output, then close all auto-generated PRs
python scripts/close_stale_draft_prs.py --max-age-hours 0

# Alternative: Close only PRs older than 1 hour (safer)
python scripts/close_stale_draft_prs.py --max-age-hours 1
```

## How It Works Now

### Auto-Healing Workflow

**copilot-agent-autofix.yml**:
1. ✅ Detects workflow failure
2. ✅ Creates issue with failure details
3. ✅ Creates its own draft PR (ONE PR per failure)
4. ✅ Invokes Copilot on the PR

### Issue-to-Draft-PR Workflow

**issue-to-draft-pr.yml**:
1. ✅ Detects new issue
2. ✅ **NEW**: Checks if issue is auto-generated → SKIP if true
3. ✅ **NEW**: Checks rate limit (max 10/hour) → SKIP if exceeded
4. ✅ Checks for existing PRs → SKIP if exists
5. ✅ Creates draft PR only for manual issues

### Result

- **Before**: 2+ PRs per workflow failure (feedback loop)
- **After**: 1 PR per workflow failure (from auto-healing only)
- **Protection**: Rate limiting prevents any spam scenario
- **Cleanup**: Automatic and manual tools to close stale PRs

## Verification

After deploying these changes:

1. **Check rate limiting works**:
   ```bash
   # Should show rate limit check in logs
   gh run view --log <run-id>
   ```

2. **Verify auto-generated issues are skipped**:
   ```bash
   # Look for "Skipping Auto-Generated Issue" in workflow logs
   gh run list --workflow="issue-to-draft-pr.yml"
   ```

3. **Monitor stale PR cleanup**:
   ```bash
   # Check cleanup workflow runs
   gh run list --workflow="close-stale-draft-prs.yml"
   ```

4. **Check current draft PR count**:
   ```bash
   gh pr list --state open --draft | wc -l
   ```

## Testing

### Test Auto-Generated Issue Detection

1. Auto-healing creates an issue with "Fix:" prefix
2. Issue-to-draft-pr should skip it with message in logs
3. No duplicate PR should be created

### Test Rate Limiting

1. Create 10 issues rapidly
2. 11th issue should be skipped with rate limit message
3. After 1 hour, rate limit should reset

### Test Stale PR Cleanup

1. Run workflow manually with dry-run:
   ```bash
   gh workflow run close-stale-draft-prs.yml -f dry_run=true -f max_age_hours=48
   ```

2. Check workflow logs for what would be closed

3. Run without dry-run to actually close PRs

## Monitoring

### Key Metrics to Watch

1. **Draft PR count**: Should stay low (<10 at any time)
   ```bash
   gh pr list --state open --draft --json number,title,createdAt
   ```

2. **Auto-healing issues**: Should NOT create duplicate PRs
   ```bash
   gh issue list --label "auto-healing" --json number,title
   ```

3. **Rate limit hits**: Check workflow logs for rate limit messages

### Alerts

Consider setting up alerts for:
- More than 20 draft PRs open
- Rate limit hit more than 5 times per day
- Stale PR cleanup failing

## Rollback

If these changes cause issues:

1. **Disable issue-to-draft-pr workflow**:
   ```bash
   # Rename to disable
   mv .github/workflows/issue-to-draft-pr.yml .github/workflows/issue-to-draft-pr.yml.disabled
   ```

2. **Disable stale PR cleanup**:
   ```bash
   mv .github/workflows/close-stale-draft-prs.yml .github/workflows/close-stale-draft-prs.yml.disabled
   ```

3. **Revert changes**:
   ```bash
   git revert <commit-sha>
   ```

## Future Improvements

1. **Better PR consolidation**: Merge multiple fix attempts into one PR
2. **Smarter retry logic**: Don't create new PRs if previous fix failed for same reason
3. **PR success tracking**: Track which auto-generated PRs actually get completed
4. **Notification system**: Alert when auto-healing creates PRs that need attention

## Related Documentation

- `.github/workflows/README-copilot-autohealing.md` - Auto-healing system overview
- `.github/workflows/README-issue-to-draft-pr.md` - Issue-to-PR conversion
- `scripts/convert_draft_prs_to_issues.py` - Legacy PR conversion tool

## Questions?

If you encounter issues or have questions about this fix:

1. Check workflow logs for error messages
2. Review the summary sections in workflow runs
3. Try the dry-run mode first before making changes
4. Monitor the draft PR count daily for the first week
