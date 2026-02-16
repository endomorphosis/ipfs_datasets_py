#!/usr/bin/env python3
"""
IPFS Import CLI

Command-line interface for importing data from IPLD format into IPFS Graph Database.

Usage:
    python scripts/migration/ipfs_import_cli.py \\
        --input graph_export.json \\
        --database default \\
        --batch-size 1000

Examples:
    # Basic import
    python scripts/migration/ipfs_import_cli.py \\
        --input my_graph.json

    # Import with validation
    python scripts/migration/ipfs_import_cli.py \\
        --input my_graph.json \\
        --validate \\
        --progress

    # Import without indexes/constraints
    python scripts/migration/ipfs_import_cli.py \\
        --input my_graph.json \\
        --no-indexes \\
        --no-constraints
"""

import argparse
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.knowledge_graphs.migration import (
    IPFSImporter,
    ImportConfig,
    MigrationFormat
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def progress_callback(nodes_imported, rels_imported, message):
    """Progress callback for import."""
    if nodes_imported > 0:
        print(f"\r{message} (Nodes: {nodes_imported})", end='', flush=True)
    elif rels_imported > 0:
        print(f"\r{message} (Relationships: {rels_imported})", end='', flush=True)
    else:
        print(f"\r{message}", end='', flush=True)


def main():
    parser = argparse.ArgumentParser(
        description='Import data from IPLD format into IPFS Graph Database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Input arguments
    parser.add_argument(
        '--input',
        '-i',
        required=True,
        help='Input file path'
    )
    parser.add_argument(
        '--format',
        choices=['dag-json', 'jsonlines'],
        default='dag-json',
        help='Input format (default: dag-json)'
    )
    
    # Database arguments
    parser.add_argument(
        '--database',
        default='default',
        help='Target database name (default: default)'
    )
    
    # Import options
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for import (default: 1000)'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate data before import'
    )
    parser.add_argument(
        '--no-indexes',
        action='store_true',
        help='Skip index creation'
    )
    parser.add_argument(
        '--no-constraints',
        action='store_true',
        help='Skip constraint creation'
    )
    parser.add_argument(
        '--allow-duplicates',
        action='store_true',
        help='Allow duplicate nodes/relationships'
    )
    
    # Display options
    parser.add_argument(
        '--progress',
        action='store_true',
        help='Show progress during import'
    )
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
    
    # Check input file exists
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1
    
    # Parse format
    input_format = MigrationFormat.DAG_JSON
    if args.format == 'jsonlines':
        input_format = MigrationFormat.JSON_LINES
    
    # Create import config
    config = ImportConfig(
        input_file=args.input,
        input_format=input_format,
        database=args.database,
        batch_size=args.batch_size,
        validate_data=args.validate,
        create_indexes=not args.no_indexes,
        create_constraints=not args.no_constraints,
        skip_duplicates=not args.allow_duplicates,
        progress_callback=progress_callback if args.progress else None
    )
    
    # Print configuration
    if not args.quiet:
        print("=" * 60)
        print("IPFS Import Configuration")
        print("=" * 60)
        print(f"Input file:         {args.input}")
        print(f"Input format:       {args.format}")
        print(f"Target database:    {args.database}")
        print(f"Batch size:         {args.batch_size}")
        print(f"Validate:           {args.validate}")
        print(f"Create indexes:     {not args.no_indexes}")
        print(f"Create constraints: {not args.no_constraints}")
        print(f"Skip duplicates:    {not args.allow_duplicates}")
        print("=" * 60)
        print()
    
    # Perform import
    try:
        importer = IPFSImporter(config)
        
        if not args.quiet:
            print("Starting import...")
            print()
        
        result = importer.import_data()
        
        if args.progress:
            print()  # New line after progress
        
        if result.success:
            print()
            print("=" * 60)
            print("Import Completed Successfully!")
            print("=" * 60)
            print(f"Nodes imported:          {result.nodes_imported}")
            print(f"Relationships imported:  {result.relationships_imported}")
            if result.nodes_skipped > 0:
                print(f"Nodes skipped:           {result.nodes_skipped}")
            if result.relationships_skipped > 0:
                print(f"Relationships skipped:   {result.relationships_skipped}")
            print(f"Duration:                {result.duration_seconds:.2f} seconds")
            print("=" * 60)
            
            # Performance stats
            if result.duration_seconds > 0:
                nodes_per_sec = result.nodes_imported / result.duration_seconds
                rels_per_sec = result.relationships_imported / result.duration_seconds
                print(f"Performance:             {nodes_per_sec:.0f} nodes/sec, {rels_per_sec:.0f} rels/sec")
                print("=" * 60)
            
            # Warnings
            if result.warnings:
                print("\nWarnings:")
                for warning in result.warnings:
                    print(f"  - {warning}")
                print("=" * 60)
            
            return 0
        else:
            print()
            print("=" * 60)
            print("Import Failed!")
            print("=" * 60)
            print(f"Nodes imported:          {result.nodes_imported}")
            print(f"Relationships imported:  {result.relationships_imported}")
            print("\nErrors:")
            for error in result.errors:
                print(f"  - {error}")
            if result.warnings:
                print("\nWarnings:")
                for warning in result.warnings:
                    print(f"  - {warning}")
            print("=" * 60)
            return 1
    
    except KeyboardInterrupt:
        print("\n\nImport interrupted by user.")
        return 130
    except Exception as e:
        logger.error(f"Import failed with exception: {e}", exc_info=args.verbose)
        return 1


if __name__ == '__main__':
    sys.exit(main())
