# Auto-Healing System Flow Diagrams

## Overview

These diagrams illustrate how the enhanced auto-healing system works.

## 1. Scraper Validation Auto-Healing Flow

```mermaid
sequenceDiagram
    participant GHA as GitHub Actions
    participant SV as Scraper Validation
    participant GH as GitHub
    participant CP as Copilot Agent
    participant DEV as Developer

    GHA->>SV: Trigger validation (schedule/push/manual)
    SV->>SV: Run scraper tests
    SV->>SV: Validate schemas
    SV->>SV: Check HuggingFace compatibility
    
    alt All validations pass
        SV->>GHA: ✅ Success
    else Validation fails
        SV->>SV: Generate failure report
        SV->>GH: Create issue with diagnostics
        Note over GH: Issue #123 created
        SV->>SV: Create fix branch
        Note over SV: autofix/scraper-validation-20251030
        SV->>GH: Create draft PR
        Note over GH: PR #45 created (draft)
        SV->>GH: @mention Copilot in PR
        Note over GH: "@copilot /fix Please analyze..."
        GH->>CP: Trigger Copilot agent
        CP->>CP: Analyze failure
        CP->>CP: Implement fixes
        CP->>GH: Push commits to PR
        GH->>DEV: Notify PR ready for review
        DEV->>GH: Review and approve
        DEV->>GH: Merge PR
    end
```

## 2. General Workflow Auto-Healing Flow

```mermaid
sequenceDiagram
    participant WF as Workflow
    participant AF as Auto-Fix Workflow
    participant AN as Analyzer
    participant FG as Fix Generator
    participant GH as GitHub
    participant CP as Copilot
    participant DEV as Developer

    WF->>WF: Run workflow
    WF->>WF: ❌ Failure detected
    WF->>AF: Trigger auto-fix (workflow_run)
    
    AF->>AF: Check for duplicates
    alt Already processed
        AF->>AF: Skip (avoid duplicate)
    else New failure
        AF->>AF: Download workflow logs
        AF->>AN: Analyze logs
        AN->>AN: Identify error patterns
        AN->>AN: Determine root cause
        AN->>FG: Generate fix proposal
        FG->>FG: Create fix plan
        FG->>FG: Generate PR content
        
        AF->>GH: Create issue
        Note over GH: Issue #124 created
        AF->>AF: Create fix branch
        Note over AF: autofix/workflow-name/fix-type/timestamp
        AF->>GH: Create draft PR
        Note over GH: PR #46 created (draft)
        AF->>GH: @mention Copilot
        Note over GH: "@copilot /fix Please implement..."
        
        GH->>CP: Trigger Copilot
        CP->>CP: Analyze issue & proposal
        CP->>CP: Implement fixes
        CP->>GH: Push commits
        GH->>DEV: Notify ready for review
        DEV->>GH: Review changes
        DEV->>GH: Approve & merge
    end
```

## 3. Component Architecture

```mermaid
graph TD
    A[Workflow Failure] --> B{Auto-Healing Trigger}
    B --> C[Download Logs]
    C --> D[Analyze Failure]
    D --> E{Error Pattern Match?}
    E -->|Yes| F[Generate Fix Proposal]
    E -->|No| G[Manual Review Required]
    F --> H[Create Issue]
    H --> I[Create Branch]
    I --> J[Create Draft PR]
    J --> K[@mention Copilot]
    K --> L{Copilot Available?}
    L -->|Yes| M[Copilot Implements Fix]
    L -->|No| N[Wait for Manual Fix]
    M --> O[Automated Tests]
    O --> P{Tests Pass?}
    P -->|Yes| Q[Ready for Review]
    P -->|No| M
    N --> Q
    G --> Q
    Q --> R[Developer Review]
    R --> S{Approved?}
    S -->|Yes| T[Merge PR]
    S -->|No| U[Request Changes]
    U --> M
    T --> V[Close Issue]
```

## 4. Data Flow

```mermaid
flowchart LR
    A[Workflow Logs] --> B[Log Parser]
    B --> C[Error Extractor]
    C --> D[Pattern Matcher]
    D --> E{Known Pattern?}
    E -->|Yes| F[Confidence Score]
    E -->|No| G[Manual Analysis]
    F --> H{Confidence > 70%?}
    H -->|Yes| I[Auto-Fix]
    H -->|No| G
    I --> J[Fix Proposal]
    G --> J
    J --> K[Issue Body]
    J --> L[PR Description]
    K --> M[GitHub Issue]
    L --> N[GitHub PR]
    N --> O[Copilot Context]
    O --> P[Implemented Fix]
```

## 5. Security Model

```mermaid
graph TD
    A[Auto-Healing System] --> B[Permissions]
    B --> C[contents:write]
    B --> D[pull-requests:write]
    B --> E[issues:write]
    B --> F[actions:read]
    
    A --> G[Protections]
    G --> H[Draft PRs Only]
    G --> I[Manual Review Required]
    G --> J[No Auto-Merge]
    G --> K[Container Isolation]
    
    A --> L[Audit Trail]
    L --> M[Git History]
    L --> N[Issue Comments]
    L --> O[PR Activity]
    L --> P[Workflow Logs]
    
    A --> Q[Token Security]
    Q --> R[Repo Scoped]
    Q --> S[Auto Expiring]
    Q --> T[No Secrets Access]
```

## 6. Monitoring & Metrics

```mermaid
flowchart TB
    A[Auto-Healing Events] --> B[Metrics Collection]
    
    B --> C[Issue Creation Rate]
    B --> D[PR Creation Rate]
    B --> E[Fix Success Rate]
    B --> F[Time to Resolution]
    
    C --> G[Alert Thresholds]
    D --> G
    E --> H[Quality Metrics]
    F --> H
    
    G --> I{Anomaly Detected?}
    I -->|Yes| J[Send Alert]
    I -->|No| K[Continue Monitoring]
    
    H --> L{Quality < Target?}
    L -->|Yes| M[Review System]
    L -->|No| K
    
    J --> N[Team Notification]
    M --> N
```

## Key Concepts

### Draft PR Approach
The system creates draft PRs to:
- ✅ Provide immediate context for Copilot
- ✅ Enable @mention triggering
- ✅ Prevent accidental merges
- ✅ Allow iterative improvements
- ✅ Maintain clear audit trail

### Copilot Integration
Copilot is triggered via:
- ✅ @mention in PR comments
- ✅ `/fix` slash command
- ✅ Structured context in PR description
- ✅ Linked issue with detailed diagnostics

### Security Boundaries
- 🔒 Draft status = manual review gate
- 🔒 Repository-scoped tokens
- 🔒 No organization access
- 🔒 Container isolation
- 🔒 Full audit logging

## Usage Patterns

### Automatic Triggering
```
Workflow Fails → Auto-Healing Triggered → Issue + PR Created → Copilot Implements → Review → Merge
```

### Manual Triggering
```
Developer Runs → Validation Fails → Issue + PR Created → Copilot Implements → Review → Merge
```

### Monitoring
```
Metrics Collected → Anomalies Detected → Alerts Sent → Team Responds
```

## Success Indicators

1. **Issue Creation**: Should be 100% on failures
2. **PR Creation**: Should be 100% when fixes are available
3. **Copilot Response**: Target 80%+ response rate
4. **Merge Rate**: Target 60%+ successful auto-generated fixes
5. **Resolution Time**: Target <24 hours from failure to merge

## Legend

- 🤖 Automated process
- 👤 Manual intervention required
- ✅ Success path
- ❌ Failure path
- 🔒 Security control
- 📊 Monitoring point
