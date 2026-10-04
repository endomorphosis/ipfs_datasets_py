# User Guides

Practical guides for using and deploying the MCP server.

## Available Guides

### [p2p-migration.md](./p2p-migration.md)
Guide for migrating from traditional client-server architecture to P2P infrastructure. Covers:
- Why P2P for MCP tools
- Migration steps and considerations
- Runtime router configuration
- Performance benefits (60% latency reduction)

### [performance-tuning.md](./performance-tuning.md)
Comprehensive performance tuning guide. Includes:
- Performance analysis and benchmarking
- Optimization strategies
- Context window management
- Latency reduction techniques

### [performance-profiling.md](./performance-profiling.md)
Profiling and benchmarking guide for the MCP server's hot paths. Covers:
- Profiling `dispatch_parallel` latency
- Using pyinstrument, memray, pytest-benchmark
- Interpreting and acting on profiling results

### [cookbook.md](./cookbook.md)
Ready-to-run recipes for common tasks. Covers:
- Parallel tool dispatch with `dispatch_parallel`
- Adaptive batching and fail-fast patterns
- Real-world usage examples

## Related Documentation

- [Quick Start](../../QUICKSTART.md) - Get started quickly
- [Architecture](../architecture/) - Technical design docs
- [API Reference](../api/tool-reference.md) - Complete API documentation
