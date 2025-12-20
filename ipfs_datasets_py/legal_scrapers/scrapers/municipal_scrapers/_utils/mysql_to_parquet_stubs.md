# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/municipal_law_database_scrapers/_utils/mysql_to_parquet.py'

Files last updated: 1765833669.3432186

Stub file last updated: 2025-12-15 13:26:20

## MySqlToParquet
```python
class MySqlToParquet:
    """
    Class to download data from MySQL and save it as parquet files.

This class handles extracting data from MySQL tables using DuckDB as an intermediary,
and saving the data as parquet files, organized by a partition column.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_files_from_sql_server_as_parquet
```python
async def get_files_from_sql_server_as_parquet(self) -> dict[str, list[str]]:
    """
    Download data from MySQL and save it as parquet files.
    
    Returns:
        dict[str, [list[str]]: A dictionary containing the following:
            html: list of string paths to html parquet files
            citation: list of string paths to citation parquet files
            embedding: list of string paths to embedding parquet files

    Example:
    >>> result = await converter.get_files_from_sql_server_as_parquet()
    >>> print(result)
    {
        "html": [
            "/path/to/output/repo_id/data/12345_html.parquet",
            "/path/to/output/repo_id/data/67890_html.parquet"
        ],
        "citation": [
            "/path/to/output/repo_id/data/12345_citation.parquet",
            "/path/to/output/repo_id/data/67890_citation.parquet"
        ],
        "embedding": [
            "/path/to/output/repo_id/data/12345_embedding.parquet"
        ]
    }
    Example Directory Structure:
    >>> output_folder/
        ├── input_from_sql
        │   ├── repo_id
        │   │   ├── data
        │   │   │   ├── 360420_html.parquet
        │   │   │   ├── 360420_citation.parquet
        │   │   │   ├── 360420_embedding.parquet
        │   │   │   ├── ...
        │   │   ├── metadata
        │   │   │   ├── 360420.json
        │   │   │   ├── ...
    Example HTML Parquet Structure:
    >>> {
        "cid":"bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa",
        "doc_id":"CO_CH15BULI_ARTIISEORBU_S15-40IN",
        "doc_order":155,
        "html_title":"<div class=\"chunk-title\">Sec. 15-40. - Injunction.</div>",
        "html":"<div class=\"chunk-content\">\n ... </div>",
        "gnis":66855
    }
    Example Citation Parquet Structure:
    >>> {
        "bluebook_cid":"bafkreid3foaz35j7msukneriyygretlr45fddc32mesk6nrfkap6bdmnn4",
        "cid":"bafkreie3sy7cjyo5bnw2pzlnomsapu4dckxhhf5i7ed2vrfqr3763pntjy",
        "title":"Sec. 18-40. - Additional court costs for employment of an investigator for the public defender's office",
        "public_law_num":"NA",
        "chapter":"Chapter 18 - COURTS",
        "ordinance":null,
        "section":null,
        "enacted":null,
        "year":null,
        "history_note":"Code 1987, § 8-21",
        "place_name":"Garland",
        "state_code":"AR",
        "bluebook_state_code":"Ark.",
        "state_name":"Arkansas",
        "chapter_num":"18",
        "title_num":"18-40",
        "date":"1987",
        "bluebook_citation":"Garland, Ark., County Code, §18-40 (1987)",
        "gnis":66855
    }
    Example Embedding Parquet Structure:
    >>> {
        "embedding_cid":"bafkreiananlow6bodt4mqf23mrqn7mpq6sz4t2ourydxvfwwtbkaapzm6y",
        "gnis":"66855",
        "cid":"bafkreicswpqclipcmiglxdmnjemod4esk3u63ocdd6rtuodjijvajxewfi",
        "text_chunk_order":1,"embedding":[0.0123, -0.0456, 0.0789, ...]
    }
    """
```
* **Async:** True
* **Method:** True
* **Class:** MySqlToParquet

## main
```python
async def main() -> int:
    """
    Main function to run the MySqlToParquet process.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A