# Simple Cron Setup for State Laws Auto-Updates

This guide shows how to set up automatic periodic updates for state laws datasets.

## Quick Start (Using Built-in Scheduler)

### 1. Install Dependencies

```bash
pip install ipfs_datasets_py
```

### 2. Add a Schedule

Add a daily update for California and New York:

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id daily_ca_ny \
    --states CA,NY \
    --interval 24
```

Add a weekly update for all states:

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron add \
    --schedule-id weekly_all \
    --states all \
    --interval 168
```

### 3. Run Scheduler Daemon

Run the scheduler as a daemon that checks for due updates:

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron daemon
```

The daemon will:
- Check every 5 minutes (configurable with `--check-interval`)
- Run any schedules that are due
- Log all operations
- Can be stopped with Ctrl+C

## Managing Schedules

### List all schedules

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron list
```

### Run a schedule manually

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron run --schedule-id daily_ca_ny
```

### Enable/disable a schedule

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron disable --schedule-id daily_ca_ny
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron enable --schedule-id daily_ca_ny
```

### Remove a schedule

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron remove --schedule-id daily_ca_ny
```

## Running as a Background Service (Linux)

### Option 1: Using systemd (Recommended)

1. Create a systemd service file:

```bash
sudo nano /etc/systemd/system/state-laws-updater.service
```

2. Add the following content (adjust paths as needed):

```ini
[Unit]
Description=State Laws Auto-Updater
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME
ExecStart=/usr/bin/python3 -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron daemon --check-interval 300
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:

```bash
sudo systemctl enable state-laws-updater
sudo systemctl start state-laws-updater
```

4. Check status:

```bash
sudo systemctl status state-laws-updater
sudo journalctl -u state-laws-updater -f  # View logs
```

### Option 2: Using screen/tmux

Run in a detachable terminal session:

```bash
screen -dmS state-laws python3 -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron daemon
```

Reattach to view:

```bash
screen -r state-laws
```

### Option 3: Traditional cron

If you prefer traditional cron, create a wrapper script:

```bash
#!/bin/bash
# /usr/local/bin/update-state-laws.sh
cd /path/to/ipfs_datasets_py
python3 -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron run --schedule-id YOUR_SCHEDULE_ID >> /var/log/state-laws-update.log 2>&1
```

Make it executable:

```bash
chmod +x /usr/local/bin/update-state-laws.sh
```

Add to crontab:

```bash
crontab -e
```

Add line (runs daily at 2 AM):

```
0 2 * * * /usr/local/bin/update-state-laws.sh
```

## RECAP Archive Updates

For RECAP Archive, you can use similar patterns but the scraper is already resumable:

```python
#!/usr/bin/env python3
import asyncio
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_recap_archive

async def update_recap():
    # Scrape last 7 days of opinions from key circuits
    result = await scrape_recap_archive(
        courts=['ca9', 'ca2', 'cadc'],  # 9th, 2nd, DC circuits
        document_types=['opinion'],
        filed_after='7_days_ago',  # Helper for relative dates
        include_text=True,
        max_documents=100,
        job_id='recap_weekly_update'
    )
    print(f"Updated {result['metadata']['documents_count']} documents")

if __name__ == '__main__':
    asyncio.run(update_recap())
```

Save as `update_recap.py` and add to cron or systemd service.

## Configuration Files

Schedules are stored in: `~/.ipfs_datasets/schedules/`
Scraping state is stored in: `~/.ipfs_datasets/scraping_state/`

You can backup these directories to preserve schedules and resume capability.

## Environment Variables

You can set these to customize behavior:

```bash
export IPFS_DATASETS_STATE_DIR="$HOME/.ipfs_datasets/scraping_state"
export IPFS_DATASETS_SCHEDULE_DIR="$HOME/.ipfs_datasets/schedules"
export IPFS_DATASETS_OUTPUT_DIR="$HOME/.ipfs_datasets/legal_datasets"
```

## Troubleshooting

### Check if scheduler daemon is running

```bash
ps aux | grep state_laws_cron
```

### View logs

If running as systemd service:

```bash
sudo journalctl -u state-laws-updater -n 100
```

### Test a schedule manually

```bash
python -m ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron run --schedule-id YOUR_SCHEDULE_ID
```

### Clear stuck state

If a job is stuck, you can delete its state:

```bash
rm ~/.ipfs_datasets/scraping_state/JOB_ID.*
```

## Best Practices

1. **Start Small**: Begin with a few states and short intervals for testing
2. **Rate Limiting**: Use appropriate delays (2-5 seconds) to avoid overwhelming source sites
3. **Monitoring**: Check logs regularly to ensure updates are running
4. **Disk Space**: Monitor available disk space, especially for full-text storage
5. **Backup**: Regularly backup your `~/.ipfs_datasets` directory
6. **Resume Capability**: Jobs automatically save state, so interrupted runs can resume

## Advanced: Docker Deployment

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install ipfs_datasets_py
CMD ["python", "-m", "ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_laws_cron", "daemon"]
```

Build and run:

```bash
docker build -t state-laws-updater .
docker run -d --name state-laws \
    -v ~/.ipfs_datasets:/root/.ipfs_datasets \
    state-laws-updater
```

## Support

For issues or questions:
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Check logs in `~/.ipfs_datasets/scraping_state/` for detailed error information
