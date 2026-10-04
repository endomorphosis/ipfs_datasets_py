# Visual Guide: Draft PR Spam Fix

## The Problem: Feedback Loop

```
┌──────────────────────────────────────────────────────────┐
│                    BEFORE THE FIX                         │
└──────────────────────────────────────────────────────────┘

    Workflow Failure
         │
         ↓
    ┌─────────────────────┐
    │ copilot-agent-      │
    │ autofix.yml         │
    └─────────┬───────────┘
              │
              ├─→ Creates Issue #100 ─────────────┐
              │   "Fix: workflow failure"         │
              │   "Auto-generated..."             │
              │                                    │
              └─→ Creates PR #200 ─────────┐      │
                  (autofix branch)         │      │
                                           │      │
                                           │      ↓
                                           │   ┌──────────────────┐
                                           │   │ issue-to-draft-  │
                                           │   │ pr.yml TRIGGERS  │
                                           │   └────────┬─────────┘
                                           │            │
                                           │            └─→ Creates PR #201
                                           │                (issue-100 branch)
                                           │
                                           ↓
                        ❌ RESULT: 2 PRs per failure!
                        
        10 workflow failures × 2 PRs each = 20 PRs
        Repeat overnight = 100+ PRs 💥
```

## The Solution: Break the Loop

```
┌──────────────────────────────────────────────────────────┐
│                    AFTER THE FIX                          │
└──────────────────────────────────────────────────────────┘

    Workflow Failure
         │
         ↓
    ┌─────────────────────┐
    │ copilot-agent-      │
    │ autofix.yml         │
    └─────────┬───────────┘
              │
              ├─→ Creates Issue #100 ─────────────┐
              │   "Fix: workflow failure"         │
              │   "Auto-generated..."             │
              │                                    │
              └─→ Creates PR #200 ─────────┐      │
                  (autofix branch)         │      │
                                           │      ↓
                                           │   ┌──────────────────┐
                                           │   │ issue-to-draft-  │
                                           │   │ pr.yml           │
                                           │   └────────┬─────────┘
                                           │            │
                                           │            ├─→ Check: Auto-generated?
                                           │            │   YES: Title has "Fix:"
                                           │            │        Body has "Auto-generated"
                                           │            │
                                           │            └─→ ✅ SKIP (no PR created)
                                           │
                                           ↓
                        ✅ RESULT: 1 PR per failure!
                        
        10 workflow failures × 1 PR each = 10 PRs
        Manageable! ✨
```

## Rate Limiting Protection

```
┌──────────────────────────────────────────────────────────┐
│              RATE LIMITING (Backup Protection)            │
└──────────────────────────────────────────────────────────┘

                    issue-to-draft-pr.yml
                            │
                            ↓
                    ┌───────────────────┐
                    │ Check: How many   │
                    │ PRs in last hour? │
                    └─────────┬─────────┘
                              │
                ┌─────────────┼─────────────┐
                │                           │
                ↓                           ↓
        ┌──────────────┐           ┌──────────────┐
        │ < 10 PRs     │           │ ≥ 10 PRs     │
        └──────┬───────┘           └──────┬───────┘
               │                          │
               ↓                          ↓
        ✅ Proceed              ❌ SKIP - Rate Limit
        Create PR                 "Too many PRs/hour"

   Even if detection fails, rate limit prevents spam!
```

## Stale PR Cleanup

```
┌──────────────────────────────────────────────────────────┐
│               AUTOMATIC CLEANUP (Every 6h)                │
└──────────────────────────────────────────────────────────┘

    Scheduler (runs every 6 hours)
         │
         ↓
    ┌─────────────────────┐
    │ close-stale-draft-  │
    │ prs.yml             │
    └─────────┬───────────┘
              │
              ↓
    Get all open draft PRs
              │
              ↓
    ┌─────────────────────────────────────┐
    │ For each PR, check:                 │
    │ 1. Created by github-actions[bot]?  │
    │ 2. Age > 48 hours?                  │
    │ 3. No activity?                     │
    └─────────┬───────────────────────────┘
              │
    ┌─────────┼─────────┐
    │         │         │
    ↓         ↓         ↓
   YES       NO        ...
    │         │
    │         └─→ Keep PR
    │
    └─→ Close with comment:
        "Stale draft PR closed automatically"
        "No activity for 48+ hours"

   Keeps the PR list clean automatically!
```

## Complete Flow Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                        COMPLETE SYSTEM                              │
└────────────────────────────────────────────────────────────────────┘

                    Workflow Failure
                           │
            ┌──────────────┴──────────────┐
            │                             │
            ↓                             ↓
    copilot-agent-autofix          (existing checks)
            │                             │
            ├─ Create Issue               │
            │  (auto-generated)           │
            │                             │
            └─ Create PR #1               │
                    │                     │
                    │                     ↓
                    │              Other workflows
                    │              may fail too
                    │                     │
                    ↓                     │
            issue-to-draft-pr.yml ←──────┘
                    │
                    ├─ 🛡️ Check: Auto-gen? → YES → Skip ✅
                    ├─ 🛡️ Check: Rate limit? → OK → Proceed
                    ├─ 🛡️ Check: Dup exists? → NO → Create PR #2
                    │
                    ↓
            Manual issues get PRs
            (not auto-generated)
                    │
                    ↓
            ┌──────────────────────┐
            │ All Draft PRs        │
            │ (both auto & manual) │
            └──────────┬───────────┘
                       │
            Every 6h   │
                       ↓
            close-stale-draft-prs.yml
                       │
                       ├─ Find stale auto PRs
                       ├─ Close with comment
                       └─ Keep fresh PRs
                       
                    Result:
                    ✅ Clean PR list
                    ✅ No spam
                    ✅ Manageable queue
```

## Key Protections

| Layer | Protection | Prevents |
|-------|-----------|----------|
| 🛡️ **Layer 1** | Auto-gen detection | Feedback loop (100+ PRs) |
| 🛡️ **Layer 2** | Rate limiting | Any spam scenario (>10/h) |
| 🛡️ **Layer 3** | Duplicate detection | Multiple PRs for same issue |
| 🧹 **Layer 4** | Stale cleanup | Abandoned PRs accumulating |

## Before vs After

| Metric | Before | After |
|--------|--------|-------|
| PRs per workflow failure | 2+ | 1 |
| Maximum PR burst | Unlimited | 10/hour |
| Stale PR accumulation | ∞ | Auto-cleaned |
| Manual intervention | Required | Optional |
| Risk of spam | High ⚠️ | Low ✅ |

## Quick Actions

### Immediate Cleanup
```bash
# See what would be closed
python scripts/close_stale_draft_prs.py --dry-run

# Close all auto-generated PRs
python scripts/close_stale_draft_prs.py --max-age-hours 0
```

### Monitor Health
```bash
# Check current draft PR count
gh pr list --state open --draft | wc -l

# Should be: 0-10 PRs ✅
# If >20 PRs: Investigate! ⚠️
```

### Verify Fix Works
```bash
# Run test suite
python tests/test_draft_pr_spam_prevention.py

# All tests should pass ✅
```

---

**Summary**: Multiple layers of protection prevent the 100+ PR spam from happening again! 🎉
