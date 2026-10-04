# Submodule Issue Resolution

## Problem
The CI/CD workflows were failing when checking out the repository with `submodules: recursive` option.

### Root Cause
The `scrape_the_law_mk3` submodule contains a nested `database` directory that is registered as a git submodule (gitlink) but has no URL configured in its `.gitmodules` file. When `actions/checkout@v4` processes submodules, it runs `git submodule foreach --recursive` commands internally during cleanup and auth setup, which fail with:

```
fatal: No url found for submodule path 'ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3/database' in .gitmodules
fatal: Failed to recurse into submodule path 'ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3'
```

## Solution
Removed submodule initialization entirely from the Docker build CI workflows:

```yaml
# Before (broken)
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    submodules: recursive  # or even 'submodules: true'

# After (working)
- name: Checkout repository
  uses: actions/checkout@v4
  # No submodules parameter - don't initialize submodules at all
```

## Why This Works
- Docker build workflows don't need the submodules to build and test Docker images
- The Docker build process clones the repository fresh inside the container
- Removing submodule initialization avoids the broken nested submodule issue entirely
- Even `submodules: true` (non-recursive) still triggers recursive git commands internally during cleanup

## Impact
- ✅ CI workflows can successfully checkout the repository
- ✅ Docker builds work correctly
- ✅ No breaking changes to existing functionality
- ✅ Workflows that DO need submodules are unaffected

## Manual Testing
To test checkout without submodules locally:

```bash
# Clone without submodules
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Verify no submodules are initialized
git submodule status
# Should show submodules with '-' prefix (not initialized)
```

## Files Modified
1. `.gitmodules` - Added comments about the broken nested submodule
2. `.github/workflows/docker-build-test.yml` - Removed `submodules` parameter from 4 checkout actions
3. `.github/workflows/docker-ci.yml` - Removed `submodules` parameter from 3 checkout actions

## Upstream Issue
The real issue is in the `scrape_the_law_mk3` repository where the `database` directory is registered as a submodule without proper configuration. This should be fixed upstream by:
1. Either removing the gitlink entry for `database`
2. Or adding proper URL configuration in `.gitmodules`

However, for this repository, we've successfully worked around it by not initializing submodules in workflows that don't need them.

## Future Considerations
If workflows need submodules in the future:
- Only enable submodule initialization in workflows that truly need the submodule code
- Consider using manual `git submodule update --init` commands with specific paths to avoid the broken nested submodule
- Test locally before pushing to avoid CI failures
