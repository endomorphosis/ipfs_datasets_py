# Infrastructure Guides

CI/CD, development infrastructure, and automation documentation.

## Contents

- [AnyIO Migration Guide](anyio_migration_guide.md) - Async framework migration
- [Copilot Auto-Fix PRs](copilot_auto_fix_all_prs.md) - Automated PR fixes
- [Copilot Invocation Update](copilot_invocation_update.md) - Copilot integration updates
- [Copilot Queue Integration](copilot_queue_integration.md) - Queue-based Copilot processing
- [GitHub CLI Rate Limiting](github_cli_rate_limiting.md) - Managing GitHub API limits
- [PR Copilot Throttling](pr_copilot_throttling.md) - Copilot throttling strategies
- [VS Code CLI Integration](vscode_cli_integration.md) - VS Code command-line integration

## CI/CD Infrastructure

### GitHub Actions
- **Auto-Healing System**: Automatically turns workflow failures into issues and draft PRs
- **Self-Hosted Runners**: x86_64, ARM64, and GPU runners
- **Multi-Architecture**: Support for different architectures

### Copilot Integration
- Automated code fixes
- PR generation from failures
- Queue-based processing
- Rate limit management

## Development Tools

### CLI Tools
- Enhanced CLI with 200+ tools
- VS Code CLI integration
- Command-line automation

### Automation
- Automated testing
- Auto-healing workflows
- Dependency management

## Infrastructure Setup

### GitHub Actions Runners

See deployment guides:
- [Runner Setup](../deployment/runner_setup.md) - Standard runners
- [ARM64 Runner Setup](../deployment/arm64_runner_setup.md) - ARM runners
- [GPU Runner Setup](../deployment/gpu_runner_setup.md) - GPU runners

### Auto-Healing System

The auto-healing system:
1. Monitors 13+ workflows
2. Creates issues for failures
3. Generates draft PRs
4. Invokes Copilot for fixes
5. Automates resolution

### Rate Limiting

Managing GitHub API limits:
- Request throttling
- Queue-based processing
- Retry strategies
- Fallback mechanisms

## Related Documentation

- [GitHub Actions Architecture](../../architecture/github_actions_architecture.md) - System design
- [Deployment Guides](../deployment/) - Runner deployment
- [Developer Guide](../../developer_guide.md) - Development setup

## Contributing

To improve infrastructure:
1. Test changes in isolation
2. Document configuration
3. Update relevant guides
4. Test with self-hosted runners
