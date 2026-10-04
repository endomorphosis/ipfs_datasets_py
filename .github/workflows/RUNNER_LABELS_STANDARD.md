# GitHub Actions Runner Labels - Standard Format

## Overview

This document defines the standardized runner labels for all GitHub Actions workflows in this repository.

## Standard Label Formats

All self-hosted runner labels follow the format: `[self-hosted, linux, <architecture>, <optional-tags>]`

### x86_64 Runners
```yaml
runs-on: [self-hosted, linux, x64]
```
- **Use for**: Standard x86_64/AMD64 compute tasks
- **Total uses**: 70 workflows

### ARM64 Runners
```yaml
runs-on: [self-hosted, linux, arm64]
```
- **Use for**: ARM64/aarch64 compute tasks
- **Total uses**: 9 workflows

### GPU Runners
```yaml
runs-on: [self-hosted, linux, x64, gpu]
```
- **Use for**: CUDA/GPU-accelerated tasks
- **Total uses**: 2 workflows
- **Requirements**: NVIDIA GPU with CUDA support

### Specialized Runners

#### Datasets Runner
```yaml
runs-on: [self-hosted, linux, arm64, datasets]
```
- **Use for**: Dataset processing on ARM64
- **Total uses**: 1 workflow

## Label Ordering Convention

Always use this specific order:
1. `self-hosted` - First (required)
2. `linux` - Operating system (required)
3. `<architecture>` - CPU architecture: `x64` or `arm64` (required)
4. `<optional-tags>` - Additional tags like `gpu`, `datasets` (optional)

### ✅ Correct Examples
```yaml
runs-on: [self-hosted, linux, x64]
runs-on: [self-hosted, linux, arm64]
runs-on: [self-hosted, linux, x64, gpu]
runs-on: [self-hosted, linux, arm64, datasets]
```

### ❌ Incorrect Examples
```yaml
runs-on: [self-hosted]                    # Missing OS and architecture
runs-on: [self-hosted, x64]               # Missing OS
runs-on: [self-hosted, ARM64, linux]      # Wrong case and order
runs-on: [self-hosted, x86_64]            # Wrong architecture label
runs-on: [self-hosted, arm64, linux]      # Wrong order
```

## Runner Configuration

### For Repository Owners

When configuring self-hosted runners, use these labels:

#### x86_64 Runner Setup
```bash
# When adding runner, use these labels:
self-hosted,linux,x64
```

#### ARM64 Runner Setup
```bash
# When adding runner, use these labels:
self-hosted,linux,arm64
```

#### GPU Runner Setup
```bash
# When adding runner, use these labels:
self-hosted,linux,x64,gpu
```

### Verification

To verify your runner labels are correct:
```bash
# List your self-hosted runners and their labels
gh api repos/{owner}/{repo}/actions/runners
```

## Why These Standards?

### Lowercase Architecture Labels
- GitHub Actions convention uses lowercase for architecture
- Prevents case-sensitivity matching issues
- Consistent with GitHub-hosted runners (`ubuntu-latest`, `windows-latest`)

### `x64` vs `x86_64`
- `x64` is the GitHub Actions standard
- Shorter and more commonly used
- Matches GitHub-hosted runner patterns

### OS Label Required
- Ensures cross-platform compatibility
- Makes runner matching more explicit
- Prevents ambiguity

### Consistent Ordering
- Makes workflows easier to read
- Prevents duplicate/similar labels with different ordering
- Simplifies grep/search operations

## Migration Notes

This standardization was implemented in **November 2024** to fix runner matching issues.

### Changes Made
- `ARM64` → `arm64` (lowercase)
- `x86_64` → `x64` (standard format)
- Added `linux` OS label where missing
- Fixed label ordering inconsistencies
- Completed incomplete `[self-hosted]` labels

### Backward Compatibility
These changes are backward compatible if your self-hosted runners have both old and new labels during the transition period.

## Troubleshooting

### Workflow Not Finding Runner

If your workflow fails with "No runner matching the specified labels":

1. Check runner labels in repository settings
2. Verify labels match the standard format
3. Ensure runner is online and not busy
4. Check workflow label spelling and casing

### Common Issues

| Issue | Solution |
|-------|----------|
| "No runner found with label ARM64" | Change to lowercase `arm64` |
| "No runner found with label x86_64" | Change to `x64` |
| Runner not matching | Add `linux` OS label |
| Wrong runner selected | Check label order and completeness |

## Resources

- [GitHub Actions: Using self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [GitHub Actions: Workflow syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idruns-on)
- [Repository Workflows](./)

## Updates

This document should be updated whenever:
- New runner types are added
- Label standards change
- New best practices emerge

Last updated: November 6, 2024
