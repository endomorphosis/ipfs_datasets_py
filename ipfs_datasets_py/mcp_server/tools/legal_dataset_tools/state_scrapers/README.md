# State-Specific Law Scrapers

This directory contains individual scrapers for each US state's official legislative website. Each scraper implements state-specific parsing logic while outputting data in a normalized schema.

## Architecture

### Normalized Schema

All scrapers output data in a consistent `NormalizedStatute` schema:

```python
@dataclass
class NormalizedStatute:
    # Identification
    state_code: str          # e.g., "CA", "NY"
    state_name: str          # e.g., "California"
    statute_id: str          # Unique identifier
    
    # Hierarchy
    code_name: str           # e.g., "Penal Code"
    title_number: str        # Title/Part number
    chapter_number: str      # Chapter number
    section_number: str      # Section number
    
    # Content
    short_title: str
    full_text: str           # Actual statute text
    summary: str
    
    # Classification
    legal_area: str          # e.g., "criminal", "civil"
    topics: List[str]        # e.g., ["murder", "homicide"]
    
    # Source
    source_url: str          # URL to official source
    official_cite: str       # Official citation
    
    # Metadata
    metadata: StatuteMetadata
    scraped_at: str
```

### Base Scraper Class

All state scrapers inherit from `BaseStateScraper`:

```python
class BaseStateScraper(ABC):
    @abstractmethod
    def get_base_url(self) -> str:
        """Get the base URL for the state's legislative website."""
        pass
    
    @abstractmethod
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of available codes/titles for this state."""
        pass
    
    @abstractmethod
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code."""
        pass
```

## Implemented Scrapers

### California (`california.py`)
- **Source**: https://leginfo.legislature.ca.gov/
- **Codes**: 29 codes (Penal Code, Vehicle Code, etc.)
- **Status**: ✅ Implemented

### New York (`new_york.py`)
- **Source**: https://www.nysenate.gov/
- **Codes**: 23+ consolidated laws
- **Status**: ✅ Implemented

### Texas (`texas.py`)
- **Source**: https://statutes.capitol.texas.gov/
- **Codes**: 24+ codes
- **Status**: ✅ Implemented

### Generic Scraper (`generic.py`)
- **Purpose**: Fallback for states without specific implementations
- **Sources**: Tries official site, then Justia, then FindLaw
- **Status**: ✅ Implemented

## Usage

### Using the Scraper Registry

```python
from state_scrapers import get_scraper_for_state, StateScraperRegistry

# Get a scraper for California
scraper = get_scraper_for_state("CA", "California")

# Scrape all codes
statutes = await scraper.scrape_all(
    legal_areas=["criminal"],
    max_statutes=100,
    rate_limit_delay=2.0
)

# Each statute is a NormalizedStatute object
for statute in statutes:
    print(f"{statute.get_citation()}: {statute.short_title}")
```

### Checking Available Scrapers

```python
# Check if a state has a scraper
has_scraper = StateScraperRegistry.has_scraper("CA")

# Get all states with scrapers
states = StateScraperRegistry.get_all_registered_states()
print(f"Scrapers available for: {states}")
```

### Through the Main API

```python
from state_laws_scraper import scrape_state_laws

# Uses state-specific scrapers by default
result = await scrape_state_laws(
    states=["CA", "NY", "TX"],
    use_state_specific_scrapers=True  # Default
)

# Fallback to Justia aggregator
result = await scrape_state_laws(
    states=["CA"],
    use_state_specific_scrapers=False
)
```

## Adding New State Scrapers

To add a scraper for a new state:

1. Create a new file (e.g., `florida.py`)
2. Inherit from `BaseStateScraper`
3. Implement required methods
4. Register the scraper

Example:

```python
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry

class FloridaScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "http://www.leg.state.fl.us/"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        # Return list of Florida statutes
        return [...]
    
    async def scrape_code(self, code_name, code_url) -> List[NormalizedStatute]:
        # Parse Florida's specific HTML structure
        # Return normalized statutes
        return [...]

# Register it
StateScraperRegistry.register("FL", FloridaScraper)
```

4. Import in `__init__.py`:

```python
from . import florida
```

## Benefits of This Approach

1. **Consistency**: All states use the same schema, making cross-state analysis easy
2. **Flexibility**: Each state can have custom parsing logic
3. **Fallback**: Generic scraper handles states without specific implementations
4. **Extensibility**: Easy to add new states
5. **Official Sources**: Scrapes directly from state legislative websites
6. **Metadata**: Captures rich metadata (effective dates, amendments, etc.)

## Schema Normalization

The normalized schema allows for:

- **Cross-state comparisons**: Compare criminal laws across states
- **Legal research**: Find similar statutes in multiple jurisdictions
- **Data analysis**: Aggregate statistics across states
- **Citation linking**: Connect related statutes
- **Historical tracking**: Track amendments and changes

## Data Processing

After scraping, the normalized data can be:

1. **Exported** to JSON, Parquet, or CSV
2. **Stored** in IPFS for immutable archiving
3. **Indexed** for fast searching
4. **Analyzed** for patterns and trends
5. **Compared** across jurisdictions

## Testing

Each scraper should be tested with:

```python
import asyncio

async def test_california():
    scraper = CaliforniaScraper("CA", "California")
    
    # Test code list
    codes = scraper.get_code_list()
    assert len(codes) == 29
    
    # Test scraping
    statutes = await scraper.scrape_code("Penal Code", codes[0]['url'])
    assert all(isinstance(s, NormalizedStatute) for s in statutes)
    
    # Test normalization
    assert statutes[0].state_code == "CA"
    assert statutes[0].code_name == "Penal Code"

asyncio.run(test_california())
```

## Future Enhancements

1. **More states**: Add scrapers for all 50 states
2. **Full text**: Scrape complete statute text, not just titles
3. **Amendments**: Track legislative changes over time
4. **Citations**: Extract and link cross-references
5. **Regulations**: Include administrative regulations
6. **Court rules**: Add court procedural rules
7. **Case law**: Link statutes to relevant cases
