# Migration Tools for IPFS Datasets Python

This directory contains tools to help with migrating from v1.x to v2.0.

## Available Tools

### migration_checker.py

Scans your codebase for deprecated imports and provides migration recommendations.

**Usage:**
```bash
# Scan current directory
python scripts/tools/migration_checker.py .

# Scan specific directory
python scripts/tools/migration_checker.py /path/to/project

# Verbose output with detailed suggestions
python scripts/tools/migration_checker.py . --verbose

# Check for v2.0 compatibility (strict mode)
python scripts/tools/migration_checker.py . --target v2.0
```

**Output:**
- Number of files scanned
- Count of deprecated imports by type (multimedia, serialization, GraphRAG)
- File-by-file breakdown
- Migration recommendations with before/after examples
- Links to relevant documentation

**Exit Codes:**
- `0`: No issues found or warnings only (v1.9)
- `1`: Deprecated imports found and target is v2.0 (errors)

## Planned Tools (v1.5 Release)

### migration_script_generator.py (Coming Soon)
Generates automated migration scripts based on scan results.

### compatibility_tester.py (Coming Soon)
Tests your code with both old and new imports to ensure compatibility.

### usage_analytics.py (Coming Soon)
Optional privacy-preserving analytics to help prioritize migration support.

## Documentation

For complete migration guidance, see:
- [MIGRATION_GUIDE_V2.md](../../docs/MIGRATION_GUIDE_V2.md) - Complete migration guide
- [DEPRECATION_TIMELINE.md](../../docs/DEPRECATION_TIMELINE.md) - Timeline and schedule
- [GRAPHRAG_CONSOLIDATION_GUIDE.md](../../docs/GRAPHRAG_CONSOLIDATION_GUIDE.md) - GraphRAG specifics
- [MULTIMEDIA_MIGRATION_GUIDE.md](../../docs/MULTIMEDIA_MIGRATION_GUIDE.md) - Multimedia specifics

## Support

For issues or questions:
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Discussions: https://github.com/endomorphosis/ipfs_datasets_py/discussions
