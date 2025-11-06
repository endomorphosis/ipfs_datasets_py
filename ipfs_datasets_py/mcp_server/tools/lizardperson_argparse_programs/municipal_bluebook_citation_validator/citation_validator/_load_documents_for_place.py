from pathlib import Path
from typing import Any
 

from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.dependencies import dependencies


def load_documents_for_place(gnis: str, document_dir: Path) -> list[dict[str, Any]]:
    """Load all HTML documents for a specific place from parquet files.

    Args:
        gnis (str): GNIS identifier for the place.
        citation_dir (Path): Directory containing citation parquet files.
    
    Returns:
        DatabaseConnection: Database of citations for the specified place.
    """
    path = document_dir / f"{gnis}_html.parquet"
    return dependencies.duckdb.from_parquet(path).fetchdf().to_dict('records')
