import argparse
from pathlib import Path

def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments for the citation validator."""
    parser = argparse.ArgumentParser(
        description="Validate Bluebook citations for municipal law"
    )
    
    parser.add_argument(
        "--citation-dir", 
        type=Path, 
        required=True,
        help="Directory containing citation parquet files (e.g., 66855_citations.parquet)"
    )
    
    parser.add_argument(
        "--document-dir",
        type=Path, 
        required=True,
        help="Directory containing HTML document parquet files (e.g., 66855_html.parquet)"
    )

    parser.add_argument(
        "--mysql-config",
        type=Path,
        required=True, 
        help="Path to YAML config file for MySQL connection settings"
    )

    parser.add_argument(
        "--error-db-path",
        type=Path,
        default="validation_errors.duckdb",
        help="Path to DuckDB file for storing validation errors"
    )
    
    parser.add_argument(
        "--output-dir",
        type=Path,
        default="./reports",
        help="Directory to save validation reports"
    )
    
    parser.add_argument(
        "--sample-size",
        type=int,
        default=385,
        help="Target number of places to sample for validation"
    )
    
    return parser.parse_args()
