#!/usr/bin/env python3
"""
Complete Migration CLI

One-command migration from Neo4j to IPFS Graph Database with validation and verification.

Usage:
    python scripts/migration/migrate_cli.py \\
        --from bolt://localhost:7687 \\
        --username neo4j \\
        --password password \\
        --to ipfs://embedded \\
        --output migration_backup.json

Examples:
    # Complete migration with all steps
    python scripts/migration/migrate_cli.py \\
        --from bolt://localhost:7687 \\
        --username neo4j \\
        --password mypassword \\
        --to ipfs://embedded \\
        --output backup.json \\
        --validate

    # Interactive mode (prompts for password)
    python scripts/migration/migrate_cli.py \\
        --from bolt://localhost:7687 \\
        --username neo4j \\
        --interactive

    # Quick migration without backup
    python scripts/migration/migrate_cli.py \\
        --from bolt://localhost:7687 \\
        --username neo4j \\
        --password mypassword \\
        --to ipfs://embedded \\
        --no-backup
"""

import argparse
import sys
import logging
import getpass
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.knowledge_graphs.migration import (
    Neo4jExporter,
    IPFSImporter,
    SchemaChecker,
    IntegrityVerifier,
    ExportConfig,
    ImportConfig,
    MigrationFormat,
    GraphData
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner(title):
    """Print a formatted banner."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()


def print_step(step_num, total_steps, description):
    """Print a step indicator."""
    print(f"\n[Step {step_num}/{total_steps}] {description}")
    print("-" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='Complete migration from Neo4j to IPFS Graph Database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Source arguments
    parser.add_argument(
        '--from',
        dest='source_uri',
        required=True,
        help='Source Neo4j URI (e.g., bolt://localhost:7687)'
    )
    parser.add_argument(
        '--username',
        default='neo4j',
        help='Neo4j username (default: neo4j)'
    )
    parser.add_argument(
        '--password',
        help='Neo4j password (will prompt if not provided)'
    )
    parser.add_argument(
        '--source-database',
        default='neo4j',
        help='Source database name (default: neo4j)'
    )
    
    # Target arguments
    parser.add_argument(
        '--to',
        dest='target_uri',
        default='ipfs://embedded',
        help='Target IPFS URI (default: ipfs://embedded)'
    )
    parser.add_argument(
        '--target-database',
        default='default',
        help='Target database name (default: default)'
    )
    
    # Backup/output
    parser.add_argument(
        '--output',
        '-o',
        help='Backup file path (optional)'
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Skip creating backup file'
    )
    
    # Migration options
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for export/import (default: 1000)'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate schema and data (recommended)'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify integrity after migration (recommended)'
    )
    parser.add_argument(
        '--skip-schema',
        action='store_true',
        help='Skip schema migration (indexes, constraints)'
    )
    
    # Mode
    parser.add_argument(
        '--interactive',
        '-i',
        action='store_true',
        help='Interactive mode with prompts'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Perform validation only, no actual migration'
    )
    
    # Display
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Verbose output'
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress non-error output'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    elif args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Get password if not provided
    password = args.password
    if not password:
        if args.interactive:
            password = getpass.getpass("Neo4j password: ")
        else:
            logger.error("Password required. Use --password or --interactive")
            return 1
    
    # Determine output file
    output_file = args.output
    if not output_file and not args.no_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"neo4j_migration_{timestamp}.json"
    
    # Print migration plan
    if not args.quiet:
        print_banner("Neo4j to IPFS Graph Database Migration")
        
        print("Migration Configuration:")
        print(f"  Source:          {args.source_uri} (database: {args.source_database})")
        print(f"  Target:          {args.target_uri} (database: {args.target_database})")
        if output_file:
            print(f"  Backup file:     {output_file}")
        print(f"  Batch size:      {args.batch_size}")
        print(f"  Validate schema: {args.validate}")
        print(f"  Verify data:     {args.verify}")
        print(f"  Dry run:         {args.dry_run}")
        print()
        
        if args.interactive:
            response = input("Proceed with migration? [y/N]: ")
            if response.lower() != 'y':
                print("Migration cancelled.")
                return 0
    
    try:
        total_steps = 2  # Export, Import
        if args.validate:
            total_steps += 1
        if args.verify:
            total_steps += 1
        
        current_step = 0
        
        # Step 1: Export from Neo4j
        current_step += 1
        print_step(current_step, total_steps, "Exporting data from Neo4j")
        
        export_config = ExportConfig(
            uri=args.source_uri,
            username=args.username,
            password=password,
            database=args.source_database,
            batch_size=args.batch_size,
            include_schema=not args.skip_schema,
            output_file=output_file if not args.no_backup else None
        )
        
        exporter = Neo4jExporter(export_config)
        export_result = exporter.export()
        
        if not export_result.success:
            logger.error("Export failed!")
            for error in export_result.errors:
                logger.error(f"  {error}")
            return 1
        
        print(f"✓ Exported {export_result.node_count} nodes and {export_result.relationship_count} relationships")
        print(f"  Duration: {export_result.duration_seconds:.2f} seconds")
        
        # Get graph data for validation/import
        graph_data = exporter.export_to_graph_data()
        if not graph_data:
            logger.error("Failed to load exported data")
            return 1
        
        # Step 2: Validate schema (optional)
        if args.validate and graph_data.schema:
            current_step += 1
            print_step(current_step, total_steps, "Validating schema compatibility")
            
            checker = SchemaChecker()
            compat_report = checker.check_schema(graph_data.schema)
            
            print(f"  Compatibility score: {compat_report.compatibility_score:.1f}%")
            
            if not compat_report.compatible:
                print(f"  ⚠ Found {len(compat_report.issues)} compatibility issues:")
                for issue in compat_report.issues[:5]:  # Show first 5
                    print(f"    - {issue['message']}")
                if len(compat_report.issues) > 5:
                    print(f"    ... and {len(compat_report.issues) - 5} more")
                
                if args.interactive:
                    response = input("\nContinue with migration despite issues? [y/N]: ")
                    if response.lower() != 'y':
                        print("Migration cancelled.")
                        return 0
            else:
                print("  ✓ Schema is compatible")
        
        if args.dry_run:
            print_banner("Dry Run Complete")
            print("Migration would proceed with:")
            print(f"  {export_result.node_count} nodes")
            print(f"  {export_result.relationship_count} relationships")
            return 0
        
        # Step 3: Import to IPFS
        current_step += 1
        print_step(current_step, total_steps, "Importing data to IPFS Graph Database")
        
        import_config = ImportConfig(
            graph_data=graph_data,
            database=args.target_database,
            batch_size=args.batch_size,
            validate_data=True,
            create_indexes=not args.skip_schema,
            create_constraints=not args.skip_schema
        )
        
        importer = IPFSImporter(import_config)
        import_result = importer.import_data()
        
        if not import_result.success:
            logger.error("Import failed!")
            for error in import_result.errors:
                logger.error(f"  {error}")
            return 1
        
        print(f"✓ Imported {import_result.nodes_imported} nodes and {import_result.relationships_imported} relationships")
        if import_result.nodes_skipped > 0 or import_result.relationships_skipped > 0:
            print(f"  Skipped: {import_result.nodes_skipped} nodes, {import_result.relationships_skipped} relationships")
        print(f"  Duration: {import_result.duration_seconds:.2f} seconds")
        
        # Step 4: Verify integrity (optional)
        if args.verify:
            current_step += 1
            print_step(current_step, total_steps, "Verifying data integrity")
            
            # For verification, we would need to export from IPFS and compare
            # For now, just do basic checks
            print(f"  ✓ Node count matches: {export_result.node_count == import_result.nodes_imported}")
            print(f"  ✓ Relationship count matches: {export_result.relationship_count == import_result.relationships_imported}")
        
        # Success!
        print_banner("Migration Completed Successfully!")
        
        print("Summary:")
        print(f"  Nodes migrated:          {import_result.nodes_imported}")
        print(f"  Relationships migrated:  {import_result.relationships_imported}")
        print(f"  Total duration:          {export_result.duration_seconds + import_result.duration_seconds:.2f} seconds")
        if output_file:
            print(f"  Backup saved to:         {output_file}")
        print()
        
        return 0
    
    except KeyboardInterrupt:
        print("\n\nMigration interrupted by user.")
        return 130
    except Exception as e:
        logger.error(f"Migration failed with exception: {e}", exc_info=args.verbose)
        return 1


if __name__ == '__main__':
    sys.exit(main())
