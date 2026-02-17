# Logic Module API Versioning Policy

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Active Policy

---

## Table of Contents

- [Versioning Strategy](#versioning-strategy)
- [Semantic Versioning](#semantic-versioning)
- [API Stability Guarantees](#api-stability-guarantees)
- [Deprecation Process](#deprecation-process)
- [Breaking Changes](#breaking-changes)
- [Migration Guides](#migration-guides)
- [Version History](#version-history)

---

## Versioning Strategy

The `ipfs_datasets_py.logic` module follows [Semantic Versioning 2.0.0](https://semver.org/) with the following structure:

```
MAJOR.MINOR.PATCH
```

### Version Components

- **MAJOR** (X.0.0): Breaking changes to public APIs
- **MINOR** (0.X.0): New features, backward-compatible
- **PATCH** (0.0.X): Bug fixes, backward-compatible

### Current Version

**Version 2.0.0** - Production-ready release with stable API surface

---

## Semantic Versioning

### MAJOR Version Increments

A MAJOR version increment indicates **breaking changes** that may require code modifications:

**Breaking Changes Include:**
- Removing public APIs or functions
- Changing function signatures (parameters, return types)
- Changing exception types thrown by public APIs
- Removing or renaming configuration options
- Changing default behavior that affects results
- Removing deprecated APIs (after deprecation period)

**Example:** v1.x → v2.0
```python
# v1.x (deprecated)
from ipfs_datasets_py.logic.tools import convert_to_fol  # OLD

# v2.0 (current)
from ipfs_datasets_py.logic.fol import FOLConverter  # NEW
converter = FOLConverter()
result = converter.convert("All cats are animals")
```

### MINOR Version Increments

A MINOR version increment adds **new features** while maintaining backward compatibility:

**Includes:**
- New public APIs or functions
- New optional parameters (with defaults)
- New converter types or prover backends
- Performance improvements
- Enhanced error messages
- New optional dependencies

**Example:** v2.0 → v2.1
```python
# v2.0 - Basic conversion
converter = FOLConverter()
result = converter.convert("text")

# v2.1 - New optional parameter
result = converter.convert("text", optimize=True)  # NEW FEATURE
```

### PATCH Version Increments

A PATCH version increment contains **bug fixes** only:

**Includes:**
- Bug fixes that restore intended behavior
- Documentation corrections
- Performance optimizations (no API changes)
- Security patches
- Test improvements

**Example:** v2.1.0 → v2.1.1
```python
# Bug fix: Handle empty input correctly
result = converter.convert("")  # Now returns proper error instead of crash
```

---

## API Stability Guarantees

### Stable Public API

The following APIs are **guaranteed stable** and will not break without MAJOR version increment:

#### Core Converters
```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.deontic import DeonticConverter
```

**Guaranteed:**
- `FOLConverter.convert(text: str, **kwargs) -> ConversionResult`
- `DeonticConverter.convert(text: str, **kwargs) -> ConversionResult`
- `ConversionResult` fields: `success`, `fol`, `confidence`, `error`

#### Integration Layer
```python
from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
```

**Guaranteed:**
- `NeurosymbolicReasoner` constructor and basic methods
- `prove_formula(formula: str, assumptions: List[str]) -> ProofResult`
- `ProofResult` fields: `status`, `proof`, `time_ms`

#### Common Utilities
```python
from ipfs_datasets_py.logic.common import (
    LogicError,
    ConversionError,
    ProofError,
    BoundedCache,
)
```

**Guaranteed:**
- Exception hierarchy (can add new exceptions, won't remove existing)
- Cache interface (`get`, `set`, `clear`, `stats`)

### Beta/Experimental APIs

The following features are **BETA** and may change in MINOR versions:

- **ZKP Module** (`logic.zkp`) - Simulation only, API may evolve
- **Neural Prover Integration** - External dependency, may change
- **GF Grammar Parser** - Limited coverage, may expand
- **Interactive Constructor** - Experimental UI features

**Usage:**
```python
# Beta feature - may change in minor versions
from ipfs_datasets_py.logic.zkp import ZKProofGenerator  # BETA
```

### Internal/Private APIs

APIs prefixed with `_` are **internal** and may change at any time:

```python
# Internal - NOT stable
from ipfs_datasets_py.logic.common._internal import _parse_formula  # DO NOT USE
```

**Rule:** Never import from `_`-prefixed modules or use `_`-prefixed functions in production code.

---

## Deprecation Process

We follow a **3-step deprecation process** with minimum 6-month notice:

### Step 1: Deprecation Warning (MINOR version)

**Timeline:** Version X.Y.0

The old API continues to work but emits a `DeprecationWarning`:

```python
import warnings

def convert_to_fol(text):  # OLD API
    warnings.warn(
        "convert_to_fol is deprecated, use FOLConverter.convert() instead. "
        "Will be removed in version 2.0.0",
        DeprecationWarning,
        stacklevel=2
    )
    return FOLConverter().convert(text)
```

**Documentation Updated:**
- Mark as deprecated in docstrings
- Add migration example
- Update README with new API

### Step 2: Deprecation Period (6 months minimum)

**Timeline:** Versions X.Y.0 through X.Z.0

- Old API continues to work with warnings
- New API recommended in all documentation
- Examples updated to use new API
- Users have time to migrate

### Step 3: Removal (MAJOR version)

**Timeline:** Version (X+1).0.0

- Old API removed completely
- Attempting to use raises `AttributeError`
- Migration guide provided

**Migration Guide Example:**
```python
# Before (v1.x)
from ipfs_datasets_py.logic.tools import convert_to_fol
result = convert_to_fol("All cats are animals")

# After (v2.0+)
from ipfs_datasets_py.logic.fol import FOLConverter
converter = FOLConverter()
result = converter.convert("All cats are animals")
```

### Compatibility Shims

For major APIs, we provide **compatibility shims** in `logic._compat`:

```python
# logic/_compat/v1.py
from ipfs_datasets_py.logic.fol import FOLConverter

def convert_to_fol(text):
    """Compatibility shim for v1.x API."""
    warnings.warn("...", DeprecationWarning)
    return FOLConverter().convert(text)
```

---

## Breaking Changes

### When Breaking Changes Are Acceptable

We only introduce breaking changes for:

1. **Security vulnerabilities** - Immediate fix required
2. **Critical bugs** - Current behavior is dangerously wrong
3. **API design improvements** - After community consensus
4. **Major refactoring** - With 6+ month deprecation period

### How We Announce Breaking Changes

Breaking changes are announced through:

1. **CHANGELOG.md** - Detailed list of changes
2. **Migration Guide** - Step-by-step upgrade instructions
3. **GitHub Release Notes** - Highlighted breaking changes
4. **Documentation** - Updated with new APIs
5. **Deprecation Warnings** - In previous MINOR versions

### Recent Breaking Changes

#### v1.0 → v2.0 (Released 2026-02-17)

**Breaking Changes:**
1. Removed `logic.tools` namespace (deprecated in v1.5)
   - **Migration:** Use `logic.fol` and `logic.deontic` instead
2. Changed `ConversionResult` structure
   - **Migration:** Update field access (see MIGRATION_GUIDE.md)
3. Removed `symbolic_prover_legacy` bridge
   - **Migration:** Use `SymbolicFOLBridge` instead

**See:** [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) for complete v1→v2 upgrade instructions

---

## Migration Guides

### v1.x → v2.0 Migration

**See:** [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) for complete guide

**Quick Migration Checklist:**
- [ ] Replace `logic.tools` imports with `logic.fol` / `logic.deontic`
- [ ] Update `ConversionResult` field access
- [ ] Replace legacy bridge imports
- [ ] Test with deprecation warnings enabled
- [ ] Run test suite

### Future Migrations

When v3.0 is released, a new migration guide will be provided.

---

## Version History

### v2.0.0 (2026-02-17) - Current Stable

**Major Changes:**
- Stable public API surface defined
- Unified converter interface
- Comprehensive error handling
- Production-ready caching
- 790+ tests (94% pass rate)

**Breaking Changes:**
- Removed deprecated `logic.tools` namespace
- Changed `ConversionResult` structure
- Removed legacy prover bridges

**See:** [CHANGELOG.md](./CHANGELOG.md) for complete history

### v1.5.0 (2025-11-15) - Last v1.x Release

**Features:**
- Added deprecation warnings for v2.0
- Introduced new converter APIs
- Enhanced fallback behaviors

### v1.0.0 (2025-06-01) - Initial Stable Release

**Features:**
- Basic FOL and Deontic conversion
- TDFOL and CEC reasoning engines
- Proof caching
- External prover bridges

---

## Best Practices

### For Library Users

1. **Pin Major Versions** in requirements.txt:
   ```txt
   ipfs-datasets-py>=2.0.0,<3.0.0  # Allow MINOR/PATCH updates
   ```

2. **Test with Warnings** enabled to catch deprecations early:
   ```python
   import warnings
   warnings.filterwarnings("error", category=DeprecationWarning)
   ```

3. **Read CHANGELOG** before upgrading MAJOR versions

4. **Use Stable APIs** - Avoid `_`-prefixed internals and BETA features in production

### For Contributors

1. **Never break public APIs** in MINOR or PATCH releases
2. **Add deprecation warnings** 6+ months before removal
3. **Update CHANGELOG.md** with all API changes
4. **Provide migration examples** for deprecated APIs
5. **Test backward compatibility** with previous MINOR version

---

## API Stability Levels

### Production Stable ✅

**Guaranteed:** No breaking changes without MAJOR version bump

- `logic.fol.FOLConverter`
- `logic.deontic.DeonticConverter`
- `logic.common` exceptions and cache
- `logic.types` core types
- `logic.integration.NeurosymbolicReasoner`

### Beta ⚠️

**Warning:** May change in MINOR versions with notice

- `logic.zkp` - Zero-knowledge proof simulation
- `logic.external_provers.neural` - Neural prover integration
- `logic.fol.interactive` - Interactive constructor
- `logic.security.advanced` - Advanced security features

### Experimental 🧪

**Caution:** May change or be removed at any time

- `logic.ml_confidence` - ML confidence scoring
- `logic.monitoring.advanced` - Advanced monitoring
- Features marked with `@experimental` decorator

### Internal 🔒

**Do Not Use:** No stability guarantees

- Any `_`-prefixed module or function
- `logic.common._internal`
- `logic.types._compat`

---

## Checking Your Version

### Programmatic Version Check

```python
from ipfs_datasets_py import __version__
print(f"Using ipfs_datasets_py version: {__version__}")

# Check if version is compatible
from packaging import version
if version.parse(__version__) < version.parse("2.0.0"):
    raise RuntimeError("Requires version 2.0.0 or later")
```

### Version Compatibility

```python
from ipfs_datasets_py.logic import check_compatibility

# Check if your code is compatible with current version
try:
    check_compatibility(required="2.0.0", features=["fol", "deontic"])
except IncompatibleVersionError as e:
    print(f"Incompatible: {e}")
```

---

## Support Policy

### Version Support Timeline

- **Current Stable** (v2.x): Full support, active development
- **Previous MAJOR** (v1.x): Security fixes only (6 months after v2.0 release)
- **Older versions** (v0.x): No support, please upgrade

### End-of-Life (EOL) Dates

| Version | Release Date | EOL Date | Status |
|---------|--------------|----------|--------|
| v2.0.x  | 2026-02-17   | TBD      | Current |
| v1.x    | 2025-06-01   | 2026-08-17 | Security fixes only |
| v0.x    | 2024-10-01   | 2025-12-01 | EOL |

---

## Questions and Feedback

**Questions about API stability?**
- Open an issue on GitHub: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Tag with `api-stability` label

**Suggestions for API improvements?**
- Start a discussion: https://github.com/endomorphosis/ipfs_datasets_py/discussions
- Tag with `api-design`

**Found a breaking change not documented?**
- File a bug report immediately
- Tag with `breaking-change` and `documentation`

---

## Summary

- **Semantic Versioning** - MAJOR.MINOR.PATCH
- **Stable APIs** - No breaking changes without MAJOR bump
- **Deprecation Period** - 6+ months with warnings
- **Beta Features** - May change in MINOR versions
- **Migration Guides** - Provided for all MAJOR versions
- **Version Support** - Current + Previous MAJOR (security only)

**For questions, see:** [CONTRIBUTING.md](./CONTRIBUTING.md) or open a GitHub issue.

---

**Document Status:** Active Policy  
**Maintained By:** Logic Module Maintainers  
**Review Frequency:** Every MAJOR release
