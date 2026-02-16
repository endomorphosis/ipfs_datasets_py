#!/usr/bin/env python3
"""
Neo4j Export CLI

Command-line interface for exporting data from Neo4j to IPLD format.

Usage:
    python scripts/migration/neo4j_export_cli.py \\
        --uri bolt://localhost:7687 \\
        --username neo4j \\
        --password password \\
        --output graph_export.json \\
        --batch-size 1000

Examples:
    # Basic export
    python scripts/migration/neo4j_export_cli.py \\
        --uri bolt://localhost:7687 \\
        --username neo4j \\
        --password mypassword \\
        --output my_graph.json

    # Export with filtering
    python scripts/migration/neo4j_export_cli.py \\
        --uri bolt://localhost:7687 \\
        --username neo4j \\
        --password mypassword \\
        --output filtered_graph.json \\
        --node-labels Person,Company \\
        --relationship-types WORKS_FOR,KNOWS

    # Large database with progress
    python scripts/migration/neo4j_export_cli.py \\
        --uri bolt://localhost:7687 \\
        --username neo4j \\
        --password mypassword \\
        --output large_graph.json \\
        --batch-size 5000 \\
        --progress
"""

import argparse
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.knowledge_graphs.migration import (
    Neo4jExporter,
    ExportConfig,
    MigrationFormat
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def progress_callback(nodes_exported, rels_exported, message):
    """Progress callback for export."""
    if nodes_exported > 0:
        print(f"\r{message} (Nodes: {nodes_exported})", end='', flush=True)
    elif rels_exported > 0:
        print(f"\r{message} (Relationships: {rels_exported})", end='', flush=True)
    else:
        print(f"\r{message}", end='', flush=True)


def main():
    parser = argparse.ArgumentParser(
        description='Export data from Neo4j to IPLD format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Connection arguments
    parser.add_argument(
        '--uri',
        required=True,
        help='Neo4j connection URI (e.g., bolt://localhost:7687)'
    )
    parser.add_argument(
        '--username',
        default='neo4j',
        help='Neo4j username (default: neo4j)'
    )
    parser.add_argument(
        '--password',
        required=True,
        help='Neo4j password'
    )
    parser.add_argument(
        '--database',
        default='neo4j',
        help='Neo4j database name (default: neo4j)'
    )
    
    # Output arguments
    parser.add_argument(
        '--output',
        '-o',
        required=True,
        help='Output file path'
    )
    parser.add_argument(
        '--format',
        choices=['dag-json', 'jsonlines'],
        default='dag-json',
        help='Output format (default: dag-json)'
    )
    
    # Export options
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for export (default: 1000)'
    )
    parser.add_argument(
        '--node-labels',
        help='Comma-separated list of node labels to export (optional)'
    )
    parser.add_argument(
        '--relationship-types',
        help='Comma-separated list of relationship types to export (optional)'
    )
    parser.add_argument(
        '--no-schema',
        action='store_true',
        help='Skip schema export (indexes, constraints)'
    )
    parser.add_argument(
        '--no-indexes',
        action='store_true',
        help='Skip index export'
    )
    parser.add_argument(
        '--no-constraints',
        action='store_true',
        help='Skip constraint export'
    )
    
    # Display options
    parser.add_argument(
        '--progress',
        action='store_true',
        help='Show progress during export'
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
    
    # Parse filters
    node_labels = None
    if args.node_labels:
        node_labels = [label.strip() for label in args.node_labels.split(',')]
    
    relationship_types = None
    if args.relationship_types:
        relationship_types = [rtype.strip() for rtype in args.relationship_types.split(',')]
    
    # Parse format
    output_format = MigrationFormat.DAG_JSON
    if args.format == 'jsonlines':
        output_format = MigrationFormat.JSON_LINES
    
    # Create export config
    config = ExportConfig(
        uri=args.uri,
        username=args.username,
        password=args.password,
        database=args.database,
        batch_size=args.batch_size,
        include_schema=not args.no_schema,
        include_indexes=not args.no_indexes,
        include_constraints=not args.no_constraints,
        output_file=args.output,
        output_format=output_format,
        node_labels=node_labels,
        relationship_types=relationship_types,
        progress_callback=progress_callback if args.progress else None
    )
    
    # Print configuration
    if not args.quiet:
        print("=" * 60)
        print("Neo4j Export Configuration")
        print("=" * 60)
        print(f"Source URI:      {args.uri}")
        print(f"Database:        {args.database}")
        print(f"Output file:     {args.output}")
        print(f"Output format:   {args.format}")
        print(f"Batch size:      {args.batch_size}")
        if node_labels:
            print(f"Node labels:     {', '.join(node_labels)}")
        if relationship_types:
            print(f"Rel types:       {', '.join(relationship_types)}")
        print(f"Include schema:  {not args.no_schema}")
        print("=" * 60)
        print()
    
    # Perform export
    try:
        exporter = Neo4jExporter(config)
        
        if not args.quiet:
            print("Starting export...")
            print()
        
        result = exporter.export()
        
        if args.progress:
            print()  # New line after progress
        
        if result.success:
            print()
            print("=" * 60)
            print("Export Completed Successfully!")
            print("=" * 60)
            print(f"Nodes exported:          {result.node_count}")
            print(f"Relationships exported:  {result.relationship_count}")
            print(f"Duration:                {result.duration_seconds:.2f} seconds")
            print(f"Output file:             {result.output_file}")
            print("=" * 60)
            
            # Performance stats
            if result.duration_seconds > 0:
                nodes_per_sec = result.node_count / result.duration_seconds
                rels_per_sec = result.relationship_count / result.duration_seconds
                print(f"Performance:             {nodes_per_sec:.0f} nodes/sec, {rels_per_sec:.0f} rels/sec")
                print("=" * 60)
            
            return 0
        else:
            print()
            print("=" * 60)
            print("Export Failed!")
            print("=" * 60)
            print("Errors:")
            for error in result.errors:
                print(f"  - {error}")
            if result.warnings:
                print("\nWarnings:")
                for warning in result.warnings:
                    print(f"  - {warning}")
            print("=" * 60)
            return 1
    
    except KeyboardInterrupt:
        print("\n\nExport interrupted by user.")
        return 130
    except Exception as e:
        logger.error(f"Export failed with exception: {e}", exc_info=args.verbose)
        return 1


if __name__ == '__main__':
    sys.exit(main())
