import logging
from typing import Any


from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.dependencies import dependencies


logger = logging.getLogger(__name__)


def setup_reference_database(sql_configs: dict[str, Any], read_only: bool = True): # -> 'DatabaseConnection'
    """Setup DuckDB with MySQL extension and establish connection."""

    sql_type = sql_configs['sql_type']
    user = sql_configs['user']
    password = sql_configs['password']
    host = sql_configs['host']
    db_name = sql_configs['db_name']

    connection_string = f"{sql_type}://{user}:{password}@{host}/{db_name}"
    db_typed = f"{sql_type}_db"

    try:
        conn = dependencies.duckdb.connect()
        conn.sql(f'INSTALL {sql_type};')
        conn.sql(f'LOAD {sql_type};')
        # Using DuckDB's preferred connection format with MySQL extension
        attach_cmd = f"ATTACH '{connection_string}' AS {db_typed} (TYPE {sql_type.upper()}"
        attach_cmd += ", READ_ONLY);" if read_only else ");"
        conn.sql(attach_cmd)
        return conn
    except Exception as e:
        logger.exception(f"Failed to connect to {sql_type} database: {e}")
        raise RuntimeError(f"Failed to set up reference database: {e}") from e
    finally:
        if conn:
            conn.close()
            logger.info(f"Closed connection to {db_typed} database: {db_name}")

