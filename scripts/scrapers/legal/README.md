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
