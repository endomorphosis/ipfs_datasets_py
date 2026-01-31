# GitHub CLI & Copilot Authentication Setup for Self-Hosted Runners

This guide explains how to configure persistent GitHub CLI and Copilot CLI authentication on self-hosted GitHub Actions runners.

## Problem Statement

GitHub Actions workflows that use `gh` CLI commands (including `gh agent-task` for Copilot Coding Agent) need proper authentication. When running on self-hosted runners, the `GITHUB_TOKEN` provided by GitHub Actions workflows has limited scope and duration, which can cause failures in:

- `gh agent-task create` commands (Copilot Coding Agent)
- `gh pr create` / `gh issue create` commands
- `gh api` calls
- Copilot CLI extension usage

## Solution

Configure persistent, long-term GitHub CLI authentication on the self-hosted runner itself. This provides:

✅ **Persistent Authentication** - Survives across workflow runs and system reboots
✅ **Full API Access** - Uses a Personal Access Token with complete scopes
✅ **Copilot CLI Support** - Enables Copilot CLI extension and agent-task commands
✅ **Multiple User Support** - Configures auth for both runner user and root
✅ **Automatic Credential Helper** - Git operations use gh authentication automatically

## Quick Start

### Prerequisites

1. **Self-hosted runner** installed and running
2. **GitHub Personal Access Token** with these scopes:
   - `repo` - Full control of private repositories
   - `workflow` - Update GitHub Action workflows
   - `write:packages` - Upload packages (optional)
   - `read:org` - Read org and team membership

### Create Personal Access Token

1. Go to https://github.com/settings/tokens/new
2. Give it a descriptive name: `Self-hosted Runner Auth`
3. Set expiration (recommend "No expiration" for production runners)
4. Select the scopes listed above
5. Click "Generate token"
6. **Copy the token immediately** (you won't see it again!)

### Run Setup Script

```bash
# On the self-hosted runner machine
cd /path/to/ipfs_datasets_py
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh
```

The script will:
1. Check if GitHub CLI is installed (installs if needed)
2. Prompt for your GitHub Personal Access Token
3. Configure GitHub CLI for runner and root users
4. Install GitHub Copilot CLI extension
5. Setup git credential helper
6. Update runner service configuration
7. Create verification script

### Verify Setup

```bash
# Run the verification script
sudo verify-gh-auth

# Or manually test
sudo -u runner gh auth status
sudo -u runner gh api user
sudo -u runner gh extension list
```

### Restart Runner Service

```bash
# Find your runner service name
sudo systemctl list-units --type=service | grep actions.runner

# Restart it
sudo systemctl restart actions.runner.endomorphosis-ipfs_datasets_py.*.service
```

## What Gets Configured

### 1. GitHub CLI Authentication Files

**For runner user (`/home/runner/.config/gh/hosts.yml`):**
```yaml
github.com:
    user: ""
    oauth_token: ghp_xxxxxxxxxxxx
    git_protocol: https
```

**For root user (`/root/.config/gh/hosts.yml`):**
```yaml
github.com:
    user: ""
    oauth_token: ghp_xxxxxxxxxxxx
    git_protocol: https
```

### 2. Runner Environment File

**File: `/home/actions-runner/.env`**
```bash
GH_TOKEN=ghp_xxxxxxxxxxxx
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
GIT_CONFIG_GLOBAL=/dev/null
GIT_CONFIG_SYSTEM=/dev/null
```

### 3. Runner Service Configuration

The systemd service file is updated to load the environment file:

```ini
[Service]
EnvironmentFile=-/home/actions-runner/.env
```

### 4. Git Credential Helper

System-wide git configuration:
```bash
git config --system credential.helper "!gh auth git-credential"
```

## Usage in Workflows

With authentication configured, workflows can use gh CLI commands without additional setup:

### Example: Using gh agent-task

```yaml
jobs:
  assign-copilot:
    runs-on: [self-hosted, linux, x64]
    steps:
      - name: Create Copilot Agent Task
        run: |
          # No GH_TOKEN needed - uses persistent auth!
          gh agent-task create --repo ${{ github.repository }}
```

### Example: Creating PRs

```yaml
jobs:
  create-pr:
    runs-on: [self-hosted, linux, x64]
    steps:
      - name: Create Draft PR
        run: |
          # Works with persistent auth
          gh pr create --draft --title "Auto-fix" --body "..." 
```

### Container-Based Jobs

For jobs running in containers, the workflow still needs to pass GH_TOKEN:

```yaml
jobs:
  container-job:
    runs-on: [self-hosted, linux, x64]
    container:
      image: python:3.12-slim
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}  # Still needed in containers
    steps:
      - name: Use gh CLI
        run: gh auth status
```

## Troubleshooting

### Authentication Not Working

```bash
# Check if gh is authenticated
sudo -u runner gh auth status

# Check environment file exists
cat /home/actions-runner/.env

# Check service file includes environment
sudo cat /etc/systemd/system/actions.runner.*.service | grep EnvironmentFile

# Restart runner service
sudo systemctl restart actions.runner.*.service
```

### Copilot CLI Not Working

```bash
# Check if extension is installed
sudo -u runner gh extension list

# Install manually if needed
sudo -u runner gh extension install github/gh-copilot

# Upgrade extension
sudo -u runner gh extension upgrade gh-copilot
```

### Token Expired or Invalid

```bash
# Remove existing auth
sudo -u runner gh auth logout

# Re-run setup script
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh
```

### Permissions Issues

```bash
# Fix ownership of config directory
sudo chown -R runner:runner /home/runner/.config/gh

# Fix permissions
sudo chmod 700 /home/runner/.config/gh
sudo chmod 600 /home/runner/.config/gh/hosts.yml
```

## Security Considerations

### Token Security

- ✅ Token is stored with restrictive permissions (600)
- ✅ Only runner user and root can read the token
- ✅ Token is stored in user home directory, not in repository
- ⚠️  Token has full repository access - protect the runner machine

### Best Practices

1. **Use a dedicated GitHub account** for runner authentication (e.g., `my-org-bot`)
2. **Create organization-level tokens** if managing multiple repositories
3. **Set token expiration** and rotate regularly (or use no expiration with good security)
4. **Monitor token usage** via GitHub's token usage page
5. **Restrict runner machine access** - only trusted users should have SSH access

### Token Scopes

Minimum required scopes:
- `repo` - For repository operations
- `workflow` - For workflow modifications

Optional but useful:
- `write:packages` - If using GitHub Packages
- `read:org` - If querying organization data
- `read:discussion` - If interacting with discussions

## Advanced Configuration

### Multiple Runners

For multiple runners, run the setup script on each:

```bash
# On runner 1
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh

# On runner 2
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh

# Each can use the same token or different tokens
```

### Custom Runner User

If your runner uses a different username:

```bash
# Set custom runner user
export RUNNER_USER=my-custom-runner-user
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh
```

### Automated Token Rotation

Create a script to update tokens automatically:

```bash
#!/bin/bash
# rotate-gh-token.sh

NEW_TOKEN="$1"
RUNNER_USER="runner"

# Update hosts.yml files
sudo sed -i "s/oauth_token: .*/oauth_token: ${NEW_TOKEN}/" \
  /home/${RUNNER_USER}/.config/gh/hosts.yml \
  /root/.config/gh/hosts.yml

# Update environment file
sudo sed -i "s/GH_TOKEN=.*/GH_TOKEN=${NEW_TOKEN}/" \
  /home/actions-runner/.env
sudo sed -i "s/GITHUB_TOKEN=.*/GITHUB_TOKEN=${NEW_TOKEN}/" \
  /home/actions-runner/.env

# Restart runner
sudo systemctl restart actions.runner.*.service

echo "Token rotated successfully"
```

## Fallback Mechanisms

Even with persistent auth configured, our workflow scripts include fallbacks:

1. **Primary**: Use persistent runner authentication
2. **Fallback 1**: Use workflow `GITHUB_TOKEN` environment variable
3. **Fallback 2**: Use `gh pr comment` with `@copilot` mention instead of `gh agent-task`

This ensures workflows continue working even if runner authentication fails.

## References

- [GitHub CLI Authentication](https://cli.github.com/manual/gh_auth_login)
- [GitHub Copilot CLI](https://github.com/features/copilot/cli)
- [GitHub Actions Self-Hosted Runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [GitHub Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token)
- [Copilot Coding Agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent)

## Support

If you encounter issues:

1. Run the verification script: `sudo verify-gh-auth`
2. Check workflow logs for specific errors
3. Review runner service logs: `sudo journalctl -u actions.runner.*.service -n 100`
4. Verify token scopes on GitHub: https://github.com/settings/tokens
