from pathlib import Path


from dependencies import dependencies


def _load_error_db_schema() -> str:
    """
    Load the error database schema into the provided database connection.

    Args:
        db: The database connection object.
    """
    this_file = Path(__file__).parent / "_error_db_schema.sql"

    with open(this_file.resolve(), "r") as file:
        error_db_sql_str = file.read()

    return error_db_sql_str


def setup_error_database(error_db_path: Path, read_only: bool = False):  # -> DatabaseConnection  
    """Connect to DuckDB database for storing validation errors."""

    error_db_sql_str = _load_error_db_schema()

    conn = dependencies.duckdb.connect(error_db_path, read_only=read_only)
    conn.sql(error_db_sql_str)
    return conn
