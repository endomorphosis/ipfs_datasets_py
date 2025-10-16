# Using the CourtListener RECAP API

## Overview

The RECAP Archive scraper uses the CourtListener API to access federal court documents from the PACER system. CourtListener is a free and open legal research website that provides access to millions of court opinions and documents.

## API Access

### Free Tier
- No API token required for basic usage
- Rate limited to a few requests per second
- Limited to 100 results per query
- Sufficient for testing and light usage

### Authenticated Tier (Recommended for Production)
- Get an API token (free)
- Higher rate limits
- Better performance
- Access to more features

## Getting an API Token

1. **Create an account** at https://www.courtlistener.com/sign-in/register/
2. **Verify your email** address
3. **Generate a token** at https://www.courtlistener.com/api/rest-info/#authentication
4. **Save your token** securely

## Using the API Token

### Option 1: Environment Variable (Recommended)
```bash
export COURTLISTENER_API_TOKEN="your_token_here"
```

The scraper will automatically use this token if set.

### Option 2: Pass as Parameter
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import search_recap_documents

result = await search_recap_documents(
    court='ca9',
    document_type='opinion',
    api_token='your_token_here'
)
```

### Option 3: Store in Config File
Create `~/.config/courtlistener/token`:
```
your_token_here
```

Then read it in your script:
```python
import os
from pathlib import Path

token_file = Path.home() / '.config' / 'courtlistener' / 'token'
api_token = token_file.read_text().strip() if token_file.exists() else None

result = await search_recap_documents(
    court='ca9',
    document_type='opinion',
    api_token=api_token
)
```

## Common Issues and Solutions

### Issue 1: No Documents Found

**Symptoms:**
- Search returns `status: success` but 0 documents
- Warning message about no matching documents

**Possible Causes:**
1. **Date range too narrow**: Try wider date ranges
2. **Court has no RECAP documents**: Not all courts have uploaded documents
3. **Specific filters too restrictive**: Try removing some filters

**Solutions:**
```python
# Try a broader search
result = await search_recap_documents(
    query='*',  # Wildcard to get all documents
    court='ca9',
    filed_after='2023-01-01',  # Wider date range
    limit=10
)

# Or search without court filter
result = await search_recap_documents(
    document_type='opinion',
    filed_after='2024-01-01',
    limit=10
)
```

### Issue 2: API Rate Limiting

**Symptoms:**
- HTTP 429 errors
- "Too many requests" messages

**Solutions:**
1. Add delays between requests:
```python
result = await scrape_recap_archive(
    courts=['ca9'],
    rate_limit_delay=2.0,  # Wait 2 seconds between requests
    max_documents=10
)
```

2. Get an API token for higher limits

3. Reduce the number of concurrent requests

### Issue 3: Network Errors

**Symptoms:**
- "Failed to resolve 'www.courtlistener.com'"
- Connection timeout errors
- DNS resolution errors

**Solutions:**
1. Check internet connectivity:
```bash
ping www.courtlistener.com
curl https://www.courtlistener.com/api/rest/v3/search/?court=ca9
```

2. Check firewall/proxy settings
3. Verify DNS is working
4. Try accessing CourtListener website in browser

### Issue 4: Empty Results for Specific Court

**Symptoms:**
- Search works for some courts but not others
- 0 documents for specific court code

**Possible Causes:**
- Court code might be incorrect
- Court might not have RECAP documents
- Date range might be outside available data

**Solutions:**
1. Verify court code at: https://www.courtlistener.com/api/rest-info/#court-codes
2. Try different court codes:
```python
# Common court codes:
# ca9 = Ninth Circuit Court of Appeals
# nysd = S.D. New York (Southern District of New York)
# dcd = D.C. District Court
# cacd = C.D. California (Central District)
# txnd = N.D. Texas (Northern District)

result = await search_recap_documents(
    court='nysd',  # Try different court
    filed_after='2023-01-01'
)
```

3. Check CourtListener website to see if court has documents

## API Documentation

### Official Documentation
- Main API docs: https://www.courtlistener.com/api/rest-info/
- Search API: https://www.courtlistener.com/api/rest/v3/search/
- Opinions API: https://www.courtlistener.com/api/rest/v3/opinions/
- Dockets API: https://www.courtlistener.com/api/rest/v3/dockets/

### Available Endpoints

The scraper uses these endpoints:

1. **Opinions Endpoint** (for opinion searches):
   - URL: `https://www.courtlistener.com/api/rest/v3/opinions/`
   - Returns: Court opinions/decisions
   - Best for: Opinion-specific searches

2. **Dockets Endpoint** (for docket searches):
   - URL: `https://www.courtlistener.com/api/rest/v3/dockets/`
   - Returns: Docket information
   - Best for: Case docket searches

3. **Unified Search** (for general searches):
   - URL: `https://www.courtlistener.com/api/rest/v3/search/`
   - Returns: Mixed results
   - Best for: Broad searches across types

### Court Codes

Common federal court codes:

**Circuit Courts:**
- `ca1` through `ca11` - First through Eleventh Circuits
- `cadc` - D.C. Circuit
- `cafc` - Federal Circuit

**District Courts (examples):**
- `nysd` - S.D. New York
- `cand` - N.D. California
- `cacd` - C.D. California
- `casd` - S.D. California
- `txnd` - N.D. Texas
- `txsd` - S.D. Texas
- `dcd` - D.C. District

**Bankruptcy Courts:**
- Add `b` prefix: `bap1`, `bap2`, etc.

Full list: https://www.courtlistener.com/api/rest-info/#court-codes

## Testing the Connection

### Simple Test Script

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import search_recap_documents

async def test_connection():
    """Test basic connection to CourtListener API."""
    print("Testing CourtListener API connection...")
    
    # Try a simple search
    result = await search_recap_documents(
        query='*',
        court='ca9',
        limit=5
    )
    
    if result['status'] == 'error':
        print(f"❌ Error: {result['error']}")
        return False
    
    if result['count'] > 0:
        print(f"✅ Success! Found {result['count']} documents")
        print(f"First case: {result['documents'][0]['case_name']}")
        return True
    else:
        print("⚠️  Connection OK but no documents found")
        print("Try different search parameters")
        return False

# Run test
success = asyncio.run(test_connection())
```

### Command Line Test

```bash
# Test API directly with curl
curl "https://www.courtlistener.com/api/rest/v3/opinions/?court=ca9&filed_after=2024-01-01" | jq '.count'

# With API token
curl -H "Authorization: Token YOUR_TOKEN" \
  "https://www.courtlistener.com/api/rest/v3/opinions/?court=ca9" | jq '.count'
```

## Rate Limits

### Free Tier
- ~100 requests per minute
- 100 results per request max
- No guarantees on availability

### Authenticated
- Higher limits (varies)
- Better performance
- More reliable

### Best Practices
1. Always use delays between requests (1-2 seconds)
2. Cache results when possible
3. Use `max_documents` to limit scraping
4. Get an API token for production
5. Handle rate limit errors gracefully

## Data Availability

### What's Available
- Federal court opinions
- PACER dockets (uploaded by RECAP users)
- Appellate court documents
- District court filings
- Bankruptcy documents

### What's NOT Available
- State court documents (use state_laws_scraper instead)
- Documents not uploaded to RECAP
- Sealed/confidential documents
- Real-time updates (there's a delay)

### Coverage
- Varies by court and time period
- More recent documents more likely available
- Popular/important cases more likely available
- Coverage improving over time as more documents uploaded

## Support

### CourtListener Support
- Contact: https://www.courtlistener.com/contact/
- Twitter: @courtlistener
- GitHub: https://github.com/freelawproject/courtlistener

### This Scraper
- Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- See `QUICK_START_GUIDE.md` for usage examples
- See `RECAP_IMPLEMENTATION_SUMMARY.md` for technical details

## Legal Notice

RECAP and CourtListener are projects of the Free Law Project. The data comes from PACER (Public Access to Court Electronic Records). 

Using this data:
- ✅ Legal for research, journalism, and public interest purposes
- ✅ Free to use with attribution
- ✅ OK to redistribute with proper licensing
- ❌ Not for unauthorized commercial purposes
- ❌ Subject to PACER and CourtListener terms of service

Always check current terms at:
- https://www.courtlistener.com/terms/
- https://pacer.uscourts.gov/
