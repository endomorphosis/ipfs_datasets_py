# GitHub Actions Self-Hosted Runner Permission Fix

## Problem

GitHub Actions workflows fail with permission errors when trying to clean up workspace directories:

```
Error: fatal: Unable to create '.git/index.lock': Permission denied
Error: EACCES: permission denied, unlink '/path/to/file'
```

This happens because:
1. Previous workflow runs may leave files owned by different users
2. The runner user can't delete files it doesn't own
3. `chmod`/`chown` don't work without proper permissions
4. `actions/checkout@v4` with `clean: true` fails to clean workspace

## Solution: Configure Passwordless Sudo

The runner needs passwordless sudo access to cleanup commands (`rm`, `chown`, `chmod`).

### Quick Fix

Run on **each runner machine** as root:

```bash
# Download the configuration script
curl -o configure_runner_sudo.sh https://raw.githubusercontent.com/endomorphosis/ipfs_datasets_py/main/.github/scripts/configure_runner_sudo.sh

# Make it executable
chmod +x configure_runner_sudo.sh

# Run it (replace 'barberb' with your runner user)
sudo bash configure_runner_sudo.sh barberb
```

### Manual Configuration

If you prefer to configure manually:

1. **Create sudoers file** (as root):

```bash
# Replace 'barberb' with your runner user
RUNNER_USER="barberb"
sudo vi /etc/sudoers.d/github-runner-$RUNNER_USER
```

2. **Add these lines**:

```
# GitHub Actions Runner - Workspace Cleanup Permissions
barberb ALL=(ALL) NOPASSWD: /bin/rm, /usr/bin/rm
barberb ALL=(ALL) NOPASSWD: /bin/chown, /usr/bin/chown
barberb ALL=(ALL) NOPASSWD: /bin/chmod, /usr/bin/chmod
```

3. **Set permissions**:

```bash
sudo chmod 0440 /etc/sudoers.d/github-runner-$RUNNER_USER
```

4. **Validate**:

```bash
sudo visudo -c -f /etc/sudoers.d/github-runner-$RUNNER_USER
```

5. **Test**:

```bash
sudo -u barberb sudo -n rm -rf /tmp/test_cleanup
```

## Affected Runners

Based on the error logs, these runners need configuration:

| Runner Name | User | Path | Status |
|------------|------|------|--------|
| `workstation-1761892995` | `barberb` | `/home/barberb/actions-runner-ipfs_datasets_py/` | ❌ Needs fix |
| `runner-fent-reactor-x86_64` | ? | `/home/actions-runner/` | ❌ Needs fix |
| Local dev | `devel` | `/home/actions-runner/` | ⚠️ May need fix |

## Verification

After configuration, the workflow cleanup step will show:

```
Current user: barberb
Workspace: /home/barberb/actions-runner-ipfs_datasets_py/_work/ipfs_datasets_py/ipfs_datasets_py
Attempting to remove workspace...
Using sudo to remove workspace...
✅ Removed with sudo
✅ Workspace cleanup completed
```

Instead of:

```
Trying regular rm...
⚠️ Regular rm failed
Trying find-based removal...
⚠️ Find-based removal incomplete
```

## Security Considerations

### Why This Is Safe

1. **Limited scope**: Only allows `rm`, `chown`, `chmod` - not full sudo access
2. **Specific paths**: Runner workspace directories only
3. **No password**: Can only be used by the runner service account
4. **Audit trail**: All sudo commands are logged in `/var/log/auth.log`

### Security Best Practices

1. **Use service account**: Runner should run as dedicated user (not your personal account)
2. **Restrict network**: Runner should not be publicly accessible
3. **Monitor logs**: Check `/var/log/auth.log` for sudo usage
4. **Update regularly**: Keep runner software up to date

## Alternative Solutions

If you can't/won't configure sudo, alternatives include:

### 1. Use GitHub-Hosted Runners
```yaml
runs-on: ubuntu-latest  # Instead of self-hosted
```
**Pros**: No permission issues
**Cons**: No access to local resources, costs money

### 2. Use Docker-Based Runner
```yaml
jobs:
  test:
    container:
      image: ubuntu:latest
```
**Pros**: Clean environment each run
**Cons**: More complex setup

### 3. Run Runner as Root (NOT RECOMMENDED)
```bash
# Don't do this - security risk
sudo ./run.sh
```
**Pros**: No permission issues
**Cons**: **MAJOR SECURITY RISK** - workflows run as root!

### 4. Accept Workspace Corruption
```yaml
- uses: actions/checkout@v4
  with:
    clean: false  # Don't try to clean
```
**Pros**: Simple
**Cons**: May cause unexpected behavior, disk fills up

## Runner Configuration Files

For each runner, edit these files after sudo configuration:

### workstation-1761892995

```bash
# Run on the runner machine as root
sudo bash /home/devel/ipfs_datasets_py/.github/scripts/configure_runner_sudo.sh barberb
```

### runner-fent-reactor-x86_64

```bash
# Determine the runner user first
ps aux | grep Runner.Listener

# Then configure (replace USER with actual user)
sudo bash /home/devel/ipfs_datasets_py/.github/scripts/configure_runner_sudo.sh USER
```

## Troubleshooting

### "sudo: a terminal is required to read the password"

This means passwordless sudo is not configured. Follow the steps above.

### "sudo: sorry, user is not allowed to execute"

The sudoers file has wrong syntax or wrong permissions. Check:
```bash
sudo visudo -c -f /etc/sudoers.d/github-runner-*
sudo ls -la /etc/sudoers.d/
```

### Cleanup still fails

Check the workflow logs to see which cleanup strategy failed:
```bash
gh run view <run-id> --log | grep -A 20 "Clean workspace"
```

If all three strategies (sudo, rm, find) fail, there may be a deeper issue:
- Check disk space: `df -h`
- Check file permissions: `ls -la /path/to/workspace`
- Check for running processes: `lsof | grep workspace`

## Monitoring

Add this to your monitoring:

```bash
# Check sudo usage by runner
sudo grep "github" /var/log/auth.log | grep "sudo:"

# Check workspace cleanup success rate
gh api repos/endomorphosis/ipfs_datasets_py/actions/runs \
  --jq '.workflow_runs[] | select(.name=="Automated PR Review") | {id: .id, conclusion: .conclusion}'
```

## References

- GitHub Actions Self-Hosted Runners: https://docs.github.com/en/actions/hosting-your-own-runners
- Sudo Configuration: https://www.sudo.ws/docs/man/sudoers.man/
- Actions Checkout: https://github.com/actions/checkout

## Support

If issues persist after configuration:

1. Check runner logs: `~/actions-runner/_diag/`
2. Check system logs: `/var/log/syslog` or `/var/log/messages`
3. Test sudo manually: `sudo -u <runner_user> sudo -n rm -rf /tmp/test`
4. Create an issue with full logs

---

**Last Updated**: November 1, 2025
**Status**: Active - requires manual runner configuration
