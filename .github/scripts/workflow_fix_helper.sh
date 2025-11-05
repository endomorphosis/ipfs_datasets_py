#!/bin/bash
# Quick Reference for GitHub Actions Worker Fixes

set -e

echo "=========================================="
echo "GitHub Actions Worker Fix - Quick Reference"
echo "=========================================="
echo ""

# Function to show usage
show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  health-check     - Check workflow health status"
    echo "  fix-workflows    - Fix missing GH_TOKEN in workflows"
    echo "  copilot-status   - Check Copilot CLI status"
    echo "  copilot-install  - Install gh-copilot extension"
    echo "  analyze <file>   - Analyze a specific workflow with Copilot"
    echo "  help             - Show this help message"
    echo ""
}

# Parse command
COMMAND="${1:-help}"

case "$COMMAND" in
    health-check)
        echo "🔍 Running workflow health check..."
        python .github/scripts/enhance_workflow_copilot_integration.py
        ;;
    
    fix-workflows)
        echo "🔧 Fixing workflow issues..."
        echo ""
        echo "Running in dry-run mode first..."
        python .github/scripts/minimal_workflow_fixer.py --dry-run
        echo ""
        read -p "Apply these fixes? (y/N) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python .github/scripts/minimal_workflow_fixer.py
            echo "✅ Fixes applied!"
        else
            echo "❌ Cancelled"
        fi
        ;;
    
    copilot-status)
        echo "🤖 Checking Copilot CLI status..."
        if command -v gh &> /dev/null; then
            echo "✅ GitHub CLI installed: $(gh --version | head -1)"
            if gh extension list 2>&1 | grep -q copilot; then
                echo "✅ Copilot extension installed"
            else
                echo "❌ Copilot extension not installed"
                echo "   Install with: gh extension install github/gh-copilot"
            fi
        else
            echo "❌ GitHub CLI not installed"
        fi
        ;;
    
    copilot-install)
        echo "📦 Installing gh-copilot extension..."
        if ! command -v gh &> /dev/null; then
            echo "❌ GitHub CLI not installed. Install it first."
            exit 1
        fi
        gh extension install github/gh-copilot
        echo "✅ Copilot extension installed!"
        ;;
    
    analyze)
        WORKFLOW_FILE="${2}"
        if [ -z "$WORKFLOW_FILE" ]; then
            echo "❌ Please specify a workflow file"
            echo "Usage: $0 analyze <workflow-file>"
            exit 1
        fi
        echo "🔍 Analyzing workflow: $WORKFLOW_FILE"
        python .github/scripts/copilot_workflow_helper.py analyze "$WORKFLOW_FILE"
        ;;
    
    help)
        show_usage
        ;;
    
    *)
        echo "❌ Unknown command: $COMMAND"
        echo ""
        show_usage
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo "For more information, see:"
echo "  .github/GITHUB_ACTIONS_FIX_GUIDE.md"
echo "=========================================="
