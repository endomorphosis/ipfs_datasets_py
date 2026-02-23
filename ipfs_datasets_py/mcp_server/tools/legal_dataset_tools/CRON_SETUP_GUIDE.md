# State Laws Cron Job Setup Guide

This guide explains how to set up periodic updates for state law datasets using the built-in scheduler.

## Quick Start

### 1. Using the CLI Tool

The easiest way to manage scheduled updates is using the `state_laws_cron.py` CLI tool:

```bash
# Navigate to the tool directory
cd ipfs_datasets_py/mcp_server/tools/legal_dataset_tools

# Add a daily update schedule for California and New York
python state_laws_cron.py add --schedule-id daily_ca_ny --states CA,NY --interval 24

# List all configured schedules
python state_laws_cron.py list

# Run a schedule immediately (useful for testing)
python state_laws_cron.py run --schedule-id daily_ca_ny

# Enable/disable schedules
python state_laws_cron.py disable --schedule-id daily_ca_ny
python state_laws_cron.py enable --schedule-id daily_ca_ny

# Remove a schedule
python state_laws_cron.py remove --schedule-id daily_ca_ny
```

### 2. Running the Continuous Scheduler (Daemon Mode)

To keep schedules running automatically, use daemon mode:

```bash
# Run the scheduler daemon (checks every 5 minutes by default)
python state_laws_cron.py daemon

# Custom check interval (in seconds)
python state_laws_cron.py daemon --check-interval 300
```

### 3. Using System Cron

For production deployments, you can use system cron to run the scheduler:

```bash
# Add to crontab
crontab -e

# Add this line to check schedules every hour
0 * * * * cd /path/to/ipfs_datasets_py/mcp_server/tools/legal_dataset_tools && python state_laws_cron.py daemon --check-interval 60
```

## Common Use Cases

### Daily Updates for Specific States

```bash
# Update California, New York, and Texas daily at 2 AM
python state_laws_cron.py add \
  --schedule-id daily_major_states \
  --states CA,NY,TX \
  --interval 24

# Focus on criminal law only
python state_laws_cron.py add \
  --schedule-id daily_criminal \
  --states CA,NY,TX \
  --legal-areas criminal \
  --interval 24
```

### Weekly Updates for All States

```bash
# Update all states weekly (168 hours)
python state_laws_cron.py add \
  --schedule-id weekly_all_states \
  --states all \
  --interval 168
```

### Multiple Legal Areas

```bash
# Update multiple legal areas
python state_laws_cron.py add \
  --schedule-id daily_employment_family \
  --states CA,NY \
  --legal-areas employment,family \
  --interval 24
```

## Configuration

### Storage Locations

- **Schedules**: `~/.ipfs_datasets/state_laws/schedule.json`
- **Scraped Data**: `~/.ipfs_datasets/state_laws/state_laws_<schedule_id>_<timestamp>.json`

### Schedule Configuration Format

Schedules are stored as JSON:

```json
{
  "daily_ca_ny": {
    "schedule_id": "daily_ca_ny",
    "states": ["CA", "NY"],
    "legal_areas": ["criminal", "employment"],
    "interval_hours": 24,
    "enabled": true,
    "created_at": "2024-01-15T10:00:00",
    "last_run": "2024-01-16T10:05:23",
    "next_run": "2024-01-17T10:05:23"
  }
}
```

## API Endpoints

The MCP dashboard also provides REST API endpoints for schedule management:

### List Schedules
```bash
curl http://localhost:8899/api/mcp/dataset/state_laws/schedules
```

### Create Schedule
```bash
curl -X POST http://localhost:8899/api/mcp/dataset/state_laws/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "schedule_id": "daily_ca",
    "states": ["CA"],
    "interval_hours": 24,
    "enabled": true
  }'
```

### Run Schedule Now
```bash
curl -X POST http://localhost:8899/api/mcp/dataset/state_laws/schedules/daily_ca/run
```

### Enable/Disable Schedule
```bash
curl -X POST http://localhost:8899/api/mcp/dataset/state_laws/schedules/daily_ca/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### Delete Schedule
```bash
curl -X DELETE http://localhost:8899/api/mcp/dataset/state_laws/schedules/daily_ca
```

## Programmatic Usage

You can also use the scheduler programmatically in Python:

```python
import anyio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
    create_schedule,
    list_schedules,
    run_schedule_now,
    enable_disable_schedule,
    remove_schedule
)

async def main():
    # Create a schedule
    schedule = await create_schedule(
        schedule_id="daily_ca",
        states=["CA"],
        legal_areas=["criminal"],
        interval_hours=24,
        enabled=True
    )
    
    # List schedules
    result = await list_schedules()
    print(f"Schedules: {result['schedules']}")
    
    # Run immediately
    result = await run_schedule_now("daily_ca")
    print(f"Scraping completed: {result['status']}")
    
    # Disable schedule
    await enable_disable_schedule("daily_ca", enabled=False)
    
    # Remove schedule
    await remove_schedule("daily_ca")

anyio.run(main)
```

## Troubleshooting

### Check Schedule Status
```bash
python state_laws_cron.py list
```

### Test a Schedule Manually
```bash
python state_laws_cron.py run --schedule-id <schedule_id>
```

### View Logs
Logs are written to the standard output. When running as a daemon, redirect to a file:
```bash
python state_laws_cron.py daemon > scheduler.log 2>&1 &
```

### Check Data Output
```bash
ls -lh ~/.ipfs_datasets/state_laws/
```

## Best Practices

1. **Start Small**: Test with a single state before scheduling all states
2. **Rate Limiting**: Use longer intervals (24+ hours) to be respectful to source websites
3. **Legal Areas**: Filter by legal areas to reduce data volume if you only need specific types
4. **Monitor Disk Space**: Scraped data accumulates over time; implement cleanup policies
5. **Backup Schedules**: The schedule.json file should be backed up regularly

## Security Considerations

1. The scheduler runs with the permissions of the user who starts it
2. Scraped data is stored in the user's home directory by default
3. Network access is required for scraping
4. Consider running in a dedicated user account for production deployments

## Support

For issues or questions:
- Check the logs for error messages
- Verify network connectivity to source websites
- Ensure sufficient disk space for scraped data
- Review the schedule configuration in schedule.json
