from pathlib import Path
from typing import Any, Callable


from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import DatabaseConnection, Dependency



class SetupDatabaseAndFiles:

    def __init__(self, 
                 resources: dict[str, Callable] = None, 
                 configs: dict[str, Any] = None
                 ) -> None:
        self.resources = resources
        self.configs = configs

        # Initialize configurations
        self.random_seed: int = configs['random_seed']
        self.mysql_configs: dict[str, str] = configs['mysql_configs']
        self.error_db_path: Path = configs['error_db_path']
        self.error_report_db_path: Path = configs['error_report_db_path']
        
        self.citation_dir: Path = configs['citation_dir']
        self.document_dir: Path = configs['document_dir']

        # Initialize resources
        self._setup_reference_db: Callable = resources['setup_reference_db']
        self._setup_error_db: Callable = resources['setup_error_db']
        self._setup_error_report_db: Callable = resources['setup_error_report_db']

        self.error_db_sql_str: str = configs['error_db_sql_str']

    def setup_error_report_database(self, read_only: bool = False):  # -> DatabaseConnection  
        """Connect to DuckDB database for storing error reports."""
        # Ensure the error database directory path exists
        if not self.error_report_db_path.exists():
            self.error_report_db_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure the database connection is established
        try:
            conn = self._setup_error_report_db(
                self.error_db_path, 
                read_only=read_only, 
            )
        except Exception as e:
            raise RuntimeError(f"Failed to set up error database: {e}") from e
        return conn

    def setup_error_database(self, read_only: bool = False):  # -> DatabaseConnection  
        """Connect to DuckDB database for storing validation errors."""
        # Ensure the error database directory path exists
        if not self.error_db_path.exists():
            self.error_db_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure the database connection is established
        try:
            conn = self._setup_error_db(
                self.error_db_path, 
                read_only=read_only, 
            )
        except Exception as e:
            raise RuntimeError(f"Failed to set up error database: {e}") from e
        return conn

    def setup_reference_database(self, read_only: bool = True) -> 'DatabaseConnection':
        """
        Setup DuckDB with MySQL extension and establish connection.
        """
        # Ensure the database connection is established
        try:
            conn = self._setup_reference_db(
                sql_configs=self.mysql_configs, 
                read_only=read_only
            )
        except Exception as e:
            raise RuntimeError(f"Failed to set up reference database: {e}") from e
        return conn

    def get_databases(self) -> tuple['DatabaseConnection', 'DatabaseConnection']:
        """
        Set up and retrieve the error and reference databases for citation validation.
        
        This method initializes both the error database and reference database by calling
        their respective setup methods, then returns them as a tuple for use in citation
        validation processes.
        
        Returns:
            tuple[list]: A tuple containing two elements:
                - error_db (list): The error database containing validation error records
                - reference_db (list): The reference database containing citation reference data
        """
        error_db = self.setup_error_database(read_only=False)
        reference_db = self.setup_reference_database(read_only=True)
        error_report_db = self._setup_error_report_db(self.error_db_path, read_only=False)

        return error_db, reference_db

    def get_all_files_in_directory(directory: Path, pattern: str) -> list[Path]:
        """Get all files in a directory matching a specific pattern."""

        if not directory.exists():
            raise FileNotFoundError(f"Directory does not exist: {directory}")

        file_list = [file for file in directory.rglob(pattern)]

        if not file_list:
            raise FileNotFoundError(f"No files matching pattern '{pattern}' found in directory: {directory}")

        return file_list

    def get_files(self) -> tuple[list[Path], list[Path]]:
        """
        Retrieves lists of paths to citation and HTML parquet files from the citation and document directory.

        Returns:
            tuple[list[Path], list[Path]]: A tuple containing:
                - First element: List of Path objects for citation parquet files (*_citation.parquet)
                - Second element: List of Path objects for HTML parquet files (*_html.parquet)
        """
        citations = self.get_all_files_in_directory("*_citation.parquet")
        html = self.get_all_files_in_directory("*_html.parquet")

        return citations, html
    
    def _make_sql_tables_dict(self, sql_configs: dict[str, Any]) -> dict[str, str]:
        """Create sql statements."""
        sql_type = sql_configs['sql_type']
        db_name = sql_configs['db_name']
        data_table_names = sql_configs['data_table_names']
        metadata_table_names = sql_configs['metadata_table_names']
        db_typed = f"{sql_type}_db"

        # Tables
        table_dict = {
            'data_table': f"{db_typed}.{db_name}.{data_table_names[0]}",
            'raw_api_output_table': f"{db_typed}.{db_name}.{data_table_names[1]}",
            'html_metadata_table': f"{db_typed}.{db_name}.{metadata_table_names[0]}",
            'place_metadata_table': f"{db_typed}.{db_name}.{metadata_table_names[1]}"
        }
        return table_dict
