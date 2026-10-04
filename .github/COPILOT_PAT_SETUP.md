# GitHub Copilot PAT Setup for Automated Issue Assignment

## Problem

The `gh agent-task create` command used in `copilot-issue-assignment.yml` requires OAuth authentication with Copilot-specific permissions. The default `GITHUB_TOKEN` provided to workflows does NOT have these permissions.

**Error Message:**
```
Error: this command requires an OAuth token. Re-authenticate with: gh auth login
```

## Solution

You need to create a **Personal Access Token (PAT)** with the required permissions and add it as a repository secret.

## Step-by-Step Setup

### 1. Create a Fine-Grained Personal Access Token

1. Go to: https://github.com/settings/tokens?type=beta
2. Click **"Generate new token"**
3. Configure the token:
   - **Token name:** `Copilot Automation for ipfs_datasets_py`
   - **Expiration:** Choose an appropriate duration (90 days recommended)
   - **Repository access:** Select "Only select repositories"
     - Choose: `endomorphosis/ipfs_datasets_py`
   
4. **Repository permissions** (set these):
   - **Codespaces:** Read and write *(required for Copilot agent features)*
   - **Contents:** Read and write
   - **Issues:** Read and write
   - **Pull requests:** Read and write
   - **Workflows:** Read and write

5. Click **"Generate token"**
6. **IMPORTANT:** Copy the token immediately (you won't see it again!)

### 2. Add Token as Repository Secret

Option A: Using GitHub CLI
```bash
gh secret set GH_COPILOT_PAT --body "YOUR_TOKEN_HERE" --repo endomorphosis/ipfs_datasets_py
```

Option B: Via GitHub Web UI
1. Go to: https://github.com/endomorphosis/ipfs_datasets_py/settings/secrets/actions
2. Click **"New repository secret"**
3. Name: `GH_COPILOT_PAT`
4. Value: Paste your token
5. Click **"Add secret"**

### 3. Update Workflow to Use PAT

Edit `.github/workflows/copilot-issue-assignment.yml`:

```yaml
- name: Invoke Copilot coding agent
  if: steps.check_concurrency.outputs.should_wait == 'false'
  env:
    # Use PAT instead of GITHUB_TOKEN
    GH_TOKEN: ${{ secrets.GH_COPILOT_PAT }}
  run: |
    ISSUE_NUMBER="${{ steps.issue.outputs.number }}"
    # ... rest of the script
```

### 4. Verify Setup

Trigger the workflow manually to test:

```bash
gh workflow run copilot-issue-assignment.yml --field issue_number=392
```

Check the workflow run to ensure it no longer shows the OAuth error.

## Alternative: Using GitHub App

If you prefer not to use a PAT, you can create a GitHub App with Copilot permissions:

1. Create a GitHub App at: https://github.com/settings/apps/new
2. Grant permissions: Codespaces, Contents, Issues, PRs, Workflows
3. Install the app on your repository
4. Generate a private key
5. Use the app credentials in your workflow with `actions/create-github-app-token@v1`

See: https://docs.github.com/en/apps/creating-github-apps

## Troubleshooting

### Error: "Context access might be invalid"
- This is a linting warning - the secret will work if configured
- Add `|| secrets.GITHUB_TOKEN` as fallback if needed

### Error: "gh agent-task: command not found"
- Ensure GitHub CLI is installed and up to date (v2.80.0+)
- Run: `gh version` to check

### Token Expired
- Tokens expire based on the duration you set
- You'll need to regenerate and update the secret when it expires
- Consider setting up token rotation automation

## Security Notes

- ⚠️ **Keep your PAT secure** - it has write access to your repository
- ✅ Use fine-grained tokens (not classic) for better security
- ✅ Set appropriate expiration dates
- ✅ Regularly audit and rotate tokens
- ✅ Use repository secrets (not environment variables in code)

## Status

- **Current State:** Workflow uses `GITHUB_TOKEN` (insufficient permissions)
- **Required:** Configure `GH_COPILOT_PAT` secret to enable Copilot automation
- **Impact:** Until configured, automated Copilot agent assignment will not work

## References

- [GitHub Fine-grained PATs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token)
- [GitHub CLI Authentication](https://cli.github.com/manual/gh_auth_login)
- [GitHub Copilot Agent Documentation](https://docs.github.com/en/copilot)
