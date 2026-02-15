# Unified Optimizer CLI Guide

**Version:** 1.0  
**Last Updated:** 2026-02-14  
**Status:** ✅ Complete

---

## Quick Start

The unified CLI provides a single entry point for all optimizer types:

```bash
python -m ipfs_datasets_py.optimizers.cli --type <OPTIMIZER_TYPE> <COMMAND> [OPTIONS]
```

**Optimizer Types:**
- `agentic` - Code optimization with multiple methods
- `logic` - Formal verification and theorem proving
- `graphrag` - Knowledge graph and ontology optimization

---

## Installation

```bash
# Install all optimizers
pip install -e ".[all]"

# Install specific optimizers
pip install -e ".[agentic]"    # Agentic optimizer
pip install -e ".[logic]"      # Logic theorem optimizer
pip install -e ".[graphrag]"   # GraphRAG optimizer
```

---

## Global Options

```bash
--type {agentic|logic|graphrag}  # Required: Optimizer type
--verbose, -v                     # Enable verbose output
--version                         # Show version information
--help, -h                        # Show help message
```

---

## Agentic Optimizer

**Focus:** Code optimization using AI-powered methods

### Commands

#### optimize
Run optimization task with specified method:
```bash
python -m ipfs_datasets_py.optimizers.cli --type agentic optimize \
    --method adversarial \
    --target myfile.py \
    --description "Optimize for performance"
```

**Methods:**
- `test_driven` - Generate tests first, then optimize
- `adversarial` - Generate multiple competing solutions
- `actor_critic` - Learn from feedback over time
- `chaos` - Inject faults to improve resilience

**Options:**
- `--method` - Optimization method (required)
- `--target` - Target file/directory (required, can repeat)
- `--description` - Task description (required)
- `--priority` - Task priority 0-100 (default: 50)
- `--dry-run` - Don't make actual changes

#### stats
Show optimization statistics:
```bash
python -m ipfs_datasets_py.optimizers.cli --type agentic stats
```

#### agents
Manage optimization agents:
```bash
# List all agents
python -m ipfs_datasets_py.optimizers.cli --type agentic agents list

# Show agent status
python -m ipfs_datasets_py.optimizers.cli --type agentic agents status <AGENT_ID>
```

#### queue
Manage task queue:
```bash
python -m ipfs_datasets_py.optimizers.cli --type agentic queue process
python -m ipfs_datasets_py.optimizers.cli --type agentic queue list
python -m ipfs_datasets_py.optimizers.cli --type agentic queue clear
```

#### rollback
Rollback a change:
```bash
python -m ipfs_datasets_py.optimizers.cli --type agentic rollback <PATCH_ID> [--force]
```

#### config
Manage configuration:
```bash
# Show configuration
python -m ipfs_datasets_py.optimizers.cli --type agentic config show

# Set configuration
python -m ipfs_datasets_py.optimizers.cli --type agentic config set \
    --key validation_level --value strict

# Reset configuration
python -m ipfs_datasets_py.optimizers.cli --type agentic config reset [--force]
```

#### validate
Validate code quality:
```bash
python -m ipfs_datasets_py.optimizers.cli --type agentic validate myfile.py \
    --level strict \
    [--sequential]
```

**Validation Levels:**
- `basic` - Syntax and AST only
- `standard` - + Type checking (default)
- `strict` - + Tests and security
- `paranoid` - + Performance analysis

### Complete Example

```bash
# 1. Configure optimizer
python -m ipfs_datasets_py.optimizers.cli --type agentic config set \
    --key validation_level --value strict

# 2. Run optimization
python -m ipfs_datasets_py.optimizers.cli --type agentic optimize \
    --method adversarial \
    --target slow_function.py \
    --description "Optimize processing speed"

# 3. Check stats
python -m ipfs_datasets_py.optimizers.cli --type agentic stats

# 4. Validate result
python -m ipfs_datasets_py.optimizers.cli --type agentic validate \
    slow_function.py --level paranoid
```

---

## Logic Theorem Optimizer

**Focus:** Formal verification and theorem proving

### Commands

#### extract
Extract logical statements from text:
```bash
python -m ipfs_datasets_py.optimizers.cli --type logic extract \
    --input contract.txt \
    --output logic.json \
    --domain legal \
    --format fol
```

**Options:**
- `--input, -i` - Input file (required)
- `--output, -o` - Output file
- `--domain` - Domain context (legal, scientific, general)
- `--format` - Logic format (fol, tdfol, cec)

#### prove
Prove theorems using integrated provers:
```bash
python -m ipfs_datasets_py.optimizers.cli --type logic prove \
    --theorem "A implies B" \
    --premises "A" \
    --goal "B" \
    --prover z3 \
    --timeout 30
```

**Options:**
- `--theorem` - Theorem to prove (required)
- `--premises` - Premises (can repeat)
- `--goal` - Goal to prove (required)
- `--prover` - Prover to use (z3, cvc5, lean, coq, all)
- `--timeout` - Timeout in seconds

#### validate
Validate logical consistency:
```bash
python -m ipfs_datasets_py.optimizers.cli --type logic validate \
    --input ontology.owl \
    --check-consistency \
    --check-completeness \
    --output report.json
```

**Options:**
- `--input, -i` - Input file (required)
- `--check-consistency` - Check logical consistency
- `--check-completeness` - Check completeness
- `--output, -o` - Output validation report

#### optimize
Run optimization cycles:
```bash
python -m ipfs_datasets_py.optimizers.cli --type logic optimize \
    --input data/ \
    --cycles 5 \
    --parallel \
    --output optimization_report.json
```

**Options:**
- `--input, -i` - Input data (required)
- `--cycles` - Number of cycles (default: 3)
- `--parallel` - Run in parallel
- `--output, -o` - Output report

#### status
Show optimizer capabilities:
```bash
python -m ipfs_datasets_py.optimizers.cli --type logic status
```

### Complete Example

```bash
# 1. Extract logic from legal document
python -m ipfs_datasets_py.optimizers.cli --type logic extract \
    --input rental_contract.txt \
    --domain legal \
    --format fol \
    --output contract_logic.json

# 2. Validate consistency
python -m ipfs_datasets_py.optimizers.cli --type logic validate \
    --input contract_logic.json \
    --check-consistency \
    --output validation_report.json

# 3. Prove a property
python -m ipfs_datasets_py.optimizers.cli --type logic prove \
    --theorem "tenant_pays_rent implies landlord_maintains_property" \
    --goal "landlord_maintains_property" \
    --prover all

# 4. Optimize extraction quality
python -m ipfs_datasets_py.optimizers.cli --type logic optimize \
    --input contracts/ \
    --cycles 3 \
    --parallel
```

---

## GraphRAG Optimizer

**Focus:** Knowledge graph and ontology optimization

### Commands

#### generate
Generate ontology from documents:
```bash
python -m ipfs_datasets_py.optimizers.cli --type graphrag generate \
    --input document.pdf \
    --domain legal \
    --strategy hybrid \
    --format owl \
    --output ontology.owl
```

**Options:**
- `--input, -i` - Input file (required)
- `--output, -o` - Output ontology file
- `--domain` - Domain context (legal, scientific, medical, general)
- `--strategy` - Extraction strategy (rule_based, neural, hybrid)
- `--format` - Output format (owl, rdf, json)

#### optimize
Optimize knowledge graph structure:
```bash
python -m ipfs_datasets_py.optimizers.cli --type graphrag optimize \
    --input ontology.owl \
    --cycles 5 \
    --target all \
    --parallel \
    --output optimized.owl
```

**Options:**
- `--input, -i` - Input ontology (required)
- `--cycles` - Optimization cycles (default: 3)
- `--target` - Target (structure, consistency, coverage, all)
- `--parallel` - Run in parallel
- `--output, -o` - Output optimized ontology

#### validate
Validate ontology quality:
```bash
python -m ipfs_datasets_py.optimizers.cli --type graphrag validate \
    --input ontology.owl \
    --check-consistency \
    --check-coverage \
    --check-clarity \
    --output validation_report.json
```

**Options:**
- `--input, -i` - Input ontology (required)
- `--check-consistency` - Check logical consistency
- `--check-coverage` - Check domain coverage
- `--check-clarity` - Check relationship clarity
- `--output, -o` - Output report

#### query
Query optimization for RAG:
```bash
python -m ipfs_datasets_py.optimizers.cli --type graphrag query \
    --ontology my_kg.owl \
    --query "climate change impacts" \
    --optimize \
    --explain \
    --output results.json
```

**Options:**
- `--ontology` - Knowledge graph file (required)
- `--query` - Query string (required)
- `--optimize` - Optimize query performance
- `--explain` - Explain query execution
- `--output, -o` - Output results

#### status
Show optimizer capabilities:
```bash
python -m ipfs_datasets_py.optimizers.cli --type graphrag status
```

### Complete Example

```bash
# 1. Generate ontology from PDF
python -m ipfs_datasets_py.optimizers.cli --type graphrag generate \
    --input legal_document.pdf \
    --domain legal \
    --strategy hybrid \
    --output legal_kg.owl

# 2. Validate quality
python -m ipfs_datasets_py.optimizers.cli --type graphrag validate \
    --input legal_kg.owl \
    --check-consistency \
    --check-coverage \
    --output validation.json

# 3. Optimize structure
python -m ipfs_datasets_py.optimizers.cli --type graphrag optimize \
    --input legal_kg.owl \
    --cycles 5 \
    --target all \
    --output legal_kg_optimized.owl

# 4. Query optimization
python -m ipfs_datasets_py.optimizers.cli --type graphrag query \
    --ontology legal_kg_optimized.owl \
    --query "contract obligations" \
    --optimize \
    --explain
```

---

## Choosing the Right Optimizer

Use the selection guide:
```bash
# See comprehensive comparison and decision tree
cat docs/optimizers/SELECTION_GUIDE.md
```

**Quick Guide:**
- **Code optimization?** → `--type agentic`
- **Formal verification?** → `--type logic`
- **Knowledge graphs?** → `--type graphrag`

---

## Error Handling

### Optimizer Not Available
If an optimizer is not installed:
```
Error: Agentic optimizer not available: No module named 'xyz'
Install with: pip install -e '.[agentic]'
```

**Solution:** Install the required optimizer package.

### Missing Dependencies
Some features require additional dependencies:
```bash
pip install numpy scipy matplotlib  # For visualizations
pip install torch transformers      # For neural strategies
```

### Verbose Mode
For debugging, use verbose mode:
```bash
python -m ipfs_datasets_py.optimizers.cli --verbose --type agentic stats
```

---

## Tips & Best Practices

### Agentic Optimizer
1. Start with `test_driven` for quick results
2. Use `adversarial` when exploring solution space
3. Set validation level based on criticality:
   - Development: `basic`
   - Production: `strict` or `paranoid`
4. Use `--dry-run` to preview changes

### Logic Theorem Optimizer
1. Choose appropriate logic format:
   - `fol` - Most widely supported
   - `tdfol` - For typed logic
   - `cec` - For CEC framework
2. Start with `z3` prover for speed
3. Use `--prover all` for maximum confidence
4. Specify domain for better extraction

### GraphRAG Optimizer
1. Choose extraction strategy:
   - `rule_based` - Fast, deterministic
   - `neural` - Flexible, powerful
   - `hybrid` - Best of both (recommended)
2. Validate before optimizing
3. Use multiple cycles for better results
4. Enable `--parallel` for large datasets

---

## Integration with Other Tools

### CI/CD Integration
```yaml
# .github/workflows/optimize.yml
- name: Run optimization
  run: |
    python -m ipfs_datasets_py.optimizers.cli \
      --type agentic optimize \
      --method test_driven \
      --target src/ \
      --description "CI optimization"
```

### Scripting
```bash
#!/bin/bash
# optimize_all.sh
for file in src/*.py; do
    python -m ipfs_datasets_py.optimizers.cli \
        --type agentic validate "$file" --level strict
done
```

### Docker
```dockerfile
RUN pip install -e ".[all]"
CMD ["python", "-m", "ipfs_datasets_py.optimizers.cli", "--type", "agentic", "stats"]
```

---

## Troubleshooting

### Command Not Found
```bash
# Ensure module path is correct
python -m ipfs_datasets_py.optimizers.cli --version

# Or add to PATH
export PATH="$PATH:$(pwd)"
./ipfs_datasets_py/optimizers/cli.py --version
```

### Import Errors
Check dependencies:
```bash
python -c "from ipfs_datasets_py.optimizers import agentic, logic_theorem_optimizer, graphrag"
```

### Permission Errors
Ensure write permissions:
```bash
chmod +w .optimizer-config.json
chmod +w output/
```

---

## Additional Resources

- **Selection Guide:** `docs/optimizers/SELECTION_GUIDE.md`
- **Implementation Details:** `OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md`
- **Quick Start:** `OPTIMIZER_IMPROVEMENTS_QUICKSTART.md`
- **API Documentation:** See each optimizer's README

---

**Questions?** Check the FAQ in SELECTION_GUIDE.md or open an issue on GitHub.

**Version:** 1.0  
**Status:** ✅ Production Ready
