# GitHub Copilot Automation Setup

## Overview

This repository has historically mixed together three separate Copilot automation surfaces:

1. local `gh copilot` extension commands
2. local standalone `copilot` CLI prompt mode
3. GitHub-hosted `@copilot` comment or PR workflows

This guide only describes how to reason about those surfaces safely. It does not treat `gh agent-task` as a canonical or verified repo workflow.

## Recommended Split

### Local helper commands

Use `gh copilot` when you want shell suggestions or explanations.

Examples:

```bash
gh copilot suggest "find the biggest test files"
gh copilot explain "git cherry-pick --no-commit <sha>"
```

The package wrapper for this path is `ipfs_datasets_py.utils.copilot_cli.CopilotCLI`.

### Local autonomous prompt mode

Use standalone `copilot` when you want local agentic execution in the working tree.

Example:

```bash
copilot --silent --stream off --allow-all-tools --no-ask-user --prompt "Inspect this repo and summarize failing tests"
```

The package wrapper for this path is `ipfs_datasets_py.utils.cli_tools.StandaloneCopilot`.

### GitHub-hosted PR or comment workflows

Treat `@copilot` mentions and related GitHub product features as separate hosted workflows. They should be documented as GitHub automation behavior, not as CLI behavior.

## What To Configure

### For local standalone `copilot`

Verify the binary:

```bash
copilot --help
copilot --version
```

If it is not on `PATH`, set:

```bash
export COPILOT_CLI_PATH=/absolute/path/to/copilot
```

### For local `gh copilot`

Verify the extension:

```bash
gh copilot --help
ipfs-datasets copilot status
```

If your automation needs the standalone binary instead of the GitHub CLI
extension, verify it with:

```bash
ipfs-datasets copilot local-status
```

Install it if needed:

```bash
ipfs-datasets copilot install
```

## CI/CD Guidance

If CI/CD needs local Copilot CLI behavior, prefer explicit installation and explicit command invocation of the standalone `copilot` binary. Do not assume legacy docs mentioning `gh agent-task` still describe a maintained path in this repo.

If CI/CD needs GitHub-hosted Copilot behavior, document that separately as a GitHub workflow integration and validate it against the current product docs before relying on it.

## Recommendation

Use this decision rule:

1. Need suggestions or explanations: use `gh copilot`.
2. Need local autonomous execution: use standalone `copilot`.
3. Need GitHub-hosted PR/comment behavior: document and validate that workflow separately.

## Troubleshooting

### `gh copilot` works but router Copilot calls fail

The router uses standalone `copilot`, not the GitHub CLI extension.

### standalone `copilot` works but `ipfs-datasets copilot` fails

The `ipfs-datasets copilot` wrapper targets `gh copilot`, so install the GitHub CLI extension.

### Historical docs mention `gh agent-task`

Treat that as legacy documentation until it is re-verified against the current GitHub tooling surface. The maintained wrapper now reports whether the installed `gh` binary actually supports `agent-task`.
