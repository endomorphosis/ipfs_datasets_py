# Docker Permission Issues - Infrastructure-Level Solutions

## Problem Summary

Self-hosted GitHub Actions runners frequently encounter Docker permission issues:
```
permission denied while trying to connect to the Docker daemon socket
```

This is **primarily an infrastructure issue** that requires runner-level configuration and cannot be fully resolved through workflow files alone.

## Infrastructure Solutions

### 1. User Group Management (Primary Solution)

**For Ubuntu/Debian systems:**
```bash
# Add the runner user to docker group
sudo usermod -aG docker github-runner

# Or for current user
sudo usermod -aG docker $(whoami)

# Verify group membership
groups github-runner
```

**For RHEL/CentOS systems:**
```bash
# Same commands, but may require different service names
sudo usermod -aG docker actions-runner
```

### 2. Systemd Service Configuration

Create service override to ensure proper group inheritance:

```bash
# Find the service name
sudo systemctl list-units | grep runner

# Create override directory
sudo mkdir -p /etc/systemd/system/actions.runner.*.service.d/

# Create override file
sudo tee /etc/systemd/system/actions.runner.*.service.d/docker.conf << EOF
[Service]
SupplementaryGroups=docker
EOF

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart actions.runner.*
```

### 3. Docker Socket Permissions (Alternative)

⚠️ **Less secure option:**

```bash
# Temporary fix
sudo chmod 666 /var/run/docker.sock

# Persistent fix via udev rule
echo 'SUBSYSTEM=="unix", GROUP="docker", MODE="0666"' | sudo tee /etc/udev/rules.d/99-docker.rules
sudo udevadm control --reload-rules
sudo systemctl restart docker
```

### 4. Automated Setup Script

Use the provided setup script:

```bash
# Make executable
chmod +x scripts/setup-runner-docker-permissions.sh

# Run diagnostics
sudo ./scripts/setup-runner-docker-permissions.sh --diagnostics

# Apply fixes
sudo ./scripts/setup-runner-docker-permissions.sh
```

## Workflow-Level Workarounds

While the issue requires infrastructure fixes, workflows can include diagnostic steps:

### Diagnostic Step

```yaml
- name: Docker Permission Diagnostics
  run: |
    echo "Current user: $(whoami)"
    echo "User groups: $(groups)"
    echo "Docker socket permissions:"
    ls -la /var/run/docker.sock
    echo "Docker group members:"
    getent group docker
    docker version || echo "Docker access failed"
```

### Conditional Docker Usage

```yaml
- name: Build with Docker (if available)
  run: |
    if docker ps >/dev/null 2>&1; then
      echo "Docker available - building container"
      docker build -t my-app .
    else
      echo "Docker not available - using alternative build"
      # Alternative build method
    fi
```

### Docker-in-Docker Alternative

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

After applying infrastructure fixes:

```bash
# 1. Verify group membership
groups $(whoami)

# 2. Test Docker access
docker ps

# 3. Check service status
sudo systemctl status actions.runner.*

# 4. Test with actual workflow
git commit --allow-empty -m "[test-docker] Testing Docker permissions"
git push
```

## Prevention During Setup

When setting up new runners:

```bash
#!/bin/bash
# runner-setup-with-docker.sh

# 1. Install Docker
curl -fsSL https://get.docker.com | sh

# 2. Create runner user (if not exists)
sudo useradd -m -s /bin/bash github-runner

# 3. Add to docker group
sudo usermod -aG docker github-runner

# 4. Configure runner
sudo -u github-runner ./config.sh --url https://github.com/user/repo --token $TOKEN

# 5. Install as service
sudo ./svc.sh install github-runner
sudo ./svc.sh start
```

## Architecture-Specific Notes

### ARM64 Runners
```bash
# May need architecture-specific Docker installation
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Verify Docker works for ARM64
docker run --rm arm64v8/alpine uname -m
```

### Multiple Runners on Same Host
```bash
# Handle multiple runner services
for service in $(systemctl list-units --type=service | grep actions.runner | awk '{print $1}'); do
    RUNNER_USER=$(systemctl show -p User "$service" --value)
    sudo usermod -aG docker "$RUNNER_USER"
    sudo systemctl restart "$service"
done
```

## Security Considerations

⚠️ **Important Security Notes:**

1. **Docker Group = Root Access**: Adding users to docker group grants root-equivalent privileges
2. **Isolation**: Use dedicated runner machines/VMs for production
3. **Monitoring**: Monitor runner activity and Docker usage
4. **Network Security**: Restrict runner network access
5. **Rootless Docker**: Consider rootless Docker for better security

### Rootless Docker Alternative

```bash
# Install rootless Docker (more secure)
curl -fsSL https://get.docker.com/rootless | sh

# Configure runner to use rootless Docker
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
export PATH=/home/github-runner/bin:$PATH
```

## Troubleshooting Commands

```bash
# Complete diagnostic script
echo "=== Docker Permission Diagnostics ==="
echo "Current user: $(whoami)"
echo "User ID: $(id)"
echo "Groups: $(groups)"
echo ""
echo "Docker socket:"
ls -la /var/run/docker.sock
echo ""
echo "Docker group:"
getent group docker
echo ""
echo "Runner services:"
systemctl list-units --type=service | grep runner
echo ""
echo "Docker test:"
docker version || echo "Docker access failed"
```

## Common Failure Patterns

1. **User in group but still fails**: Service needs restart
2. **Group membership not inherited**: Systemd override required  
3. **Socket permissions reset**: Need persistent udev rule
4. **Multiple Docker versions**: Conflicting Docker installations

## Quick Fix Commands

```bash
# Quick fix for immediate testing (not permanent)
sudo chmod 666 /var/run/docker.sock

# Permanent fix
sudo usermod -aG docker $(whoami)
sudo systemctl restart actions.runner.*

# Emergency fix (restart Docker with open permissions)
sudo systemctl stop docker
sudo dockerd --group docker --host unix:///var/run/docker.sock &
```

## References

- [Docker Post-installation steps](https://docs.docker.com/engine/install/linux-postinstall/)
- [GitHub Actions Self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [Systemd service configuration](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [Docker security considerations](https://docs.docker.com/engine/security/)

## Conclusion

Docker permission issues with self-hosted runners are **infrastructure problems** requiring:

1. **System-level configuration** (user groups, systemd services)
2. **Security considerations** (docker group = root access)
3. **Proper runner setup** during initial installation
4. **Monitoring and maintenance** of runner environments

Workflow files can include diagnostics and workarounds, but the fundamental fix must be applied at the infrastructure level.