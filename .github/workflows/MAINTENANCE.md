# Workflow Auto-Healing System Maintenance

## Overview

This document explains how to maintain the auto-healing workflow system, particularly the workflow trigger list that enables automatic detection and fixing of failed workflows.

## The Problem

GitHub Actions **does not support wildcards** in `workflow_run` triggers. This means you cannot use:

```yaml
on:
  workflow_run:
    workflows: ["*"]  # ❌ This doesn't work!
```

Instead, you must explicitly list all workflow names:

```yaml
on:
  workflow_run:
    workflows:
      - "Workflow Name 1"
      - "Workflow Name 2"
      # ... etc
```

## The Solution

We've created automated scripts to manage this workflow list:

### 1. Generate Workflow List

`generate_workflow_list.py` - Scans the `.github/workflows/` directory and extracts all workflow names (excluding auto-fix workflows).

**Usage:**
```bash
# Output as YAML (for workflow files)
python3 .github/scripts/generate_workflow_list.py yaml

# Output as JSON
python3 .github/scripts/generate_workflow_list.py json

# Output as plain list
python3 .github/scripts/generate_workflow_list.py list

# Get count
python3 .github/scripts/generate_workflow_list.py count
```

### 2. Update Auto-Fix Workflow

`update_autofix_workflow_list.py` - Automatically updates the `copilot-agent-autofix.yml` file with the current list of workflows.

**Usage:**
```bash
python3 .github/scripts/update_autofix_workflow_list.py
```

This script:
- Scans all workflows in `.github/workflows/`
- Excludes auto-fix related workflows (to prevent infinite loops)
- Updates the `workflow_run.workflows` list in `copilot-agent-autofix.yml`
- Preserves all other workflow configuration

## When to Run the Update Script

Run the update script whenever you:
- ✅ Add a new workflow file
- ✅ Rename an existing workflow (change the `name:` field)
- ✅ Delete a workflow file
- ✅ Notice the auto-healing system is not triggering for a new workflow

## Manual Verification

After updating, verify the changes:

1. **Check YAML syntax:**
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('.github/workflows/copilot-agent-autofix.yml'))"
   ```

2. **Review the workflow list:**
   ```bash
   grep -A 20 "workflows:" .github/workflows/copilot-agent-autofix.yml
   ```

3. **Test with a failing workflow:**
   - Trigger a workflow that will fail
   - Watch for the auto-healing workflow to trigger
   - Check the Actions tab for "Copilot Agent Auto-Healing" run

## Troubleshooting

### Auto-healing workflow not triggering

**Symptoms:** A workflow fails but no auto-healing PR is created.

**Possible causes:**
1. The workflow name is not in the trigger list
2. The workflow is in the `excluded_workflows` list in config
3. The workflow name contains "Auto-Healing" or "Auto-Fix"
4. The workflow didn't actually fail (check conclusion)

**Solution:**
```bash
# 1. Check if workflow is in the list
python3 .github/scripts/generate_workflow_list.py list | grep "Your Workflow Name"

# 2. Update the trigger list
python3 .github/scripts/update_autofix_workflow_list.py

# 3. Check the config
cat .github/workflows/workflow-auto-fix-config.yml | grep -A 10 excluded_workflows
```

### Infinite loop detection

The system prevents infinite loops by:
- Excluding workflows with "Auto-Healing" or "Auto-Fix" in the name
- Checking for existing fix PRs before creating new ones
- Using a rate limiter (max PRs per day)

### Duplicate workflow names

If you have duplicate workflow names in the list:
```bash
python3 .github/scripts/generate_workflow_list.py list | sort | uniq -d
```

This indicates multiple workflow files have the same `name:` field. Each workflow should have a unique name.

## Best Practices

1. **Use descriptive workflow names** - Makes it easier to track which workflows are covered
2. **Run the update script after workflow changes** - Keep the trigger list in sync
3. **Test new workflows** - Intentionally fail them once to verify auto-healing works
4. **Monitor auto-healing metrics** - Use the metrics script to track system effectiveness
   ```bash
   python3 .github/scripts/analyze_autohealing_metrics.py
   ```

## Integration with CI/CD

You can add a CI check to ensure the workflow list is up-to-date:

```yaml
- name: Verify auto-healing workflow list is current
  run: |
    # Generate expected list
    python3 .github/scripts/generate_workflow_list.py yaml > /tmp/expected.txt
    
    # Extract current list from workflow file
    python3 -c "
    import yaml
    with open('.github/workflows/copilot-agent-autofix.yml') as f:
        data = yaml.safe_load(f)
        workflows = data['on']['workflow_run']['workflows']
        for w in sorted(workflows):
            print(f'      - \"{w}\"')
    " > /tmp/current.txt
    
    # Compare
    if ! diff /tmp/expected.txt /tmp/current.txt; then
        echo "❌ Workflow list is out of date!"
        echo "Run: python3 .github/scripts/update_autofix_workflow_list.py"
        exit 1
    fi
    echo "✅ Workflow list is up to date"
```

## Related Files

- `.github/workflows/copilot-agent-autofix.yml` - Main auto-healing workflow
- `.github/workflows/workflow-auto-fix-config.yml` - Configuration
- `.github/scripts/generate_workflow_list.py` - List generator
- `.github/scripts/update_autofix_workflow_list.py` - Automatic updater
- `.github/scripts/analyze_workflow_failure.py` - Failure analyzer
- `.github/scripts/generate_workflow_fix.py` - Fix generator
- `.github/scripts/apply_workflow_fix.py` - Fix applier

## Additional Resources

- [GitHub Actions workflow_run documentation](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_run)
- [Auto-Healing System README](.github/workflows/README-copilot-autohealing.md)
- [Quick Start Guide](.github/workflows/QUICKSTART-copilot-autohealing.md)
