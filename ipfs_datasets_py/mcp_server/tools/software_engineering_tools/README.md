# Software Engineering Tools for MCP Dashboard

This directory contains comprehensive tools for software engineering, DevOps, and MLOps workflows in the MCP server dashboard.

## Overview

The software engineering tools provide functionality for:
- **Repository Analysis**: GitHub/GitLab repository scraping and health analysis
- **CI/CD Integration**: GitHub Actions workflow analysis and log parsing
- **Log Analysis**: Systemd and Kubernetes log parsing and pattern detection
- **Dependency Management**: Dependency chain analysis and cycle detection
- **Workflow Orchestration**: DAG-based workflow planning with speculative execution
- **Resource Prediction**: ML-based GPU provisioning prediction
- **Error Detection**: Pattern matching and auto-healing coordination
- **Theorem Validation**: Temporal deontic logic for software engineering rules

## Tools

### 1. GitHub Repository Scraper (`github_repository_scraper.py`)

Scrapes and analyzes GitHub repositories including metadata, PRs, issues, workflows, and commits.

**Key Functions:**
- `scrape_github_repository()`: Extract comprehensive repository data
- `analyze_repository_health()`: Calculate repository health scores

**Example:**
```python
result = scrape_github_repository(
    repository_url="https://github.com/pytorch/pytorch",
    include_prs=True,
    max_items=100
)
print(f"Repository: {result['repository']['name']}")
print(f"Stars: {result['repository']['stars']}")
print(f"PRs: {len(result['pull_requests'])}")
```

### 2. GitHub Actions Analyzer (`github_actions_analyzer.py`)

Analyzes GitHub Actions workflows, runs, and logs for CI/CD insights.

**Key Functions:**
- `analyze_github_actions()`: Analyze workflow performance and patterns
- `parse_workflow_logs()`: Extract errors and warnings from logs

**Example:**
```python
analysis = analyze_github_actions(
    repository_url="https://github.com/pytorch/pytorch",
    max_runs=100
)
print(f"Success rate: {analysis['success_rate']}%")
print(f"Average duration: {analysis['average_duration']}s")
```

### 3. Systemd Log Parser (`systemd_log_parser.py`)

Parses and analyzes systemd journal logs for service health monitoring.

**Key Functions:**
- `parse_systemd_logs()`: Parse systemd logs with filtering
- `analyze_service_health()`: Calculate service health scores

**Example:**
```python
logs = parse_systemd_logs(
    log_content=journal_output,
    service_filter="nginx"
)
health = analyze_service_health(logs, "nginx")
print(f"Health score: {health['health_score']}")
```

### 4. Kubernetes Log Analyzer (`kubernetes_log_analyzer.py`)

Parses and analyzes Kubernetes cluster logs for pod and deployment monitoring.

**Key Functions:**
- `parse_kubernetes_logs()`: Parse K8s logs with namespace/pod filtering
- `analyze_pod_health()`: Calculate pod health scores

**Example:**
```python
logs = parse_kubernetes_logs(
    log_content=kubectl_logs,
    namespace_filter="production"
)
health = analyze_pod_health(logs, "my-app-pod")
print(f"Pod health: {health['health_status']}")
```

### 5. Dependency Chain Analyzer (`dependency_chain_analyzer.py`)

Analyzes dependency chains to detect cycles and calculate depths.

**Key Functions:**
- `analyze_dependency_chain()`: Detect cycles and analyze structure
- `parse_package_json_dependencies()`: Parse package.json
- `suggest_dependency_improvements()`: Recommend improvements

**Example:**
```python
deps = {"A": ["B"], "B": ["C"], "C": ["A"]}
analysis = analyze_dependency_chain(deps)
print(f"Cycles found: {len(analysis['cycles'])}")
```

### 6. DAG Workflow Planner (`dag_workflow_planner.py`)

Creates and analyzes DAG-based workflows with speculative execution planning.

**Key Functions:**
- `create_workflow_dag()`: Create DAG from task list
- `plan_speculative_execution()`: Plan resource provisioning (dagseq2dagseq)

**Example:**
```python
tasks = [
    {"id": "build", "dependencies": [], "estimated_duration": 300},
    {"id": "test", "dependencies": ["build"], "estimated_duration": 600}
]
dag = create_workflow_dag(tasks)
plan = plan_speculative_execution(dag, {"cpu": 16, "gpu": 4})
print(f"GPU schedule: {plan['gpu_provisioning_schedule']}")
```

### 7. GPU Provisioning Predictor (`gpu_provisioning_predictor.py`)

Predicts GPU resource needs based on workflow history and call stack analysis.

**Key Functions:**
- `predict_gpu_needs()`: Predict future GPU requirements
- `analyze_resource_utilization()`: Analyze historical usage patterns

**Example:**
```python
prediction = predict_gpu_needs(
    workflow_history=past_runs,
    current_call_stack=["preprocess", "train"],
    look_ahead_steps=5
)
print(f"Predicted GPUs: {prediction['predicted_gpu_count']}")
```

### 8. Error Pattern Detector (`error_pattern_detector.py`)

Detects common error patterns in logs and suggests fixes.

**Key Functions:**
- `detect_error_patterns()`: Identify recurring error patterns
- `suggest_fixes()`: Provide fix recommendations

**Example:**
```python
patterns = detect_error_patterns(error_logs)
for pattern in patterns['most_common']:
    fixes = suggest_fixes(pattern['pattern'])
    print(f"{pattern['pattern']}: {fixes['fixes'][0]['action']}")
```

### 9. Auto-Healing Coordinator (`auto_healing_coordinator.py`)

Coordinates auto-healing workflows based on detected errors.

**Key Functions:**
- `coordinate_auto_healing()`: Plan and execute healing actions
- `monitor_healing_effectiveness()`: Track healing success rates

**Example:**
```python
error_report = detect_error_patterns(logs)
healing = coordinate_auto_healing(error_report, dry_run=True)
print(f"Planned actions: {len(healing['healing_actions'])}")
```

### 10. Software Theorems (`software_theorems.py`)

Defines and validates software engineering rules using temporal deontic logic.

**Key Functions:**
- `list_software_theorems()`: List available theorems
- `validate_against_theorem()`: Validate situations against theorems
- `apply_theorem_actions()`: Execute recommended actions

**Available Theorems:**
- CI Failure Notification: Alert team after 3 CI failures
- Deployment Rollback: Auto-rollback on high error rates
- Code Review Requirement: Enforce reviews for large PRs
- Resource Scaling: Auto-scale on high CPU usage
- Security Scan Requirement: Block deploys without security scans
- Dependency Update: Force critical security updates
- Test Coverage: Enforce minimum coverage thresholds
- Log Retention: Archive old logs
- Incident Escalation: Escalate unresolved incidents
- GPU Provisioning: Provision GPUs based on predictions

**Example:**
```python
theorems = list_software_theorems(domain_filter="devops")
context = {"ci_failed_count": 5, "notification_sent": False}
validation = validate_against_theorem("ci_failure_notification", context)
if validation['theorem_applies']:
    print(f"Actions: {validation['recommended_actions']}")
```

## Integration with MCP Dashboard

These tools are automatically discovered and registered by the MCP server when it starts. They can be accessed through:

1. **MCP Tool Protocol**: Direct tool invocation via MCP clients
2. **REST API**: HTTP endpoints at `/api/mcp/tools/{category}/{tool_name}/execute`
3. **Dashboard UI**: Web interface at `/mcp/software`

## Usage in Dashboard

The software engineering dashboard provides:
- Repository ingestion and health monitoring
- CI/CD workflow visualization
- Log analysis and error pattern detection
- Dependency graph visualization
- Resource prediction and GPU provisioning
- Auto-healing status and coordination
- Theorem validation and enforcement

## Dependencies

Core dependencies (optional):
- `requests`: For GitHub API access
- `psutil`: For system resource monitoring
- Standard library: `json`, `logging`, `re`, `datetime`, `collections`

## Development

To add new software engineering tools:

1. Create a new Python file in this directory
2. Define functions with proper docstrings
3. Ensure functions accept and return dictionaries
4. Add error handling and logging
5. Update `__init__.py` to export the new tool

## Testing

Run tests for software engineering tools:

```bash
pytest tests/test_software_engineering_tools.py
```

## License

Part of the ipfs_datasets_py project. See main repository LICENSE file.
