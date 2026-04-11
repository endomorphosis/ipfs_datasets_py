# Legal Data Scrapers

This directory contains specialized scrapers for legal and regulatory data sources.

## Available Scrapers

### us_code_scraper.py
Scraper for the United States Code.

**Features:**
- Scrapes USC titles and sections
- Structured XML/HTML parsing
- Incremental updates

**Usage:**
```bash
python scripts/scrapers/legal/us_code_scraper.py [options]
```

### state_laws_scraper.py
Scraper for state legislation and laws.

**Features:**
- Multi-state support
- Bill tracking
- Legislative session data

**Usage:**
```bash
python scripts/scrapers/legal/state_laws_scraper.py [state] [options]
```

### municipal_laws_scraper.py
Scraper for municipal codes and ordinances.

**Features:**
- City and county codes
- Ordinance tracking
- Historical versions

**Usage:**
```bash
python scripts/scrapers/legal/municipal_laws_scraper.py [municipality] [options]
```

### recap_archive_scraper.py
Scraper for the RECAP archive (court documents).

**Features:**
- Federal court dockets
- Case documents
- Metadata extraction

**Usage:**
```bash
python scripts/scrapers/legal/recap_archive_scraper.py [options]
```

### federal_register_scraper.py
Scraper for the Federal Register.

**Features:**
- Daily register entries
- Agency documents
- Rules and notices

**Usage:**
```bash
python scripts/scrapers/legal/federal_register_scraper.py [options]
```

### netherlands_laws_scraper.py
Scraper for Netherlands laws from official Dutch government law pages.

**Features:**
- Crawls official `wetten.overheid.nl` discovery/search pages
- Supports explicit BWBR law-document URLs
- Downloads per-law `/informatie` metadata pages
- Writes document, article, search, and JSON-LD outputs
- Persists scrape-run metadata with discovery/fetch/parse counters

**Usage:**
```bash
ipfs-datasets legal scrape-netherlands-laws \
  --seed_urls '["https://wetten.overheid.nl/zoeken/zoekresultaat/titel/verloten/titelf/0/tekstf/1/d/10-5-2025/dx/0/page/1/count/100/s/2"]' \
  --output_dir ~/.ipfs_datasets/netherlands_laws \
  --max_seed_pages 10 \
  --crawl_depth 1 \
  --max_documents 50 \
  --rate_limit_delay 0.5 \
  --skip_existing true
```

**Outputs:**
- `netherlands_laws_index_latest.jsonl`: document-level normalized law records
- `netherlands_laws_articles_index_latest.jsonl`: article-level records
- `netherlands_laws_search_index_latest.jsonl`: combined document/article search rows
- `netherlands_laws_jsonld/NETHERLANDS-LAWS.jsonld`: JSON-LD export
- `netherlands_laws_run_metadata_latest.json`: run counters and error log

**How To Tell It Is Working:**
- `seed_pages_visited` should increase above 0 when discovery pages are reachable
- `candidate_links_found` and `official_law_documents_accepted` should grow as BWBR links are discovered
- `documents_fetched` and `documents_parsed` should track successful law retrieval/parsing
- `documents_skipped` should increase on reruns when `--skip_existing true` is used
- `errors` in the run metadata should stay small and inspectable rather than silently ignored

## Integration

These scrapers can be used with the Legal Dataset Tools in the MCP server:

```bash
# Via MCP tools
ipfs-datasets tools run legal_dataset_tools scrape_jurisdiction --jurisdiction "us_federal"

# Direct execution
python scripts/scrapers/legal/us_code_scraper.py
```

## Requirements

Most scrapers require additional dependencies:
- `beautifulsoup4` - HTML parsing
- `lxml` - XML parsing
- `requests` - HTTP requests
- `playwright` - Browser automation (for some scrapers)

Install with:
```bash
pip install beautifulsoup4 lxml requests playwright
```

## Data Storage

Scraped data is typically stored in:
- IPFS (via ipfs_kit_py)
- Local cache directories
- Dataset formats (Parquet, JSON, etc.)

## Notes

- Some scrapers may require API keys or credentials
- Respect rate limits and robots.txt
- See individual scraper files for detailed documentation
