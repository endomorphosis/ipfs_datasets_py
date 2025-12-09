# GitHub Actions Self-Hosted Runner Setup Guide

This guide will help you set up a self-hosted GitHub Actions runner for the `ipfs_datasets_py` repository.

## Prerequisites

✅ **System Requirements:**
- Ubuntu 24.04 LTS (already confirmed)
- x86_64 architecture (already confirmed)
- Docker installed (already confirmed)
- GitHub CLI installed (already confirmed)

## Step-by-Step Setup

### 1. Authenticate with GitHub

First, you need to authenticate with GitHub CLI:

```bash
gh auth login
```

Follow these prompts:
- **Where do you use GitHub?** → Select `GitHub.com`
- **What is your preferred protocol?** → Select `HTTPS` (recommended) or `SSH`
- **Authenticate Git with your GitHub credentials?** → Select `Yes`
- **How would you like to authenticate GitHub CLI?** → Select `Login with a web browser`

Copy the one-time code and open it in your browser to complete authentication.

### 2. Verify Authentication

```bash
gh auth status
```

You should see confirmation that you're logged in.

### 3. Check Repository Access

Verify you have access to the repository:

```bash
gh repo view endomorphosis/ipfs_datasets_py
```

### 4. Run the Setup Script

Once authenticated, run the setup script:

```bash
./setup_self_hosted_runner.sh
```

The script will:
- ✅ Check system requirements
- 📥 Download the latest GitHub Actions runner
- ⚙️ Configure the runner for your repository
- 🔧 Create a systemd service for automatic startup
- 🚀 Start the runner service

### 5. Verify Runner Installation

Check if the service is running:

```bash
sudo systemctl status actions.runner.*
```

Check runner logs:

```bash
sudo journalctl -u actions.runner.* -f
```

### 6. Test the Runner

The repository already has workflows configured for self-hosted runners. You can test by:

1. Going to the GitHub repository: https://github.com/endomorphosis/ipfs_datasets_py
2. Navigate to **Actions** tab
3. Find **"Self-Hosted Runner Test"** workflow
4. Click **"Run workflow"** to trigger a test

Or trigger via commit message:
```bash
git commit -m "Test self-hosted runner [test-runner]" --allow-empty
git push
```

## Runner Configuration

The runner will be configured with:
- **Name:** `$(hostname)-$(timestamp)`
- **Labels:** `self-hosted`, `x86_64`, `linux`
- **Repository:** `endomorphosis/ipfs_datasets_py`
- **Work Directory:** `/home/actions-runner/_work`

## Existing Workflows

The repository already has several workflows configured for self-hosted runners:

1. **Self-Hosted Runner Test** (`.github/workflows/self-hosted-runner.yml`)
   - Tests basic runner functionality
   - Builds Docker images
   - Runs system tests

2. **GPU Runner** (`.github/workflows/gpu-tests.yml`)
   - For GPU-enabled testing (if NVIDIA GPUs are available)

3. **ARM64 Runner** (`.github/workflows/arm64-runner.yml`)
   - For ARM64 architecture testing

## Using the Runner in Workflows

To use your self-hosted runner in GitHub Actions workflows, specify:

```yaml
jobs:
  test:
    runs-on: [self-hosted, x86_64, linux]
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      # ... your steps
```

## Management Commands

### Check Runner Status
```bash
sudo systemctl status actions.runner.*
```

### View Runner Logs
```bash
sudo journalctl -u actions.runner.* -f
```

### Stop Runner
```bash
sudo systemctl stop actions.runner.*
```

### Start Runner
```bash
sudo systemctl start actions.runner.*
```

### Remove Runner
```bash
cd /home/actions-runner
./config.sh remove --token $(gh api --method POST -H "Accept: application/vnd.github.v3+json" "/repos/endomorphosis/ipfs_datasets_py/actions/runners/remove-token" --jq .token)
```

## Troubleshooting

### Runner Not Appearing in GitHub
1. Check service status: `sudo systemctl status actions.runner.*`
2. Check logs: `sudo journalctl -u actions.runner.* -f`
3. Verify network connectivity: `curl -I https://github.com`

### Permission Issues
1. Ensure runner directory has correct ownership: `sudo chown -R $(whoami):$(whoami) /home/actions-runner`
2. Check Docker permissions: `docker run hello-world`

### Token Issues
- Registration tokens expire after 1 hour
- If setup fails, get a new token: `gh api --method POST -H "Accept: application/vnd.github.v3+json" "/repos/endomorphosis/ipfs_datasets_py/actions/runners/registration-token" --jq .token`

## Security Considerations

⚠️ **Important Security Notes:**
- Self-hosted runners can access your local machine
- Only use with trusted repositories
- Consider running in isolated environments for public repositories
- Regularly update the runner software

## Next Steps

After setup:
1. ✅ Verify runner appears in GitHub repository settings under "Actions" → "Runners"
2. 🧪 Run a test workflow to confirm functionality
3. 🔒 Review security settings and runner permissions
4. 📊 Monitor runner usage and performance

## Support

For issues:
- Check the [GitHub Actions documentation](https://docs.github.com/en/actions/hosting-your-own-runners)
- Review repository workflows in `.github/workflows/`
- Check existing runner setup scripts in the repository