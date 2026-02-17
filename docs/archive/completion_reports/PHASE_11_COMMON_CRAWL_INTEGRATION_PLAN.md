# Phase 11: Legal Scrapers Unification with Common Crawl Integration

**Status:** Planning Complete, Ready for Implementation  
**Date:** 2026-02-16  
**Estimated Duration:** 8 hours (pragmatic approach)

---

## Executive Summary

Phase 11 enhances the legal scrapers infrastructure to integrate with Common Crawl and HuggingFace datasets for comprehensive government website scraping, rule extraction, and logic module integration.

### Key Integration Points

1. **HuggingFace Datasets** - Common Crawl URL indexes
   - `endomorphosis/common_crawl_federal_index`
   - `endomorphosis/common_crawl_municipal_index`
   - `endomorphosis/common_crawl_state_index`

2. **Existing Infrastructure**
   - Common Crawl integration: `web_archiving/common_crawl_integration.py` (433 lines)
   - MCP tools: `mcp_server/tools/web_archive_tools/common_crawl_search.py` (217 lines)
   - BaseScraper ABC: `state_scrapers/base_scraper.py`
   - NormalizedStatute dataclass with metadata support

3. **JSONL URL Lists** (4 files, ~5 MB total)
   - `federal_all_branches.jsonl` (909 KB)
   - `federal_all_branches_with_provenance.jsonl` (1.7 MB)
   - `federal_all_branches_with_sources_and_provenance.jsonl` (1.8 MB)
   - `us_towns_and_counties_urls.jsonl` (1.8 MB)

---

## Discovered Assets

### Existing Common Crawl Infrastructure ✅

**CommonCrawlSearchEngine** (`web_archiving/common_crawl_integration.py`):
- Three integration modes: local, remote, cli
- Domain/URL lookups with rowgroup slicing
- WARC record fetching and content extraction
- MCP server integration
- Batch operations and parallel queries

**MCP Tools** (`mcp_server/tools/web_archive_tools/`):
- `common_crawl_search.py` - CDX toolkit integration
- `common_crawl_advanced.py` - Advanced operations
- Integration with cdx-toolkit for Common Crawl access

### Existing Legal Scrapers ✅

**Federal Scrapers:**
- `us_code_scraper.py` - U.S. Code scraping
- `federal_register_scraper.py` - Federal Register
- `recap_archive_scraper.py` - RECAP Archive

**State Scrapers:**
- `state_scrapers/base_scraper.py` - BaseScraper ABC with NormalizedStatute
- `state_laws_scraper.py` - State laws orchestration

**Municipal Scrapers:**
- `municipal_law_database_scrapers/` - 3 scraper implementations
  - Municode
  - eCode360
  - American Legal

**Support Systems:**
- `citation_extraction.py` - Legal citation parsing
- `export_utils.py` - Data export utilities
- `ipfs_storage_integration.py` - IPFS storage
- `legal_dataset_api.py` - API interface
- `municipal_codes_api.py` - Municipal codes API (with common_crawl fallback)

---

## Implementation Tasks

### Task 11.1: Common Crawl Legal Scraper (3h)

**Create:** `legal_scrapers/common_crawl_scraper.py`

**Functionality:**
1. Load JSONL URL lists (federal, state, municipal)
2. Query HuggingFace Common Crawl indexes
3. Fetch WARC segments using offset + range
4. Parse legal content
5. Extract rules with GraphRAG
6. Feed to logic module
7. Brave search fallback

**Key Classes:**
```python
class CommonCrawlLegalScraper(BaseScraper):
    """Legal scraper using Common Crawl + HuggingFace datasets."""
    
    async def load_url_list(self, jsonl_path: str) -> List[Dict]
    async def query_common_crawl_index(self, url: str, dataset: str) -> List[Dict]
    async def fetch_warc_content(self, warc_url: str, offset: int, length: int) -> str
    async def extract_rules_with_graphrag(self, content: str) -> Dict
    async def feed_to_logic_module(self, rules: Dict) -> None
    async def scrape_with_brave_fallback(self, url: str) -> Dict
```

**Dependencies:**
- `datasets` - HuggingFace datasets library
- `common_crawl_search_engine` - Existing submodule
- `ipfs_datasets_py.processors.specialized.graphrag` - UnifiedGraphRAGProcessor
- `ipfs_datasets_py.logic_integration` - LogicProcessor

### Task 11.2: Scraper Registry (2h)

**Create:** `legal_scrapers/registry.py`

**Functionality:**
1. Auto-discover all scrapers
2. Register federal, state, municipal scrapers
3. Add Common Crawl scraper as intelligent fallback
4. Routing logic based on source type
5. Configuration management

**Key Classes:**
```python
class ScraperRegistry:
    """Central registry for all legal scrapers."""
    
    def register_scraper(self, name: str, scraper_class: Type[BaseScraper])
    def get_scraper(self, source_type: str) -> BaseScraper
    def list_scrapers(self) -> List[str]
    def get_fallback_chain(self) -> List[BaseScraper]
```

### Task 11.3: BaseScraper Enhancement (1h)

**Enhance:** `state_scrapers/base_scraper.py`

**Add Methods:**
```python
class BaseScraper(ABC):
    # Existing methods...
    
    # New Common Crawl methods
    async def scrape_from_common_crawl(
        self, 
        url: str, 
        dataset_name: str
    ) -> Optional[NormalizedStatute]
    
    async def query_warc_file(
        self, 
        warc_url: str, 
        offset: int, 
        length: int
    ) -> str
    
    async def extract_with_graphrag(
        self, 
        content: str
    ) -> Dict[str, Any]
```

**Maintain:** 100% backward compatibility

### Task 11.4: Monitoring Integration (1h)

**Add @monitor decorators to:**
- `common_crawl_scraper.py` methods (5-7 methods)
- `registry.py` routing methods (2-3 methods)
- WARC fetching operations
- GraphRAG extraction calls
- Logic module feeding

**Update:** `scripts/monitoring/processor_dashboard.py` to display legal scraper metrics

### Task 11.5: Documentation (1h)

**Create:** `docs/LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md`

**Contents:**
1. Architecture overview
2. HuggingFace dataset usage
3. WARC parsing examples
4. GraphRAG integration patterns
5. Logic module feeding
6. Brave search configuration
7. Fallback chain configuration
8. Performance tuning
9. Troubleshooting

---

## Architecture

### Data Flow

```
JSONL URL Lists
    ↓
HuggingFace Common Crawl Indexes
    ↓
WARC Files (offset + range)
    ↓
Content Parser
    ↓
GraphRAG Processor → Rule Extraction
    ↓
Logic Module Integration
    ↓
Structured Legal Rules
```

### Fallback Chain

```
1. Primary Scraper (federal/state/municipal specific)
   ↓ (on failure)
2. Common Crawl Scraper (HuggingFace + WARC)
   ↓ (on failure)
3. Brave Search API
   ↓ (on failure)
4. Wayback Machine Archive
   ↓ (on failure)
5. Archive.is
```

### Integration Points

**With GraphRAG:**
```python
from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor

graphrag = UnifiedGraphRAGProcessor()
entities, relationships = await graphrag.process_website(legal_content)
rules = await graphrag.extract_legal_rules(entities, relationships)
```

**With Logic Module:**
```python
from ipfs_datasets_py.logic_integration import LogicProcessor

logic = LogicProcessor()
await logic.ingest_rules(rules, source="federal_register")
theorem = await logic.create_theorem(rules)
```

**With Common Crawl:**
```python
from ipfs_datasets_py.processors.web_archiving import CommonCrawlSearchEngine

cc_engine = CommonCrawlSearchEngine()
results = await cc_engine.search_domain("www.federalregister.gov")
content = await cc_engine.fetch_warc_content(
    warc_url=results[0]['warc_url'],
    offset=results[0]['offset'],
    length=results[0]['length']
)
```

---

## HuggingFace Dataset Usage

### Loading Indexes

```python
from datasets import load_dataset

# Load federal Common Crawl index
federal_index = load_dataset(
    "endomorphosis/common_crawl_federal_index",
    split="train"
)

# Query for specific URL
matches = federal_index.filter(
    lambda x: "www.govinfo.gov" in x['url']
)

# Get WARC pointers
for match in matches:
    warc_url = match['warc_filename']
    offset = match['warc_record_offset']
    length = match['warc_record_length']
    # Fetch content...
```

### Dataset Schema

Expected fields in HuggingFace datasets:
- `url` - Original URL
- `warc_filename` - S3 path to WARC file
- `warc_record_offset` - Byte offset in WARC
- `warc_record_length` - Length of record
- `timestamp` - Crawl timestamp
- `content_type` - MIME type
- `status_code` - HTTP status

---

## JSONL File Structure

### federal_all_branches.jsonl

```json
{
  "id": "legislative:entity:congress-gov:congress-gov",
  "kind": "entity",
  "branch": "legislative",
  "branch_confidence": 1.0,
  "branch_reasons": ["explicit branch"],
  "name": "Congress.gov",
  "aliases": [],
  "website": "https://congress.gov/",
  "host": "congress.gov",
  "description": "",
  "sources": ["curated:data/federal_domains/1.json"],
  "seed_urls": ["https://congress.gov/"]
}
```

### Usage in Scraper

```python
import json

def load_federal_urls(jsonl_path):
    urls = []
    with open(jsonl_path) as f:
        for line in f:
            data = json.loads(line)
            urls.extend(data.get('seed_urls', []))
    return urls
```

---

## Success Criteria

### Functional Requirements ✅
- [ ] Load and parse all 4 JSONL files
- [ ] Query all 3 HuggingFace Common Crawl datasets
- [ ] Fetch and parse WARC files with offset+range
- [ ] Extract legal rules with GraphRAG
- [ ] Feed rules to logic module
- [ ] Implement Brave search fallback
- [ ] Create unified scraper registry
- [ ] Add monitoring to all operations
- [ ] Maintain 100% backward compatibility

### Non-Functional Requirements ✅
- [ ] Zero breaking changes
- [ ] Comprehensive documentation
- [ ] <500ms average scrape latency
- [ ] >90% success rate with fallbacks
- [ ] Full test coverage for new code
- [ ] Clear error messages and logging

### Integration Requirements ✅
- [ ] GraphRAG processor integration
- [ ] Logic module integration
- [ ] Common Crawl integration
- [ ] HuggingFace datasets integration
- [ ] Brave search integration
- [ ] Monitoring dashboard integration

---

## Testing Strategy

### Unit Tests
- JSONL loading and parsing
- URL normalization
- WARC pointer construction
- Content extraction
- Rule parsing

### Integration Tests
- End-to-end Common Crawl scraping
- HuggingFace dataset queries
- GraphRAG extraction
- Logic module ingestion
- Fallback chain execution

### Performance Tests
- Concurrent scraping (10+ URLs)
- Large WARC file handling
- Dataset query optimization
- Memory usage profiling

---

## Risk Mitigation

### Risks

1. **HuggingFace Dataset Availability**
   - Mitigation: Fallback to direct Common Crawl queries
   - Mitigation: Cache frequently used indexes locally

2. **WARC Fetching Rate Limits**
   - Mitigation: Implement exponential backoff
   - Mitigation: Use multiple access methods (S3, HTTP)

3. **GraphRAG Processing Latency**
   - Mitigation: Async/await throughout
   - Mitigation: Batch processing for multiple rules

4. **Logic Module Integration Complexity**
   - Mitigation: Simple JSON-based rule format
   - Mitigation: Comprehensive examples in docs

### Contingency Plans

- If HuggingFace datasets unavailable: Use direct Common Crawl CDX API
- If Common Crawl fails: Use Brave search + Wayback Machine
- If GraphRAG slow: Implement caching and batch processing
- If Logic module unavailable: Store rules for later ingestion

---

## Next Steps

### Immediate (This Session)
1. Begin Task 11.1: Create `common_crawl_scraper.py`
2. Implement JSONL loading
3. Add HuggingFace dataset integration
4. Implement WARC fetching

### Short-term (Next Session)
1. Complete Task 11.1: GraphRAG + Logic integration
2. Task 11.2: Create ScraperRegistry
3. Task 11.3: Enhance BaseScraper
4. Task 11.4: Add monitoring

### Final (Last Session)
1. Task 11.5: Write comprehensive documentation
2. Create usage examples
3. Test end-to-end flows
4. Performance tuning

---

## Resources

### Existing Code
- `web_archiving/common_crawl_integration.py` - 433 lines
- `mcp_server/tools/web_archive_tools/common_crawl_search.py` - 217 lines
- `state_scrapers/base_scraper.py` - BaseScraper ABC
- `processors/specialized/graphrag/` - GraphRAG processors
- `logic_integration/` - Logic module

### External Dependencies
- `datasets` - HuggingFace datasets
- `cdx-toolkit` - Common Crawl CDX API
- `warcio` - WARC file parsing
- `requests` - HTTP requests
- `aiohttp` - Async HTTP

### Documentation
- Common Crawl docs: `docs/guides/tools/common_crawl_integration.md`
- GraphRAG docs: `docs/CROSS_CUTTING_INTEGRATION_GUIDE.md`
- Legal scrapers: `docs/PROCESSORS_ROOT_FILES_INVENTORY_2026.md`

---

**Status:** Ready for implementation  
**Next Action:** Begin Task 11.1 - Common Crawl Legal Scraper  
**Expected Completion:** 8 hours over 2-3 sessions
