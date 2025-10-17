# Quick Start Guide - RECAP & State Laws Dataset Builder

## What Was Fixed

The caselaw MCP dashboard at `http://127.0.0.1:8899/mcp/caselaw` now:
- ✅ Shows **9 tools** instead of 4
- ✅ Has fully functional **RECAP Archive Dataset Builder**
- ✅ Has fully functional **State Laws Dataset Builder**
- ✅ Supports **resume capability** for interrupted jobs
- ✅ Provides **cron job scheduling** for automatic updates

## Quick Test (5 minutes)

### 1. Start the Dashboard

```bash
cd /path/to/ipfs_datasets_py
python -m ipfs_datasets_py.mcp_dashboard
```

Dashboard starts at: `http://127.0.0.1:8899`

### 2. Navigate to Caselaw Section

Open browser: `http://127.0.0.1:8899/mcp/caselaw`

You should see:
- **9 tools available** (instead of 4)
- "Dataset Workflows" section with tabs:
  - US Code Dataset
  - State Laws Dataset
  - RECAP Archive Dataset

### 3. Test RECAP Archive (Small Dataset)

In the "RECAP Archive Dataset" tab:

1. **Select Court**: Choose "Ninth Circuit"
2. **Document Types**: Select "Opinions"
3. **Date Range**: 
   - Filed After: 2024-01-01
   - Filed Before: 2024-01-31
4. **Options**: Check "Include full document text"
5. Click **"Start Scraping"**

The dashboard will:
- Show progress in real-time
- Display fetched documents in preview table
- Allow export as JSON or save to IPFS

### 4. Test State Laws (Small Dataset)

In the "State Laws Dataset" tab:

1. **Select States**: Choose "CA" and "NY"
2. **Legal Areas**: Leave blank for all areas
3. **Max Statutes**: 10 (for quick test)
4. Click **"Start Scraping"**

## Using via Python API

### Example 1: Scrape RECAP Archive

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_recap_archive

async def scrape_9th_circuit():
    result = await scrape_recap_archive(
        courts=['ca9'],              # 9th Circuit Court of Appeals
        document_types=['opinion'],   # Only opinions
        filed_after='2024-01-01',    # Last year
        filed_before='2024-12-31',
        include_text=True,            # Include full text
        max_documents=50,             # Limit for testing
        job_id='test_9th_circuit'    # For resume capability
    )
    
    print(f"Status: {result['status']}")
    print(f"Documents: {result['metadata']['documents_count']}")
    print(f"Job ID: {result['job_id']}")
    
    return result

# Run it
result = asyncio.run(scrape_9th_circuit())
```

### Example 2: Search RECAP Archive

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import search_recap_documents

async def search_copyright_cases():
    result = await search_recap_documents(
        query='copyright',
        court='ca9',
        document_type='opinion',
        filed_after='2023-01-01',
        limit=10
    )
    
    print(f"Found {result['count']} documents")
    
    for doc in result['documents']:
        print(f"- {doc['case_name']} ({doc['date_filed']})")
    
    return result

result = asyncio.run(search_copyright_cases())
```

### Example 3: Scrape State Laws

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_state_laws

async def scrape_california_laws():
    result = await scrape_state_laws(
        states=['CA'],
        legal_areas=['criminal', 'civil'],
        output_format='json',
        max_statutes=100
    )
    
    print(f"Status: {result['status']}")
    print(f"Statutes: {result['metadata']['statutes_count']}")
    
    return result

result = asyncio.run(scrape_california_laws())
```

### Example 4: Resume Interrupted Job

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_recap_archive

async def resume_large_job():
    # First run (gets interrupted)
    try:
        result = await scrape_recap_archive(
            courts=['ca9', 'ca2', 'cadc'],
            document_types=['opinion'],
            max_documents=1000,
            job_id='large_federal_dataset',  # Important for resume!
            resume=False
        )
    except KeyboardInterrupt:
        print("Job interrupted! Can resume later...")
    
    # Resume later
    result = await scrape_recap_archive(
        courts=['ca9', 'ca2', 'cadc'],
        document_types=['opinion'],
        max_documents=1000,
        job_id='large_federal_dataset',  # Same job_id
        resume=True                       # Resume from saved state
    )
    
    print(f"Completed: {result['metadata']['documents_count']} documents")
    
    return result
```

## Setting Up Automatic Updates

### Option 1: Simple Daemon (Recommended for Testing)

```bash
# Add a daily schedule for important states
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id daily_important \
    --states CA,NY,TX,FL \
    --interval 24

# Run the scheduler daemon
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron daemon
```

The daemon will:
- Check every 5 minutes for due schedules
- Run scraping automatically when schedule is due
- Save all output and logs
- Handle errors and retries

### Option 2: Systemd Service (Recommended for Production)

Create `/etc/systemd/system/state-laws-updater.service`:

```ini
[Unit]
Description=State Laws Auto-Updater
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME
ExecStart=/usr/bin/python3 -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron daemon
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable state-laws-updater
sudo systemctl start state-laws-updater
sudo systemctl status state-laws-updater
```

View logs:

```bash
sudo journalctl -u state-laws-updater -f
```

### Option 3: Docker Container

```bash
# Pull or build image
docker build -t state-laws-updater .

# Run with volume mount for persistent data
docker run -d \
    --name state-laws \
    -v ~/.ipfs_datasets:/root/.ipfs_datasets \
    state-laws-updater
```

## Managing Schedules

### Add Schedules

```bash
# Daily update for CA and NY
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id daily_ca_ny \
    --states CA,NY \
    --interval 24

# Weekly update for all states
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id weekly_all \
    --states all \
    --interval 168
```

### List Schedules

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron list
```

Output:
```
Configured Schedules (2):

✓ daily_ca_ny
  States: CA, NY
  Interval: 24 hours
  Last run: 2024-01-15T10:30:00
  Next run: 2024-01-16T10:30:00

✓ weekly_all
  States: all
  Interval: 168 hours
  Last run: never
  Next run: 2024-01-22T00:00:00
```

### Run Schedule Manually

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron run \
    --schedule-id daily_ca_ny
```

### Enable/Disable Schedule

```bash
# Disable (keeps schedule but doesn't run)
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron disable \
    --schedule-id weekly_all

# Re-enable
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron enable \
    --schedule-id weekly_all
```

### Remove Schedule

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron remove \
    --schedule-id weekly_all
```

## Using MCP Tools via JSON-RPC

The dashboard uses MCP JSON-RPC protocol. You can call tools directly:

```bash
curl -X POST http://127.0.0.1:8899/api/mcp/caselaw/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "scrape_recap_archive",
    "params": {
      "courts": ["ca9"],
      "document_types": ["opinion"],
      "max_documents": 10
    },
    "id": 1
  }'
```

Or via REST API fallback:

```bash
curl -X POST http://127.0.0.1:8899/api/mcp/dataset/recap/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "courts": ["ca9"],
    "document_types": ["opinion"],
    "max_documents": 10
  }'
```

## Monitoring Jobs

### List All Jobs

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_manager import list_scraping_jobs

jobs = list_scraping_jobs()

for job in jobs:
    print(f"{job['job_id']}: {job['status']}")
    print(f"  Progress: {job['progress']['percentage']:.1f}%")
    print(f"  Items: {job['progress']['items_processed']}/{job['progress']['items_total']}")
```

### Check Job Status

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_manager import ScrapingState

state = ScrapingState('my_job_id')
if state.load():
    metadata = state.get_metadata()
    print(f"Status: {metadata['status']}")
    print(f"Progress: {metadata['progress']}")
```

## Data Location

All data is stored in `~/.ipfs_datasets/`:

```
~/.ipfs_datasets/
├── scraping_state/          # Job state for resume capability
│   ├── recap_*.json         # Job metadata
│   └── recap_*.pickle       # Job data
├── schedules/               # Cron schedules
│   └── schedules.json
└── legal_datasets/          # Output data (configurable)
    ├── recap/
    ├── state_laws/
    └── us_code/
```

## Troubleshooting

### Dashboard shows 4 tools instead of 9

Check the API endpoint:
```bash
curl http://127.0.0.1:8899/api/mcp/caselaw/tools
```

Should return:
```json
{
  "success": true,
  "tool_count": 9,
  "tools": {
    "check_document_consistency": {...},
    "query_theorems": {...},
    "bulk_process_caselaw": {...},
    "add_theorem": {...},
    "scrape_recap_archive": {...},
    "search_recap_documents": {...},
    "scrape_state_laws": {...},
    "list_scraping_jobs": {...},
    "scrape_us_code": {...}
  }
}
```

### Scraping fails with network error

Check internet access to source sites:
```bash
curl -I https://www.courtlistener.com
```

### Job won't resume

Check state files exist:
```bash
ls -la ~/.ipfs_datasets/scraping_state/
```

Load state manually:
```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_manager import ScrapingState
state = ScrapingState('your_job_id')
success = state.load()
print(f"Loaded: {success}")
if success:
    print(f"Status: {state.metadata['status']}")
    print(f"Items: {len(state.scraped_data)}")
```

## Next Steps

1. **Try the dashboard**: Navigate to `http://127.0.0.1:8899/mcp/caselaw`
2. **Test RECAP scraping**: Start with a small date range and one court
3. **Set up a schedule**: Use the cron tool to automate updates
4. **Explore the API**: Try the Python examples above
5. **Read the docs**: See `RECAP_IMPLEMENTATION_SUMMARY.md` for details

## Support

- **GitHub Issues**: https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Documentation**: See `RECAP_IMPLEMENTATION_SUMMARY.md`
- **Cron Setup**: See `ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/CRON_SETUP_SIMPLE.md`

## Common Use Cases

### Use Case 1: Build Federal Circuit Court Dataset

```python
# Scrape all Circuit Courts for the last 6 months
result = await scrape_recap_archive(
    courts=['ca1', 'ca2', 'ca3', 'ca4', 'ca5', 'ca6', 
            'ca7', 'ca8', 'ca9', 'ca10', 'ca11', 'cadc', 'cafc'],
    document_types=['opinion'],
    filed_after='2023-07-01',
    filed_before='2024-01-01',
    include_text=True,
    job_id='federal_circuits_6mo'
)
```

### Use Case 2: Track State Law Changes

```bash
# Set up daily monitoring for key states
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id track_important_states \
    --states CA,NY,TX,FL,PA,IL,OH,GA,NC,MI \
    --interval 24
```

### Use Case 3: Build Patent Law Dataset

```python
# Scrape Federal Circuit (patent appeals)
recap_result = await scrape_recap_archive(
    courts=['cafc'],  # Federal Circuit
    document_types=['opinion'],
    filed_after='2020-01-01',
    include_text=True,
    job_id='patent_appeals'
)

# Scrape US Code Title 35 (Patents)
usc_result = await scrape_us_code(
    titles=[35],
    include_metadata=True
)
```

### Use Case 4: Research Specific Case

```python
# Search for a case
result = await search_recap_documents(
    case_name='Smith v. Jones',
    court='ca9',
    limit=10
)

# Get full document
if result['documents']:
    doc_id = result['documents'][0]['id']
    doc = await get_recap_document(
        document_id=str(doc_id),
        include_text=True
    )
```

That's it! The RECAP Archive and State Laws dataset builder is now fully functional and ready to use.
