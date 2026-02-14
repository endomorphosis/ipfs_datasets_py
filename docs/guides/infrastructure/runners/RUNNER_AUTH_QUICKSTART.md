# Quick Setup: GitHub CLI Auth on Self-Hosted Runner

**One-command setup for GitHub CLI and Copilot authentication on self-hosted runners.**

## TL;DR

```bash
# 1. Create token at: https://github.com/settings/tokens/new
#    Scopes needed: repo, workflow

# 2. Run setup script
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh

# 3. Restart runner
sudo systemctl restart actions.runner.*.service

# 4. Verify
sudo verify-gh-auth
```

## Why This is Needed

GitHub Actions workflows using `gh agent-task` (Copilot Coding Agent) or other gh CLI commands fail without proper authentication:

❌ **Before Setup:**
```
Error: gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable
Error: gh agent-task: command not found or authentication failed
```

✅ **After Setup:**
```
✅ GitHub CLI authenticated
✅ Copilot CLI ready
✅ All gh commands work in workflows
```

## Token Scopes Required

Create token at: https://github.com/settings/tokens/new

**Required:**
- ✅ `repo` - Full control of private repositories
- ✅ `workflow` - Update GitHub Action workflows

**Optional:**
- ⚪ `write:packages` - If using GitHub Packages
- ⚪ `read:org` - If querying organization

## What Gets Configured

| Component | Location | Purpose |
|-----------|----------|---------|
| **GH CLI Auth** | `/home/runner/.config/gh/hosts.yml` | Persistent gh authentication |
| **Root GH Auth** | `/root/.config/gh/hosts.yml` | For container jobs |
| **Copilot CLI** | `gh extension: gh-copilot` | Copilot commands |
| **Runner Env** | `/home/actions-runner/.env` | GH_TOKEN for service |
| **Git Helper** | System git config | Auto git authentication |

## Verification

```bash
# Quick check
sudo verify-gh-auth

# Manual verification
sudo -u runner gh auth status          # ✅ Should show authenticated
sudo -u runner gh api user              # ✅ Should show user info
sudo -u runner gh extension list        # ✅ Should show gh-copilot
```

## Troubleshooting

### "Token invalid"
```bash
# Re-run setup with new token
sudo ./scripts/setup_gh_copilot_auth_on_runner.sh
```

### "Copilot CLI not found"
```bash
# Install manually
sudo -u runner gh extension install github/gh-copilot
```

### "Still not working in workflows"
```bash
# Restart runner service
sudo systemctl restart actions.runner.*.service

# Check service is loading environment
sudo systemctl show actions.runner.*.service | grep EnvironmentFile
```

## Usage in Workflows

After setup, use gh CLI without extra configuration:

```yaml
jobs:
  use-copilot:
    runs-on: [self-hosted, linux, x64]
    steps:
      - name: Create Copilot Task
        run: |
          gh agent-task create --repo ${{ github.repository }}
          # Works! Uses runner's persistent auth
```

## Security Note

⚠️ **Token has full repo access - secure your runner machine!**

Best practices:
- Use dedicated GitHub bot account
- Restrict SSH access to runner
- Monitor token usage regularly
- Rotate tokens periodically

## Links

- **Full Documentation:** [docs/RUNNER_AUTHENTICATION_SETUP.md](guides/deployment/runner_authentication_setup.md)
- **Setup Script:** [scripts/setup_gh_copilot_auth_on_runner.sh](../scripts/setup_gh_copilot_auth_on_runner.sh)
- **GitHub CLI Docs:** https://cli.github.com/manual/gh_auth_login
- **Copilot CLI:** https://github.com/features/copilot/cli
