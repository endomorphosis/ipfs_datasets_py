"""Fixtures for MySQL to Parquet conversion tests."""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import Mock, MagicMock, patch
import sys

import duckdb
import pandas as pd
import pytest
import yaml

try:
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers._utils.mysql_to_parquet import (
        make_mysql_to_parquet,
        make_sql_statements,
    )
except Exception as e:
    raise ImportError(f"Failed to import make_mysql_to_parquet: {e}") from e

try:
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers._utils.configs import (
        Configs, Paths, paths, configs
    )
except Exception as e:
    raise ImportError(f"Failed to import Configs from configs.py: {e}") from e


# Mock the configs before importing mysql_to_parquet
mock_paths = Mock()
mock_paths.ROOT_DIR = Path("/tmp/test_configs")
mock_paths.HOME_DIR = Path("/tmp")
mock_paths.OUTPUT_TO_HUGGING_FACE_DIR = Path("/tmp/test_configs/output_to_hugging_face")
mock_paths.INPUT_FROM_SQL = Path("/tmp/test_configs/input_from_sql")
mock_paths.HASHES_CSV_PATH = Path("/tmp/test_configs/hashes.csv")
mock_paths.CONFIG_YAML_PATH = Path("/tmp/test_configs/configs.yaml")
mock_paths.SQL_CONFIG_YAML_PATH = Path("/tmp/test_configs/sql_configs.yaml")

mock_configs = Mock()
mock_configs.paths = mock_paths
mock_configs.BATCH_SIZE = 100
mock_configs.CLEAR_HASHES_CSV = True
mock_configs.FILE_PATH_ENDING = "html"


from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers._utils.mysql_to_parquet import (
    make_mysql_to_parquet,
)



# locations table schema:
# CREATE TABLE IF NOT EXISTS locations (
#     id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
# 	gnis MEDIUMINT UNSIGNED NOT NULL,
# 	fips MEDIUMINT UNSIGNED NOT NULL,
# 	place_name VARCHAR(60) NOT NULL,
# 	state_name VARCHAR(32) NOT NULL,
# 	class_code VARCHAR(2) NOT NULL,
# 	primary_lat_dec DECIMAL(9,7) NOT NULL,
# 	primary_long_dec DECIMAL(9,7) NOT NULL,
#     primary_point VARCHAR(33) NOT NULL,
#     state_code VARCHAR(2),
#     domain_name VARCHAR(50),
#     domain TEXT DEFAULT NULL,
#     population MEDIUMINT UNSIGNED DEFAULT NULL,
# 	INDEX idx_gnis (gnis),
# 	INDEX idx_fips (fips),
# 	INDEX idx_state_name (state_name)
# );


# municode_html_stats table schema:
# CREATE TABLE IF NOT EXISTS municode_html_stats (
#   gnis MEDIUMINT UNSIGNED PRIMARY KEY,
#   we_have_all_the_laws BOOL NOT NULL DEFAULT TRUE,
#   total_sections INT UNSIGNED NOT NULL DEFAULT 0,
#   missing_sections INT UNSIGNED NOT NULL DEFAULT 0,
#   last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
# );


# municode_sections table schema:
# CREATE TABLE IF NOT EXISTS municode_sections (
#     id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
#     cid VARCHAR(250) NOT NULL,
# 	gnis MEDIUMINT UNSIGNED NOT NULL,
#     node_id VARCHAR(100) NOT NULL,
#     node_depth SMALLINT UNSIGNED NOT NULL,
#     doc_order_id INT UNSIGNED NOT NULL,
#     doc_type SMALLINT UNSIGNED NOT NULL,
# 	html_title TEXT,
#     html TEXT,
# 	title VARCHAR(500),
# 	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
#     plaintext TEXT DEFAULT NULL,
#     public_law_num VARCHAR(255) DEFAULT NULL,
#     statute_num VARCHAR(255) DEFAULT NULL,
#     bill_enacted VARCHAR(255) DEFAULT NULL,
#     year DATE DEFAULT NULL,
#     UNIQUE INDEX (cid),
#     INDEX idx_gnis_node_id (gnis, node_depth),
#     INDEX idx_gnis_node_depth (gnis, node_id),
#     INDEX idx_gnis_title (gnis, title(100)),
#     INDEX idx_gnis_html (gnis, html(100)),
# 	INDEX idx_gnis_plaintext (gnis, plaintext(100)),
#     FULLTEXT INDEX idx_plaintext (plaintext),
#     FULLTEXT INDEX idx_plaintext (html)
# )	


# municode_api_output table schema:
# CREATE TABLE IF NOT EXISTS municode_api_output (
#     id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
#     cid VARCHAR(250) NOT NULL,
# 	gnis MEDIUMINT UNSIGNED NOT NULL,
# 	has_html_content BOOL NOT NULL,
#     content_json JSON NOT NULL,
# 	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
# 	INDEX idx_gnis (gnis),
# 	INDEX idx_cid (cid), 
#     INDEX idx_updated_at (updated_at),
#     UNIQUE INDEX (cid)
# )



# ============================================================================
# MySQL Table Creation Helpers
# ============================================================================

@pytest.fixture
def test_db_connection():
    """Create an in-memory DuckDB database for testing."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()

@pytest.fixture
def test_db_cursor(test_db_connection):
    """Create a cursor for the test DuckDB database."""
    cursor = test_db_connection.cursor()
    yield cursor
    cursor.close()

@pytest.fixture
def make_locations_table(test_db_cursor):
    """Create locations table matching the schema."""
    query = '''
        CREATE TABLE IF NOT EXISTS locations (
            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            gnis MEDIUMINT UNSIGNED NOT NULL,
            fips MEDIUMINT UNSIGNED NOT NULL,
            place_name VARCHAR(60) NOT NULL,
            state_name VARCHAR(32) NOT NULL,
            class_code VARCHAR(2) NOT NULL,
            primary_lat_dec DECIMAL(9,7) NOT NULL,
            primary_long_dec DECIMAL(9,7) NOT NULL,
            primary_point VARCHAR(33) NOT NULL,
            state_code VARCHAR(2),
            domain_name VARCHAR(50),
            domain TEXT DEFAULT NULL,
            population MEDIUMINT UNSIGNED DEFAULT NULL,
            INDEX idx_gnis (gnis),
            INDEX idx_fips (fips),
            INDEX idx_state_name (state_name)
        )
    '''
    test_db_cursor.execute(query)
    return test_db_cursor

@pytest.fixture
def make_municode_html_stats_table(test_db_cursor):
    """Create municode_html_stats table matching the schema."""
    query = '''
        CREATE TABLE IF NOT EXISTS municode_html_stats (
            gnis MEDIUMINT UNSIGNED PRIMARY KEY,
            we_have_all_the_laws BOOL NOT NULL DEFAULT TRUE,
            total_sections INT UNSIGNED NOT NULL DEFAULT 0,
            missing_sections INT UNSIGNED NOT NULL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    '''
    test_db_cursor.execute(query)
    return test_db_cursor


@pytest.fixture
def make_municode_sections_table(test_db_cursor):
    """Create municode_sections table matching the schema."""
    query = '''
        CREATE TABLE IF NOT EXISTS municode_sections (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            cid VARCHAR(250) NOT NULL,
            gnis MEDIUMINT UNSIGNED NOT NULL,
            node_id VARCHAR(100) NOT NULL,
            node_depth SMALLINT UNSIGNED NOT NULL,
            doc_order_id INT UNSIGNED NOT NULL,
            doc_type SMALLINT UNSIGNED NOT NULL,
            html_title TEXT,
            html TEXT,
            title VARCHAR(500),
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            plaintext TEXT DEFAULT NULL,
            public_law_num VARCHAR(255) DEFAULT NULL,
            statute_num VARCHAR(255) DEFAULT NULL,
            bill_enacted VARCHAR(255) DEFAULT NULL,
            year DATE DEFAULT NULL,
            UNIQUE INDEX (cid),
            INDEX idx_gnis_node_id (gnis, node_depth),
            INDEX idx_gnis_node_depth (gnis, node_id),
            INDEX idx_gnis_title (gnis, title(100)),
            INDEX idx_gnis_html (gnis, html(100)),
            INDEX idx_gnis_plaintext (gnis, plaintext(100)),
            FULLTEXT INDEX idx_plaintext (plaintext),
            FULLTEXT INDEX idx_html_fulltext (html)
        )
    '''
    test_db_cursor.execute(query)
    return test_db_cursor

@pytest.fixture
def make_municode_api_output_table(test_db_cursor):
    """Create municode_api_output table matching the schema."""
    query = '''
        CREATE TABLE IF NOT EXISTS municode_api_output (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            cid VARCHAR(250) NOT NULL,
            gnis MEDIUMINT UNSIGNED NOT NULL,
            has_html_content BOOL NOT NULL,
            content_json JSON NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_gnis (gnis),
            INDEX idx_cid (cid), 
            INDEX idx_updated_at (updated_at),
            UNIQUE INDEX (cid)
        )
    '''
    test_db_cursor.execute(query)
    return test_db_cursor

@pytest.fixture
def make_mysql_tables(
    make_locations_table,
    make_municode_html_stats_table,
    make_municode_sections_table,
    make_municode_api_output_table
):
    """Create all MySQL tables matching the documented schemas."""
    return make_municode_api_output_table


@pytest.fixture
def make_database(test_db_cursor, make_mysql_tables):
    """Factory function to create test database with all tables."""
    def _make_database():
        try:
            return test_db_cursor
        except Exception as e:
            raise FixtureError(f"make_database setup failed: {e}") from e
    return _make_database


# ============================================================================
# Test Data Generation Helpers
# ============================================================================


@pytest.fixture
def location_row():
    """Sample row for locations table."""
    return {
        'id': 41,
        'gnis': 2412936,
        'fips': 645358,
        'place_name': 'Town of Mammoth Lakes',
        'state_name': 'California',
        'class_code': 'C1',
        'primary_lat_dec': 37.6272627,
        'primary_long_dec': -99.9999999,
        'primary_point': 'POINT (-118.9899436 37.6272627)\r',
        'state_code': 'CA',
        'domain_name': 'http://www.ci.mammoth-lakes.ca.us',
        'domain': 'http://www.ci.mammoth-lakes.ca.us',
        'population': None
    }


@pytest.fixture
def html_stats_row():
    """Sample row for municode_html_stats table."""
    return {
        'gnis': 2412936,
        'we_have_all_the_laws': True,
        'total_sections': 409,
        'missing_sections': 0,
        'last_updated': '2025-02-18 01:52:22'
    }


@pytest.fixture
def municode_api_output_row():
    """Sample row for municode_api_output table."""
    return {
        'id': 799303,
        'cid': 'bafkreia6phv5uf5c6hschz57unpqunjdpsg66hcaryjkwo2ukwmfjttadm',
        'gnis': 2412936,
        'original_file_name': '2412936_COOR_TIT10VETR_CH10.12SPLI_10.12.030SPLICESTDE.json',
        'has_html_content': True,
        'content_json': '{"Id": "COOR_TIT10VETR_CH10.12SPLI_10.12.030SPLICESTDE", "Notes": [], "Title": "10.12.030. - Speed limits; certain streets designated.", "Drafts": [], "Content": "<div class=\\"chunk-content\\">\\n            <p class=\\"incr0\\">\\n               (a)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content1\\">\\n               There is determined and declared a prima facie speed limit of 25 miles per hour on\\n               Old Mammoth Road, between Main Street (State Route 203) and a point 700 feet south\\n               of the intersection of Old Mammoth Road and Chateau Road.\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr0\\">\\n               (b)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content1\\">\\n               There is determined and declared a prima facie speed limit of 35 miles per hour on\\n               the following named roads:\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (1)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Lake Mary Road, between Minaret Road/Main Street (State Route 203) and the Ski Tunnel;\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (2)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Forest Trail, between Minaret Road (State Route 203) and the easterly end of Pinecrest\\n               Avenue;\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (3)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Meridian Boulevard, from 150 feet east of the intersection of Meridian Boulevard and\\n               Sierra Park Road to Old Mammoth Road;\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (4)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Minaret Road, between Meridian Boulevard and Old Mammoth Road;\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (5)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Old Mammoth Road, between Ski Trail and Evergreen Street.\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr0\\">\\n               (c)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content1\\">\\n               There is determined and declared a prima facie speed limit of 40 miles per hour on\\n               the following named streets:\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (1)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Meridian Boulevard, between Old Mammoth Road and Majestic Pines Drive;\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (2)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Minaret Road, between Lake Mary Road/Main Street (State Route 203) and Meridian Boulevard;\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr1\\">\\n               (3)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content2\\">\\n               Old Mammoth Road, from 700 feet south of the intersection of Old Mammoth Road and\\n               Chateau Road to Ski Trail.\\n               </p>\\n            \\t\\t\\n            <p class=\\"incr0\\">\\n               (d)\\n               </p>\\n            \\t\\t\\n            <p class=\\"content1\\">\\n               There is determined and declared a prima facie speed limit of 45 miles per hour on\\n               Meridian Boulevard, from Main Street (State Route 203) to 150 feet east of Sierra\\n               Park Road.\\n               </p>\\n            \\t\\t\\n            <p class=\\"historynote0\\">\\n               (Prior Code, § 11.12.030; Code 1990, § 10.04.030; Ord. No. 89-15, § 1, 1989; Ord.\\n               No. 92-09, § 1, 1992; Ord. No. 02-04, § 1, 2002)\\n               </p></div>", "DocType": 1, "SortDate": null, "AmendedBy": [], "Footnotes": null, "IsAmended": false, "IsUpdated": false, "NodeDepth": 3, "TitleHtml": "<div class=\\"chunk-title\\">10.12.030. - Speed limits; certain streets designated.</div>", "DocOrderId": 817, "CompareStatus": 4, "ChunkGroupStartingNodeId": "COOR_TIT10VETR"}',
        'updated_at': '2025-02-11 12:15:43'
    }


@pytest.fixture
def municode_sections_row():
    """Sample row for municode_sections table."""
    return {
        'id': 799303,
        'cid': 'bafkreia6phv5uf5c6hschz57unpqunjdpsg66hcaryjkwo2ukwmfjttadm',
        'gnis': 2412936,
        'node_id': 'COOR_TIT10VETR_CH10.12SPLI_10.12.030SPLICESTDE',
        'node_depth': 3,
        'doc_order_id': 817,
        'doc_type': 1,
        'html_title': '<div class="chunk-title">10.12.030. - Speed limits; certain streets designated.</div>',
        'html': '<div class="chunk-content">\n            <p class="incr0">\n               (a)\n               </p>\n            		\n            <p class="content1">\n               There is determined and declared a prima facie speed limit of 25 miles per hour on\n               Old Mammoth Road, between Main Street (State Route 203) and a point 700 feet south\n               of the intersection of Old Mammoth Road and Chateau Road.\n               </p>\n            		\n            <p class="incr0">\n               (b)\n               </p>\n            		\n            <p class="content1">\n               There is determined and declared a prima facie speed limit of 35 miles per hour on\n               the following named roads:\n               </p>\n            		\n            <p class="incr1">\n               (1)\n               </p>\n            		\n            <p class="content2">\n               Lake Mary Road, between Minaret Road/Main Street (State Route 203) and the Ski Tunnel;\n               </p>\n            		\n            <p class="incr1">\n               (2)\n               </p>\n            		\n            <p class="content2">\n               Forest Trail, between Minaret Road (State Route 203) and the easterly end of Pinecrest\n               Avenue;\n               </p>\n            		\n            <p class="incr1">\n               (3)\n               </p>\n            		\n            <p class="content2">\n               Meridian Boulevard, from 150 feet east of the intersection of Meridian Boulevard and\n               Sierra Park Road to Old Mammoth Road;\n               </p>\n            		\n            <p class="incr1">\n               (4)\n               </p>\n            		\n            <p class="content2">\n               Minaret Road, between Meridian Boulevard and Old Mammoth Road;\n               </p>\n            		\n            <p class="incr1">\n               (5)\n               </p>\n            		\n            <p class="content2">\n               Old Mammoth Road, between Ski Trail and Evergreen Street.\n               </p>\n            		\n            <p class="incr0">\n               (c)\n               </p>\n            		\n            <p class="content1">\n               There is determined and declared a prima facie speed limit of 40 miles per hour on\n               the following named streets:\n               </p>\n            		\n            <p class="incr1">\n               (1)\n               </p>\n            		\n            <p class="content2">\n               Meridian Boulevard, between Old Mammoth Road and Majestic Pines Drive;\n               </p>\n            		\n            <p class="incr1">\n               (2)\n               </p>\n            		\n            <p class="content2">\n               Minaret Road, between Lake Mary Road/Main Street (State Route 203) and Meridian Boulevard;\n               </p>\n            		\n            <p class="incr1">\n               (3)\n               </p>\n            		\n            <p class="content2">\n               Old Mammoth Road, from 700 feet south of the intersection of Old Mammoth Road and\n               Chateau Road to Ski Trail.\n               </p>\n            		\n            <p class="incr0">\n               (d)\n               </p>\n            		\n            <p class="content1">\n               There is determined and declared a prima facie speed limit of 45 miles per hour on\n               Meridian Boulevard, from Main Street (State Route 203) to 150 feet east of Sierra\n               Park Road.\n               </p>\n            		\n            <p class="historynote0">\n               (Prior Code, § 11.12.030; Code 1990, § 10.04.030; Ord. No. 89-15, § 1, 1989; Ord.\n               No. 92-09, § 1, 1992; Ord. No. 02-04, § 1, 2002)\n               </p></div>',
        'title': '10.12.030. - Speed limits; certain streets designated.',
        'updated_at': '2025-02-11 12:15:43',
        'plaintext': None,
        'public_law_num': None,
        'statute_num': None,
        'bill_enacted': None,
        'year': None
    }




@pytest.fixture
def insert_location_row(test_db_cursor, location_row):
    """Insert a location row into the locations table."""
    query = '''
        INSERT INTO locations (
            id, gnis, fips, place_name, state_name, class_code,
            primary_lat_dec, primary_long_dec, primary_point,
            state_code, domain_name, domain, population
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    test_db_cursor.execute(query, tuple(location_row.values()))
    return test_db_cursor


@pytest.fixture
def insert_html_stats_row(test_db_cursor, html_stats_row):
    """Insert an html_stats row into the municode_html_stats table."""
    query = '''
        INSERT INTO municode_html_stats (
            gnis, we_have_all_the_laws, total_sections,
            missing_sections, last_updated
        ) VALUES (?, ?, ?, ?, ?)
    '''
    test_db_cursor.execute(query, tuple(html_stats_row.values()))
    return test_db_cursor


@pytest.fixture
def insert_municode_api_output_row(test_db_cursor, municode_api_output_row):
    """Insert a municode_api_output row into the municode_api_output table."""
    query = '''
        INSERT INTO municode_api_output (
            id, cid, gnis, has_html_content,
            content_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    '''
    test_db_cursor.execute(query, (
        municode_api_output_row['id'],
        municode_api_output_row['cid'],
        municode_api_output_row['gnis'],
        municode_api_output_row['has_html_content'],
        municode_api_output_row['content_json'],
        municode_api_output_row['updated_at']
    ))
    return test_db_cursor


@pytest.fixture
def insert_municode_sections_row(test_db_cursor, municode_sections_row):
    """Insert a municode_sections row into the municode_sections table."""
    query = '''
        INSERT INTO municode_sections (
            id, cid, gnis, node_id, node_depth, doc_order_id,
            doc_type, html_title, html, title, updated_at,
            plaintext, public_law_num, statute_num, bill_enacted, year
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    test_db_cursor.execute(query, tuple(municode_sections_row.values()))
    return test_db_cursor



def generate_embedding_rows(gnis_values, rows_per_gnis=1, dimensions=768, base_data=None):
    """Generate embedding table test data.
    
    Args:
        gnis_values: List of GNIS values to generate data for
        rows_per_gnis: Number of rows to generate per GNIS value
        dimensions: Number of dimensions for embedding vector
        base_data: Optional dict with specific values
    
    Returns:
        List of tuples representing embedding table rows
    """
    rows = []
    for gnis in gnis_values:
        for i in range(rows_per_gnis):
            if base_data and 'embedding' in base_data:
                embedding_vector = base_data['embedding']
            else:
                embedding_vector = str([0.0] * dimensions)
            
            if base_data:
                rows.append((
                    base_data.get('embedding_cid', f'emb_cid_{gnis}_{i}'),
                    gnis,
                    base_data.get('cid', f'cid_{gnis}_{i}'),
                    base_data.get('text_chunk_order', i),
                    embedding_vector
                ))
            else:
                rows.append((f'emb_cid_{gnis}_{i}', gnis, f'cid_{gnis}_{i}', i, '[]'))
    return rows


class FixtureError(Exception):
    """Exception raised when a fixture encounters an error during setup or teardown."""
    pass


@pytest.fixture
def output_directory(tmp_path: Path):
    """output directory exists"""
    try:
        output_dir = tmp_path / "output_directory"
        output_dir.mkdir(parents=True, exist_ok=True)
        yield output_dir
    except Exception as e:
        raise FixtureError(f"output_directory setup failed: {e}") from e

@pytest.fixture
def mock_duckdb():
    """Create a mock duckdb connection"""
    # Create a mock database connection
    mock_db_connection = MagicMock()
    
    # Store query results
    mock_db_connection._query_results = {}
    mock_db_connection._gnis_list = []

    def sql_side_effect(query):
        """Mock sql() method that returns appropriate results based on query"""
        mock_result = MagicMock()
        
        # Check if it's a complete groups query
        if "we_have_all_the_laws = 1" in query:
            mock_df = pd.DataFrame({'gnis': mock_db_connection._gnis_list})
            mock_series = pd.Series(mock_db_connection._gnis_list)
            mock_df.__getitem__ = lambda x: mock_series
            mock_result.to_df.return_value = mock_df
            return mock_result
        
        # Check if it's a metadata query
        if "place_metadata" in query and "html_metadata" in query:
            # Extract gnis from query
            gnis_match = re.search(r"gnis = '(\d+)'", query)
            if gnis_match:
                gnis = int(gnis_match.group(1))
                mock_df = pd.DataFrame({
                    'place_name': ['Test Place'],
                    'state_name': ['Test State'],
                    'state_code': ['AR'],
                    'class_code': ['h1'],
                    'total_sections': [10],
                    'last_updated': ['2024-01-01']
                })
                mock_result.to_df.return_value = mock_df
                return mock_result
        
        # Check if it's an html data query
        if "SELECT gnis, cid, node_id AS doc_id" in query:
            gnis_match = re.search(r"gnis = '(\d+)'", query)
            if gnis_match:
                gnis = int(gnis_match.group(1))
                # Return html data for this gnis
                html_data = mock_db_connection._query_results.get(f'html_{gnis}', [])
                if html_data:
                    df = pd.DataFrame(html_data)
                    mock_arrow = MagicMock()
                    mock_arrow.to_pandas.return_value = df
                    mock_result.arrow.return_value = mock_arrow
                    return mock_result
        
        # Check if it's a raw API output query
        if "content_json" in query or query.startswith("SELECT * FROM"):
            gnis_match = re.search(r"gnis = '(\d+)'", query)
            if gnis_match:
                gnis = int(gnis_match.group(1))
                # Return empty dataframe for now - citations are complex
                df = pd.DataFrame()
                mock_arrow = MagicMock()
                mock_arrow.to_pandas.return_value = df
                mock_result.arrow.return_value = mock_arrow
                return mock_result
        
        # Default empty result
        mock_df = pd.DataFrame()
        mock_series = pd.Series([])
        mock_df.__getitem__ = lambda x: mock_series
        mock_result.to_df.return_value = mock_df
        mock_result.arrow.return_value = MagicMock(to_pandas=lambda: mock_df)
        return mock_result
    
    mock_db_connection.sql.side_effect = sql_side_effect
    return mock_db_connection

@pytest.fixture
def mock_resources(mock_duckdb):
    """Create mock resources for MySqlToParquet"""
    try:
        logger = MagicMock(spec_set=logging.Logger)
        resources = {
            'logger': logger,
            'duckdb': mock_duckdb,
        }
        yield resources
    except Exception as e:
        raise FixtureError(f"mock_resources setup failed: {e}") from e

@pytest.fixture
def mock_sql_configs(output_directory):
    return {
        "DATABASE_NAME": "test_db",
        "HOST": "localhost",
        "USER": "test_user",
        "PASSWORD": "test_password",
        "COMPRESSION_TYPE": "gzip",
        "LIMIT": 100000,
        "BATCH_SIZE": 5000,
        "PARTITION_COLUMN": "gnis",
        "OUTPUT_FOLDER": output_directory,
    }

@pytest.fixture
def mock_sql_tables():
    mock_tables = Mock()
    mock_tables.DATA_TABLE_NAMES = ["html", "citation"]
    mock_tables.METADATA_TABLE_NAMES = ["html_metadata", "place_metadata"]
    return mock_tables

@pytest.fixture
def mock_configs_instance(output_directory, mock_sql_configs, mock_sql_tables):
    """Create mock Configs instance"""
    try:
        configs = Mock()
        configs.TARGET_DIR_NAME = "test_target"

        # Mock SQL configs
        configs.sql = Mock()
        for key, value in mock_sql_configs.items():
            setattr(configs.sql, key, value)
        # Mock SQL tables
        configs.sql.tables = mock_sql_tables
        yield configs
    except Exception as e:
        raise FixtureError(f"mock_configs_instance setup failed: {e}") from e


@pytest.fixture
def mysql_to_parquet_instance(output_directory, mock_resources, mock_configs_instance):
    """a MySqlToParquet instance is initialized"""
    try:
        # Inject the mock database connection
        instance = make_mysql_to_parquet(
            configs=mock_configs_instance,
            resources=mock_resources
        )
        yield instance
        
    except Exception as e:
        raise FixtureError(f"mysql_to_parquet_instance setup failed: {e}") from e

@pytest.fixture
def make_mysql_to_parquet_instance(mock_configs_instance, mock_resources):

    def _factory(config_overrides={}, mock_resource_overrides={}):
        if config_overrides:
            for key, value in config_overrides.items():
                setattr(mock_configs_instance, key, value)
        if mock_resource_overrides:
            for key, value in mock_resource_overrides.items():
                mock_resources[key] = value
        try:
            # Inject the mock database connection
            instance = make_mysql_to_parquet(
                configs=mock_configs_instance,
                resources=mock_resources
            )
            yield instance
        except Exception as e:
            raise FixtureError(f"mysql_to_parquet_instance setup failed: {e}") from e
    return _factory


@pytest.fixture
def mysql_server_running():
    """MySQL server is running"""
    mock_connection = Mock()
    mock_cursor = MagicMock()
    mock_connection.cursor.return_value = mock_cursor
    mock_connection.commit.return_value = None
    mock_connection.close.return_value = None
    mock_cursor.execute.return_value = None
    mock_cursor.close.return_value = None
    
    yield mock_connection


@pytest.fixture
def mock_mysql_factory(mysql_server_running):
    """Factory to create MySQL database mocks with custom data.
    
    Returns a callable that accepts:
        html_data: List of tuples for html table rows (or dict with gnis_values/rows_per_gnis)
        citation_data: List of tuples for citation table rows (or dict with gnis_values/rows_per_gnis)
        embedding_data: List of tuples for embedding table rows (or dict with gnis_values/rows_per_gnis)
    
    Example:
        def test_something(mock_mysql_factory):
            db = mock_mysql_factory(
                html_data={'gnis_values': [66855, 67890], 'rows_per_gnis': 5},
                citation_data={'gnis_values': [66855], 'rows_per_gnis': 3}
            )
    """
    def _factory(html_data=None, citation_data=None, embedding_data=None):
        try:
            cursor = mysql_server_running.cursor.return_value
            
            # Convert dict specs to actual data
            if isinstance(html_data, dict):
                html_data = generate_html_rows(
                    gnis_values=html_data.get('gnis_values', []),
                    rows_per_gnis=html_data.get('rows_per_gnis', 1),
                    base_data=html_data.get('base_data')
                )
            if isinstance(citation_data, dict):
                citation_data = generate_citation_rows(
                    gnis_values=citation_data.get('gnis_values', []),
                    rows_per_gnis=citation_data.get('rows_per_gnis', 1),
                    base_data=citation_data.get('base_data')
                )
            if isinstance(embedding_data, dict):
                embedding_data = generate_embedding_rows(
                    gnis_values=embedding_data.get('gnis_values', []),
                    rows_per_gnis=embedding_data.get('rows_per_gnis', 1),
                    dimensions=embedding_data.get('dimensions', 768),
                    base_data=embedding_data.get('base_data')
                )
            
            # Default to empty lists
            html_data = html_data or []
            citation_data = citation_data or []
            embedding_data = embedding_data or []
            
            cursor.last_query_type = None
            
            def execute_side_effect(query, params=None):
                if 'html' in query.lower():
                    cursor.last_query_type = 'html'
                elif 'citation' in query.lower():
                    cursor.last_query_type = 'citation'
                elif 'embedding' in query.lower():
                    cursor.last_query_type = 'embedding'
            
            def fetchall_side_effect():
                if cursor.last_query_type == 'html':
                    return html_data
                elif cursor.last_query_type == 'citation':
                    return citation_data
                elif cursor.last_query_type == 'embedding':
                    return embedding_data
                return []
            
            cursor.execute.side_effect = execute_side_effect
            cursor.fetchall.side_effect = fetchall_side_effect
            
            return mysql_server_running
        except Exception as e:
            raise FixtureError(f"mock_mysql_factory setup failed: {e}") from e
    
    return _factory


@pytest.fixture
def mysql_database_with_10_html_10_citation_5_embedding(mock_mysql_factory):
    """MySQL database contains html table with 10 rows, citation table with 10 rows, and embedding table with 5 rows"""
    return mock_mysql_factory(
        html_data={'gnis_values': [66855], 'rows_per_gnis': 10},
        citation_data={'gnis_values': [66855], 'rows_per_gnis': 10},
        embedding_data={'gnis_values': [66855], 'rows_per_gnis': 5}
    )


@pytest.fixture
def mysql_database_with_two_gnis_html(mock_mysql_factory):
    """MySQL html table has gnis values [66855, 67890]"""
    db = mock_mysql_factory(
        html_data={'gnis_values': [66855, 67890], 'rows_per_gnis': 1}
    )
    db.test_gnis_values = [66855, 67890]
    return db


@pytest.fixture
def mysql_database_with_two_gnis_citation(mock_mysql_factory):
    """MySQL citation table has gnis values [66855, 67890]"""
    return mock_mysql_factory(
        citation_data={'gnis_values': [66855, 67890], 'rows_per_gnis': 1}
    )


@pytest.fixture
def mysql_database_with_one_gnis_embedding(mock_mysql_factory):
    """MySQL embedding table has gnis value 66855"""
    return mock_mysql_factory(
        embedding_data={'gnis_values': [66855], 'rows_per_gnis': 1}
    )


@pytest.fixture
def mysql_database_with_one_html_row(mock_mysql_factory):
    """MySQL html table has 1 row"""
    return mock_mysql_factory(
        html_data=[('test_cid', 'test_doc_id', 1, 'test_title', 'test_html', 66855)]
    )


@pytest.fixture
def mysql_database_with_one_citation_row(mock_mysql_factory):
    """MySQL citation table has 1 row"""
    return mock_mysql_factory(
        citation_data=[('test_bb_cid', 'test_cid', 'test_title', 'test_chapter', 'test_citation', 66855, 'AR')]
    )


@pytest.fixture
def mysql_database_with_one_embedding_row(mock_mysql_factory):
    """MySQL embedding table has 1 row"""
    return mock_mysql_factory(
        embedding_data=[('test_emb_cid', 66855, 'test_cid', 1, '[]')]
    )


@pytest.fixture
def mysql_database_with_specific_html_row(mock_mysql_factory):
    """MySQL html table has row with specific cid, doc_id, and gnis"""
    return mock_mysql_factory(
        html_data=[(
            'bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa',
            'CO_CH15BULI_ARTIISEORBU_S15-40IN',
            1,
            'test_title',
            'test_html',
            66855
        )]
    )


@pytest.fixture
def mysql_database_with_specific_citation_row(mock_mysql_factory):
    """MySQL citation table has row with specific bluebook_citation, gnis, and state_code"""
    return mock_mysql_factory(
        citation_data=[(
            'test_bb_cid',
            'test_cid',
            'test_title',
            'test_chapter',
            'Garland, Ark., County Code, §18-40 (1987)',
            66855,
            'AR'
        )]
    )


@pytest.fixture
def mysql_database_with_specific_embedding_row(mock_mysql_factory):
    """MySQL embedding table has row with gnis 66855, text_chunk_order 1, and embedding vector with 768 dimensions"""
    return mock_mysql_factory(
        embedding_data=[(
            'test_emb_cid',
            66855,
            'test_cid',
            1,
            str([0.0] * 768)
        )]
    )


@pytest.fixture
def mysql_database_with_three_gnis_values(mock_mysql_factory):
    """MySQL tables contain gnis values [66855, 67890, 68000]"""
    return mock_mysql_factory(
        html_data={'gnis_values': [66855, 67890, 68000], 'rows_per_gnis': 1},
        citation_data={'gnis_values': [66855, 67890, 68000], 'rows_per_gnis': 1},
        embedding_data={'gnis_values': [66855, 67890, 68000], 'rows_per_gnis': 1}
    )


@pytest.fixture
def mysql_database_with_gnis_360420(mock_mysql_factory):
    """MySQL tables contain gnis value 360420"""
    return mock_mysql_factory(
        html_data={'gnis_values': [360420], 'rows_per_gnis': 1},
        citation_data={'gnis_values': [360420], 'rows_per_gnis': 1},
        embedding_data={'gnis_values': [360420], 'rows_per_gnis': 1}
    )


@pytest.fixture
def mysql_database_with_zero_rows(mock_mysql_factory):
    """MySQL html table has 0 rows, citation table has 0 rows, and embedding table has 0 rows"""
    return mock_mysql_factory()


@pytest.fixture
def mysql_server_not_reachable():
    """MySQL server is not reachable"""
    mock_connection = Mock()
    mock_connection.connect.side_effect = ConnectionError("Failed to connect to MySQL server")
    yield mock_connection

@pytest.fixture
def output_directory_cannot_be_created():
    """output directory does not exist and cannot be created"""
    invalid_path = "/invalid/path/that/cannot/be/created"
    with patch('os.makedirs', side_effect=OSError("Failed to create output directory")):
        yield invalid_path


@pytest.fixture
def disk_with_zero_bytes_free():
    """disk has 0 bytes free"""
    try:
        with patch('builtins.open', side_effect=OSError("No space left on device")):
            yield
    except Exception as e:
        raise FixtureError(f"disk_with_zero_bytes_free setup failed: {e}") from e