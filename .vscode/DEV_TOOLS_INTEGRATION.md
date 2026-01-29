# VSCode Dev Tools Integration

## Overview

The development tools from `scripts/dev_tools/` have been integrated into VSCode tasks for easy access and execution.

## Available Dev Tools Tasks

All dev tools are accessible through VSCode's **Terminal > Run Task** menu (or `Ctrl+Shift+P` → "Tasks: Run Task").

### 1. Dev Tools: Check Python Compilation
**Purpose:** Validates that all Python files in a directory compile without syntax errors.

**Usage:**
- Runs: `scripts/dev_tools/compile_checker.py`
- Prompts for: Directory path to check
- Default: `ipfs_datasets_py`

**Example Output:**
```
Total files checked: 150
Successful compilations: 150
Failed compilations: 0
Success rate: 100%
```

### 2. Dev Tools: Check Imports
**Purpose:** Validates all Python imports in a directory are correct and resolvable.

**Usage:**
- Runs: `scripts/dev_tools/comprehensive_import_checker.py`
- Prompts for: Directory path to check
- Default: `ipfs_datasets_py`

**Use Case:** Find missing imports or circular dependencies before committing code.

### 3. Dev Tools: Python Code Quality Check
**Purpose:** Performs comprehensive code quality checks including style, complexity, and best practices.

**Usage:**
- Runs: `scripts/dev_tools/comprehensive_python_checker.py`
- Prompts for: Directory path to check
- Default: `ipfs_datasets_py`

**Use Case:** Pre-commit code quality validation.

### 4. Dev Tools: Audit Docstrings
**Purpose:** Analyzes docstring quality and completeness across the codebase.

**Usage:**
- Runs: `scripts/dev_tools/docstring_audit.py`
- Prompts for: Directory path to audit
- Default: `ipfs_datasets_py`
- Output: `docstring_report.json`

**Use Case:** Ensure proper documentation standards are maintained.

### 5. Dev Tools: Find Documentation
**Purpose:** Discovers and catalogs all TODO.md and CHANGELOG.md files with timestamps.

**Usage:**
- Runs: `scripts/dev_tools/find_documentation.py`
- Prompts for: Directory to search
- Default: `.` (entire workspace)
- Output: JSON format

**Use Case:** Track documentation across the project structure.

### 6. Dev Tools: Analyze Stub Coverage
**Purpose:** Analyzes stub file coverage and identifies missing implementations.

**Usage:**
- Runs: `scripts/dev_tools/stub_coverage_analysis.py`
- Prompts for: Directory path to analyze
- Default: `ipfs_datasets_py`

**Use Case:** Find incomplete stub implementations.

### 7. Dev Tools: Split TODO List
**Purpose:** Splits master TODO list into separate TODO.md files per subdirectory.

**Usage:**
- Runs: `scripts/dev_tools/split_todo_script.py`
- No prompts (uses defaults)

**Use Case:** Organize massive TODO lists by worker assignments.

### 8. Dev Tools: Update TODO Workers
**Purpose:** Updates existing TODO.md files with worker assignments.

**Usage:**
- Runs: `scripts/dev_tools/update_todo_workers.py`
- No prompts (uses defaults)

**Use Case:** Add worker assignments to TODO files after splitting.

## How to Use

### Method 1: Command Palette
1. Press `Ctrl+Shift+P` (Windows/Linux) or `Cmd+Shift+P` (Mac)
2. Type "Tasks: Run Task"
3. Select one of the "Dev Tools:" tasks
4. Enter any prompted parameters (directory paths, etc.)

### Method 2: Terminal Menu
1. Go to **Terminal > Run Task**
2. Select one of the "Dev Tools:" tasks
3. Enter any prompted parameters

### Method 3: Keyboard Shortcut
1. Press `Ctrl+Shift+B` (default build task shortcut)
2. Select from available tasks

## Task Configuration

Tasks are defined in `.vscode/tasks.json` and include:

- **Group:** Most dev tools are in the "test" group for easy filtering
- **Presentation:** Tasks open in a new panel with always-visible output
- **Problem Matchers:** None (pure informational output)
- **Working Directory:** Always set to workspace root

## Input Variables

The following input variables are used across dev tools tasks:

| Variable | Description | Default |
|----------|-------------|---------|
| `compileCheckPath` | Path for compilation checks | `ipfs_datasets_py` |
| `importCheckPath` | Directory for import validation | `ipfs_datasets_py` |
| `pythonCheckPath` | Directory for code quality checks | `ipfs_datasets_py` |
| `docstringAuditPath` | Directory for docstring audit | `ipfs_datasets_py` |
| `findDocsPath` | Directory to find documentation | `.` |
| `stubAnalysisPath` | Directory for stub analysis | `ipfs_datasets_py` |

## Integration with CI/CD

These dev tools are also used in GitHub Actions workflows:

- **documentation-maintenance.yml:** Uses `find_documentation.py` and `docstring_audit.py`
- Can be run locally via VSCode tasks before pushing to verify CI will pass

## Benefits

1. **Easy Access:** No need to remember command-line syntax
2. **Consistent Execution:** Same commands as CI/CD pipelines
3. **Interactive:** VSCode prompts for parameters
4. **Integrated Output:** Results appear in VSCode terminal
5. **Discoverable:** All tools visible in Task Runner menu

## Troubleshooting

### Task Not Found
If you don't see the dev tools tasks:
1. Reload VSCode window (`Ctrl+Shift+P` → "Reload Window")
2. Verify `.vscode/tasks.json` exists
3. Check JSON is valid: `python -m json.tool .vscode/tasks.json`

### Python Not Found
Tasks use `python` command. Ensure:
1. Python 3 is installed and in PATH
2. Virtual environment is activated if required
3. Dependencies are installed: `pip install -r requirements.txt`

### Permission Denied
On Unix systems, ensure scripts are executable:
```bash
chmod +x scripts/dev_tools/*.py
```

## Customization

To modify a task:
1. Open `.vscode/tasks.json`
2. Find the task by label
3. Modify `args`, `options`, or other properties
4. Save and reload window

To add a new dev tool task:
1. Add your script to `scripts/dev_tools/`
2. Add a new task object to `tasks` array in `.vscode/tasks.json`
3. Follow the existing pattern for consistency

## Related Documentation

- [scripts/dev_tools/README.md](../scripts/dev_tools/README.md) - Dev tools documentation
- [.github/workflows/README-documentation-maintenance.md](../.github/workflows/README-documentation-maintenance.md) - CI/CD usage
- [docs/CLAUDE.md](../docs/CLAUDE.md) - Tool standards and guidelines
