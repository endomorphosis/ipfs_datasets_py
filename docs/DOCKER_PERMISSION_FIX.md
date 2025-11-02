# Docker Permission Issues - Self-Hosted Runner Solutions

## Problem Description

Self-hosted GitHub Actions runners commonly encounter Docker permission issues with the error:
```
permission denied while trying to connect to the Docker daemon socket
```

This occurs because the runner process doesn't have access to the Docker daemon socket (`/var/run/docker.sock`).

## Root Cause Analysis

1. **Runner User Permissions**: The GitHub Actions runner service runs under a specific user (often `github-runner` or the user who installed it)
2. **Docker Socket Ownership**: Docker daemon socket is typically owned by `root:docker` with permissions `660`
3. **Group Membership**: The runner user must be in the `docker` group to access the socket
4. **Service Context**: Even if the user is in the docker group, the service may not inherit group memberships properly

## Solution 1: Add Runner User to Docker Group (Recommended)

### For Standard Installation

```bash
# 1. Identify the runner user
ps aux | grep Runner.Listener
# or check service configuration
sudo systemctl status actions.runner.*

# 2. Add user to docker group (replace 'runner-user' with actual username)
sudo usermod -aG docker runner-user

# 3. Verify group membership
groups runner-user

# 4. Restart the runner service
sudo systemctl restart actions.runner.*

# 5. Test Docker access
sudo -u runner-user docker ps
```

### For GitHub-Hosted Style Setup

```bash
# If runner was installed as 'github-runner' user
sudo usermod -aG docker github-runner

# Restart Docker service to ensure proper permissions
sudo systemctl restart docker

# Restart runner service
sudo systemctl restart github-runner
```

## Solution 2: Docker Socket Permissions (Alternative)

⚠️ **Less secure** - only use if adding to docker group doesn't work:

```bash
# Option A: Change socket permissions (temporary)
sudo chmod 666 /var/run/docker.sock

# Option B: Create persistent permission rule
echo 'SUBSYSTEM=="unix", GROUP="docker", MODE="0666"' | sudo tee /etc/udev/rules.d/99-docker.rules
sudo udevadm control --reload-rules
sudo systemctl restart docker
```

## Solution 3: Systemd Service Configuration

Create or modify the runner service to ensure proper group inheritance:

```bash
# Find the service file
sudo find /etc/systemd/system -name "*runner*" -o -name "*actions*"

# Edit the service file
sudo nano /etc/systemd/system/actions.runner.*.service
```

Add these lines to the `[Service]` section:
```ini
[Service]
# Ensure the service inherits group memberships
SupplementaryGroups=docker
# Alternative: run with specific group
Group=docker
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart actions.runner.*
```

## Solution 4: Workflow-Level Workarounds

### Pre-flight Docker Check

Add this step to workflows to diagnose Docker access:

```yaml
- name: Docker Diagnostics
  run: |
    echo "Current user: $(whoami)"
    echo "User groups: $(groups)"
    echo "Docker socket permissions:"
    ls -la /var/run/docker.sock
    echo "Docker group members:"
    getent group docker
    echo "Testing Docker access:"
    docker version || echo "Docker access failed"
```

### Conditional Docker Commands

```yaml
- name: Safe Docker Test
  run: |
    if docker ps >/dev/null 2>&1; then
      echo "✅ Docker access working"
      docker --version
    else
      echo "❌ Docker access failed - checking alternatives"
      # Try with sudo (not recommended for production)
      sudo docker --version
    fi
```

## Solution 5: Docker-in-Docker Alternative

If direct Docker access can't be resolved, use Docker-in-Docker:

```yaml
services:
  docker:
    image: docker:24-dind
    privileged: true
    environment:
      DOCKER_TLS_CERTDIR: ""
      DOCKER_HOST: tcp://docker:2375

steps:
  - name: Setup Docker Client
    run: |
      export DOCKER_HOST=tcp://docker:2375
      docker version
```

## Verification Steps

After applying any solution:

```bash
# 1. Check service status
sudo systemctl status actions.runner.*

# 2. Verify Docker access
sudo -u $(systemctl show -p User actions.runner.*.service --value) docker ps

# 3. Test with actual workflow
# Push commit with: [test-docker] Docker permission test

# 4. Monitor logs
sudo journalctl -u actions.runner.* -f
```

## Prevention: Runner Setup Script

Create an automated setup script:

```bash
#!/bin/bash
# setup-runner-docker.sh

set -e

RUNNER_USER=${1:-$(whoami)}

echo "Setting up Docker permissions for runner user: $RUNNER_USER"

# Add user to docker group
sudo usermod -aG docker "$RUNNER_USER"

# Ensure docker service is running
sudo systemctl enable docker
sudo systemctl start docker

# Verify setup
echo "Verifying setup..."
groups "$RUNNER_USER" | grep docker && echo "✅ User in docker group" || echo "❌ User NOT in docker group"

# Test docker access
if sudo -u "$RUNNER_USER" docker ps >/dev/null 2>&1; then
    echo "✅ Docker access working for $RUNNER_USER"
else
    echo "❌ Docker access still failing for $RUNNER_USER"
    echo "Manual steps may be required:"
    echo "1. Logout/login the user or restart the service"
    echo "2. Check systemd service configuration"
fi

echo "Setup complete. You may need to restart the runner service."
```

## Architecture-Specific Considerations

### ARM64 Runners
```bash
# ARM64 may require additional Docker setup
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### Multiple Runners
```bash
# For multiple runners on same machine
for service in $(systemctl list-units --type=service | grep actions.runner | awk '{print $1}'); do
    echo "Restarting $service"
    sudo systemctl restart "$service"
done
```

## Troubleshooting

### Common Issues

1. **Group membership not inherited**: Restart the service after adding to group
2. **Socket not accessible**: Check `/var/run/docker.sock` permissions
3. **Service user mismatch**: Verify which user the service runs as
4. **SELinux/AppArmor**: May require additional security context configuration

### Debug Commands

```bash
# Check all relevant permissions
echo "=== Docker Socket ==="
ls -la /var/run/docker.sock

echo "=== Docker Group ==="
getent group docker

echo "=== Runner Service User ==="
systemctl show -p User actions.runner.*.service

echo "=== Current Groups ==="
groups $(systemctl show -p User actions.runner.*.service --value)
```

## Security Notes

- Adding users to the `docker` group grants root-equivalent access
- Consider using rootless Docker for better security isolation
- Monitor runner activity and restrict network access
- Use dedicated runner machines/VMs for production environments

## Further Reading

- [Docker Post-installation Steps](https://docs.docker.com/engine/install/linux-postinstall/)
- [GitHub Actions Runner Security](https://docs.github.com/en/actions/hosting-your-own-runners/about-self-hosted-runners#self-hosted-runner-security)
- [Rootless Docker](https://docs.docker.com/engine/security/rootless/)