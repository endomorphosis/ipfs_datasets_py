# Quick Start: Self-Hosted Runner Secrets

## 🚀 30-Second Setup

On your self-hosted runner machine, run:

```bash
# Clone the repository (if not already done)
cd /path/to/ipfs_datasets_py

# Run the setup script
sudo bash scripts/setup_runner_secrets.sh
```

The script will:
1. Create `/etc/github-runner-secrets/` directory
2. Prompt you for API keys (OpenAI, Anthropic, OpenRouter)
3. Create secure JSON file with your keys
4. Set proper permissions (600)
5. Verify everything works

## ✅ That's It!

Your workflows will now automatically use these secrets without exposing them on GitHub.

## 📝 Manual Setup (Alternative)

If you prefer manual setup:

```bash
# 1. Create directory
sudo mkdir -p /etc/github-runner-secrets
sudo chmod 700 /etc/github-runner-secrets

# 2. Create secrets file
sudo nano /etc/github-runner-secrets/secrets.json
```

Add this content:
```json
{
  "OPENAI_API_KEY": "sk-your-key-here",
  "ANTHROPIC_API_KEY": "sk-ant-your-key-here",
  "OPENROUTER_API_KEY": "sk-or-your-key-here"
}
```

```bash
# 3. Secure the file
sudo chmod 600 /etc/github-runner-secrets/secrets.json
sudo chown runner:runner /etc/github-runner-secrets/secrets.json

# 4. Test it
sudo -u runner python3 scripts/load_runner_secrets.py --check
```

## 🔍 Verify Setup

```bash
# Check that secrets are loaded
sudo -u runner python3 scripts/load_runner_secrets.py --check

# Should show:
# ✅ Loaded 3 secret(s):
#    - OPENAI_API_KEY: sk-proj-...
#    - ANTHROPIC_API_KEY: sk-ant-...
#    - OPENROUTER_API_KEY: sk-or-...
```

## 💡 Usage in Workflows

Your workflows automatically use these secrets. No changes needed!

The `pr-completion-monitor.yml` workflow already includes:

```yaml
- name: Load runner secrets
  run: python3 scripts/load_runner_secrets.py --export
```

This makes secrets available as `${{ env.OPENAI_API_KEY }}` etc.

## 🔄 Update Secrets

To change API keys later:

```bash
# Method 1: Run setup script again
sudo bash scripts/setup_runner_secrets.sh

# Method 2: Edit manually
sudo nano /etc/github-runner-secrets/secrets.json
```

No need to restart the runner!

## 🔒 Security

- ✅ Secrets stored locally on runner (not on GitHub)
- ✅ File permissions prevent unauthorized access (600)
- ✅ Only runner user can read the file
- ✅ Secrets masked in workflow logs
- ✅ Never exposed in GitHub UI

## 📚 More Information

- **Full Guide**: [SECRETS-MANAGEMENT.md](../.github/workflows/SECRETS-MANAGEMENT.md)
- **Secrets Manager**: [load_runner_secrets.py](load_runner_secrets.py)
- **Setup Script**: [setup_runner_secrets.sh](setup_runner_secrets.sh)

## 🆘 Troubleshooting

**Issue: Permission denied**
```bash
# Fix ownership and permissions
sudo chown runner:runner /etc/github-runner-secrets/secrets.json
sudo chmod 600 /etc/github-runner-secrets/secrets.json
```

**Issue: Secrets not found**
```bash
# Verify file exists
ls -l /etc/github-runner-secrets/secrets.json

# If not, run setup script
sudo bash scripts/setup_runner_secrets.sh
```

**Issue: Invalid JSON**
```bash
# Validate JSON
cat /etc/github-runner-secrets/secrets.json | python3 -m json.tool
```

## 💰 Cost Comparison

**OpenAI GPT-4o-mini** (recommended):
- ~$0.036/day for 10 PRs checked every 2 hours
- Most cost-effective option

**Anthropic Claude**:
- ~$0.72/day for 10 PRs checked every 2 hours
- More expensive but high quality

**No API Key** (heuristic mode):
- $0/day (free!)
- Less accurate, uses keyword matching

## 🎯 Quick Reference

```bash
# Setup
sudo bash scripts/setup_runner_secrets.sh

# Verify
sudo -u runner python3 scripts/load_runner_secrets.py --check

# Update
sudo nano /etc/github-runner-secrets/secrets.json

# Test in workflow
python3 scripts/load_runner_secrets.py --export
```

---

**Ready to use!** Your self-hosted runner now has secure secrets management. 🎉
