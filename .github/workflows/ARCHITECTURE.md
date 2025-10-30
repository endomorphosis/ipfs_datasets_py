# Auto-Healing System Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          GitHub Actions Workflows                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  Docker  │  │   MCP    │  │   PDF    │  │   GPU    │  │  Tests   │    │
│  │  Build   │  │  Tests   │  │Processing│  │  Tests   │  │  Runner  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │             │             │             │             │            │
│       └─────────────┴─────────────┴─────────────┴─────────────┘            │
│                              │                                              │
│                         ❌ FAILURE                                          │
└──────────────────────────────┼──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Copilot Agent Auto-Healing System                         │
│                    (.github/workflows/copilot-agent-autofix.yml)             │
└─────────────────────────────────────────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌──────────────┐      ┌────────────────┐     ┌──────────────┐
│   DETECT     │      │    ANALYZE     │     │   PROPOSE    │
│              │      │                │     │              │
│ • Monitor    │─────▶│ • Get logs    │────▶│ • Generate   │
│   workflow   │      │ • Pattern     │     │   fix        │
│   failures   │      │   match       │     │ • Confidence │
│ • Filter     │      │ • Root cause  │     │   scoring    │
│   events     │      │ • Error type  │     │ • Branch     │
└──────────────┘      └────────────────┘     └──────┬───────┘
                                                    │
                                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CREATE COPILOT TASK                                  │
│                                                                              │
│  .github/copilot-tasks/fix-workflow-failure.md                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ # Fix Workflow Failure                                             │    │
│  │                                                                     │    │
│  │ ## Problem Statement                                               │    │
│  │ Workflow "Docker Build" failed with error...                       │    │
│  │                                                                     │    │
│  │ ## Analysis                                                         │    │
│  │ - Error Type: Missing Dependency                                   │    │
│  │ - Root Cause: pytest-asyncio not installed                         │    │
│  │ - Confidence: 90%                                                   │    │
│  │                                                                     │    │
│  │ ## Your Task                                                        │    │
│  │ 1. Add pytest-asyncio to requirements.txt                          │    │
│  │ 2. Update workflow install step                                    │    │
│  │ 3. Test the changes                                                │    │
│  │                                                                     │    │
│  │ ## Success Criteria                                                │    │
│  │ - Dependency installed                                             │    │
│  │ - Workflow runs successfully                                       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CREATE PULL REQUEST                                  │
│                                                                              │
│  Branch: autofix/docker-build/add-dependency/20251029                       │
│  Labels: auto-healing, automated-fix, workflow-fix                          │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ # 🤖 Automated Workflow Fix                                        │    │
│  │                                                                     │    │
│  │ @copilot Please analyze this workflow failure and implement        │    │
│  │ the proposed fix.                                                   │    │
│  │                                                                     │    │
│  │ ## Analysis                                                         │    │
│  │ <details>                                                           │    │
│  │ <summary>Failure analysis (click to expand)</summary>              │    │
│  │ ```json                                                             │    │
│  │ {                                                                   │    │
│  │   "error_type": "Missing Dependency",                              │    │
│  │   "root_cause": "ModuleNotFoundError: pytest-asyncio",             │    │
│  │   "confidence": 90,                                                 │    │
│  │   "fix_type": "add_dependency"                                     │    │
│  │ }                                                                   │    │
│  │ ```                                                                 │    │
│  │ </details>                                                          │    │
│  │                                                                     │    │
│  │ ## Fix Proposal                                                     │    │
│  │ <details>                                                           │    │
│  │ <summary>Proposed changes (click to expand)</summary>              │    │
│  │ ```json                                                             │    │
│  │ {                                                                   │    │
│  │   "fixes": [                                                        │    │
│  │     {                                                               │    │
│  │       "file": "requirements.txt",                                  │    │
│  │       "action": "add_line",                                        │    │
│  │       "content": "pytest-asyncio==0.21.0"                          │    │
│  │     }                                                               │    │
│  │   ]                                                                 │    │
│  │ }                                                                   │    │
│  │ ```                                                                 │    │
│  │ </details>                                                          │    │
│  │                                                                     │    │
│  │ See `.github/copilot-tasks/fix-workflow-failure.md` for details   │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       MENTION @COPILOT IN COMMENT                            │
│                                                                              │
│  PR Comment:                                                                 │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ @copilot Please implement the workflow fix as described in the     │    │
│  │ PR description. The failure analysis and fix proposal are          │    │
│  │ available in the branch. Follow the instructions in                │    │
│  │ `.github/copilot-tasks/fix-workflow-failure.md`.                   │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     🤖 GITHUB COPILOT AGENT                                  │
│                                                                              │
│  1. Receives notification via @mention                                       │
│  2. Reads PR description and task file                                       │
│  3. Reviews failure analysis and fix proposal                                │
│  4. Analyzes repository context                                              │
│  5. Implements the fix                                                       │
│  6. Commits changes to PR branch                                             │
│  7. Validates syntax and tests                                               │
│                                                                              │
│  Implementation:                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ Added to requirements.txt:                                         │    │
│  │ + pytest-asyncio==0.21.0                                           │    │
│  │                                                                     │    │
│  │ Updated .github/workflows/docker-build-test.yml:                   │    │
│  │   - name: Install dependencies                                     │    │
│  │     run: |                                                          │    │
│  │ +     pip install -r requirements.txt                              │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CI/CD VALIDATION                                     │
│                                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │  Syntax  │  │  Build   │  │  Tests   │  │  Lint    │                  │
│  │  Check   │  │  Process │  │  Suite   │  │  Check   │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │             │             │             │                          │
│       └─────────────┴─────────────┴─────────────┘                          │
│                          │                                                  │
│                     ✅ PASS                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       READY FOR HUMAN REVIEW                                 │
│                                                                              │
│  Developer Actions:                                                          │
│  1. Review Copilot's implementation                                          │
│  2. Check test results (all passing)                                         │
│  3. Verify fix addresses root cause                                          │
│  4. Approve and merge PR                                                     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ ✅ All checks passed                                               │    │
│  │ ✅ Copilot implemented fix correctly                               │    │
│  │ ✅ Tests validate the fix works                                    │    │
│  │ ✅ Code review looks good                                          │    │
│  │                                                                     │    │
│  │ [Approve and Merge]                                                │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ✅ FIX MERGED                                        │
│                                                                              │
│  • Workflow now passes                                                       │
│  • Issue auto-updated                                                        │
│  • Metrics recorded                                                          │
│  • System continues monitoring                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Detection Layer
- Monitors all workflow runs via `workflow_run` event
- Filters for failures only
- Excludes self-healing workflows to prevent loops

### 2. Analysis Layer
- Downloads logs from failed jobs
- Uses pattern matching (regex) to identify error types
- Calculates confidence scores (70-95%)
- Determines root cause

### 3. Proposal Layer
- Generates specific fix based on error type
- Creates detailed task file for Copilot
- Prepares PR content with analysis
- Generates branch name and labels

### 4. Integration Layer
- Creates PR with comprehensive information
- **Directly mentions @copilot** (no label needed)
- Provides task file with instructions
- Links analysis and proposal

### 5. Implementation Layer
- **GitHub Copilot Agent** automatically invoked
- Reads task file and context
- Implements suggested fixes
- Commits to PR branch

### 6. Validation Layer
- CI/CD runs automatically
- Tests validate fix
- Syntax and linting checks
- Reports status

### 7. Review Layer
- Human reviews implementation
- Checks test results
- Verifies fix quality
- Merges when ready

## Supported Error Types

| Error Type           | Detection Pattern                      | Fix Strategy                    | Confidence |
|---------------------|----------------------------------------|---------------------------------|------------|
| Missing Dependency  | `ModuleNotFoundError`, `ImportError`   | Add to requirements.txt         | 90%        |
| Timeout             | `timeout`, `deadline exceeded`         | Increase timeout values         | 95%        |
| Permission          | `Permission denied`, `403 Forbidden`   | Add permissions section         | 80%        |
| Docker              | `docker.*error`, `daemon`              | Add Buildx, fix config          | 85%        |
| Network             | `ConnectionError`, `Failed to fetch`   | Add retry logic                 | 75%        |
| Resource            | `Out of memory`, `Disk full`           | Increase resources              | 90%        |
| Test Failure        | `FAILED`, `AssertionError`             | Fix test config                 | 70%        |
| Syntax              | `SyntaxError`, `invalid syntax`        | Fix YAML/code syntax            | 85%        |

## Time Comparison

### Traditional Manual Fix
```
┌─────────────┐
│ Failure     │ (1 minute - detection)
├─────────────┤
│ Developer   │ (5-10 minutes - context switch)
│ Notified    │
├─────────────┤
│ Investigate │ (10-20 minutes - log review)
│ Logs        │
├─────────────┤
│ Identify    │ (5-10 minutes - root cause)
│ Root Cause  │
├─────────────┤
│ Create Fix  │ (10-15 minutes - coding)
├─────────────┤
│ Create PR   │ (5 minutes - PR creation)
├─────────────┤
│ Review      │ (30-120 minutes - waiting)
├─────────────┤
│ Merge       │ (1 minute - merge)
└─────────────┘

Total: 30-60+ minutes (if developer available)
```

### Auto-Healing with Copilot Agent
```
┌─────────────┐
│ Failure     │ (1 minute - detection)
├─────────────┤
│ Analysis    │ (30 seconds - automatic)
├─────────────┤
│ Proposal    │ (30 seconds - automatic)
├─────────────┤
│ PR Created  │ (10 seconds - automatic)
├─────────────┤
│ @copilot    │ (1-10 minutes - automatic)
│ Implements  │
├─────────────┤
│ Tests Run   │ (2-5 minutes - automatic)
├─────────────┤
│ Review      │ (2-5 minutes - when convenient)
├─────────────┤
│ Merge       │ (1 minute - merge)
└─────────────┘

Total: 5-15 minutes (no waiting for developer)
```

**Time Savings: 80-90%**

## Security Model

```
┌─────────────────────────────────────────────────────────────┐
│                        SECURITY LAYERS                       │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌────────────────┐    ┌──────────────┐
│ 1. Branch     │    │ 2. Pull        │    │ 3. CI/CD     │
│    Protection │    │    Request     │    │    Validation│
│                │    │                │    │              │
│ • No direct   │    │ • All changes  │    │ • Syntax     │
│   commits     │    │   in PR        │    │   check      │
│ • Force push  │    │ • Detailed     │    │ • Build test │
│   disabled    │    │   description  │    │ • Unit tests │
│ • Reviews     │    │ • Auto-labeled │    │ • Integration│
│   required    │    │ • Tracked      │    │ • Linting    │
└───────────────┘    └────────────────┘    └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     4. HUMAN REVIEW                          │
│                                                              │
│  • Developer reviews Copilot's implementation                │
│  • Verifies tests pass                                       │
│  • Checks for security issues                                │
│  • Confirms fix addresses root cause                         │
│  • Final approval required                                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     5. MERGE TO MAIN                         │
│                                                              │
│  • Manual merge required                                     │
│  • No auto-merge                                             │
│  • Audit trail preserved                                     │
└─────────────────────────────────────────────────────────────┘
```

## Metrics Dashboard

```
┌──────────────────────────────────────────────────────────────┐
│              AUTO-HEALING METRICS DASHBOARD                   │
└──────────────────────────────────────────────────────────────┘

📊 Success Rate
████████████████████████████████████░░░░░░  84%
Total: 50 PRs | Merged: 42 | Closed: 5 | Open: 3

⏱️  Average Resolution Time
████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░  2.3 hours
Min: 0.5h | Median: 1.8h | Max: 8.2h

🔍 Error Type Distribution
Dependency      ████████████████░░░░░░░░░░  30%
Timeout         ████████████░░░░░░░░░░░░░░  24%
Docker          ████████░░░░░░░░░░░░░░░░░░  16%
Permission      ███████░░░░░░░░░░░░░░░░░░░  14%
Network         █████░░░░░░░░░░░░░░░░░░░░░  10%
Test            ███░░░░░░░░░░░░░░░░░░░░░░░   6%

📈 Recent Activity (30 days)
PRs Created: 15
Average/day: 0.5
Success Rate: 87%
```

---

**Auto-Healing**: Workflows that fix themselves. 🤖✨
