#!/bin/bash
# Fix Self-Hosted Runner Permissions
# Run this script on the fent-reactor machine to fix Git permission issues
#
# Usage: sudo bash fix_runner_permissions.sh

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 Fixing Self-Hosted Runner Permissions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
   echo "❌ Please run as root (use sudo)"
   exit 1
fi

WORKSPACE_DIR="/home/actions-runner/_work/ipfs_datasets_py"
RUNNER_USER="devel"

echo "📁 Workspace: $WORKSPACE_DIR"
echo "👤 Runner User: $RUNNER_USER"
echo ""

# Step 1: Check if workspace exists
if [ ! -d "$WORKSPACE_DIR" ]; then
    echo "⚠️  Workspace directory not found. Creating it..."
    mkdir -p "$WORKSPACE_DIR"
fi

# Step 2: Fix ownership
echo "🔧 Step 1/5: Fixing ownership..."
chown -R "$RUNNER_USER:$RUNNER_USER" "$WORKSPACE_DIR"
echo "✅ Ownership fixed"
echo ""

# Step 3: Fix permissions
echo "🔧 Step 2/5: Fixing permissions..."
chmod -R 755 "$WORKSPACE_DIR"
echo "✅ Permissions fixed"
echo ""

# Step 4: Clean corrupted workspace
if [ -d "$WORKSPACE_DIR/ipfs_datasets_py" ]; then
    echo "🔧 Step 3/5: Cleaning potentially corrupted workspace..."
    rm -rf "$WORKSPACE_DIR/ipfs_datasets_py"
    echo "✅ Workspace cleaned (will be recreated on next run)"
else
    echo "🔧 Step 3/5: No existing workspace to clean"
fi
echo ""

# Step 5: Add git safe directory
echo "🔧 Step 4/5: Adding git safe directory..."
sudo -u "$RUNNER_USER" git config --global --add safe.directory "$WORKSPACE_DIR/ipfs_datasets_py" 2>/dev/null || true
echo "✅ Git safe directory configured"
echo ""

# Step 6: Verify runner service
echo "🔧 Step 5/5: Checking runner service..."
if systemctl list-units --type=service | grep -q "actions.runner"; then
    RUNNER_SERVICE=$(systemctl list-units --type=service | grep "actions.runner" | awk '{print $1}' | head -1)
    echo "   Found runner service: $RUNNER_SERVICE"
    echo "   Restarting service..."
    systemctl restart "$RUNNER_SERVICE"
    echo "✅ Runner service restarted"
else
    echo "⚠️  Runner service not found (may be running manually)"
    echo "   If using manual runner, restart with: ./svc.sh stop && ./svc.sh start"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Permissions Fix Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 Next Steps:"
echo "1. Trigger a test workflow run:"
echo "   gh workflow run \"enhanced-pr-completion-monitor.yml\" --ref main"
echo ""
echo "2. Monitor workflow execution:"
echo "   gh run list --workflow=enhanced-pr-completion-monitor.yml --limit 3"
echo ""
echo "3. Check for successful checkout in logs"
echo ""
echo "Expected result: Next workflow run should succeed"
echo ""
