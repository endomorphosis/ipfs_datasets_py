# Neural/LLM-Based Prover Integration

This directory contains integrations with neural and LLM-based reasoning systems.

## Available Provers

### SymbolicAI ✅ **WORKING**

**File:** `symbolicai_prover_bridge.py` (14.2 KB)

**Developer:** ExtensityAI  
**Website:** https://github.com/ExtensityAI/symbolicai

**Features:**
- LLM-powered semantic reasoning
- Natural language ↔ Logic conversion
- Formula explanations
- Proof strategy suggestions
- Multi-LLM support (OpenAI, Anthropic, etc.)
- Hybrid neural + symbolic proving

**Installation:**
```bash
pip install symbolicai

# Set API key
export OPENAI_API_KEY="your-key"
# or
export ANTHROPIC_API_KEY="your-key"
```

**Usage:**
```python
from ipfs_datasets_py.logic.external_provers.neural import SymbolicAIProverBridge

prover = SymbolicAIProverBridge(
    confidence_threshold=0.8,
    enable_cache=True
)

# Prove with neural reasoning
result = prover.prove(formula, strategy='neural_guided')

# Get explanation
explanation = prover.explain(formula)

# Get proof strategies
strategies = prover.suggest_proof_strategy(formula)
```

**Performance:**
- Average: 1000-5000ms (uncached)
- Success rate: ~75% on FOL
- With cache: 0.1ms (10000-50000x speedup!)
- Cost: ~$0.01 per uncached query

---

## Neural vs Other Approaches

| Feature | Neural (SymbolicAI) | SMT (Z3) | Native |
|---------|-------------------|----------|---------|
| Speed (uncached) | Slow (1-5s) | Fast (10-100ms) | Very Fast (1-10ms) |
| Speed (cached) | ⚡ 0.1ms | ⚡ 0.1ms | ⚡ 0.1ms |
| NL Understanding | ✅ Excellent | ❌ No | ❌ No |
| Explanations | ✅ Yes | ❌ No | ❌ No |
| Correctness | ⚠️ Probabilistic | ✅ Proven | ✅ Proven |
| Cost | 💰 API fees | ✅ Free | ✅ Free |
| Semantic Reasoning | ✅ Excellent | ❌ No | ⚠️ Limited |

## Key Advantages

### 1. Natural Language Understanding

```python
prover = SymbolicAIProverBridge()

# Convert natural language to logic
text = "All humans are mortal. Socrates is human."
# LLM can understand and convert to formal logic

# Explain formulas in plain English
formula = parse_tdfol("forall x. P(x) -> Q(x)")
explanation = prover.explain(formula)
print(explanation)
# "For all x, if P holds for x, then Q also holds for x..."
```

### 2. Proof Strategy Suggestions

```python
formula = parse_tdfol("(P & Q) -> R")
strategies = prover.suggest_proof_strategy(formula)

# Output might include:
# - "Use conjunction elimination on P & Q"
# - "Apply modus ponens"
# - "Try proof by contradiction"
```

### 3. Hybrid Proving

```python
prover = SymbolicAIProverBridge(use_symbolic_fallback=True)

# Neural reasoning first
result = prover.prove(formula, strategy='hybrid')

# If confidence < 0.8, automatically falls back to symbolic
if result.fallback_used:
    print("Symbolic prover confirmed the result!")
```

### 4. Caching for Cost Savings

```python
prover = SymbolicAIProverBridge(enable_cache=True)

# First call: LLM API call (~$0.01)
result1 = prover.prove(formula)  # 3000ms, $0.01

# Second call: Cache hit (free!)
result2 = prover.prove(formula)  # 0.1ms, $0.00

# 1000 queries with 50% hit rate:
# Without cache: $10, ~50 minutes
# With cache: $5, ~25 minutes
# Savings: $5, 25 minutes!
```

## Strategies

### 1. Neural Guided (Default)

```python
result = prover.prove(formula, strategy='neural_guided')
```

- LLM analyzes formula
- Suggests reasoning steps
- Optional symbolic fallback

### 2. Pure Neural

```python
result = prover.prove(formula, strategy='pure_neural')
```

- LLM reasoning only
- No symbolic fallback
- Fastest neural option

### 3. Hybrid

```python
result = prover.prove(formula, strategy='hybrid')
```

- Neural first, then symbolic
- Best of both worlds
- Highest confidence

## Best Practices

### 1. Always Enable Caching

```python
# LLM calls are expensive!
prover = SymbolicAIProverBridge(enable_cache=True)
```

### 2. Set Appropriate Confidence Threshold

```python
# Higher threshold = more fallback to symbolic
prover = SymbolicAIProverBridge(confidence_threshold=0.8)
```

### 3. Use for the Right Tasks

**Good for:**
- Natural language understanding
- Semantic reasoning
- Formula explanations
- Proof guidance
- When formal methods fail

**Not ideal for:**
- Pure arithmetic
- Time-critical paths (unless cached)
- When 100% correctness required
- Cost-sensitive applications (unless cached)

### 4. Monitor Costs

```python
from ipfs_datasets_py.logic.external_provers.monitoring import get_global_monitor

monitor = get_global_monitor()

# Track all proofs
with monitor.track_proof("symbolicai"):
    result = prover.prove(formula)

# Check costs
stats = monitor.get_stats("symbolicai")
uncached = stats['cache_misses']
cost_estimate = uncached * 0.01  # $0.01 per call
print(f"Estimated cost: ${cost_estimate:.2f}")
```

## Result Structure

```python
@dataclass
class NeuralProofResult:
    is_valid: bool              # Whether formula is valid
    confidence: float           # Confidence (0.0-1.0)
    reasoning: List[str]        # Step-by-step reasoning
    proof_sketch: str           # Informal proof
    counterexample: str         # Counterexample if not valid
    fallback_used: bool         # Whether symbolic was used
    proof_time: float           # Time in seconds
    llm_used: str              # LLM engine used
```

## Code Reuse

SymbolicAI integration reuses **1,876 LOC** of existing code:

- `logic/integration/symbolic_fol_bridge.py` (563 LOC)
- `logic/integration/symbolic_contracts.py` (763 LOC)
- `logic/integration/symbolic_logic_primitives.py` (550 LOC)

Only **14.2 KB** of new code was needed for the prover bridge!

## Troubleshooting

### API Key Not Set

```
Error: No API key configured
```

**Solution:**
```bash
export OPENAI_API_KEY="your-key"
# or
export ANTHROPIC_API_KEY="your-key"
```

### Slow Performance

```
Taking 5+ seconds per proof
```

**Solutions:**
1. Enable caching: `enable_cache=True`
2. Use cache warming for common queries
3. Consider hybrid strategy with symbolic fallback
4. Check network connectivity

### High Costs

```
API bills increasing
```

**Solutions:**
1. Enable caching (saves 50%+ with normal hit rates)
2. Monitor cache hit rates
3. Use for appropriate tasks only
4. Consider local LLM models (if supported)

---

**Last Updated:** February 12, 2026
