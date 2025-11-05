# CI/CD Setup Quick Reference

## 🚀 Quick Setup

```bash
cd /home/barberb/ipfs_datasets_py
./setup_cicd_runner.sh
```

**You'll need**: GitHub registration token from https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners/new

## ✅ Validate Setup

```bash
./test_cicd_runner.sh
```

## 📋 Management Commands

### Check Status
```bash
cd ~/actions-runner-ipfs_datasets_py
sudo ./svc.sh status
```

### View Logs
```bash
sudo journalctl -u actions.runner.* -f
```

### Restart Runner
```bash
cd ~/actions-runner-ipfs_datasets_py
sudo ./svc.sh restart
```

### Stop Runner
```bash
cd ~/actions-runner-ipfs_datasets_py
sudo ./svc.sh stop
```

### Start Runner
```bash
cd ~/actions-runner-ipfs_datasets_py
sudo ./svc.sh start
```

## 🧪 Test Runner

```bash
cd /home/barberb/ipfs_datasets_py
git commit --allow-empty -m "[test-runner] Testing self-hosted runner"
git push
```

Then check: https://github.com/endomorphosis/ipfs_datasets_py/actions

## 📚 Documentation

- **Full Guide**: `CICD_RUNNER_SETUP_GUIDE.md`
- **Runner Setup**: `docs/RUNNER_SETUP.md`
- **CI/CD Analysis**: `CI_CD_ANALYSIS.md`
- **Docker Setup**: `DOCKER_GITHUB_ACTIONS_SETUP.md`

## 🔍 Verify on GitHub

- **Runners**: https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners
- **Actions**: https://github.com/endomorphosis/ipfs_datasets_py/actions
- **Workflows**: `.github/workflows/`

## 🐛 Troubleshooting

### Runner not showing up
```bash
sudo journalctl -u actions.runner.* -n 50
cd ~/actions-runner-ipfs_datasets_py
sudo ./svc.sh restart
```

### Docker permission denied
```bash
sudo usermod -aG docker $USER
newgrp docker
docker ps
```

### Clean Docker resources
```bash
docker system prune -af
cd ~/actions-runner-ipfs_datasets_py/_work
rm -rf *
```

## 🎮 GPU Support

If you have NVIDIA GPU:

### Check GPU
```bash
nvidia-smi
```

### Test Docker GPU access
```bash
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

### Install GPU support
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

## 💡 Tips

- Runner labels: `self-hosted`, `linux`, `x86_64` (+ `gpu`, `cuda` if GPU available)
- Use `[test-runner]` in commit messages to trigger runner tests
- Use `[skip ci]` to skip CI runs
- Monitor disk space in `~/actions-runner-ipfs_datasets_py/_work/`
- Check Actions tab for workflow runs

## 📞 Support

- Repository Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- GitHub Actions Docs: https://docs.github.com/en/actions/hosting-your-own-runners
