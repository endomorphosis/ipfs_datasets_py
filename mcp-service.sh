#!/bin/bash
# MCP Service Management Script
# Provides easy management of the IPFS Datasets MCP systemd service

set -e

SERVICE_NAME="ipfs-datasets-mcp.service"
MCP_URL="http://127.0.0.1:8899/api/mcp/status"

show_status() {
    echo "=== IPFS Datasets MCP Service Status ==="
    systemctl is-enabled $SERVICE_NAME 2>/dev/null && echo "✅ Service enabled for boot" || echo "❌ Service NOT enabled for boot"
    
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo "✅ Service is running"
        echo ""
        echo "=== Service Details ==="
        systemctl status $SERVICE_NAME --no-pager -l
        echo ""
        echo "=== MCP API Status ==="
        if curl -s -f $MCP_URL > /dev/null 2>&1; then
            echo "✅ MCP API responding"
            curl -s $MCP_URL | python -m json.tool 2>/dev/null || echo "Response: $(curl -s $MCP_URL)"
        else
            echo "❌ MCP API not responding"
        fi
    else
        echo "❌ Service is not running"
        echo ""
        echo "=== Recent logs ==="
        journalctl -u $SERVICE_NAME -n 10 --no-pager
    fi
}

start_service() {
    echo "Starting MCP service..."
    sudo systemctl start $SERVICE_NAME
    sleep 3
    show_status
}

stop_service() {
    echo "Stopping MCP service..."
    sudo systemctl stop $SERVICE_NAME
    echo "✅ Service stopped"
}

restart_service() {
    echo "Restarting MCP service..."
    sudo systemctl restart $SERVICE_NAME
    sleep 3
    show_status
}

enable_service() {
    echo "Enabling MCP service for boot..."
    sudo systemctl enable $SERVICE_NAME
    echo "✅ Service enabled for boot"
}

disable_service() {
    echo "Disabling MCP service from boot..."
    sudo systemctl disable $SERVICE_NAME
    echo "✅ Service disabled from boot"
}

show_logs() {
    echo "=== MCP Service Logs ==="
    journalctl -u $SERVICE_NAME -f
}

show_help() {
    echo "MCP Service Management Script"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  status     Show service status and health (default)"
    echo "  start      Start the service"
    echo "  stop       Stop the service"
    echo "  restart    Restart the service"
    echo "  enable     Enable service to start on boot"
    echo "  disable    Disable service from starting on boot"
    echo "  logs       Show live service logs"
    echo "  help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 status"
    echo "  $0 restart"
    echo "  $0 enable"
    echo ""
    echo "Service file: /etc/systemd/system/$SERVICE_NAME"
}

# Main command handling
case "${1:-status}" in
    "status"|"")
        show_status
        ;;
    "start")
        start_service
        ;;
    "stop")
        stop_service
        ;;
    "restart")
        restart_service
        ;;
    "enable")
        enable_service
        ;;
    "disable")
        disable_service
        ;;
    "logs")
        show_logs
        ;;
    "help"|"--help"|"-h")
        show_help
        ;;
    *)
        echo "Error: Unknown command '$1'"
        echo ""
        show_help
        exit 1
        ;;
esac