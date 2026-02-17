# CLI Usage Guide

Complete guide to using ipfs-datasets command-line interface.

## Installation

```bash
pip install -e ".[all]"
```

## Basic Usage

```bash
ipfs-datasets [command] [subcommand] [options]
```

## Graph Commands

### create - Initialize graph database

```bash
ipfs-datasets graph create --driver-url ipfs://localhost:5001
```

### add-entity - Add entity to graph

```bash
ipfs-datasets graph add-entity \
    --id person1 \
    --type Person \
    --props '{"name":"Alice","age":30}'
```

### add-rel - Add relationship

```bash
ipfs-datasets graph add-rel \
    --source person1 \
    --target person2 \
    --type KNOWS \
    --props '{"since":2020}'
```

### query - Execute Cypher query

```bash
ipfs-datasets graph query --cypher "MATCH (n) RETURN n LIMIT 10"

# With parameters
ipfs-datasets graph query \
    --cypher "MATCH (p:Person) WHERE p.age > \$min_age RETURN p" \
    --params '{"min_age":25}'
```

### search - Hybrid search

```bash
ipfs-datasets graph search \
    --query "machine learning" \
    --type hybrid \
    --limit 20
```

### tx-begin - Begin transaction

```bash
ipfs-datasets graph tx-begin
```

### tx-commit - Commit transaction

```bash
ipfs-datasets graph tx-commit --tx-id abc123
```

### tx-rollback - Rollback transaction

```bash
ipfs-datasets graph tx-rollback --tx-id abc123
```

### index - Create index

```bash
ipfs-datasets graph index --label Person --property name
```

### constraint - Add constraint

```bash
ipfs-datasets graph constraint \
    --label Person \
    --property email \
    --type unique
```

## Dataset Commands

```bash
# Load dataset
ipfs-datasets dataset load squad

# Load with options
ipfs-datasets dataset load squad --split train --format json
```

## IPFS Commands

```bash
# Pin content
ipfs-datasets ipfs pin --content "my data"

# Pin file
ipfs-datasets ipfs pin --file /path/to/file.txt

# Get from IPFS
ipfs-datasets ipfs get --cid QmHash123
```

## Vector Commands

```bash
# Search vectors
ipfs-datasets vector search --query "machine learning" --limit 10
```

## Output Formats

Most commands support multiple output formats:

```bash
# Pretty printed (default)
ipfs-datasets graph query --cypher "MATCH (n) RETURN n"

# JSON output
ipfs-datasets graph query --cypher "MATCH (n) RETURN n" --output json

# Compact format
ipfs-datasets graph query --cypher "MATCH (n) RETURN n" --output compact
```

## Error Handling

CLI provides helpful error messages:

```bash
$ ipfs-datasets graph query
Error: --cypher required

Usage: ipfs-datasets graph query --cypher <query> [--params <json>]
```

## See Also

- [Getting Started](GETTING_STARTED.md)
- [API Reference](../api/CORE_OPERATIONS_API.md)
- [Examples](../../examples/)
