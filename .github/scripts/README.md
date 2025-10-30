# GitHub Actions Auto-Fix Scripts

This directory contains Python scripts used by the Workflow Auto-Fix System to automatically detect, analyze, and fix failed GitHub Actions workflows.

## 🚀 How Auto-Healing Works (Updated 2025-10-30)

The auto-healing workflow now properly integrates with **GitHub Copilot Coding Agent**:

1. **Detection**: `copilot-agent-autofix.yml` is triggered when a workflow fails
2. **Analysis**: Scripts analyze logs and identify the root cause
3. **Issue Creation**: A detailed issue is created with:
   - Error analysis
   - Failure logs
   - Fix recommendations
   - Proposed changes
4. **Copilot Assignment**: The issue is assigned to `Copilot`
   - ⚡ **This triggers the GitHub Copilot Coding Agent automatically**
5. **Automatic Fix**: Copilot Coding Agent (asynchronously):
   - Analyzes the issue and repository context
   - Creates a new branch
   - Implements the fix
   - Opens a draft PR for review

### Key Change
Previously, the workflow manually created PRs and mentioned `@copilot` in comments. Now it properly triggers the Copilot Coding Agent by **assigning the issue to Copilot**, which is the recommended method per GitHub's documentation.

## Scripts

### 1. `analyze_workflow_failure.py`

**Purpose**: Analyzes failed workflow runs to identify root causes.

**Usage**:
```bash
python analyze_workflow_failure.py \
  --run-id <workflow_run_id> \
  --workflow-name "Workflow Name" \
  --logs-dir /path/to/logs \
  --output /path/to/analysis.json
```

**Features**:
- Parses workflow logs for error patterns
- Identifies common failure types
- Provides confidence scores
- Extracts affected files
- Generates recommendations

**Supported Error Types**:
- Dependency errors (missing packages)
- Syntax errors
- Test failures
- Timeouts
- Permission errors
- Network errors
- Docker errors
- Resource exhaustion
- Missing environment variables

### 2. `generate_workflow_fix.py`

**Purpose**: Generates fix proposals based on failure analysis.

**Usage**:
```bash
python generate_workflow_fix.py \
  --analysis /path/to/analysis.json \
  --workflow-name "Workflow Name" \
  --output /path/to/proposal.json
```

**Features**:
- Creates fix proposals with specific changes
- Generates PR title and description
- Assigns appropriate labels
- Suggests reviewers
- Formats changes as YAML/code snippets

**Output**: JSON file containing:
- Branch name
- PR title and description
- List of fixes to apply
- Labels and metadata
- Confidence scores

### 3. `apply_workflow_fix.py`

**Purpose**: Applies the fixes from the proposal to repository files.

**Usage**:
```bash
python apply_workflow_fix.py \
  --proposal /path/to/proposal.json \
  --repo-path /path/to/repo
```

**Features**:
- Safely modifies YAML workflow files
- Updates requirements.txt
- Adds/modifies configuration
- Creates review notes for complex fixes
- Tracks all applied changes

**Actions**:
- `add_install_step`: Adds pip install to workflow
- `add_line`: Adds line to file
- `add_timeout`: Adds timeout configuration
- `add_permissions`: Adds permissions block
- `add_retry_action`: Adds retry logic
- `add_docker_setup`: Adds Docker setup steps
- `change_runner`: Changes runner type
- `add_env`: Adds environment variables

### 4. `test_browser.py`, `test_performance.py`, etc.

**Purpose**: Testing scripts for GitHub Actions workflows.

These are pre-existing test scripts that validate different aspects of the workflow system.

## Dependencies

### Required Python Packages

```bash
pip install PyYAML requests
```

### System Requirements

- Python 3.10+
- git
- GitHub CLI (gh)

## Testing

### Unit Tests

Test individual scripts:

```bash
# Create test data
mkdir -p /tmp/test_logs
echo "ERROR: ModuleNotFoundError: No module named 'pytest'" > /tmp/test_logs/job_1.log

# Test analyzer
python analyze_workflow_failure.py \
  --run-id 12345 \
  --workflow-name "Test" \
  --logs-dir /tmp/test_logs \
  --output /tmp/analysis.json

# Verify output
cat /tmp/analysis.json
```

### Integration Tests

Test full workflow:

```bash
# Run full pipeline
./test_autofix_pipeline.sh
```

## Error Patterns

The analyzer uses regex patterns to identify errors. To add new patterns:

1. Edit `analyze_workflow_failure.py`
2. Add pattern to `FAILURE_PATTERNS` dictionary:

```python
'new_error_type': {
    'patterns': [
        r'your regex pattern',
    ],
    'error_type': 'Display Name',
    'fix_type': 'fix_action',
    'confidence': 85,
}
```

3. Add corresponding fix generator in `generate_workflow_fix.py`
4. Add fix applier in `apply_workflow_fix.py`

## Common Issues

### Issue: Script fails with import error

**Solution**: Install required packages:
```bash
pip install PyYAML requests
```

### Issue: Cannot parse YAML

**Cause**: Invalid YAML syntax in workflow file

**Solution**: 
- Use YAML linter to validate
- Check for tabs vs spaces
- Verify indentation

### Issue: No patterns matched

**Cause**: Unknown error pattern

**Solution**:
- Review logs manually
- Add new pattern to analyzer
- Increase context lines

### Issue: Fix not applied

**Cause**: File not found or permission error

**Solution**:
- Check file paths
- Verify repository structure
- Check file permissions

## Development

### Adding New Fix Types

1. **Identify Pattern**: Study failed workflow logs
2. **Add Pattern**: Add regex to analyzer
3. **Create Generator**: Add fix generation logic
4. **Implement Applier**: Add fix application logic
5. **Test**: Create test case
6. **Document**: Update this README

### Code Style

- Follow PEP 8
- Use type hints
- Add docstrings
- Keep functions focused
- Handle errors gracefully

### Testing New Patterns

```python
import re

pattern = r'your regex here'
test_log = "ERROR: your error message"

match = re.search(pattern, test_log, re.IGNORECASE)
if match:
    print(f"Matched: {match.group(0)}")
    print(f"Groups: {match.groups()}")
```

## Debugging

### Enable Verbose Logging

Add debug prints:

```python
import sys
print(f"DEBUG: Processing {file}", file=sys.stderr)
```

### Save Intermediate Results

```python
import json

# Save for inspection
with open('/tmp/debug_data.json', 'w') as f:
    json.dump(data, f, indent=2)
```

### Test with Known Failures

Create test logs with known error patterns:

```bash
# Create test log
cat > /tmp/test.log << 'EOF'
ERROR: ModuleNotFoundError: No module named 'pytest-asyncio'
  File "test_async.py", line 5
    import pytest_asyncio
EOF

# Test analyzer
python analyze_workflow_failure.py \
  --run-id test \
  --workflow-name "Test" \
  --logs-dir /tmp \
  --output /tmp/test_analysis.json

# Check results
jq . /tmp/test_analysis.json
```

## Architecture

```
Workflow Failure
      ↓
analyze_workflow_failure.py
      ├─ Read logs
      ├─ Extract errors
      ├─ Match patterns
      ├─ Determine root cause
      └─ Generate recommendations
      ↓
analysis.json
      ↓
generate_workflow_fix.py
      ├─ Parse analysis
      ├─ Generate fixes
      ├─ Create PR content
      └─ Format changes
      ↓
proposal.json
      ↓
apply_workflow_fix.py
      ├─ Parse proposal
      ├─ Modify files
      ├─ Update YAML
      └─ Create review notes
      ↓
Repository Changes
```

## Contributing

To contribute:

1. Fork the repository
2. Create feature branch
3. Add your changes
4. Test thoroughly
5. Submit pull request

## License

Same as parent repository.

## Support

For issues or questions:
- Check workflow logs
- Review documentation
- Create GitHub issue
- Tag maintainers

## See Also

- [Workflow Auto-Fix Documentation](README-workflow-auto-fix.md)
- [GitHub Actions Documentation](https://docs.github.com/actions)
- [PyYAML Documentation](https://pyyaml.org/)
