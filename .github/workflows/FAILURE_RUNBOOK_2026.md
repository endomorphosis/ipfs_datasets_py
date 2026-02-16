# GitHub Actions Workflow Failure Runbook

**Date Created:** 2026-02-16  
**Last Updated:** 2026-02-16  
**Purpose:** Quick reference guide for diagnosing and resolving common workflow failures

---

## 🚨 Emergency Quick Actions

### Workflow Stuck or Hanging
```bash
# Check runner status
gh workflow view <workflow-name>

# Cancel stuck run
gh run cancel <run-id>

# View running jobs
gh run list --workflow=<workflow-name> --status=in_progress
```

### Critical Workflow Failing on Main
```bash
# Re-run failed jobs only
gh run rerun <run-id> --failed

# Re-run entire workflow
gh run rerun <run-id>

# Manually trigger workflow
gh workflow run <workflow-name>
```

---

## 📋 Common Failure Scenarios

### 1. Self-Hosted Runner Not Available

**Symptoms:**
- Workflow stuck in "Queued" state for >5 minutes
- Error: "No runners available"
- Jobs with `runs-on: [self-hosted, linux, x64]` never start

**Diagnosis:**
```bash
# Check workflow status
gh run view <run-id>

# Check runner availability (via GitHub UI)
# Settings → Actions → Runners
```

**Root Causes:**
- Runner offline (service stopped, machine reboot)
- Runner at capacity (too many concurrent jobs)
- Runner labels mismatch (workflow expects label runner doesn't have)
- Network connectivity issues

**Resolution:**

**Option 1: Restart Runner Service**
```bash
# SSH to runner machine
ssh runner-host

# Check runner status
sudo systemctl status actions.runner.*

# Restart runner
sudo systemctl restart actions.runner.*

# Verify restart
sudo systemctl status actions.runner.*
```

**Option 2: Check Runner Capacity**
```bash
# On runner machine, check active jobs
ps aux | grep Runner.Listener

# Check system resources
htop  # or top
df -h  # disk space
```

**Option 3: Cancel and Re-run**
```bash
# Cancel stuck run
gh run cancel <run-id>

# Wait 1 minute for runner to become available
sleep 60

# Re-run workflow
gh run rerun <run-id>
```

**Prevention:**
- ✅ Use runner gating (check-runner-availability template)
- ✅ Add fallback to GitHub-hosted runners
- ✅ Monitor runner health with alerts
- ✅ Set appropriate timeout-minutes (prevents indefinite queuing)

---

### 2. Docker Build Fails

**Symptoms:**
- Error: "Cannot connect to Docker daemon"
- Error: "No space left on device"
- Error: "permission denied while trying to connect to Docker daemon"

**Diagnosis:**
```bash
# Check Docker daemon status
docker info

# Check disk space
df -h

# Check Docker service
sudo systemctl status docker
```

**Root Causes:**
- Docker daemon not running
- Disk full (Docker images and layers)
- Permission issues (user not in docker group)
- Docker buildx issues

**Resolution:**

**Option 1: Docker Daemon Not Running**
```bash
# Start Docker daemon
sudo systemctl start docker

# Enable on boot
sudo systemctl enable docker

# Verify
docker info
```

**Option 2: Disk Space Full**
```bash
# Clean up Docker resources
docker system prune -af

# Remove old images
docker image prune -af

# Remove old containers
docker container prune -f

# Remove old volumes
docker volume prune -f

# Check space freed
df -h
```

**Option 3: Permission Issues**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Restart runner service (to apply group change)
sudo systemctl restart actions.runner.*
```

**Option 4: Buildx Issues**
```bash
# Remove buildx builders
docker buildx rm --all-inactive

# Create new builder
docker buildx create --use

# Verify
docker buildx ls
```

**Prevention:**
- ✅ Regular cleanup jobs (daily/weekly)
- ✅ Monitor disk usage (alert at 80%)
- ✅ Use Docker layer caching
- ✅ Set Docker prune policies

---

### 3. Copilot API Failures

**Symptoms:**
- Error: "Failed to invoke Copilot"
- 401 Unauthorized errors
- 403 Forbidden errors
- Rate limit exceeded

**Diagnosis:**
```bash
# Check GitHub token permissions
gh auth status

# View recent API calls
gh api rate_limit

# Test Copilot API access
gh copilot --version
```

**Root Causes:**
- GitHub token expired or invalid
- Insufficient token permissions
- API rate limit hit
- Copilot not enabled for repository

**Resolution:**

**Option 1: Token Issues**
```bash
# Re-authenticate
gh auth login

# Verify token has required scopes
gh auth status
# Should show: repo, workflow, write:packages

# Regenerate token if needed (GitHub UI)
# Settings → Developer settings → Personal access tokens
```

**Option 2: Rate Limit**
```bash
# Check rate limit status
gh api rate_limit

# Wait for rate limit reset
# View reset time in response

# Implement exponential backoff in workflow
```

**Option 3: Permissions**
```yaml
# Ensure workflow has correct permissions
permissions:
  contents: write
  pull-requests: write
  issues: write
  actions: read
```

**Prevention:**
- ✅ Use PAT with long expiration (1 year)
- ✅ Implement rate limit backoff
- ✅ Monitor API usage
- ✅ Cache API responses when possible

---

### 4. Test Failures

**Symptoms:**
- Tests fail intermittently
- Tests timeout
- "Address already in use" errors
- Import errors

**Diagnosis:**
```bash
# View test logs
gh run view <run-id> --log-failed

# Run tests locally
cd /home/runner/work/ipfs_datasets_py/ipfs_datasets_py
python -m pytest tests/ -v

# Check for flaky tests
pytest tests/ --count=10  # Run 10 times
```

**Root Causes:**
- Flaky tests (timing issues, race conditions)
- Resource constraints (CPU, memory, disk)
- External dependency issues (network, services)
- Port conflicts (multiple tests using same port)
- Missing dependencies

**Resolution:**

**Option 1: Re-run (Transient Failure)**
```bash
# Re-run failed jobs only
gh run rerun <run-id> --failed

# Or re-run entire workflow
gh run rerun <run-id>
```

**Option 2: Resource Constraints**
```bash
# On runner, check resources
htop  # CPU and memory
iostat  # Disk I/O
df -h  # Disk space

# Reduce parallel test execution
pytest tests/ -n auto  # Auto-detect CPUs
pytest tests/ -n 2     # Limit to 2 workers
```

**Option 3: Port Conflicts**
```bash
# Check for port in use
netstat -tulpn | grep <port>

# Kill process using port
kill -9 <pid>

# Or use random ports in tests
# Instead of: port = 8000
# Use: port = random.randint(30000, 60000)
```

**Option 4: Missing Dependencies**
```bash
# Install dependencies
pip install -e ".[test]"

# Or specific dependency
pip install <package-name>

# Verify imports
python -c "import package_name"
```

**Prevention:**
- ✅ Fix flaky tests (add proper waits, use locks)
- ✅ Add retries for network calls
- ✅ Mock external dependencies
- ✅ Increase timeout values (timeout-minutes: 30)
- ✅ Use unique ports in tests

---

### 5. Permission Denied Errors

**Symptoms:**
- Error: "Permission denied"
- 403 Forbidden
- "Resource not accessible by integration"

**Diagnosis:**
```bash
# Check workflow permissions
cat .github/workflows/<workflow-name>.yml | grep -A 5 permissions

# View run details
gh run view <run-id>
```

**Root Causes:**
- Insufficient GITHUB_TOKEN permissions
- Branch protection rules block automation
- Repository settings restrict workflows
- Organization policies

**Resolution:**

**Option 1: Workflow Permissions**
```yaml
# Add explicit permissions to workflow
permissions:
  contents: write      # For pushing commits
  pull-requests: write # For creating/updating PRs
  issues: write        # For creating/updating issues
  actions: read        # For reading workflow status
  packages: write      # For publishing packages
```

**Option 2: Branch Protection**
```bash
# Check branch protection rules
# Settings → Branches → Branch protection rules

# Options:
# - Allow GitHub Actions to bypass
# - Add workflow app to allowed actors
# - Temporarily disable protection for testing
```

**Option 3: Repository Settings**
```bash
# Check workflow permissions
# Settings → Actions → General → Workflow permissions

# Set to: "Read and write permissions"
# Enable: "Allow GitHub Actions to create and approve pull requests"
```

**Prevention:**
- ✅ Use explicit permissions in all workflows
- ✅ Document required permissions
- ✅ Test with restricted tokens
- ✅ Review branch protection settings

---

### 6. Timeout Errors

**Symptoms:**
- Job cancelled after timeout
- "The job running on runner has exceeded the maximum execution time of X minutes"

**Diagnosis:**
```bash
# Check job logs for timeout
gh run view <run-id> --log

# Check workflow for timeout settings
cat .github/workflows/<workflow-name>.yml | grep timeout-minutes
```

**Root Causes:**
- Job legitimately taking too long
- Hanging operation (network, deadlock)
- Infinite loop or retry without limit
- Missing timeout-minutes (defaults to 360 minutes)

**Resolution:**

**Option 1: Increase Timeout (if legitimate)**
```yaml
jobs:
  my-job:
    runs-on: ubuntu-latest
    timeout-minutes: 60  # Increase from default
    steps:
      # ...
```

**Option 2: Fix Hanging Operation**
```bash
# Add timeouts to commands
- name: Long running command
  run: |
    timeout 300 ./long-command.sh  # 5 minute timeout
    
# Or use command timeout
- name: With timeout
  timeout-minutes: 10
  run: |
    ./command.sh
```

**Option 3: Add Progress Output**
```bash
# Prevent timeout by showing progress
- name: Long operation
  run: |
    for i in {1..100}; do
      echo "Progress: $i%"
      ./do-work.sh
      sleep 1
    done
```

**Prevention:**
- ✅ Set appropriate timeout-minutes on all jobs
- ✅ Add timeouts to external commands
- ✅ Show progress output (prevents no-output timeout)
- ✅ Break long operations into smaller jobs

---

### 7. GitHub Actions Service Issues

**Symptoms:**
- Multiple workflows failing simultaneously
- "GitHub Actions is experiencing issues"
- Workflow runs not starting
- API errors across workflows

**Diagnosis:**
```bash
# Check GitHub status
curl https://www.githubstatus.com/api/v2/status.json

# Or visit: https://www.githubstatus.com/

# Check specific service
gh api /meta
```

**Root Causes:**
- GitHub Actions service degradation
- API rate limiting (organization-wide)
- Scheduled maintenance
- Network issues

**Resolution:**

**Option 1: Wait for Service Recovery**
```bash
# Monitor status page
# https://www.githubstatus.com/

# Subscribe to status updates
# Email/SMS/Slack notifications

# Re-run workflows after recovery
gh run rerun <run-id>
```

**Option 2: Fallback to GitHub-Hosted Runners**
```yaml
# If self-hosted runners unreachable
# Temporarily switch to GitHub-hosted
runs-on: ubuntu-latest  # Instead of self-hosted
```

**Option 3: Reduce API Usage**
```bash
# Temporarily disable non-critical workflows
# Reduce polling frequency
# Use caching to reduce API calls
```

**Prevention:**
- ✅ Monitor GitHub status proactively
- ✅ Have fallback to GitHub-hosted runners
- ✅ Implement exponential backoff
- ✅ Cache API responses

---

### 8. Artifact Upload/Download Failures

**Symptoms:**
- "Unable to upload artifact"
- "Artifact not found"
- "Failed to download artifact"

**Diagnosis:**
```bash
# List artifacts for run
gh run view <run-id> --log | grep artifact

# Check artifact retention settings
# Settings → Actions → General → Artifact retention
```

**Root Causes:**
- Artifact name conflicts
- Network issues during upload
- Artifact expired (retention period)
- Artifact too large (>10GB limit)

**Resolution:**

**Option 1: Unique Artifact Names**
```yaml
- name: Upload artifact
  uses: actions/upload-artifact@v4
  with:
    name: test-results-${{ github.run_id }}  # Unique name
    path: test-results/
```

**Option 2: Retry Upload**
```yaml
- name: Upload artifact with retry
  uses: nick-invision/retry@v2
  with:
    timeout_minutes: 5
    max_attempts: 3
    command: |
      gh actions upload-artifact test-results.zip
```

**Option 3: Check Artifact Size**
```bash
# Check size before upload
du -sh test-results/

# If too large, compress
tar -czf results.tar.gz test-results/
```

**Prevention:**
- ✅ Use unique artifact names (include run ID)
- ✅ Compress large artifacts
- ✅ Set appropriate retention period
- ✅ Add retry logic for uploads

---

## 🔍 Diagnostic Commands Reference

### Workflow Status
```bash
# List recent workflow runs
gh run list --workflow=<workflow-name> --limit=10

# View specific run
gh run view <run-id>

# View run logs
gh run view <run-id> --log

# View failed jobs only
gh run view <run-id> --log-failed

# Watch run in real-time
gh run watch <run-id>
```

### Runner Management
```bash
# List runners (requires admin)
gh api /repos/:owner/:repo/actions/runners

# Check runner status (on runner machine)
sudo systemctl status actions.runner.*

# View runner logs
sudo journalctl -u actions.runner.* -f

# Restart runner
sudo systemctl restart actions.runner.*
```

### API and Rate Limits
```bash
# Check rate limit
gh api rate_limit

# Check authentication
gh auth status

# Test API access
gh api /repos/:owner/:repo
```

### Job Control
```bash
# Cancel run
gh run cancel <run-id>

# Re-run failed jobs
gh run rerun <run-id> --failed

# Re-run all jobs
gh run rerun <run-id>

# Manually trigger workflow
gh workflow run <workflow-name>
```

---

## 📞 Escalation Path

### Level 1: Self-Service (0-15 minutes)
1. Check this runbook for common issues
2. Review workflow logs
3. Try re-running failed jobs
4. Check GitHub status page

### Level 2: Team (15-60 minutes)
1. Contact DevOps team in #devops-support
2. Provide: run ID, workflow name, error message
3. Check team documentation for recent changes
4. Review recent PRs that modified workflows

### Level 3: External (60+ minutes)
1. Check GitHub Community Forum
2. Open GitHub Support ticket
3. Contact runner infrastructure team
4. Escalate to management if critical

---

## 📚 Additional Resources

### Documentation
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workflow Syntax Reference](https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions)
- [Self-Hosted Runners](https://docs.github.com/en/actions/hosting-your-own-runners)

### Internal Resources
- [Workflow Catalog](WORKFLOW_CATALOG.md) - All workflows documented
- [Improvement Plan](COMPREHENSIVE_IMPROVEMENT_PLAN_2026.md) - Full plan
- [Security Best Practices](SECURITY_BEST_PRACTICES.md) - Security guidelines
- [Runner Gating Guide](RUNNER_GATING_GUIDE.md) - Runner availability

### Monitoring
- [GitHub Status](https://www.githubstatus.com/)
- [Workflow Health Dashboard](workflow-health-dashboard.yml) - Internal monitoring
- [Alert Manager](workflow-alert-manager.yml) - Automated alerts

---

## ✅ Checklist for Investigating Failures

**Before Escalating:**
- [ ] Checked workflow logs
- [ ] Verified runner availability
- [ ] Checked GitHub status page
- [ ] Tried re-running failed jobs
- [ ] Reviewed recent code changes
- [ ] Checked for similar past failures
- [ ] Verified permissions and tokens
- [ ] Checked disk space and resources

**Information to Provide When Escalating:**
- [ ] Workflow name
- [ ] Run ID
- [ ] Error message (full text)
- [ ] Steps already attempted
- [ ] Environment details (runner type, OS)
- [ ] Recent changes (PRs, commits)
- [ ] Frequency (one-time, intermittent, consistent)

---

**Created:** 2026-02-16  
**Maintained by:** DevOps Team  
**Review Schedule:** Monthly  
**Last Review:** 2026-02-16
