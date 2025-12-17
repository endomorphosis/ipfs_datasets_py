"""Test stubs for MySQL to Parquet conversion."""

import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest


@pytest.mark.asyncio
async def test_return_value_is_a_dict(mysql_to_parquet_instance, mysql_database_with_10_html_10_citation_5_embedding):
    """
    Given MySQL database contains html table with 10 rows
    And MySQL database contains citation table with 10 rows
    And MySQL database contains embedding table with 5 rows
    When get_files_from_sql_server_as_parquet is called
    Then return value is a dict
    """
    expected_type = dict
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_type = type(result)
    
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_key", ["html", "citation", "embedding"])
async def test_dict_contains_key(mysql_to_parquet_instance, mysql_database_with_10_html_10_citation_5_embedding, expected_key):
    """
    Given MySQL database contains html table with 10 rows
    And MySQL database contains citation table with 10 rows
    And MySQL database contains embedding table with 5 rows
    When get_files_from_sql_server_as_parquet is called
    Then dict contains expected key
    """
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_contains_key = expected_key in result
    
    assert actual_contains_key, f"expected key {expected_key}, got {list(result.keys())}"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["html", "citation", "embedding"])
async def test_value_is_a_list(mysql_to_parquet_instance, mysql_database_with_10_html_10_citation_5_embedding, key):
    """
    Given MySQL database contains html table with 10 rows
    And MySQL database contains citation table with 10 rows
    And MySQL database contains embedding table with 5 rows
    When get_files_from_sql_server_as_parquet is called
    Then all key values are lists
    """
    expected_type = list
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_type = type(result[key])
    
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


@pytest.mark.asyncio
async def test_html_list_contains_2_file_paths(mysql_to_parquet_instance, mysql_database_with_two_gnis_html):
    """
    Given MySQL html table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then "html" list contains 2 file paths
    """
    expected_count = 2
    html_key = "html"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_count = len(result[html_key])
    
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


@pytest.mark.asyncio
async def test_html_paths_end_with_html_parquet(mysql_to_parquet_instance, mysql_database_with_two_gnis_html):
    """
    Given MySQL html table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then each path ends with "_html.parquet"
    """
    expected_suffix = "_html.parquet"
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_ends_with_suffix = result[html_key][first_index].endswith(expected_suffix)
    
    assert actual_ends_with_suffix, f"expected path to end with {expected_suffix}, got {result[html_key][first_index]}"


@pytest.mark.asyncio
async def test_html_files_exist_on_disk(mysql_to_parquet_instance, mysql_database_with_two_gnis_html):
    """
    Given MySQL html table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then each file exists on disk
    """
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_file_exists = os.path.exists(result[html_key][first_index])
    
    assert actual_file_exists, f"expected file to exist, got {result[html_key][first_index]}"


@pytest.mark.asyncio
async def test_html_files_are_readable_as_parquet(mysql_to_parquet_instance, mysql_database_with_two_gnis_html):
    """
    Given MySQL html table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then each file is readable as parquet
    """
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    parquet_table = pq.read_table(result[html_key][first_index])
    actual_is_readable = parquet_table is not None
    
    assert actual_is_readable, f"expected parquet file to be readable, got {result[html_key][first_index]}"


@pytest.mark.asyncio
async def test_citation_list_contains_2_file_paths(mysql_to_parquet_instance, mysql_database_with_two_gnis_citation):
    """
    Given MySQL citation table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then "citation" list contains 2 file paths
    """
    expected_count = 2
    citation_key = "citation"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_count = len(result[citation_key])
    
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


@pytest.mark.asyncio
async def test_citation_paths_end_with_citation_parquet(mysql_to_parquet_instance, mysql_database_with_two_gnis_citation):
    """
    Given MySQL citation table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then each path ends with "_citation.parquet"
    """
    expected_suffix = "_citation.parquet"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_ends_with_suffix = result[citation_key][first_index].endswith(expected_suffix)
    
    assert actual_ends_with_suffix, f"expected path to end with {expected_suffix}, got {result[citation_key][first_index]}"


@pytest.mark.asyncio
async def test_citation_files_exist_on_disk(mysql_to_parquet_instance, mysql_database_with_two_gnis_citation):
    """
    Given MySQL citation table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then each file exists on disk
    """
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_file_exists = os.path.exists(result[citation_key][first_index])
    
    assert actual_file_exists, f"expected file to exist, got {result[citation_key][first_index]}"


@pytest.mark.asyncio
async def test_citation_files_are_readable_as_parquet(mysql_to_parquet_instance, mysql_database_with_two_gnis_citation):
    """
    Given MySQL citation table has gnis values [66855, 67890]
    When get_files_from_sql_server_as_parquet is called
    Then each file is readable as parquet
    """
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    parquet_table = pq.read_table(result[citation_key][first_index])
    actual_is_readable = parquet_table is not None
    
    assert actual_is_readable, f"expected parquet file to be readable, got {result[citation_key][first_index]}"


@pytest.mark.asyncio
async def test_embedding_list_contains_1_file_path(mysql_to_parquet_instance, mysql_database_with_one_gnis_embedding):
    """
    Given MySQL embedding table has gnis value 66855
    When get_files_from_sql_server_as_parquet is called
    Then "embedding" list contains 1 file path
    """
    expected_count = 1
    embedding_key = "embedding"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_count = len(result[embedding_key])
    
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


@pytest.mark.asyncio
async def test_embedding_path_ends_with_embedding_parquet(mysql_to_parquet_instance, mysql_database_with_one_gnis_embedding):
    """
    Given MySQL embedding table has gnis value 66855
    When get_files_from_sql_server_as_parquet is called
    Then path ends with "_embedding.parquet"
    """
    expected_suffix = "_embedding.parquet"
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_ends_with_suffix = result[embedding_key][first_index].endswith(expected_suffix)
    
    assert actual_ends_with_suffix, f"expected path to end with {expected_suffix}, got {result[embedding_key][first_index]}"


@pytest.mark.asyncio
async def test_embedding_file_exists_on_disk(mysql_to_parquet_instance, mysql_database_with_one_gnis_embedding):
    """
    Given MySQL embedding table has gnis value 66855
    When get_files_from_sql_server_as_parquet is called
    Then file exists on disk
    """
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_file_exists = os.path.exists(result[embedding_key][first_index])
    
    assert actual_file_exists, f"expected file to exist, got {result[embedding_key][first_index]}"


@pytest.mark.asyncio
async def test_embedding_file_is_readable_as_parquet(mysql_to_parquet_instance, mysql_database_with_one_gnis_embedding):
    """
    Given MySQL embedding table has gnis value 66855
    When get_files_from_sql_server_as_parquet is called
    Then file is readable as parquet
    """
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    parquet_table = pq.read_table(result[embedding_key][first_index])
    actual_is_readable = parquet_table is not None
    
    assert actual_is_readable, f"expected parquet file to be readable, got {result[embedding_key][first_index]}"


@pytest.mark.asyncio
async def test_html_parquet_contains_cid_column(mysql_to_parquet_instance, mysql_database_with_one_html_row):
    """
    Given MySQL html table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first html parquet file is read
    Then parquet contains column "cid"
    """
    expected_column = "cid"
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_html_parquet_contains_doc_id_column(mysql_to_parquet_instance, mysql_database_with_one_html_row):
    """
    Given MySQL html table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first html parquet file is read
    Then parquet contains column "doc_id"
    """
    expected_column = "doc_id"
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_html_parquet_contains_doc_order_column(mysql_to_parquet_instance, mysql_database_with_one_html_row):
    """
    Given MySQL html table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first html parquet file is read
    Then parquet contains column "doc_order"
    """
    expected_column = "doc_order"
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_html_parquet_contains_html_title_column(mysql_to_parquet_instance, mysql_database_with_one_html_row):
    """
    Given MySQL html table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first html parquet file is read
    Then parquet contains column "html_title"
    """
    expected_column = "html_title"
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_html_parquet_contains_html_column(mysql_to_parquet_instance, mysql_database_with_one_html_row):
    """
    Given MySQL html table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first html parquet file is read
    Then parquet contains column "html"
    """
    expected_column = "html"
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_html_parquet_contains_gnis_column(mysql_to_parquet_instance, mysql_database_with_one_html_row):
    """
    Given MySQL html table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first html parquet file is read
    Then parquet contains column "gnis"
    """
    expected_column = "gnis"
    html_key = "html"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_citation_parquet_contains_bluebook_cid_column(mysql_to_parquet_instance, mysql_database_with_one_citation_row):
    """
    Given MySQL citation table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first citation parquet file is read
    Then parquet contains column "bluebook_cid"
    """
    expected_column = "bluebook_cid"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_citation_parquet_contains_cid_column(mysql_to_parquet_instance, mysql_database_with_one_citation_row):
    """
    Given MySQL citation table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first citation parquet file is read
    Then parquet contains column "cid"
    """
    expected_column = "cid"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_citation_parquet_contains_title_column(mysql_to_parquet_instance, mysql_database_with_one_citation_row):
    """
    Given MySQL citation table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first citation parquet file is read
    Then parquet contains column "title"
    """
    expected_column = "title"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_citation_parquet_contains_chapter_column(mysql_to_parquet_instance, mysql_database_with_one_citation_row):
    """
    Given MySQL citation table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first citation parquet file is read
    Then parquet contains column "chapter"
    """
    expected_column = "chapter"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_citation_parquet_contains_bluebook_citation_column(mysql_to_parquet_instance, mysql_database_with_one_citation_row):
    """
    Given MySQL citation table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first citation parquet file is read
    Then parquet contains column "bluebook_citation"
    """
    expected_column = "bluebook_citation"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_citation_parquet_contains_gnis_column(mysql_to_parquet_instance, mysql_database_with_one_citation_row):
    """
    Given MySQL citation table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first citation parquet file is read
    Then parquet contains column "gnis"
    """
    expected_column = "gnis"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_citation_parquet_contains_state_code_column(mysql_to_parquet_instance, mysql_database_with_one_citation_row):
    """
    Given MySQL citation table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first citation parquet file is read
    Then parquet contains column "state_code"
    """
    expected_column = "state_code"
    citation_key = "citation"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_embedding_parquet_contains_embedding_cid_column(mysql_to_parquet_instance, mysql_database_with_one_embedding_row):
    """
    Given MySQL embedding table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first embedding parquet file is read
    Then parquet contains column "embedding_cid"
    """
    expected_column = "embedding_cid"
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_embedding_parquet_contains_gnis_column(mysql_to_parquet_instance, mysql_database_with_one_embedding_row):
    """
    Given MySQL embedding table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first embedding parquet file is read
    Then parquet contains column "gnis"
    """
    expected_column = "gnis"
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_embedding_parquet_contains_cid_column(mysql_to_parquet_instance, mysql_database_with_one_embedding_row):
    """
    Given MySQL embedding table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first embedding parquet file is read
    Then parquet contains column "cid"
    """
    expected_column = "cid"
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_embedding_parquet_contains_text_chunk_order_column(mysql_to_parquet_instance, mysql_database_with_one_embedding_row):
    """
    Given MySQL embedding table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first embedding parquet file is read
    Then parquet contains column "text_chunk_order"
    """
    expected_column = "text_chunk_order"
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_embedding_parquet_contains_embedding_column(mysql_to_parquet_instance, mysql_database_with_one_embedding_row):
    """
    Given MySQL embedding table has 1 row
    When get_files_from_sql_server_as_parquet is called
    And first embedding parquet file is read
    Then parquet contains column "embedding"
    """
    expected_column = "embedding"
    embedding_key = "embedding"
    first_index = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_contains_column = expected_column in df.columns
    
    assert actual_contains_column, f"expected column {expected_column}, got {list(df.columns)}"


@pytest.mark.asyncio
async def test_html_parquet_row_has_correct_cid(mysql_to_parquet_instance, mysql_database_with_specific_html_row):
    """
    Given MySQL html table has row with cid "bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa"
    And row has doc_id "CO_CH15BULI_ARTIISEORBU_S15-40IN"
    And row has gnis 66855
    When get_files_from_sql_server_as_parquet is called
    And html parquet for gnis 66855 is read
    Then parquet row has cid "bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa"
    """
    expected_cid = "bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa"
    html_key = "html"
    first_index = 0
    cid_column = "cid"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_cid = df.iloc[first_row][cid_column]
    
    assert actual_cid == expected_cid, f"expected {expected_cid}, got {actual_cid}"


@pytest.mark.asyncio
async def test_html_parquet_row_has_correct_doc_id(mysql_to_parquet_instance, mysql_database_with_specific_html_row):
    """
    Given MySQL html table has row with cid "bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa"
    And row has doc_id "CO_CH15BULI_ARTIISEORBU_S15-40IN"
    And row has gnis 66855
    When get_files_from_sql_server_as_parquet is called
    And html parquet for gnis 66855 is read
    Then parquet row has doc_id "CO_CH15BULI_ARTIISEORBU_S15-40IN"
    """
    expected_doc_id = "CO_CH15BULI_ARTIISEORBU_S15-40IN"
    html_key = "html"
    first_index = 0
    doc_id_column = "doc_id"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_doc_id = df.iloc[first_row][doc_id_column]
    
    assert actual_doc_id == expected_doc_id, f"expected {expected_doc_id}, got {actual_doc_id}"


@pytest.mark.asyncio
async def test_html_parquet_row_has_correct_gnis(mysql_to_parquet_instance, mysql_database_with_specific_html_row):
    """
    Given MySQL html table has row with cid "bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa"
    And row has doc_id "CO_CH15BULI_ARTIISEORBU_S15-40IN"
    And row has gnis 66855
    When get_files_from_sql_server_as_parquet is called
    And html parquet for gnis 66855 is read
    Then parquet row has gnis 66855
    """
    expected_gnis = 66855
    html_key = "html"
    first_index = 0
    gnis_column = "gnis"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[html_key][first_index])
    actual_gnis = df.iloc[first_row][gnis_column]
    
    assert actual_gnis == expected_gnis, f"expected {expected_gnis}, got {actual_gnis}"


@pytest.mark.asyncio
async def test_citation_parquet_row_has_correct_bluebook_citation(mysql_to_parquet_instance, mysql_database_with_specific_citation_row):
    """
    Given MySQL citation table has row with bluebook_citation "Garland, Ark., County Code, §18-40 (1987)"
    And row has gnis 66855
    And row has state_code "AR"
    When get_files_from_sql_server_as_parquet is called
    And citation parquet for gnis 66855 is read
    Then parquet row has bluebook_citation "Garland, Ark., County Code, §18-40 (1987)"
    """
    expected_bluebook_citation = "Garland, Ark., County Code, §18-40 (1987)"
    citation_key = "citation"
    first_index = 0
    bluebook_citation_column = "bluebook_citation"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_bluebook_citation = df.iloc[first_row][bluebook_citation_column]
    
    assert actual_bluebook_citation == expected_bluebook_citation, f"expected {expected_bluebook_citation}, got {actual_bluebook_citation}"


@pytest.mark.asyncio
async def test_citation_parquet_row_has_correct_gnis(mysql_to_parquet_instance, mysql_database_with_specific_citation_row):
    """
    Given MySQL citation table has row with bluebook_citation "Garland, Ark., County Code, §18-40 (1987)"
    And row has gnis 66855
    And row has state_code "AR"
    When get_files_from_sql_server_as_parquet is called
    And citation parquet for gnis 66855 is read
    Then parquet row has gnis 66855
    """
    expected_gnis = 66855
    citation_key = "citation"
    first_index = 0
    gnis_column = "gnis"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_gnis = df.iloc[first_row][gnis_column]
    
    assert actual_gnis == expected_gnis, f"expected {expected_gnis}, got {actual_gnis}"


@pytest.mark.asyncio
async def test_citation_parquet_row_has_correct_state_code(mysql_to_parquet_instance, mysql_database_with_specific_citation_row):
    """
    Given MySQL citation table has row with bluebook_citation "Garland, Ark., County Code, §18-40 (1987)"
    And row has gnis 66855
    And row has state_code "AR"
    When get_files_from_sql_server_as_parquet is called
    And citation parquet for gnis 66855 is read
    Then parquet row has state_code "AR"
    """
    expected_state_code = "AR"
    citation_key = "citation"
    first_index = 0
    state_code_column = "state_code"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[citation_key][first_index])
    actual_state_code = df.iloc[first_row][state_code_column]
    
    assert actual_state_code == expected_state_code, f"expected {expected_state_code}, got {actual_state_code}"


@pytest.mark.asyncio
async def test_embedding_parquet_row_has_correct_gnis(mysql_to_parquet_instance, mysql_database_with_specific_embedding_row):
    """
    Given MySQL embedding table has row with gnis 66855
    And row has text_chunk_order 1
    And row has embedding vector with 768 dimensions
    When get_files_from_sql_server_as_parquet is called
    And embedding parquet for gnis 66855 is read
    Then parquet row has gnis 66855
    """
    expected_gnis = 66855
    embedding_key = "embedding"
    first_index = 0
    gnis_column = "gnis"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_gnis = df.iloc[first_row][gnis_column]
    
    assert actual_gnis == expected_gnis, f"expected {expected_gnis}, got {actual_gnis}"


@pytest.mark.asyncio
async def test_embedding_parquet_row_has_correct_text_chunk_order(mysql_to_parquet_instance, mysql_database_with_specific_embedding_row):
    """
    Given MySQL embedding table has row with gnis 66855
    And row has text_chunk_order 1
    And row has embedding vector with 768 dimensions
    When get_files_from_sql_server_as_parquet is called
    And embedding parquet for gnis 66855 is read
    Then parquet row has text_chunk_order 1
    """
    expected_text_chunk_order = 1
    embedding_key = "embedding"
    first_index = 0
    text_chunk_order_column = "text_chunk_order"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_text_chunk_order = df.iloc[first_row][text_chunk_order_column]
    
    assert actual_text_chunk_order == expected_text_chunk_order, f"expected {expected_text_chunk_order}, got {actual_text_chunk_order}"


@pytest.mark.asyncio
async def test_embedding_parquet_row_has_correct_embedding_dimensions(mysql_to_parquet_instance, mysql_database_with_specific_embedding_row):
    """
    Given MySQL embedding table has row with gnis 66855
    And row has text_chunk_order 1
    And row has embedding vector with 768 dimensions
    When get_files_from_sql_server_as_parquet is called
    And embedding parquet for gnis 66855 is read
    Then parquet row embedding has 768 values
    """
    expected_dimensions = 768
    embedding_key = "embedding"
    first_index = 0
    embedding_column = "embedding"
    first_row = 0
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    df = pd.read_parquet(result[embedding_key][first_index])
    actual_dimensions = len(df.iloc[first_row][embedding_column])
    
    assert actual_dimensions == expected_dimensions, f"expected {expected_dimensions}, got {actual_dimensions}"


@pytest.mark.asyncio
async def test_output_directory_contains_subdirectory_for_gnis_66855(mysql_to_parquet_instance, mysql_database_with_three_gnis_values):
    """
    Given MySQL tables contain gnis values [66855, 67890, 68000]
    When get_files_from_sql_server_as_parquet is called
    Then output directory contains subdirectory for gnis 66855
    """
    expected_gnis = 66855
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    subdirs = [d.name for d in output_dir.rglob('*') if d.is_dir()]
    actual_contains_gnis = str(expected_gnis) in subdirs
    
    assert actual_contains_gnis, f"expected subdirectory for gnis {expected_gnis}, got {subdirs}"


@pytest.mark.asyncio
async def test_output_directory_contains_subdirectory_for_gnis_67890(mysql_to_parquet_instance, mysql_database_with_three_gnis_values):
    """
    Given MySQL tables contain gnis values [66855, 67890, 68000]
    When get_files_from_sql_server_as_parquet is called
    Then output directory contains subdirectory for gnis 67890
    """
    expected_gnis = 67890
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    subdirs = [d.name for d in output_dir.rglob('*') if d.is_dir()]
    actual_contains_gnis = str(expected_gnis) in subdirs
    
    assert actual_contains_gnis, f"expected subdirectory for gnis {expected_gnis}, got {subdirs}"


@pytest.mark.asyncio
async def test_output_directory_contains_subdirectory_for_gnis_68000(mysql_to_parquet_instance, mysql_database_with_three_gnis_values):
    """
    Given MySQL tables contain gnis values [66855, 67890, 68000]
    When get_files_from_sql_server_as_parquet is called
    Then output directory contains subdirectory for gnis 68000
    """
    expected_gnis = 68000
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    subdirs = [d.name for d in output_dir.rglob('*') if d.is_dir()]
    actual_contains_gnis = str(expected_gnis) in subdirs
    
    assert actual_contains_gnis, f"expected subdirectory for gnis {expected_gnis}, got {subdirs}"


@pytest.mark.asyncio
async def test_data_directory_exists(mysql_to_parquet_instance, mysql_database_with_gnis_360420):
    """
    Given MySQL tables contain gnis value 360420
    When get_files_from_sql_server_as_parquet is called
    Then directory "input_from_sql/repo_id/data" exists
    """
    expected_directory = "input_from_sql/repo_id/data"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    full_path = output_dir / expected_directory
    actual_exists = full_path.exists()
    
    assert actual_exists, f"expected directory {expected_directory}, got directory does not exist"


@pytest.mark.asyncio
async def test_metadata_directory_exists(mysql_to_parquet_instance, mysql_database_with_gnis_360420):
    """
    Given MySQL tables contain gnis value 360420
    When get_files_from_sql_server_as_parquet is called
    Then directory "input_from_sql/repo_id/metadata" exists
    """
    expected_directory = "input_from_sql/repo_id/metadata"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    full_path = output_dir / expected_directory
    actual_exists = full_path.exists()
    
    assert actual_exists, f"expected directory {expected_directory}, got directory does not exist"


@pytest.mark.asyncio
async def test_html_parquet_file_exists(mysql_to_parquet_instance, mysql_database_with_gnis_360420):
    """
    Given MySQL tables contain gnis value 360420
    When get_files_from_sql_server_as_parquet is called
    Then file "input_from_sql/repo_id/data/360420_html.parquet" exists
    """
    expected_file = "input_from_sql/repo_id/data/360420_html.parquet"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    full_path = output_dir / expected_file
    actual_exists = full_path.exists()
    
    assert actual_exists, f"expected file {expected_file}, got file does not exist"


@pytest.mark.asyncio
async def test_citation_parquet_file_exists(mysql_to_parquet_instance, mysql_database_with_gnis_360420):
    """
    Given MySQL tables contain gnis value 360420
    When get_files_from_sql_server_as_parquet is called
    Then file "input_from_sql/repo_id/data/360420_citation.parquet" exists
    """
    expected_file = "input_from_sql/repo_id/data/360420_citation.parquet"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    full_path = output_dir / expected_file
    actual_exists = full_path.exists()
    
    assert actual_exists, f"expected file {expected_file}, got file does not exist"


@pytest.mark.asyncio
async def test_embedding_parquet_file_exists(mysql_to_parquet_instance, mysql_database_with_gnis_360420):
    """
    Given MySQL tables contain gnis value 360420
    When get_files_from_sql_server_as_parquet is called
    Then file "input_from_sql/repo_id/data/360420_embedding.parquet" exists
    """
    expected_file = "input_from_sql/repo_id/data/360420_embedding.parquet"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    output_dir = Path(mysql_to_parquet_instance.output_dir)
    full_path = output_dir / expected_file
    actual_exists = full_path.exists()
    
    assert actual_exists, f"expected file {expected_file}, got file does not exist"


@pytest.mark.asyncio
async def test_empty_html_table_returns_empty_list(mysql_to_parquet_instance, mysql_database_with_zero_rows):
    """
    Given MySQL html table has 0 rows
    And MySQL citation table has 0 rows
    And MySQL embedding table has 0 rows
    When get_files_from_sql_server_as_parquet is called
    Then "html" list is empty
    """
    expected_length = 0
    html_key = "html"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_length = len(result[html_key])
    
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


@pytest.mark.asyncio
async def test_empty_citation_table_returns_empty_list(mysql_to_parquet_instance, mysql_database_with_zero_rows):
    """
    Given MySQL html table has 0 rows
    And MySQL citation table has 0 rows
    And MySQL embedding table has 0 rows
    When get_files_from_sql_server_as_parquet is called
    Then "citation" list is empty
    """
    expected_length = 0
    citation_key = "citation"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_length = len(result[citation_key])
    
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


@pytest.mark.asyncio
async def test_empty_embedding_table_returns_empty_list(mysql_to_parquet_instance, mysql_database_with_zero_rows):
    """
    Given MySQL html table has 0 rows
    And MySQL citation table has 0 rows
    And MySQL embedding table has 0 rows
    When get_files_from_sql_server_as_parquet is called
    Then "embedding" list is empty
    """
    expected_length = 0
    embedding_key = "embedding"
    
    result = await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
    actual_length = len(result[embedding_key])
    
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


@pytest.mark.asyncio
async def test_mysql_connection_failure_raises_error(mysql_to_parquet_instance, mysql_server_not_reachable):
    """
    Given MySQL server is not reachable
    When get_files_from_sql_server_as_parquet is called
    Then ConnectionError is raised
    """
    with pytest.raises(ConnectionError, match=r"Failed to connect to MySQL server"):
        await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()


@pytest.mark.asyncio
async def test_invalid_output_directory_raises_error(mysql_to_parquet_instance, output_directory_cannot_be_created):
    """
    Given output directory does not exist
    And output directory cannot be created
    When get_files_from_sql_server_as_parquet is called
    Then OSError is raised
    """
    with pytest.raises(OSError, match=r"Failed to create output directory"):
        await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()


@pytest.mark.asyncio
async def test_disk_full_during_write_raises_error(mysql_to_parquet_instance, disk_with_zero_bytes_free):
    """
    Given MySQL tables contain 1000 rows
    And disk has 0 bytes free
    When get_files_from_sql_server_as_parquet is called
    Then OSError is raised
    """
    with pytest.raises(OSError, match=r"No space left on device"):
        await mysql_to_parquet_instance.get_files_from_sql_server_as_parquet()
