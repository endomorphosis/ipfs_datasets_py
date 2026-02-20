# Web Archive Tools

MCP tools for web search, archiving, and data discovery. Provides integration with major
search APIs, the Wayback Machine, Common Crawl, GitHub, HuggingFace Hub, and more.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `brave_search.py` | `brave_search()`, `brave_news_search()` | Web search via Brave Search API |
| `common_crawl_search.py` | `common_crawl_search()` | Query Common Crawl CDX index for matching URLs |
| `common_crawl_advanced.py` | `common_crawl_advanced_search()`, `extract_common_crawl_data()` | Advanced Common Crawl extraction |
| `wayback_machine_search.py` | `wayback_search()`, `wayback_get_snapshots()` | Search and retrieve Wayback Machine snapshots |
| `github_search.py` | `github_search_repos()`, `github_search_code()`, `github_search_users()` | GitHub API search |
| `huggingface_search.py` | `huggingface_search_models()`, `huggingface_search_datasets()` | HuggingFace Hub search |
| `google_search.py` | `google_search()` | Google Search API integration |
| `serpstack_search.py` | `serpstack_search()` | SerpStack SERP data API |
| `openverse_search.py` | `openverse_search()` | Open-licensed media search via Openverse API |
| `archive_is_integration.py` | `archive_is_save()`, `archive_is_check()` | Save/check URLs with archive.is |
| `autoscraper_integration.py` | `autoscraper_learn()`, `autoscraper_scrape()` | AutoScraper-based dynamic web scraping |
| `create_warc.py` | `create_warc()` | Create WARC archives from URLs |
| `extract_text_from_warc.py` | `extract_text_from_warc()` | Extract text content from WARC files |
| `extract_links_from_warc.py` | `extract_links_from_warc()` | Extract hyperlinks from WARC files |
| `extract_metadata_from_warc.py` | `extract_metadata_from_warc()` | Extract HTTP metadata from WARC files |
| `extract_dataset_from_cdxj.py` | `extract_dataset_from_cdxj()` | Build a dataset from a CDX-J index |
| `index_warc.py` | `index_warc()` | Index a WARC file for fast lookup |
| `ipwb_integration.py` | `ipwb_index()`, `ipwb_replay()` | InterPlanetary Wayback (IPWB) operations |

## Usage

### Web search via Brave

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import brave_search

result = await brave_search(
    query="IPFS distributed storage benchmarks",
    max_results=10,
    search_type="web"   # "web" | "news" | "images"
)
# Returns: {"status": "success", "results": [{"url": "...", "title": "...", "snippet": "..."}]}
```

### Search Common Crawl

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import common_crawl_search

result = await common_crawl_search(
    url_pattern="*.arxiv.org/abs/*",
    crawl_id="CC-MAIN-2024-10",   # Optional: specific crawl
    max_results=100,
    output_format="json"
)
```

### Wayback Machine

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import wayback_search

# Get snapshots of a URL
result = await wayback_search(
    url="https://example.com",
    start_date="2020-01-01",
    end_date="2024-12-31",
    limit=50
)
```

### GitHub search

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import github_search_repos

result = await github_search_repos(
    query="ipfs python dataset",
    language="python",
    min_stars=10,
    max_results=30
)
```

### HuggingFace Hub search

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import huggingface_search_datasets

result = await huggingface_search_datasets(
    query="legal court documents",
    task="text-classification",
    max_results=20
)
```

### WARC archive workflow

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    create_warc, extract_text_from_warc, index_warc
)

# 1. Create WARC from URLs
warc = await create_warc(
    urls=["https://example.com", "https://example.org"],
    output_path="/data/archive.warc.gz"
)

# 2. Index the WARC
index = await index_warc(warc_path="/data/archive.warc.gz")

# 3. Extract text
texts = await extract_text_from_warc(
    warc_path="/data/archive.warc.gz",
    content_type_filter="text/html"
)
```

## API Keys Required

| Tool | API Key Environment Variable | Required? |
|------|------------------------------|-----------|
| `brave_search` | `BRAVE_API_KEY` | Yes |
| `google_search` | `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_CX` | Yes |
| `serpstack_search` | `SERPSTACK_API_KEY` | Yes |
| `github_search` | `GITHUB_TOKEN` | No (rate-limited without) |
| All others | None | No |

## Dependencies

**Required:**
- `requests` — HTTP client

**Optional (graceful degradation if missing):**
- `wayback` / `internetarchive` — Wayback Machine integration
- `cdx-toolkit` — Common Crawl CDX queries
- `warcio` — WARC file creation and parsing
- `beautifulsoup4` — HTML parsing for text extraction
- `autoscraper` — dynamic scraping

## Status

| Tool | Status |
|------|--------|
| `brave_search` | ✅ Production ready |
| `common_crawl_search` | ✅ Production ready |
| `wayback_machine_search` | ✅ Production ready |
| `github_search` | ✅ Production ready |
| `huggingface_search` | ✅ Production ready |
| `serpstack_search` | ✅ Production ready (requires API key) |
| WARC tools | ✅ Production ready |
| `ipwb_integration` | ⚠️ Requires IPWB installation |
