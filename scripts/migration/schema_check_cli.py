#!/usr/bin/env python3
"""
Schema Compatibility Check CLI

Check schema compatibility between Neo4j and IPFS Graph Database before migration.

Usage:
    python scripts/migration/schema_check_cli.py --input graph_export.json

Examples:
    # Check schema from exported file
    python scripts/migration/schema_check_cli.py --input my_graph.json

    # Check with detailed report
    python scripts/migration/schema_check_cli.py --input my_graph.json --verbose
"""

import argparse
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.knowledge_graphs.migration import (
    SchemaChecker,
    GraphData,
    MigrationFormat
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Check schema compatibility for migration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--input',
        '-i',
        required=True,
        help='Input file with graph data'
    )
    parser.add_argument(
        '--format',
        choices=['dag-json', 'jsonlines'],
        default='dag-json',
        help='Input format (default: dag-json)'
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Verbose output with detailed report'
    )
    
    args = parser.parse_args()
    
    # Check input file
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1
    
    # Parse format
    input_format = MigrationFormat.DAG_JSON
    if args.format == 'jsonlines':
        input_format = MigrationFormat.JSON_LINES
    
    try:
        # Load graph data
        print(f"Loading graph data from {args.input}...")
        graph_data = GraphData.load_from_file(args.input, input_format)
        
        if not graph_data.schema:
            print("No schema found in export file.")
            print("Schema information is optional but recommended for complete migration.")
            return 0
        
        # Check schema
        print("\nChecking schema compatibility...")
        checker = SchemaChecker()
        report = checker.check_schema(graph_data.schema)
        
        # Print results
        print("\n" + "=" * 60)
        print("Schema Compatibility Report")
        print("=" * 60)
        print(f"Overall Score:    {report.compatibility_score:.1f}%")
        print(f"Compatible:       {'✓ Yes' if report.compatible else '✗ No'}")
        print()
        
        # Schema summary
        print("Schema Summary:")
        print(f"  Node labels:         {len(graph_data.schema.node_labels)}")
        print(f"  Relationship types:  {len(graph_data.schema.relationship_types)}")
        print(f"  Indexes:             {len(graph_data.schema.indexes)}")
        print(f"  Constraints:         {len(graph_data.schema.constraints)}")
        print()
        
        # Issues
        if report.issues:
            print(f"Issues Found: {len(report.issues)}")
            for i, issue in enumerate(report.issues, 1):
                severity = issue.get('severity', 'info')
                message = issue['message']
                print(f"  {i}. [{severity.upper()}] {message}")
            print()
        
        # Warnings
        if report.warnings:
            print(f"Warnings: {len(report.warnings)}")
            for i, warning in enumerate(report.warnings, 1):
                print(f"  {i}. {warning}")
            print()
        
        # Recommendations
        if report.recommendations:
            print("Recommendations:")
            for i, rec in enumerate(report.recommendations, 1):
                print(f"  {i}. {rec}")
            print()
        
        # Verbose details
        if args.verbose:
            print("=" * 60)
            print("Detailed Schema Information")
            print("=" * 60)
            
            if graph_data.schema.node_labels:
                print("\nNode Labels:")
                for label in sorted(graph_data.schema.node_labels):
                    print(f"  - {label}")
            
            if graph_data.schema.relationship_types:
                print("\nRelationship Types:")
                for rtype in sorted(graph_data.schema.relationship_types):
                    print(f"  - {rtype}")
            
            if graph_data.schema.indexes:
                print("\nIndexes:")
                for idx in graph_data.schema.indexes:
                    name = idx.get('name', 'unnamed')
                    itype = idx.get('type', 'unknown')
                    print(f"  - {name} ({itype})")
            
            if graph_data.schema.constraints:
                print("\nConstraints:")
                for con in graph_data.schema.constraints:
                    name = con.get('name', 'unnamed')
                    ctype = con.get('type', 'unknown')
                    print(f"  - {name} ({ctype})")
            
            print()
        
        print("=" * 60)
        
        # Return code based on compatibility
        if report.compatible:
            print("\n✓ Schema is compatible with IPFS Graph Database")
            return 0
        else:
            print("\n⚠ Schema has compatibility issues. Review before migration.")
            return 2  # Warning exit code
    
    except Exception as e:
        logger.error(f"Schema check failed: {e}", exc_info=args.verbose)
        return 1


if __name__ == '__main__':
    sys.exit(main())
