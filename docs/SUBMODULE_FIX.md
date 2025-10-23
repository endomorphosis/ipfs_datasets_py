# Submodule Issue Resolution

## Problem
The CI/CD workflows were failing when checking out the repository with `submodules: recursive` option.

### Root Cause
The `scrape_the_law_mk3` submodule contains a nested `database` directory that is registered as a git submodule (gitlink) but has no URL configured in its `.gitmodules` file. When git tries to recursively initialize submodules, it fails with:

```
fatal: No url found for submodule path 'ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3/database' in .gitmodules
fatal: Failed to recurse into submodule path 'ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3'
```

## Solution
Changed all GitHub Actions workflows from using `submodules: recursive` to `submodules: true`:

```yaml
# Before (broken)
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    submodules: recursive

# After (working)
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    submodules: true
```

## Impact
- ✅ Both submodules (`scrape_the_law_mk3` and `ipfs_kit_py`) are properly initialized
- ✅ CI workflows can successfully checkout the repository
- ✅ The broken nested `database` submodule is ignored (as intended)
- ✅ All submodule content is available for use

## Manual Testing
To test submodule initialization locally:

```bash
# Clean submodules
git submodule deinit -f --all
rm -rf .git/modules/*

# Initialize submodules (non-recursive)
git submodule update --init

# Verify status
git submodule status

# Should show both submodules initialized:
#  08413253ca17e99ae7a47f6e793c0c751cb30034 ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3
#  6b1a15533bcb492d209700f809545c0eb616b4b3 ipfs_kit_py
```

## Files Modified
1. `.gitmodules` - Added comments about the broken nested submodule
2. `.github/workflows/docker-build-test.yml` - Changed 4 instances
3. `.github/workflows/docker-ci.yml` - Changed 3 instances

## Upstream Issue
The real issue is in the `scrape_the_law_mk3` repository where the `database` directory is registered as a submodule without proper configuration. This should be fixed upstream by:
1. Either removing the gitlink entry for `database`
2. Or adding proper URL configuration in `.gitmodules`

However, for this repository, we've worked around it by not using recursive initialization.

## Future Considerations
If additional nested submodules are added to any of our submodules in the future:
- They must have proper `.gitmodules` configuration
- Or we must continue using non-recursive initialization
- Test locally before pushing to avoid CI failures
