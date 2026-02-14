# IPFS Datasets MCP Systemd Service Setup

## Overview
Successfully configured the IPFS Datasets MCP server to run automatically on boot using systemd with auto-restart capabilities.

## Service Configuration

### Service File Location
```
/etc/systemd/system/ipfs-datasets-mcp.service
```

### Service Features
- ✅ **Auto-start on boot**: Service is enabled and will start automatically when the system boots
- ✅ **Auto-restart on failure**: Service will restart automatically if it crashes or fails
- ✅ **Security hardening**: Runs with limited privileges and filesystem access
- ✅ **Logging**: All output is logged to systemd journal
- ✅ **Resource limits**: Memory and CPU usage is monitored

### Restart Policy
- **Restart**: `always` - Service will restart on any failure
- **RestartSec**: `15` seconds - Wait time between restart attempts
- **StartLimitIntervalSec**: `300` seconds (5 minutes) - Time window for restart attempts
- **StartLimitBurst**: `5` - Maximum restart attempts within the time window

## Management Commands

### Using the CLI Tool
```bash
# Start MCP service
./ipfs-datasets mcp start

# Check MCP service status
./ipfs-datasets mcp status

# Stop MCP service
./ipfs-datasets mcp stop
```

### Using systemctl
```bash
# Check service status
sudo systemctl status ipfs-datasets-mcp.service

# Start service
sudo systemctl start ipfs-datasets-mcp.service

# Stop service
sudo systemctl stop ipfs-datasets-mcp.service

# Restart service
sudo systemctl restart ipfs-datasets-mcp.service

# Enable service (auto-start on boot)
sudo systemctl enable ipfs-datasets-mcp.service

# Disable service (don't auto-start on boot)
sudo systemctl disable ipfs-datasets-mcp.service

# View logs
journalctl -u ipfs-datasets-mcp.service -f
```

### Using the Management Script
A convenient management script is available at `./mcp-service.sh`:

```bash
# Show status (default)
./mcp-service.sh status
./mcp-service.sh

# Start/stop/restart service
./mcp-service.sh start
./mcp-service.sh stop
./mcp-service.sh restart

# Enable/disable boot startup
./mcp-service.sh enable
./mcp-service.sh disable

# View live logs
./mcp-service.sh logs

# Show help
./mcp-service.sh help
```

## Service Details

### Runtime Configuration
- **User**: `barberb`
- **Working Directory**: `/home/barberb/ipfs_datasets_py`
- **Python Environment**: Uses project virtual environment at `.venv/bin/python`
- **Host**: `127.0.0.1`
- **Port**: `8899`
- **API Endpoint**: `http://127.0.0.1:8899/api/mcp/status`

### Environment Variables
```bash
PATH=/home/barberb/ipfs_datasets_py/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PYTHONPATH=/home/barberb/ipfs_datasets_py
MCP_DASHBOARD_HOST=127.0.0.1
MCP_DASHBOARD_PORT=8899
MCP_DASHBOARD_BLOCKING=1
```

### Security Settings
- **NoNewPrivileges**: `true` - Prevents privilege escalation
- **PrivateTmp**: `true` - Uses private temporary filesystem
- **ProtectSystem**: `strict` - System filesystem is read-only
- **ProtectHome**: `read-only` - Home directories are read-only
- **ReadWritePaths**: Limited to project directory and configuration paths

## Verification

### Service Status Check
```bash
./mcp-service.sh status
```
Expected output:
- ✅ Service enabled for boot
- ✅ Service is running
- ✅ MCP API responding

### API Health Check
```bash
curl -s http://127.0.0.1:8899/api/mcp/status | python -m json.tool
```

### Auto-restart Test
The service has been tested and confirmed to automatically restart after process termination.

## Troubleshooting

### View Service Logs
```bash
journalctl -u ipfs-datasets-mcp.service -f
```

### Check Port Conflicts
```bash
sudo netstat -tlnp | grep 8899
```

### Manual Service Control
```bash
# Force stop all related processes
sudo pkill -f "ipfs_datasets_py.mcp_dashboard"

# Reset failed service state
sudo systemctl reset-failed ipfs-datasets-mcp.service

# Reload systemd configuration
sudo systemctl daemon-reload
```

### Service File Updates
After modifying the service file:
```bash
sudo cp /home/barberb/ipfs_datasets_py/ipfs-datasets-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart ipfs-datasets-mcp.service
```

## Files Created/Modified

1. **Service File**: `/home/barberb/ipfs_datasets_py/ipfs-datasets-mcp.service` (source)
2. **Systemd Service**: `/etc/systemd/system/ipfs-datasets-mcp.service` (deployed)
3. **Management Script**: `/home/barberb/ipfs_datasets_py/mcp-service.sh`

The MCP server is now running as a proper system service with automatic startup and restart capabilities!