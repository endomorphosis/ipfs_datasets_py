#!/bin/bash
# Script to test the auto-healing workflow system
# This creates a test workflow that will intentionally fail, triggering the auto-healing system

set -e

echo "🧪 Auto-Healing Workflow Test"
echo "=============================="
echo ""
echo "This script will help you test the auto-healing system by:"
echo "1. Showing how to manually trigger a test"
echo "2. Providing commands to check if the system is working"
echo ""

# Check if gh CLI is available
if ! command -v gh &> /dev/null; then
    echo "❌ ERROR: GitHub CLI (gh) is not installed"
    echo "   Install from: https://cli.github.com/"
    exit 1
fi

echo "✅ GitHub CLI is available"
echo ""

# Get list of recent failed workflows
echo "📊 Recent failed workflows:"
echo "----------------------------"
gh run list --status=failure --limit=5 --json workflowName,conclusion,createdAt,databaseId \
    --jq '.[] | "\(.databaseId)\t\(.workflowName)\t\(.createdAt)"' 2>/dev/null || echo "No recent failures"
echo ""

# Check if auto-healing has run recently
echo "🔍 Recent auto-healing runs:"
echo "----------------------------"
gh run list --workflow="Copilot Agent Auto-Healing" --limit=5 \
    --json conclusion,createdAt,event --jq '.[] | "\(.createdAt)\t\(.conclusion)\t\(.event)"' 2>/dev/null || echo "No recent runs"
echo ""

# Show how to manually trigger
echo "📝 How to test manually:"
echo "----------------------------"
echo ""
echo "Method 1: Trigger via CLI"
echo "  gh workflow run copilot-agent-autofix.yml \\"
echo "    --field workflow_name=\"Docker Build and Test\""
echo ""
echo "Method 2: Trigger via UI"
echo "  1. Go to Actions tab: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions"
echo "  2. Select 'Copilot Agent Auto-Healing'"
echo "  3. Click 'Run workflow'"
echo "  4. Enter a workflow name or run ID"
echo ""
echo "Method 3: Wait for a real failure"
echo "  The system will automatically trigger when any monitored workflow fails"
echo ""

# Offer to trigger a manual test
echo "❓ Would you like to manually trigger a test? (y/n)"
read -r response

if [ "$response" = "y" ] || [ "$response" = "Y" ]; then
    echo ""
    echo "📋 Available workflows to test with:"
    python3 .github/scripts/generate_workflow_list.py list | nl
    echo ""
    echo "Enter a workflow name (or press Enter to skip):"
    read -r workflow_name
    
    if [ -n "$workflow_name" ]; then
        echo ""
        echo "🚀 Triggering auto-healing workflow for: $workflow_name"
        if gh workflow run copilot-agent-autofix.yml --field workflow_name="$workflow_name"; then
            echo "✅ Workflow triggered successfully!"
            echo ""
            echo "🔍 Monitor the workflow:"
            echo "   gh run list --workflow=\"Copilot Agent Auto-Healing\" --limit=1"
            echo ""
            echo "   Or visit: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions"
        else
            echo "❌ Failed to trigger workflow"
            exit 1
        fi
    fi
fi

echo ""
echo "✅ Test complete!"
echo ""
echo "📚 Next steps:"
echo "  - Monitor the Actions tab for auto-healing runs"
echo "  - Look for new issues with label 'workflow-failure'"
echo "  - Check for PRs with labels 'automated-fix', 'auto-healing'"
echo "  - See .github/workflows/FIX_SUMMARY.md for more details"
