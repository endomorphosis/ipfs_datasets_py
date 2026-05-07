# GitHub Copilot CLI Integration

## Overview

This repository uses two different Copilot command-line surfaces, and they are not interchangeable:

1. `gh copilot`
Used for shell and explanation helpers such as `gh copilot suggest` and `gh copilot explain`.

2. `copilot`
Used for local non-interactive prompt mode and agentic task execution.

3. GitHub-hosted `@copilot` or PR/issue workflows
These are separate GitHub product flows, not the local CLI wrapper used by this package.

The codebase now follows that split explicitly:

- `ipfs-datasets copilot ...` wraps the `gh copilot` extension.
- `llm_router` and related fallback paths use the standalone `copilot` binary.
- Docs should not describe `gh copilot` as an autonomous file-editing agent.

## What The Repo Uses

### `gh copilot` extension

This is the surface wrapped by `ipfs_datasets_py.utils.copilot_cli.CopilotCLI`.

Supported operations in this repo:

- status and installation checks
- command suggestions
- code explanations
- MCP development-tool wrappers around those same operations

Typical commands:

```bash
gh copilot suggest "find the largest files in this repo"
gh copilot explain "git rebase --rebase-merges origin/main"
```

### standalone `copilot`

This is the surface used by `llm_router`, SyMAI fallback generation, and implementation-daemon fallback command construction.

The default non-interactive template is now:

```bash
copilot --silent --stream off --allow-all-tools --no-ask-user --model <model> -p "<prompt>"
```

That matches the installed CLI help more closely than the old `npx --yes @github/copilot` assumption.

## Installation And Verification

### Verify `gh copilot`

```bash
gh copilot --help
ipfs-datasets copilot status
```

If the extension is missing:

```bash
ipfs-datasets copilot install
```

### Verify standalone `copilot`

```bash
copilot --help
copilot --version
```

If the binary is installed somewhere custom, set:

```bash
export COPILOT_CLI_PATH=/absolute/path/to/copilot
```

## Environment Variables

The repo recognizes these Copilot-related settings:

- `COPILOT_CLI_PATH`: explicit standalone `copilot` binary path
- `IPFS_DATASETS_PY_COPILOT_CLI_CMD`: override the standalone command template used by router-style generation
- `IPFS_DATASETS_PY_COPILOT_CLI_MODEL`: preferred standalone Copilot model for router calls

If `IPFS_DATASETS_PY_COPILOT_CLI_CMD` is unset, the repo now defaults to the local `copilot` binary instead of `npx`.

## Repo Conventions

### Use `ipfs-datasets copilot` for helper flows

These commands talk to `gh copilot` and are intended for command suggestions or explanations:

```bash
ipfs-datasets copilot status
ipfs-datasets copilot suggest "list files modified today"
ipfs-datasets copilot git "undo the last commit but keep the changes"
ipfs-datasets copilot explain "pytest -k wallet_release --maxfail=1"
```

### Use standalone `copilot` for autonomous local work

For local agentic work, call the standalone binary directly:

```bash
copilot --silent --stream off --allow-all-tools --no-ask-user -p "Summarize the failing tests in this repository"
```

Add `--allow-all-paths` only when the task genuinely needs filesystem access outside the current working tree.

## Guidance For Automation

### Local automation

Use the standalone `copilot` binary for local scripted prompting and repo-aware agentic work.

### In-process Python integrations

Use the package wrappers instead of shelling out ad hoc:

- `ipfs_datasets_py.utils.copilot_cli.CopilotCLI` for `gh copilot`
- `ipfs_datasets_py.utils.cli_tools.StandaloneCopilot` for standalone `copilot`

### GitHub-hosted workflows

Do not assume that `@copilot` comments, draft-PR workflows, or other GitHub-hosted automation are equivalent to local CLI execution. Those flows should be documented separately as GitHub product workflows, not as CLI behavior.

## Known Non-Goals

This guide does not treat `gh agent-task` as a canonical or verified repo workflow. Historical docs in the repository mention it, but the maintained local integration points are `gh copilot` and standalone `copilot`.

## Troubleshooting

### `ipfs-datasets copilot status` shows GitHub CLI but not Copilot

The base `gh` binary exists, but the `gh-copilot` extension is missing. Install it with `ipfs-datasets copilot install`.

### Router Copilot calls fail even though `gh copilot` works

Those are different binaries. `llm_router` uses standalone `copilot`, not `gh copilot`.

### Standalone Copilot is installed in a custom location

Set `COPILOT_CLI_PATH` or override `IPFS_DATASETS_PY_COPILOT_CLI_CMD`.

### Installation Issues

```bash
# Permission denied
sudo npm install -g @github/copilot

# Check Node.js version
node --version  # Should be 22+
npm --version   # Should be 10+
```

### Authentication Issues

```bash
# Ensure GitHub CLI is authenticated
gh auth status

# Re-authenticate if needed
gh auth login
```

### Tool Permission Issues

```bash
# If tools are blocked, use --allow-all-tools
copilot -p "your prompt" --allow-all-tools

# Or allow specific tools
copilot -p "your prompt" --allow-tool 'shell(git)' --allow-tool 'shell(gh)'
```

### Timeout Issues

The Python wrapper has a 5-minute timeout per command. For long-running tasks:

```bash
# Split into smaller tasks
copilot -p "Work on PR #246 only" --allow-all-tools

# Instead of
copilot -p "Work on all 30 PRs" --allow-all-tools
```

## Examples

### Example 1: Fix Permission Error

```bash
copilot -p "PR #246 has a permission error in the GitHub Actions workflow. \
Checkout the branch, analyze the error logs, implement the fix (probably \
needs to chmod or fix ownership), commit and push." --allow-all-tools
```

### Example 2: Fix Syntax Error

```bash
copilot -p "PR #242 has an IndentationError in comprehensive_runner_validation.py. \
Checkout the branch, fix the indentation, run the file to verify it works, \
then commit and push." --allow-all-tools
```

### Example 3: Review and Improve

```bash
copilot -p "Review PR #246, suggest improvements to the fix, and implement \
them if they make sense. Focus on following Python best practices." --allow-all-tools
```

## Integration with Existing Tools

### Works with

- ✅ `scripts/batch_assign_copilot_to_prs.py` - Assign @copilot to PRs
- ✅ `scripts/invoke_copilot_coding_agent_on_prs.py` - Intelligent task assignment
- ✅ `scripts/copilot_pr_manager.py` - Interactive PR management
- ✅ `scripts/automated_pr_review.py` - Weighted PR analysis
- ✅ `.github/workflows/pr-copilot-reviewer.yml` - Automated reviews

### Workflow

1. **Auto-healing creates PR** → `.github/workflows/copilot-agent-autofix.yml`
2. **Assign @copilot** → `batch_assign_copilot_to_prs.py`
3. **Copilot CLI implements** → `copilot_cli_pr_worker.py`
4. **Human reviews** → GitHub UI
5. **Merge** → `gh pr merge`

## Next Steps

### Immediate Actions

1. **Test on a single PR:**
   ```bash
   python scripts/copilot_cli_pr_worker.py --pr 242 --dry-run
   python scripts/copilot_cli_pr_worker.py --pr 242
   ```

2. **Monitor progress:**
   ```bash
   gh pr view 242
   gh pr checks 242
   ```

3. **Scale to batch processing:**
   ```bash
   python scripts/copilot_cli_pr_worker.py --all --limit 5
   ```

### Future Enhancements

- [ ] Add Copilot CLI to GitHub Actions workflows
- [ ] Create scheduled job to process PRs nightly
- [ ] Integrate with MCP dashboard for monitoring
- [ ] Add metrics tracking (success rate, time per PR)
- [ ] Implement smart prioritization (syntax errors first, then permissions)

## Resources

- **Copilot CLI Docs:** https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli
- **Installation Guide:** https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli
- **Coding Agent:** https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- **Code Review Agent:** https://docs.github.com/en/copilot/concepts/agents/code-review

## Summary

The GitHub Copilot CLI provides **autonomous PR implementation** capabilities that complement the existing @copilot comment system. It can:

- 🔍 Analyze 31 draft PRs waiting for implementation
- 🔧 Implement fixes for permission, syntax, and other errors
- 🚀 Process PRs in batch (recommended: 5-10 at a time)
- ✅ Commit and push changes automatically
- 📊 Provide detailed analysis and summaries

**Status:** ✅ Installed, tested, and ready for production use

**Next:** Run `python scripts/copilot_cli_pr_worker.py --pr 242` to fix the syntax error in PR #242
