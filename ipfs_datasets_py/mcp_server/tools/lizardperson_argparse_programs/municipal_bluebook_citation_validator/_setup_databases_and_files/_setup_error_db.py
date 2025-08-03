from pathlib import Path


from ..dependencies import dependencies
from ..utils import load_sql_file


def setup_error_database(error_db_path: Path, read_only: bool = False):  # -> DatabaseConnection  
    """Connect to DuckDB database for storing validation errors."""

    error_db_schema_path = Path(__file__).parent / "_error_db_schema.sql"

    error_db_sql_str = load_sql_file(error_db_schema_path, encoding="utf-8")

    conn = dependencies.duckdb.connect(error_db_path, read_only=read_only)
    conn.sql(error_db_sql_str)
    return conn
