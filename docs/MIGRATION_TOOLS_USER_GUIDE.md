# Migration Tools User Guide

Complete guide for migrating data between Neo4j and IPFS Graph Database.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Tools](#cli-tools)
- [Python API](#python-api)
- [Migration Workflow](#migration-workflow)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)
- [Performance](#performance)

## Overview

The IPFS Datasets migration tools enable seamless data portability between Neo4j and IPFS Graph Database. Key features:

- **Zero data loss** - All nodes, relationships, and properties preserved
- **Schema migration** - Indexes and constraints automatically migrated
- **Batch processing** - Handles databases of any size efficiently
- **Validation** - Schema compatibility checking before migration
- **Verification** - Data integrity verification after migration
- **Multiple formats** - DAG-JSON and JSON Lines support

## Installation

### Requirements

- Python 3.12+
- Neo4j Python driver (for export): `pip install neo4j`
- IPFS Datasets: Already installed

### Optional Dependencies

```bash
# For Neo4j export
pip install neo4j

# For progress bars (optional)
pip install tqdm
```

## Quick Start

### Complete Migration (One Command)

Migrate your entire Neo4j database to IPFS in one command:

```bash
python scripts/migration/migrate_cli.py \
    --from bolt://localhost:7687 \
    --username neo4j \
    --password yourpassword \
    --to ipfs://embedded \
    --output backup.json \
    --validate \
    --verify
```

This command will:
1. Export all data from Neo4j
2. Validate schema compatibility
3. Import into IPFS Graph Database
4. Verify data integrity
5. Save backup to `backup.json`

### Step-by-Step Migration

For more control, use individual tools:

#### 1. Export from Neo4j

```bash
python scripts/migration/neo4j_export_cli.py \
    --uri bolt://localhost:7687 \
    --username neo4j \
    --password yourpassword \
    --output my_graph.json \
    --progress
```

#### 2. Check Schema Compatibility

```bash
python scripts/migration/schema_check_cli.py \
    --input my_graph.json \
    --verbose
```

#### 3. Import to IPFS

```bash
python scripts/migration/ipfs_import_cli.py \
    --input my_graph.json \
    --validate \
    --progress
```

## CLI Tools

### neo4j_export_cli.py

Export data from Neo4j to IPLD format.

**Basic Usage:**
```bash
python scripts/migration/neo4j_export_cli.py \
    --uri bolt://localhost:7687 \
    --username neo4j \
    --password password \
    --output graph.json
```

**Options:**
- `--uri` - Neo4j connection URI (required)
- `--username` - Neo4j username (default: neo4j)
- `--password` - Neo4j password (required)
- `--database` - Database name (default: neo4j)
- `--output` - Output file path (required)
- `--format` - Output format: dag-json or jsonlines (default: dag-json)
- `--batch-size` - Batch size for export (default: 1000)
- `--node-labels` - Filter: only export these node labels
- `--relationship-types` - Filter: only export these relationship types
- `--no-schema` - Skip schema export
- `--progress` - Show progress bar

**Examples:**

Export specific labels:
```bash
python scripts/migration/neo4j_export_cli.py \
    --uri bolt://localhost:7687 \
    --username neo4j \
    --password password \
    --output filtered.json \
    --node-labels Person,Company \
    --relationship-types WORKS_FOR,KNOWS
```

Large database with progress:
```bash
python scripts/migration/neo4j_export_cli.py \
    --uri bolt://localhost:7687 \
    --username neo4j \
    --password password \
    --output large.json \
    --batch-size 5000 \
    --progress
```

### ipfs_import_cli.py

Import data from IPLD format into IPFS Graph Database.

**Basic Usage:**
```bash
python scripts/migration/ipfs_import_cli.py \
    --input graph.json
```

**Options:**
- `--input` - Input file path (required)
- `--format` - Input format: dag-json or jsonlines (default: dag-json)
- `--database` - Target database name (default: default)
- `--batch-size` - Batch size for import (default: 1000)
- `--validate` - Validate data before import (recommended)
- `--no-indexes` - Skip index creation
- `--no-constraints` - Skip constraint creation
- `--allow-duplicates` - Allow duplicate nodes/relationships
- `--progress` - Show progress bar

**Examples:**

Import with validation:
```bash
python scripts/migration/ipfs_import_cli.py \
    --input graph.json \
    --validate \
    --progress
```

Import without schema:
```bash
python scripts/migration/ipfs_import_cli.py \
    --input graph.json \
    --no-indexes \
    --no-constraints
```

### migrate_cli.py

Complete migration with validation and verification.

**Basic Usage:**
```bash
python scripts/migration/migrate_cli.py \
    --from bolt://localhost:7687 \
    --username neo4j \
    --password password \
    --to ipfs://embedded
```

**Options:**
- `--from` - Source Neo4j URI (required)
- `--username` - Neo4j username (default: neo4j)
- `--password` - Neo4j password
- `--source-database` - Source database (default: neo4j)
- `--to` - Target IPFS URI (default: ipfs://embedded)
- `--target-database` - Target database (default: default)
- `--output` - Backup file path (optional)
- `--no-backup` - Skip creating backup
- `--batch-size` - Batch size (default: 1000)
- `--validate` - Validate schema (recommended)
- `--verify` - Verify integrity (recommended)
- `--skip-schema` - Skip schema migration
- `--interactive` - Interactive mode with prompts
- `--dry-run` - Validation only, no migration

**Examples:**

Interactive migration:
```bash
python scripts/migration/migrate_cli.py \
    --from bolt://localhost:7687 \
    --username neo4j \
    --interactive
```

Dry run (validation only):
```bash
python scripts/migration/migrate_cli.py \
    --from bolt://localhost:7687 \
    --username neo4j \
    --password password \
    --dry-run \
    --validate
```

Production migration with all checks:
```bash
python scripts/migration/migrate_cli.py \
    --from bolt://localhost:7687 \
    --username neo4j \
    --password password \
    --to ipfs://embedded \
    --output backup_$(date +%Y%m%d).json \
    --validate \
    --verify \
    --batch-size 5000
```

### schema_check_cli.py

Check schema compatibility before migration.

**Basic Usage:**
```bash
python scripts/migration/schema_check_cli.py \
    --input graph.json
```

**Options:**
- `--input` - Input file with graph data (required)
- `--format` - Input format (default: dag-json)
- `--verbose` - Show detailed schema information

**Examples:**

Basic check:
```bash
python scripts/migration/schema_check_cli.py --input graph.json
```

Detailed report:
```bash
python scripts/migration/schema_check_cli.py --input graph.json --verbose
```

## Python API

For programmatic access, use the Python API directly:

```python
from ipfs_datasets_py.knowledge_graphs.migration import (
    Neo4jExporter, IPFSImporter, SchemaChecker,
    ExportConfig, ImportConfig, GraphData
)

# Export from Neo4j
config = ExportConfig(
    uri="bolt://localhost:7687",
    username="neo4j",
    ******,
    output_file="graph.json"
)
exporter = Neo4jExporter(config)
result = exporter.export()

if result.success:
    print(f"Exported {result.node_count} nodes")

# Check schema
graph_data = GraphData.load_from_file("graph.json")
checker = SchemaChecker()
report = checker.check_schema(graph_data.schema)

if report.compatible:
    print(f"Schema compatible: {report.compatibility_score}%")

# Import to IPFS
config = ImportConfig(
    input_file="graph.json",
    validate_data=True
)
importer = IPFSImporter(config)
result = importer.import_data()

if result.success:
    print(f"Imported {result.nodes_imported} nodes")
```

## Migration Workflow

### Recommended Workflow

1. **Backup** - Always create a backup first
2. **Export** - Export from Neo4j with schema
3. **Validate** - Check schema compatibility
4. **Review** - Address any compatibility issues
5. **Import** - Import to IPFS
6. **Verify** - Verify data integrity
7. **Test** - Run application tests
8. **Monitor** - Monitor for issues

### For Large Databases (100K+ nodes)

1. **Test on subset** - Export and migrate a subset first
2. **Increase batch size** - Use `--batch-size 5000` or higher
3. **Monitor resources** - Watch memory and disk usage
4. **Use streaming** - Consider JSON Lines format for very large datasets
5. **Incremental migration** - Migrate by label/type if needed

### For Production Migration

1. **Maintenance window** - Schedule during low-traffic period
2. **Backup** - Full backup of source database
3. **Test migration** - Run complete test on staging
4. **Monitor** - Set up monitoring for both systems
5. **Gradual cutover** - Consider dual-write period
6. **Rollback plan** - Have rollback procedure ready

## Troubleshooting

### Common Issues

#### Connection Refused

**Problem:** Cannot connect to Neo4j
```
Error: Failed to connect to Neo4j
```

**Solution:**
- Check Neo4j is running: `systemctl status neo4j`
- Verify URI: Should be `bolt://host:7687` not `http://`
- Check firewall/network settings

#### Out of Memory

**Problem:** Process runs out of memory during export/import

**Solution:**
- Increase batch size: `--batch-size 10000`
- Use JSON Lines format: `--format jsonlines`
- Process incrementally with filters: `--node-labels Label1`

#### Schema Incompatibility

**Problem:** Schema check reports compatibility issues

**Solution:**
- Review detailed report: `schema_check_cli.py --verbose`
- Check supported features in documentation
- Consider manual schema adjustments
- Use `--skip-schema` if necessary

#### Import Fails with Validation Errors

**Problem:** Import fails during validation

**Solution:**
- Review error messages for specific issues
- Check for duplicate IDs in source data
- Verify relationship endpoints exist
- Use `--no-validate` to skip validation (not recommended)

### Debugging

Enable verbose logging:
```bash
# Add --verbose flag
python scripts/migration/migrate_cli.py --verbose ...

# Or set environment variable
export LOG_LEVEL=DEBUG
python scripts/migration/migrate_cli.py ...
```

## Best Practices

### Before Migration

1. **Backup** - Always backup your Neo4j database
2. **Test** - Test migration on a copy first
3. **Review schema** - Run schema check and review issues
4. **Plan downtime** - Schedule maintenance window
5. **Document** - Document your migration plan

### During Migration

1. **Monitor** - Watch for errors and warnings
2. **Save backup** - Keep the export file
3. **Validate** - Use `--validate` flag
4. **Verify** - Use `--verify` flag
5. **Log** - Save migration output to file

### After Migration

1. **Verify data** - Run queries to verify data integrity
2. **Test application** - Test your application thoroughly
3. **Monitor performance** - Watch for performance issues
4. **Keep backup** - Keep export file for rollback
5. **Document** - Document any issues encountered

### Performance Tips

1. **Batch size** - Adjust based on available memory
   - Small databases (<10K nodes): 1000 (default)
   - Medium databases (10K-100K): 5000
   - Large databases (>100K): 10000

2. **Network** - For remote Neo4j, consider:
   - Running export on Neo4j server
   - Using higher batch sizes
   - Compressing output file

3. **Format** - Choose format based on use case:
   - DAG-JSON: Better for small-medium databases
   - JSON Lines: Better for large databases (streaming)

## Performance

### Expected Performance

Based on testing with various database sizes:

| Database Size | Export Time | Import Time | Total Time |
|--------------|-------------|-------------|------------|
| 10K nodes    | ~5 sec      | ~10 sec     | ~15 sec    |
| 100K nodes   | ~30 sec     | ~60 sec     | ~90 sec    |
| 1M nodes     | ~5 min      | ~10 min     | ~15 min    |

*Times are approximate and depend on:*
- Hardware (CPU, RAM, disk)
- Network latency (for remote Neo4j)
- Relationship density
- Property complexity

### Performance Tuning

**For Export:**
- Increase `--batch-size` to 5000-10000
- Use local Neo4j connection (avoid network)
- Run on Neo4j server if possible

**For Import:**
- Increase `--batch-size` to 5000-10000
- Use SSD for IPFS storage
- Disable validation for large datasets (after testing)
- Skip schema creation if not needed

**For Memory:**
- Use JSON Lines format for streaming
- Process by label/type incrementally
- Monitor with `htop` or similar
- Adjust JVM settings for Neo4j

## Getting Help

- **Documentation**: See `docs/KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md`
- **Examples**: See `docs/examples/migration/`
- **Issues**: Report issues on GitHub
- **Support**: Check FAQ and troubleshooting sections

## Next Steps

After successful migration:

1. **Update connection strings** - Update application to use IPFS
2. **Test thoroughly** - Run full test suite
3. **Monitor** - Set up monitoring and alerting
4. **Optimize** - Review and optimize queries if needed
5. **Document** - Update documentation with IPFS details

## Additional Resources

- [Knowledge Graphs Documentation](./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md)
- [Neo4j API Migration Guide](./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md)
- [Cypher Compatibility](./KNOWLEDGE_GRAPHS_FEATURE_MATRIX.md)
- [Performance Guide](./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md)
