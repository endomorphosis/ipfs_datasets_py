# Self-Hosted Runner Secrets Management

## Overview

This guide explains how to securely manage API keys and secrets on self-hosted GitHub Actions runners without exposing them in GitHub repository secrets or workflow logs.

## Problem

When using services like OpenAI, Anthropic, or OpenRouter in workflows, you need to provide API keys. The standard approach of using GitHub repository secrets has limitations:

1. **Visibility**: Repository secrets are visible in the GitHub UI to repository admins
2. **Sharing**: Secrets are shared across all workflows in the repository
3. **Rotation**: Changing secrets requires updating GitHub UI
4. **Audit**: Limited audit trail for secret access

## Solution

Store secrets locally on the self-hosted runner machine, where only the runner service can access them. This provides:

- ✅ **Security**: Secrets never leave the runner machine
- ✅ **Privacy**: Secrets not visible in GitHub UI
- ✅ **Control**: Easy to rotate and manage locally
- ✅ **Audit**: OS-level audit trails for file access
- ✅ **Isolation**: Each runner can have different secrets

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Self-Hosted Runner Machine                          │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │ /etc/github-runner-secrets/secrets.json     │  │
│  │ {                                            │  │
│  │   "OPENAI_API_KEY": "sk-...",               │  │
│  │   "ANTHROPIC_API_KEY": "sk-ant-...",        │  │
│  │   "OPENROUTER_API_KEY": "sk-or-..."         │  │
│  │ }                                            │  │
│  │ Permissions: 600 (read/write owner only)    │  │
│  └──────────────────────────────────────────────┘  │
│                       ↓                              │
│  ┌──────────────────────────────────────────────┐  │
│  │ scripts/load_runner_secrets.py               │  │
│  │ - Loads secrets from local file              │  │
│  │ - Masks secrets in workflow logs             │  │
│  │ - Exports to GitHub Actions environment      │  │
│  └──────────────────────────────────────────────┘  │
│                       ↓                              │
│  ┌──────────────────────────────────────────────┐  │
│  │ Workflow Steps                               │  │
│  │ - Access secrets via ${{ env.OPENAI_API_KEY }}│ │
│  │ - Secrets masked in logs                     │  │
│  │ - Never exposed to GitHub                    │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## Setup Instructions

### Step 1: Create Secrets Directory on Runner

SSH into your self-hosted runner machine and create a secure directory:

```bash
# Create secrets directory
sudo mkdir -p /etc/github-runner-secrets

# Set secure permissions (only owner can access)
sudo chmod 700 /etc/github-runner-secrets
```

### Step 2: Create Secrets File

Create a JSON file with your API keys:

```bash
# Create secrets file
sudo bash -c 'cat > /etc/github-runner-secrets/secrets.json << EOF
{
  "OPENAI_API_KEY": "sk-your-openai-key-here",
  "ANTHROPIC_API_KEY": "sk-ant-your-anthropic-key-here",
  "OPENROUTER_API_KEY": "sk-or-your-openrouter-key-here"
}
EOF'
```

### Step 3: Secure the Secrets File

Set restrictive permissions so only the runner user can read it:

```bash
# Set file permissions (read/write for owner only)
sudo chmod 600 /etc/github-runner-secrets/secrets.json

# Set owner to runner user (adjust username if different)
sudo chown runner:runner /etc/github-runner-secrets/secrets.json

# Verify permissions
ls -l /etc/github-runner-secrets/secrets.json
# Should show: -rw------- 1 runner runner
```

### Step 4: Verify Setup

Test that the secrets can be loaded:

```bash
# Run as the runner user
sudo -u runner python3 scripts/load_runner_secrets.py --check

# Expected output:
# ================================================================================
# 🔐 Secrets Manager Summary
# ================================================================================
# ✅ Loaded 3 secret(s):
#    - OPENAI_API_KEY: sk-proj-...
#    - ANTHROPIC_API_KEY: sk-ant-a...
#    - OPENROUTER_API_KEY: sk-or-v1-...
# ================================================================================
```

## Usage in Workflows

### Method 1: Using the Secrets Manager Script (Recommended)

Update your workflows to load secrets at the start:

```yaml
jobs:
  your-job:
    runs-on: [self-hosted, linux, x64]
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      
      - name: Load runner secrets
        run: python3 scripts/load_runner_secrets.py --export
      
      - name: Use secrets in subsequent steps
        env:
          OPENAI_API_KEY: ${{ env.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ env.ANTHROPIC_API_KEY }}
          OPENROUTER_API_KEY: ${{ env.OPENROUTER_API_KEY }}
        run: |
          # Your command that uses the secrets
          python your_script.py
```

### Method 2: Direct Environment Variables

Alternatively, configure secrets as environment variables for the runner service:

```bash
# Edit runner service file
sudo systemctl edit github-runner.service

# Add environment variables:
[Service]
Environment="OPENAI_API_KEY=sk-..."
Environment="ANTHROPIC_API_KEY=sk-ant-..."
Environment="OPENROUTER_API_KEY=sk-or-..."

# Restart runner
sudo systemctl restart github-runner.service
```

Then use them directly in workflows:

```yaml
jobs:
  your-job:
    runs-on: [self-hosted, linux, x64]
    
    steps:
      - name: Use secrets
        run: |
          # Secrets are automatically available
          echo "OpenAI key is set: ${OPENAI_API_KEY:+yes}"
```

## Security Best Practices

### 1. File Permissions

Always ensure secrets files have restrictive permissions:

```bash
# Check permissions
ls -l /etc/github-runner-secrets/secrets.json

# Should be: -rw------- (600)
# If not, fix with:
sudo chmod 600 /etc/github-runner-secrets/secrets.json
```

### 2. Owner and Group

Ensure the file is owned by the runner user:

```bash
# Check ownership
ls -l /etc/github-runner-secrets/secrets.json

# Should be owned by runner user
# If not, fix with:
sudo chown runner:runner /etc/github-runner-secrets/secrets.json
```

### 3. Secret Rotation

To rotate secrets:

```bash
# Edit the secrets file
sudo vim /etc/github-runner-secrets/secrets.json

# Update the API keys
# Save and exit

# No need to restart runner or update GitHub
```

### 4. Audit Access

Enable file access auditing (optional):

```bash
# On Linux with auditd
sudo auditctl -w /etc/github-runner-secrets/secrets.json -p r -k secret-access

# View audit logs
sudo ausearch -k secret-access
```

### 5. Backup

Backup secrets file securely:

```bash
# Create encrypted backup
sudo gpg --symmetric --cipher-algo AES256 /etc/github-runner-secrets/secrets.json

# Store secrets.json.gpg in a secure location
```

## Advanced Configuration

### Multiple Secrets Files

You can have multiple secrets files for different purposes:

```bash
# Production secrets
/etc/github-runner-secrets/secrets.json

# Development secrets
/etc/github-runner-secrets/secrets-dev.json

# Specify in workflow:
python3 scripts/load_runner_secrets.py --secrets-file /etc/github-runner-secrets/secrets-dev.json --export
```

### Secrets per Repository

Organize secrets by repository:

```bash
/etc/github-runner-secrets/
├── repo1-secrets.json
├── repo2-secrets.json
└── shared-secrets.json

# In workflow:
- name: Load repo-specific secrets
  run: |
    python3 scripts/load_runner_secrets.py \
      --secrets-file /etc/github-runner-secrets/${{ github.repository }}-secrets.json \
      --export
```

### Environment-Based Secrets

Different secrets for different environments:

```bash
/etc/github-runner-secrets/
├── production-secrets.json
├── staging-secrets.json
└── development-secrets.json

# In workflow:
- name: Load environment secrets
  run: |
    python3 scripts/load_runner_secrets.py \
      --secrets-file /etc/github-runner-secrets/${{ github.event.inputs.environment }}-secrets.json \
      --export
```

## Troubleshooting

### Issue: Permission Denied

**Error:**
```
❌ Permission denied reading /etc/github-runner-secrets/secrets.json
```

**Solution:**
```bash
# Check current permissions
ls -l /etc/github-runner-secrets/secrets.json

# Fix ownership
sudo chown runner:runner /etc/github-runner-secrets/secrets.json

# Fix permissions
sudo chmod 600 /etc/github-runner-secrets/secrets.json
```

### Issue: File Not Found

**Error:**
```
❌ No secrets loaded. Please configure secrets on the runner.
```

**Solution:**
```bash
# Verify file exists
ls -l /etc/github-runner-secrets/secrets.json

# If not, create it following Step 2 above
```

### Issue: Invalid JSON

**Error:**
```
❌ Invalid JSON in secrets file
```

**Solution:**
```bash
# Validate JSON syntax
cat /etc/github-runner-secrets/secrets.json | python3 -m json.tool

# Fix any JSON syntax errors
```

### Issue: Secrets Not Available in Workflow

**Error:**
Secrets are loaded but not available in subsequent steps.

**Solution:**
Make sure you're using `--export` flag:
```yaml
- name: Load runner secrets
  run: python3 scripts/load_runner_secrets.py --export
```

And accessing them correctly:
```yaml
- name: Use secrets
  env:
    OPENAI_API_KEY: ${{ env.OPENAI_API_KEY }}
  run: your_command
```

## Comparison: GitHub Secrets vs. Runner Secrets

| Feature | GitHub Secrets | Runner Secrets |
|---------|---------------|----------------|
| **Storage Location** | GitHub servers | Runner machine |
| **Visibility** | Repository admins | Root/runner user only |
| **Access Method** | `${{ secrets.NAME }}` | `${{ env.NAME }}` |
| **Rotation** | Update in GitHub UI | Edit local file |
| **Audit Trail** | GitHub audit log | OS audit log |
| **Scope** | Repository-wide | Runner-specific |
| **Setup Complexity** | Low | Medium |
| **Security** | Good | Excellent |
| **Cost** | Free | Free |

## Migration from GitHub Secrets

If you're currently using GitHub secrets and want to migrate:

1. **Backup**: Document all current secrets in GitHub
2. **Create**: Set up runner secrets file with same values
3. **Test**: Test with one workflow using runner secrets
4. **Update**: Update workflows to use `env` instead of `secrets`
5. **Remove**: Optionally remove from GitHub secrets

**Before:**
```yaml
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

**After:**
```yaml
steps:
  - name: Load runner secrets
    run: python3 scripts/load_runner_secrets.py --export
  
  - name: Use secrets
    env:
      OPENAI_API_KEY: ${{ env.OPENAI_API_KEY }}
    run: your_command
```

## Example Workflows

### Complete PR Completion Monitor Example

```yaml
name: PR Completion Monitor

on:
  schedule:
    - cron: '0 */2 * * *'
  workflow_dispatch:

jobs:
  check-prs:
    runs-on: [self-hosted, linux, x64]
    
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      
      - name: Load runner secrets
        run: python3 scripts/load_runner_secrets.py --export
      
      - name: Check PR completion
        env:
          OPENAI_API_KEY: ${{ env.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ env.ANTHROPIC_API_KEY }}
          OPENROUTER_API_KEY: ${{ env.OPENROUTER_API_KEY }}
        run: |
          python3 scripts/check_pr_completion.py
```

## Security Checklist

Before deploying to production, verify:

- [ ] Secrets file permissions are 600 (`-rw-------`)
- [ ] Secrets directory permissions are 700 (`drwx------`)
- [ ] File owner is the runner user
- [ ] Secrets file is not in git repository
- [ ] Secrets file is backed up securely
- [ ] Multiple runners have separate secrets files
- [ ] Audit logging is enabled (optional)
- [ ] Secrets are rotated regularly
- [ ] No secrets in workflow logs

## Related Documentation

- [GitHub Actions Self-Hosted Runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [Secrets Manager Script](../scripts/load_runner_secrets.py)
- [PR Completion Monitor Workflow](pr-completion-monitor.yml)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Verify file permissions and ownership
3. Test with `--check` flag
4. Review workflow logs for errors

## Version

1.0.0

## Last Updated

2025-11-02
