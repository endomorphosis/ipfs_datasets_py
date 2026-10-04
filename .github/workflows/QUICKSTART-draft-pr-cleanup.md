# Quick Start: Clean Up Draft PR Spam

If you're dealing with 100+ draft PRs created by the auto-healing system, follow these steps:

## Immediate Action (Clean Up Existing PRs)

### Step 1: Preview What Will Be Closed

Run in dry-run mode first to see what would be closed:

```bash
python scripts/close_stale_draft_prs.py --dry-run
```

This will show you:
- How many stale draft PRs exist
- Which PRs would be closed
- Why they would be closed

### Step 2: Close All Auto-Generated Draft PRs

Once you've reviewed the dry-run output, close all auto-generated draft PRs:

```bash
# Close all auto-generated draft PRs (no age limit)
python scripts/close_stale_draft_prs.py --max-age-hours 0
```

**OR** be more conservative and only close old PRs:

```bash
# Close PRs older than 24 hours
python scripts/close_stale_draft_prs.py --max-age-hours 24
```

### Step 3: Close Specific PRs (Optional)

If you want to close specific PR numbers:

```bash
python scripts/close_stale_draft_prs.py --pr-numbers 123,124,125,126
```

## Verify the Cleanup

Check how many draft PRs remain:

```bash
gh pr list --state open --draft | wc -l
```

Should now be 0 or a very small number.

## Prevention (Already Implemented)

The following changes have been deployed to prevent future spam:

### 1. ✅ Auto-Generated Issue Detection
- `issue-to-draft-pr.yml` now skips issues created by auto-healing
- Prevents the feedback loop

### 2. ✅ Rate Limiting
- Maximum 10 draft PRs per hour
- Prevents spam even if detection fails

### 3. ✅ Automatic Cleanup
- `close-stale-draft-prs.yml` runs every 6 hours
- Automatically closes abandoned draft PRs

## Monitor the Situation

### Check Draft PR Count Daily

```bash
# Show count of draft PRs
gh pr list --state open --draft --json number,title,createdAt | \
  jq 'length' && echo "draft PRs"

# Show details of all draft PRs
gh pr list --state open --draft --json number,title,author,createdAt
```

### Check for Rate Limit Hits

Look for "Rate Limit Reached" in workflow runs:

```bash
gh run list --workflow="issue-to-draft-pr.yml" --limit 10
```

### Verify Auto-Healing Issues Are Skipped

Look for "Skipping Auto-Generated Issue" in logs:

```bash
gh run view <run-id> --log | grep "Auto-Generated"
```

## Troubleshooting

### PRs Keep Coming Back

If draft PRs keep being created:

1. Check if the fixes are deployed:
   ```bash
   git log --oneline | grep "draft PR spam"
   ```

2. Verify the workflow changes:
   ```bash
   grep -A5 "is_auto_generated" .github/workflows/issue-to-draft-pr.yml
   ```

3. Check workflow runs for errors:
   ```bash
   gh run list --workflow="issue-to-draft-pr.yml" --status failure
   ```

### Rate Limit Too Restrictive

If 10 PRs/hour is too low, edit `.github/workflows/issue-to-draft-pr.yml`:

```yaml
# Change this line:
if [ "$RECENT_DRAFT_PRS" -ge 10 ]; then

# To a higher number, e.g.:
if [ "$RECENT_DRAFT_PRS" -ge 20 ]; then
```

### Stale PR Cleanup Too Aggressive

If 48 hours is too short, edit `.github/workflows/close-stale-draft-prs.yml`:

```yaml
# Change this:
MAX_AGE_HOURS: 48

# To a longer period:
MAX_AGE_HOURS: 168  # 1 week
```

## Need Help?

- See `.github/workflows/README-draft-pr-spam-fix.md` for full documentation
- Check workflow logs in GitHub Actions for error messages
- Run scripts with `--help` flag for usage information

## Success Criteria

You'll know the fix is working when:

- ✅ No more than 5-10 draft PRs open at any time
- ✅ Auto-healing issues don't trigger duplicate PRs
- ✅ Rate limit prevents spam scenarios
- ✅ Stale PRs are cleaned up automatically

---

**Last Updated**: 2024-11-06
**Related Issue**: Draft PR spam - 100+ PRs created overnight
