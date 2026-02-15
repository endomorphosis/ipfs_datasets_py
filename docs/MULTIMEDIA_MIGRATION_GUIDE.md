# Multimedia Migration Guide

**Version:** 1.0  
**Date:** 2026-02-15  
**Status:** Multimedia Core Migration Complete  
**Deprecation Target:** v2.0.0 (6 months)

---

## Overview

The multimedia processing functionality has been migrated from `data_transformation/multimedia/` to `processors/multimedia/` to create a cleaner architectural separation. This guide helps you update your code to use the new location.

**Migration Status:**
- ✅ Core multimedia files migrated and working
- ✅ Deprecation shim active with backward compatibility
- ✅ All functionality preserved
- ⚠️ Old imports show DeprecationWarning

---

## Quick Migration

### Before (Deprecated)
```python
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper
from ipfs_datasets_py.data_transformation.multimedia import MediaProcessor
from ipfs_datasets_py.data_transformation.multimedia import MediaUtils
from ipfs_datasets_py.data_transformation.multimedia import EmailProcessor
from ipfs_datasets_py.data_transformation.multimedia import DiscordWrapper
```

### After (Current)
```python
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
from ipfs_datasets_py.processors.multimedia import MediaProcessor
from ipfs_datasets_py.processors.multimedia import MediaUtils
from ipfs_datasets_py.processors.multimedia import EmailProcessor
from ipfs_datasets_py.processors.multimedia import DiscordWrapper
```

**That's it!** Just change `data_transformation.multimedia` to `processors.multimedia`.

---

## What Changed

### Location Change

| Component | Old Location | New Location | Status |
|-----------|-------------|--------------|--------|
| FFmpegWrapper | data_transformation/multimedia/ | processors/multimedia/ | ✅ Migrated |
| YtDlpWrapper | data_transformation/multimedia/ | processors/multimedia/ | ✅ Migrated |
| MediaProcessor | data_transformation/multimedia/ | processors/multimedia/ | ✅ Migrated |
| MediaUtils | data_transformation/multimedia/ | processors/multimedia/ | ✅ Migrated |
| EmailProcessor | data_transformation/multimedia/ | processors/multimedia/ | ✅ Migrated |
| DiscordWrapper | data_transformation/multimedia/ | processors/multimedia/ | ✅ Migrated |

### What Stayed the Same

✅ **All class names remain unchanged**  
✅ **All method signatures remain unchanged**  
✅ **All functionality remains unchanged**  
✅ **No breaking changes to your code** (until v2.0.0)

---

## Migration Steps

### Step 1: Find Old Imports

Search your codebase for old imports:

```bash
grep -r "from ipfs_datasets_py.data_transformation.multimedia" .
grep -r "import ipfs_datasets_py.data_transformation.multimedia" .
```

### Step 2: Replace Imports

**Option A: Automated (Recommended)**
```bash
# On Linux/Mac
find . -name "*.py" -type f -exec sed -i 's/data_transformation\.multimedia/processors.multimedia/g' {} +

# On Mac (BSD sed)
find . -name "*.py" -type f -exec sed -i '' 's/data_transformation\.multimedia/processors.multimedia/g' {} +
```

**Option B: Manual**
Open each file and replace:
- `from ipfs_datasets_py.data_transformation.multimedia` → `from ipfs_datasets_py.processors.multimedia`
- `import ipfs_datasets_py.data_transformation.multimedia` → `import ipfs_datasets_py.processors.multimedia`

### Step 3: Test

Run your tests to ensure everything works:

```bash
pytest tests/
```

### Step 4: Verify No Warnings

Run your code and check for DeprecationWarnings:

```python
import warnings
warnings.simplefilter('always', DeprecationWarning)

# Your code here
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper  # No warning ✅
```

---

## Detailed Migration Examples

### Example 1: Video Processing

**Before:**
```python
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper, YtDlpWrapper

# Download video
downloader = YtDlpWrapper()
video_path = downloader.download("https://youtube.com/watch?v=...")

# Process video
ffmpeg = FFmpegWrapper()
ffmpeg.extract_audio(video_path, "audio.mp3")
```

**After:**
```python
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper, YtDlpWrapper

# Same code - no changes needed!
downloader = YtDlpWrapper()
video_path = downloader.download("https://youtube.com/watch?v=...")

ffmpeg = FFmpegWrapper()
ffmpeg.extract_audio(video_path, "audio.mp3")
```

### Example 2: Email Processing

**Before:**
```python
from ipfs_datasets_py.data_transformation.multimedia import EmailProcessor

processor = EmailProcessor()
emails = processor.fetch_from_imap(
    host="imap.gmail.com",
    username="user@gmail.com",
    password="password"
)
```

**After:**
```python
from ipfs_datasets_py.processors.multimedia import EmailProcessor

# Same code - no changes needed!
processor = EmailProcessor()
emails = processor.fetch_from_imap(
    host="imap.gmail.com",
    username="user@gmail.com",
    password="password"
)
```

### Example 3: Discord Export

**Before:**
```python
from ipfs_datasets_py.data_transformation.multimedia import DiscordWrapper

discord = DiscordWrapper()
messages = discord.export_channel("channel_id")
```

**After:**
```python
from ipfs_datasets_py.processors.multimedia import DiscordWrapper

# Same code - no changes needed!
discord = DiscordWrapper()
messages = discord.export_channel("channel_id")
```

### Example 4: Media Analysis

**Before:**
```python
from ipfs_datasets_py.data_transformation.multimedia import MediaUtils

utils = MediaUtils()
metadata = utils.extract_metadata("video.mp4")
duration = utils.get_duration("video.mp4")
```

**After:**
```python
from ipfs_datasets_py.processors.multimedia import MediaUtils

# Same code - no changes needed!
utils = MediaUtils()
metadata = utils.extract_metadata("video.mp4")
duration = utils.get_duration("video.mp4")
```

---

## Deprecation Timeline

### Current (v1.x)
- ✅ Old imports still work
- ⚠️ DeprecationWarning displayed
- ✅ Full backward compatibility maintained

### v1.9 (3 months)
- ⚠️ Strong deprecation warnings
- 📝 Final migration reminders
- ✅ Still backward compatible

### v2.0.0 (6 months)
- ❌ Old imports will fail
- ✅ Must use new location
- 🚫 Deprecation shim removed

**Recommendation:** Migrate now to avoid issues when v2.0.0 is released.

---

## Migration Checklist

Use this checklist to track your migration progress:

- [ ] Find all old multimedia imports in your codebase
- [ ] Update imports to use `processors.multimedia`
- [ ] Run automated tests
- [ ] Verify no DeprecationWarnings
- [ ] Update documentation/comments
- [ ] Update requirements/dependencies (if pinned to specific versions)
- [ ] Test in staging environment
- [ ] Deploy to production

---

## Common Issues & Solutions

### Issue 1: DeprecationWarning Still Appearing

**Problem:**
```
DeprecationWarning: ipfs_datasets_py.data_transformation.multimedia is deprecated...
```

**Solution:**
You still have an old import somewhere. Search your code:
```bash
grep -r "data_transformation.multimedia" .
```

### Issue 2: Import Error After Migration

**Problem:**
```
ModuleNotFoundError: No module named 'ipfs_datasets_py.processors.multimedia'
```

**Solution:**
1. Check your ipfs_datasets_py version: `pip show ipfs_datasets_py`
2. Update to latest: `pip install --upgrade ipfs_datasets_py`
3. Reinstall in development mode: `pip install -e .`

### Issue 3: Mixed Old and New Imports

**Problem:**
Some files use old imports, others use new imports.

**Solution:**
Use automated replacement to ensure consistency:
```bash
find . -name "*.py" -type f -exec sed -i 's/data_transformation\.multimedia/processors.multimedia/g' {} +
```

### Issue 4: Functionality Not Working

**Problem:**
After migration, some multimedia feature doesn't work.

**Solution:**
1. Verify you have required dependencies: `pip install ipfs_datasets_py[multimedia]`
2. Check that the feature worked before migration
3. Report issue on GitHub if it's a regression

---

## Advanced Topics

### Using Both Old and New (Not Recommended)

While the deprecation shim allows old and new imports to coexist, **we strongly recommend** migrating all imports at once to avoid confusion.

```python
# Don't do this (mixing old and new)
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper  # Old
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper  # New

# Do this (all new)
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper, YtDlpWrapper
```

### Conditional Imports (Legacy Support)

If you need to support both old and new versions:

```python
try:
    # Try new location first
    from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
except ImportError:
    # Fall back to old location (for older versions)
    from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
```

**Note:** This is only needed if you're supporting very old versions of ipfs_datasets_py.

### Verifying Migration Programmatically

```python
import sys
import warnings

# Catch deprecation warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always", DeprecationWarning)
    
    # Your imports here
    from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
    
    # Check for warnings
    if w:
        print(f"⚠️ Found {len(w)} deprecation warnings:")
        for warning in w:
            print(f"  - {warning.message}")
    else:
        print("✅ No deprecation warnings!")
```

---

## API Reference

All classes maintain the same API. For detailed API documentation, see:

- **FFmpegWrapper:** [processors/multimedia/ffmpeg_wrapper.py](../../ipfs_datasets_py/processors/multimedia/ffmpeg_wrapper.py)
- **YtDlpWrapper:** [processors/multimedia/ytdlp_wrapper.py](../../ipfs_datasets_py/processors/multimedia/ytdlp_wrapper.py)
- **MediaProcessor:** [processors/multimedia/media_processor.py](../../ipfs_datasets_py/processors/multimedia/media_processor.py)
- **MediaUtils:** [processors/multimedia/media_utils.py](../../ipfs_datasets_py/processors/multimedia/media_utils.py)
- **EmailProcessor:** [processors/multimedia/email_processor.py](../../ipfs_datasets_py/processors/multimedia/email_processor.py)
- **DiscordWrapper:** [processors/multimedia/discord_wrapper.py](../../ipfs_datasets_py/processors/multimedia/discord_wrapper.py)

---

## FAQ

### Q: Why was this changed?

**A:** To create better architectural separation:
- `processors/` = High-level user-facing APIs
- `data_transformation/` = Low-level utilities and infrastructure

### Q: Do I have to migrate immediately?

**A:** No, but we recommend it. Old imports work until v2.0.0 (6 months), but migrating now avoids future issues.

### Q: Will my code break?

**A:** Not until v2.0.0. The deprecation shim maintains full backward compatibility.

### Q: What about the large submodules (omni_converter_mk2, convert_to_txt)?

**A:** They remain accessible in `processors/multimedia/` and may be simplified in future updates. You can continue using them as-is.

### Q: Can I help?

**A:** Yes! Report any migration issues on GitHub, suggest documentation improvements, or help other users migrate.

---

## Getting Help

- **GitHub Issues:** [ipfs_datasets_py/issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Documentation:** [docs/](../../docs/)
- **Migration Support:** Open an issue with the `migration` label

---

## Summary

**Migration is simple:**
1. Replace `data_transformation.multimedia` with `processors.multimedia`
2. Test your code
3. Done!

**No API changes, no functionality changes, just a location change.**

**Timeline:** 6 months until old location stops working (v2.0.0)

**Status:** Migration encouraged now, required by v2.0.0

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-15  
**Next Review:** Before v2.0.0 release
