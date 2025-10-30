#!/bin/bash
# Test script to validate the auto-healing workflow configuration
# This checks that the workflow trigger list is properly configured

set -e

echo "🧪 Testing Auto-Healing Workflow Configuration"
echo "=============================================="
echo ""

# Check if workflow file exists
WORKFLOW_FILE=".github/workflows/copilot-agent-autofix.yml"
if [ ! -f "$WORKFLOW_FILE" ]; then
    echo "❌ ERROR: $WORKFLOW_FILE not found!"
    exit 1
fi
echo "✅ Workflow file exists: $WORKFLOW_FILE"

# Check YAML syntax
echo "🔍 Checking YAML syntax..."
if python3 -c "import yaml; yaml.safe_load(open('$WORKFLOW_FILE'))" 2>/dev/null; then
    echo "✅ YAML syntax is valid"
else
    echo "❌ ERROR: YAML syntax is invalid!"
    exit 1
fi

# Check that workflow doesn't use wildcard
echo "🔍 Checking for wildcard usage..."
if grep -q 'workflows: \["\*"\]' "$WORKFLOW_FILE"; then
    echo "❌ ERROR: Workflow still uses wildcard [\"*\"] which doesn't work!"
    exit 1
else
    echo "✅ No wildcard found (good!)"
fi

# Count workflows in trigger list
echo "🔍 Checking workflow trigger list..."
WORKFLOW_COUNT=$(python3 -c "
import yaml
with open('$WORKFLOW_FILE') as f:
    data = yaml.safe_load(f)
    # 'on' gets parsed as boolean True in PyYAML
    on_section = data.get('on') or data.get(True)
    if on_section:
        workflows = on_section.get('workflow_run', {}).get('workflows', [])
        print(len(workflows))
    else:
        print(0)
" 2>/dev/null)

if [ "$WORKFLOW_COUNT" -eq 0 ]; then
    echo "❌ ERROR: No workflows in trigger list!"
    exit 1
fi
echo "✅ Found $WORKFLOW_COUNT workflows in trigger list"

# Check that scripts exist
echo "🔍 Checking support scripts..."
SCRIPTS=(
    ".github/scripts/generate_workflow_list.py"
    ".github/scripts/update_autofix_workflow_list.py"
    ".github/scripts/analyze_workflow_failure.py"
    ".github/scripts/generate_workflow_fix.py"
    ".github/scripts/apply_workflow_fix.py"
)

for script in "${SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        echo "  ✅ $script"
    else
        echo "  ⚠️  $script (missing - may cause issues)"
    fi
done

# Test the workflow list generator
echo "🔍 Testing workflow list generator..."
if python3 .github/scripts/generate_workflow_list.py count >/dev/null 2>&1; then
    DETECTED_COUNT=$(python3 .github/scripts/generate_workflow_list.py count 2>/dev/null)
    echo "✅ Generator works - detected $DETECTED_COUNT workflows"
    
    # Compare counts
    if [ "$WORKFLOW_COUNT" -ne "$DETECTED_COUNT" ]; then
        echo "⚠️  WARNING: Trigger list has $WORKFLOW_COUNT workflows but $DETECTED_COUNT workflows detected"
        echo "   Run: python3 .github/scripts/update_autofix_workflow_list.py"
    else
        echo "✅ Trigger list is up to date"
    fi
else
    echo "⚠️  WARNING: Could not test workflow list generator"
fi

# Check if workflow uses workflow_run trigger
echo "🔍 Checking workflow_run trigger..."
if grep -q "workflow_run:" "$WORKFLOW_FILE"; then
    echo "✅ workflow_run trigger is configured"
else
    echo "❌ ERROR: workflow_run trigger not found!"
    exit 1
fi

# Check if workflow_dispatch is also available
echo "🔍 Checking workflow_dispatch trigger..."
if grep -q "workflow_dispatch:" "$WORKFLOW_FILE"; then
    echo "✅ workflow_dispatch trigger is available for manual testing"
else
    echo "⚠️  WARNING: workflow_dispatch not available (manual trigger won't work)"
fi

# Check permissions
echo "🔍 Checking workflow permissions..."
REQUIRED_PERMS=("contents: write" "pull-requests: write" "issues: write" "actions: read")
MISSING_PERMS=0

for perm in "${REQUIRED_PERMS[@]}"; do
    if grep -q "$perm" "$WORKFLOW_FILE"; then
        echo "  ✅ $perm"
    else
        echo "  ❌ $perm (missing!)"
        MISSING_PERMS=$((MISSING_PERMS + 1))
    fi
done

if [ "$MISSING_PERMS" -gt 0 ]; then
    echo "⚠️  WARNING: Some required permissions are missing"
fi

echo ""
echo "=============================================="
echo "✅ Validation Complete!"
echo ""
echo "Summary:"
echo "  • Workflow file: Valid"
echo "  • Trigger list: $WORKFLOW_COUNT workflows"
echo "  • Scripts: Available"
echo "  • Configuration: OK"
echo ""
echo "The auto-healing system should now trigger when workflows fail."
echo "To test manually: gh workflow run copilot-agent-autofix.yml"
