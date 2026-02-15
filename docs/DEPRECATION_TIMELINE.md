# Deprecation Timeline

**Created:** 2026-02-15  
**Status:** ACTIVE  
**Timeline:** 6 months (v1.0 → v2.0)

---

## Executive Summary

This document outlines the **6-month deprecation timeline** for components consolidated during the processor/data_transformation integration. All deprecated components will continue to work with warnings until **v2.0 release (approximately August 2026)**.

**Key Points:**
- ✅ **All legacy code works** with deprecation warnings
- ⏰ **6-month migration period** (February 2026 - August 2026)
- 📚 **Migration guides available** for all deprecated components
- 🔔 **Enhanced warnings** in v1.5 (May 2026)
- ⚠️ **Final warnings** in v1.9 (July 2026)
- 🚫 **Removal in v2.0** (August 2026)

---

## Timeline Overview

```
NOW (v1.0)          v1.5 (3mo)         v1.9 (5mo)         v2.0 (6mo)
Feb 2026            May 2026           Jul 2026           Aug 2026
    │                   │                  │                  │
    │                   │                  │                  │
    ▼                   ▼                  ▼                  ▼
┌───────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Deprecation  │  │   Enhanced   │  │    Final     │  │   REMOVAL    │
│   Warnings    │  │   Warnings   │  │   Warning    │  │   Complete   │
│   Active      │  │   + Tools    │  │   Period     │  │              │
└───────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
     │                   │                  │                  │
     │ All code works    │ Migration tools  │ EOL approaching  │ Deprecated
     │ with warnings     │ available        │ Prepare now!     │ code removed
     │                   │                  │                  │
```

---

## Deprecation Schedule

### Phase 1: Deprecation Warnings Active (v1.0 - February 2026)

**Status:** ✅ **CURRENT PHASE**

**What Works:**
- All deprecated imports work with `DeprecationWarning`
- All deprecated APIs function identically to new APIs
- No breaking changes
- Full backward compatibility

**Deprecated Components:**

#### 1. Multimedia (data_transformation/multimedia/)

**Deprecated Imports:**
```python
from ipfs_datasets_py.data_transformation.multimedia import (
    FFmpegWrapper,      # ⚠️ Deprecated
    YtDlpWrapper,       # ⚠️ Deprecated
    MediaProcessor,     # ⚠️ Deprecated
    MediaUtils,         # ⚠️ Deprecated
    EmailProcessor,     # ⚠️ Deprecated
    DiscordWrapper      # ⚠️ Deprecated
)
```

**New Location:**
```python
from ipfs_datasets_py.processors.multimedia import (
    FFmpegWrapper,      # ✅ Use this
    YtDlpWrapper,       # ✅ Use this
    MediaProcessor,     # ✅ Use this
    MediaUtils,         # ✅ Use this
    EmailProcessor,     # ✅ Use this
    DiscordWrapper      # ✅ Use this
)
```

**Removal Date:** v2.0 (August 2026)  
**Migration Guide:** [MULTIMEDIA_MIGRATION_GUIDE.md](./MULTIMEDIA_MIGRATION_GUIDE.md)

#### 2. Serialization (data_transformation/ root)

**Deprecated Imports:**
```python
from ipfs_datasets_py.data_transformation import (
    car_conversion,         # ⚠️ Deprecated (use serialization.car_conversion)
    jsonl_to_parquet,       # ⚠️ Deprecated (use serialization.jsonl_to_parquet)
    dataset_serialization,  # ⚠️ Deprecated (use serialization.dataset_serialization)
    ipfs_parquet_to_car     # ⚠️ Deprecated (use serialization.ipfs_parquet_to_car)
)

from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils  # ⚠️ Deprecated
```

**New Location:**
```python
from ipfs_datasets_py.data_transformation.serialization import (
    car_conversion,         # ✅ Use this
    jsonl_to_parquet,       # ✅ Use this
    dataset_serialization,  # ✅ Use this
    ipfs_parquet_to_car     # ✅ Use this
)

from ipfs_datasets_py.data_transformation.serialization.car_conversion import DataInterchangeUtils  # ✅ Use this
```

**Removal Date:** v2.0 (August 2026)  
**Migration Guide:** See [PHASE_2_SERIALIZATION_COMPLETE.md](./PHASE_2_SERIALIZATION_COMPLETE.md)

#### 3. GraphRAG Processors (processors/ root)

**Deprecated Classes:**
```python
from ipfs_datasets_py.processors import (
    GraphRAGProcessor,                    # ⚠️ Deprecated (use UnifiedGraphRAGProcessor)
    WebsiteGraphRAGProcessor,             # ⚠️ Deprecated (use UnifiedGraphRAGProcessor)
    AdvancedGraphRAGWebsiteProcessor      # ⚠️ Deprecated (use UnifiedGraphRAGProcessor)
)
```

**New Implementation:**
```python
from ipfs_datasets_py.processors.graphrag.unified_graphrag import (
    UnifiedGraphRAGProcessor,    # ✅ Use this
    GraphRAGConfiguration,       # ✅ Use this
    GraphRAGResult               # ✅ Use this
)

# Or from main package
from ipfs_datasets_py import (
    UnifiedGraphRAGProcessor,    # ✅ Use this
    GraphRAGConfiguration,       # ✅ Use this
    GraphRAGResult               # ✅ Use this
)
```

**Removal Date:** v2.0 (August 2026)  
**Migration Guide:** [GRAPHRAG_CONSOLIDATION_GUIDE.md](./GRAPHRAG_CONSOLIDATION_GUIDE.md)

### Phase 2: Enhanced Warnings & Tools (v1.5 - May 2026)

**Release Date:** ~May 15, 2026 (3 months from now)

**Changes:**
- Enhanced deprecation warnings with direct links to migration guides
- Automated migration checker tool
- Migration script generator
- Usage analytics (optional, privacy-preserving)

**Warning Example (v1.5):**
```python
DeprecationWarning: 
  data_transformation.multimedia.FFmpegWrapper is deprecated and will be 
  removed in v2.0 (August 2026). 
  
  Migration guide: https://github.com/endomorphosis/ipfs_datasets_py/blob/main/docs/MULTIMEDIA_MIGRATION_GUIDE.md
  
  Quick fix:
    OLD: from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
    NEW: from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
  
  Run migration checker: python -m ipfs_datasets_py.tools.migration_checker
```

**New Tools:**

1. **Migration Checker** - Scan codebase for deprecated imports
```bash
python -m ipfs_datasets_py.tools.migration_checker /path/to/your/code
```

2. **Migration Script Generator** - Auto-generate migration scripts
```bash
python -m ipfs_datasets_py.tools.migration_generator /path/to/your/code
```

3. **Compatibility Tester** - Test code with both old and new imports
```bash
python -m ipfs_datasets_py.tools.compatibility_tester /path/to/your/code
```

### Phase 3: Final Warning Period (v1.9 - July 2026)

**Release Date:** ~July 15, 2026 (5 months from now)

**Changes:**
- **LOUD warnings** on every deprecated import
- Console banner on application start if deprecated imports detected
- Email notification to package maintainers (if registered)
- Countdown to v2.0 in warning messages

**Warning Example (v1.9):**
```python
╔═══════════════════════════════════════════════════════════════════════╗
║                         DEPRECATION WARNING                            ║
║                                                                        ║
║  You are using DEPRECATED imports that will be REMOVED in v2.0       ║
║  Release date: ~August 15, 2026 (1 MONTH FROM NOW!)                  ║
║                                                                        ║
║  Deprecated: data_transformation.multimedia.FFmpegWrapper             ║
║  Use instead: processors.multimedia.FFmpegWrapper                     ║
║                                                                        ║
║  Run: python -m ipfs_datasets_py.tools.migration_checker             ║
║  to find all deprecated imports in your codebase.                    ║
╚═══════════════════════════════════════════════════════════════════════╝
```

**Actions Required:**
- **All users MUST migrate** before v2.0
- Test your code with new imports
- Update dependencies to use new APIs
- Run migration checker to ensure full migration

### Phase 4: Removal (v2.0 - August 2026)

**Release Date:** ~August 15, 2026 (6 months from now)

**Changes:**
- **BREAKING:** All deprecated imports removed
- **BREAKING:** All deprecated classes removed
- Clean architecture without legacy code
- Performance improvements from removal of shims
- Reduced package size

**What's Removed:**
1. `data_transformation/multimedia/` (except for omni_converter_mk2 and convert_to_txt if not migrated)
2. `data_transformation/car_conversion.py` (shim removed)
3. `data_transformation/jsonl_to_parquet.py` (shim removed)
4. `data_transformation/dataset_serialization.py` (shim removed)
5. `data_transformation/ipfs_parquet_to_car.py` (shim removed)
6. `processors/graphrag_processor.py` (deprecated processor)
7. `processors/website_graphrag_processor.py` (deprecated processor)
8. `processors/advanced_graphrag_website_processor.py` (deprecated processor)

**Migration Required:**
- Code using deprecated imports will break
- ImportError will be raised
- No backward compatibility

**Upgrade Path:**
```bash
# Before upgrading to v2.0:
1. Run migration checker
   python -m ipfs_datasets_py.tools.migration_checker .

2. Fix all deprecated imports
   python -m ipfs_datasets_py.tools.migration_generator . --apply

3. Test with v1.9
   pip install 'ipfs_datasets_py>=1.9,<2.0'
   python -m pytest

4. Upgrade to v2.0
   pip install 'ipfs_datasets_py>=2.0'
```

---

## Component-by-Component Timeline

### Multimedia Components

| Component | Deprecated In | Enhanced Warnings | Final Warning | Removal |
|-----------|--------------|-------------------|---------------|---------|
| FFmpegWrapper | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| YtDlpWrapper | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| MediaProcessor | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| MediaUtils | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| EmailProcessor | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| DiscordWrapper | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |

### Serialization Components

| Component | Deprecated In | Enhanced Warnings | Final Warning | Removal |
|-----------|--------------|-------------------|---------------|---------|
| car_conversion (root) | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| jsonl_to_parquet (root) | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| dataset_serialization (root) | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| ipfs_parquet_to_car (root) | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |

### GraphRAG Components

| Component | Deprecated In | Enhanced Warnings | Final Warning | Removal |
|-----------|--------------|-------------------|---------------|---------|
| GraphRAGProcessor | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| WebsiteGraphRAGProcessor | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |
| AdvancedGraphRAGWebsiteProcessor | v1.0 (Feb 2026) | v1.5 (May 2026) | v1.9 (Jul 2026) | v2.0 (Aug 2026) |

---

## Migration Checklist

### For Application Developers

- [ ] **Month 1 (February):** Acknowledge deprecation warnings
- [ ] **Month 2 (March):** Review migration guides
- [ ] **Month 3 (April):** Update imports in development environment
- [ ] **Month 4 (May):** Test with v1.5, run migration checker
- [ ] **Month 5 (June):** Deploy updated code to production
- [ ] **Month 6 (July):** Verify no deprecation warnings with v1.9
- [ ] **Month 7 (August):** Upgrade to v2.0

### For Library Developers

- [ ] **Month 1:** Pin to `ipfs_datasets_py<2.0` in requirements
- [ ] **Month 2:** Plan migration strategy
- [ ] **Month 3:** Update library code to use new imports
- [ ] **Month 4:** Release updated library version
- [ ] **Month 5:** Update documentation
- [ ] **Month 6:** Test with v1.9
- [ ] **Month 7:** Update requirements to allow v2.0

### For Package Maintainers

- [ ] **v1.0 (Feb):** Release with deprecation warnings
- [ ] **v1.2 (Mar):** Monitor deprecation warning usage (if analytics enabled)
- [ ] **v1.5 (May):** Release migration tools and enhanced warnings
- [ ] **v1.7 (Jun):** Send email notifications to registered users
- [ ] **v1.9 (Jul):** Final warning release with countdown
- [ ] **v2.0 (Aug):** Remove deprecated code, release clean version

---

## FAQs

### Q: Can I continue using deprecated imports in v1.x?

**A:** Yes! All deprecated imports will continue to work in v1.x with deprecation warnings. You have until v2.0 (August 2026) to migrate.

### Q: What if I can't migrate before v2.0?

**A:** Pin your dependency to v1.x:
```python
# requirements.txt
ipfs_datasets_py>=1.0,<2.0
```

However, we recommend migrating as soon as possible to benefit from bug fixes and new features in v2.0+.

### Q: Will there be any breaking changes besides deprecation removals?

**A:** No. The ONLY breaking changes in v2.0 are the removal of deprecated components. All non-deprecated APIs remain unchanged.

### Q: How do I find all deprecated imports in my codebase?

**A:** Use the migration checker tool (available in v1.5):
```bash
python -m ipfs_datasets_py.tools.migration_checker /path/to/your/code
```

Or manually search:
```bash
# Search for deprecated multimedia imports
grep -r "from.*data_transformation.multimedia import" .

# Search for deprecated serialization imports
grep -r "from.*data_transformation.car_conversion import" .
grep -r "from.*data_transformation.jsonl_to_parquet import" .

# Search for deprecated GraphRAG imports
grep -r "from.*processors.graphrag_processor import" .
grep -r "from.*processors.website_graphrag_processor import" .
```

### Q: Are there any performance improvements in the new APIs?

**A:** Yes! The unified implementations are more efficient:
- Reduced import time (no shim overhead)
- Better memory usage (no duplicate code loaded)
- Optimized async operations in UnifiedGraphRAGProcessor

### Q: What happens to my existing data stored with deprecated APIs?

**A:** Your data is safe! Only the Python APIs are changing. Data formats (IPLD, CAR, Parquet) remain 100% compatible.

### Q: Can I suppress deprecation warnings?

**A:** Yes, but NOT recommended for production:
```python
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
```

Better approach: Fix the deprecated imports.

### Q: Will there be automatic migration tools?

**A:** Yes! Starting in v1.5 (May 2026), we provide:
- Migration checker (find deprecated imports)
- Migration script generator (auto-fix imports)
- Compatibility tester (verify migration)

### Q: What if I find a bug in the new implementation?

**A:** Please report it immediately:
1. GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
2. Include "deprecation migration" label
3. We'll prioritize migration-related bugs

---

## Communication Plan

### User Notifications

**v1.0 (February 2026):**
- ✅ Deprecation warnings in code
- ✅ Documentation published
- ✅ GitHub announcement

**v1.2 (March 2026):**
- Blog post on website
- Email to registered users (if available)
- Social media announcements

**v1.5 (May 2026):**
- Release notes highlighting migration tools
- Updated documentation with tool usage
- Community webinar (if interest)

**v1.7 (June 2026):**
- Email reminders to registered users
- GitHub issue trackers for migration help
- Community support thread

**v1.9 (July 2026):**
- Final warning announcements
- Countdown in release notes
- Migration deadline reminders

**v2.0 (August 2026):**
- Major version release announcement
- Celebration of clean architecture 🎉
- Post-migration support

### Support Resources

**During Migration Period:**
- GitHub Discussions for migration questions
- Migration guide documentation
- Example migration scripts
- Community support

**After v2.0:**
- Updated documentation
- New tutorials with v2.0 APIs
- Performance optimization guides

---

## Version Compatibility Matrix

| Your Code Uses | v1.0-1.4 | v1.5-1.8 | v1.9 | v2.0+ |
|----------------|----------|----------|------|-------|
| **New APIs only** | ✅ Works | ✅ Works | ✅ Works | ✅ Works |
| **Mixed (new + deprecated)** | ⚠️ Works with warnings | ⚠️ Works with loud warnings | ⚠️ Works with LOUD warnings | ❌ Breaks |
| **Deprecated only** | ⚠️ Works with warnings | ⚠️ Works with loud warnings | ⚠️ Works with LOUD warnings | ❌ Breaks |

**Recommendation:** Migrate to "New APIs only" before v2.0

---

## Summary

**Timeline:** 6 months from February 2026 to August 2026

**Key Dates:**
- **Now (v1.0):** Deprecation warnings active
- **May 2026 (v1.5):** Enhanced warnings + migration tools
- **July 2026 (v1.9):** Final warning period (1 month to v2.0)
- **August 2026 (v2.0):** Deprecated code removed

**Action Items:**
1. ✅ Acknowledge deprecation warnings
2. 📚 Review migration guides
3. 🔧 Update your code to use new imports
4. ✅ Test with v1.5 and migration tools
5. 🚀 Deploy migrated code before v2.0

**Support:**
- Migration guides: [docs/](.)
- GitHub Issues: [github.com/endomorphosis/ipfs_datasets_py/issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- Community support: GitHub Discussions

**You have 6 months to migrate. Start planning now!**

---

**Last Updated:** 2026-02-15  
**Status:** Active  
**Next Review:** v1.5 release (May 2026)
