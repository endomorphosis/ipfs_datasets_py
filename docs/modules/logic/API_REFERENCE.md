# Logic Modules - API Reference

Complete API reference for the logic modules.

## Table of Contents

1. [FOL Conversion API](#fol-conversion-api)
2. [Deontic Logic API](#deontic-logic-api)
3. [Proof Execution API](#proof-execution-api)
4. [Caching API](#caching-api)
5. [Batch Processing API](#batch-processing-api)
6. [Benchmarking API](#benchmarking-api)
7. [ML Confidence API](#ml-confidence-api)

---

## FOL Conversion API

### `convert_text_to_fol()`

Convert natural language text to First-Order Logic formulas.

```python
async def convert_text_to_fol(
    text_input: Union[str, Dict[str, Any]],
    domain_predicates: Optional[List[str]] = None,
    output_format: str = "json",
    confidence_threshold: float = 0.7,
    include_metadata: bool = True,
    use_nlp: bool = True,
) -> Dict[str, Any]
```

**Parameters:**
- `text_input`: Natural language text string or dataset dictionary
- `domain_predicates`: Optional list of domain-specific predicate names
- `output_format`: Output format - "json", "prolog", or "tptp"
- `confidence_threshold`: Minimum confidence (0.0-1.0) for including results
- `include_metadata`: Whether to include metadata in output
- `use_nlp`: Use NLP-enhanced extraction (spaCy) vs regex fallback

**Returns:**
Dictionary with structure:
```python
{
    "status": "success",
    "fol_formulas": [
        {
            "original_text": str,
            "fol_formula": str,
            "confidence": float,
            "predicates_used": List[str],
            "quantifiers": List[str],
            "operators": List[str]
        }
    ],
    "summary": {
        "total_statements": int,
        "successful_conversions": int,
        "conversion_rate": float,
        "average_confidence": float,
        "unique_predicates": List[str],
        "quantifier_distribution": Dict[str, int],
        "operator_distribution": Dict[str, int]
    },
    "metadata": {...}
}
```

**Example:**
```python
result = await convert_text_to_fol(
    "All humans are mortal",
    confidence_threshold=0.7,
    use_nlp=True
)
```

---

### `extract_predicates_nlp()`

Extract predicates using NLP with fallback to regex.

```python
def extract_predicates_nlp(
    text: str,
    use_spacy: bool = True,
    spacy_model: str = "en_core_web_sm"
) -> Dict[str, List[str]]
```

**Parameters:**
- `text`: Natural language text to analyze
- `use_spacy`: Whether to attempt spaCy extraction
- `spacy_model`: Name of spaCy model to use

**Returns:**
```python
{
    "nouns": List[str],
    "verbs": List[str],
    "adjectives": List[str],
    "relations": List[str],
    "entities": List[str]  # Only with spaCy
}
```

**Example:**
```python
predicates = extract_predicates_nlp(
    "The quick brown fox jumps",
    use_spacy=True
)
```

---

### `extract_semantic_roles()`

Extract semantic roles (agent, patient, action) from text.

```python
def extract_semantic_roles(
    text: str,
    use_spacy: bool = True
) -> List[Dict[str, Any]]
```

**Parameters:**
- `text`: Natural language text
- `use_spacy`: Whether to use spaCy (required for SRL)

**Returns:**
```python
[
    {
        "action": str,
        "agent": Optional[str],
        "patient": Optional[str],
        "location": Optional[str],
        "time": Optional[str]
    }
]
```

**Example:**
```python
roles = extract_semantic_roles("John gives Mary a book")
# [{"action": "give", "agent": "John", "patient": "book"}]
```

---

## Deontic Logic API

### `detect_normative_conflicts()`

Detect conflicts between deontic norms.

```python
def detect_normative_conflicts(
    norms: List[Dict[str, Any]]
) -> List[Dict[str, Any]]
```

**Parameters:**
- `norms`: List of norm dictionaries with structure:
  ```python
  {
      "type": DeonticOperator,  # OBLIGATION, PERMISSION, PROHIBITION
      "action": str,
      "subject": str,
      "temporal_constraint": Optional[Dict],
      "condition": Optional[str],
      "authority_level": Optional[str],
      "created_at": Optional[str]
  }
  ```

**Returns:**
```python
[
    {
        "type": str,  # "direct", "permission", "temporal", "conditional"
        "severity": str,  # "high", "medium", "low"
        "norm1_index": int,
        "norm2_index": int,
        "description": str,
        "resolution_strategies": List[str]
    }
]
```

**Conflict Types:**
- **Direct**: Obligation ∧ Prohibition
- **Permission**: Permission ∧ Prohibition
- **Temporal**: Overlapping time constraints
- **Conditional**: Same condition, conflicting operators

**Resolution Strategies:**
- `lex_superior`: Higher authority prevails
- `lex_posterior`: Newer norm prevails
- `lex_specialis`: More specific prevails
- `prohibition_prevails`: Prohibition overrides permission

**Example:**
```python
norms = [
    {"type": DeonticOperator.OBLIGATION, "action": "attend", "subject": "employee"},
    {"type": DeonticOperator.PROHIBITION, "action": "attend", "subject": "employee"}
]
conflicts = detect_normative_conflicts(norms)
```

---

## Proof Execution API

### `ProofExecutionEngine`

Execute formal proofs using theorem provers.

```python
class ProofExecutionEngine:
    def __init__(
        self,
        temp_dir: Optional[str] = None,
        timeout: int = 60,
        default_prover: Optional[str] = None,
        enable_rate_limiting: bool = True,
        enable_validation: bool = True,
        enable_caching: bool = True,
        cache_size: int = 1000,
        cache_ttl: int = 3600,
    )
```

**Parameters:**
- `temp_dir`: Directory for temporary files
- `timeout`: Proof timeout in seconds
- `default_prover`: Default prover ("z3", "cvc5", "lean", "coq")
- `enable_rate_limiting`: Enable rate limiting (100 calls/min)
- `enable_validation`: Enable input validation
- `enable_caching`: Enable proof caching
- `cache_size`: Maximum cache entries
- `cache_ttl`: Cache time-to-live in seconds

**Methods:**

#### `prove_deontic_formula()`

```python
def prove_deontic_formula(
    self,
    formula: DeonticFormula,
    prover: Optional[str] = None,
    user_id: str = "default",
    use_cache: bool = True,
) -> ProofResult
```

**Parameters:**
- `formula`: Deontic formula to prove
- `prover`: Prover to use (overrides default)
- `user_id`: User identifier for rate limiting
- `use_cache`: Whether to use cached results

**Returns:**
```python
ProofResult(
    prover: str,
    statement: str,
    status: ProofStatus,  # PROVEN, UNPROVEN, ERROR, TIMEOUT
    proof_text: Optional[str],
    execution_time: float,
    errors: List[str]
)
```

**Example:**
```python
engine = ProofExecutionEngine(enable_caching=True)
formula = DeonticFormula(operator="OBLIGATION", action="attend")
result = engine.prove_deontic_formula(formula, prover="z3")
```

---

## Caching API

### `ProofCache`

LRU cache for proof results.

```python
class ProofCache:
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 3600,
        ipfs_backed: bool = False,
        cache_dir: Optional[Path] = None
    )
```

**Parameters:**
- `max_size`: Maximum number of cached proofs
- `default_ttl`: Default time-to-live in seconds
- `ipfs_backed`: Whether to use IPFS for storage
- `cache_dir`: Directory for file-based cache

**Methods:**

#### `get()`

```python
def get(self, formula: str, prover: str) -> Optional[Dict[str, Any]]
```

Retrieve cached proof result.

#### `put()`

```python
def put(
    self,
    formula: str,
    prover: str,
    result: Dict[str, Any],
    ttl: Optional[int] = None
) -> None
```

Store proof result in cache.

#### `get_statistics()`

```python
def get_statistics(self) -> Dict[str, Any]
```

**Returns:**
```python
{
    "size": int,
    "max_size": int,
    "hits": int,
    "misses": int,
    "hit_rate": float,
    "evictions": int,
    "expirations": int,
    "total_puts": int,
    "ipfs_backed": bool
}
```

**Example:**
```python
cache = ProofCache(max_size=1000, default_ttl=3600)
cache.put("formula", "z3", {"result": "proven"})
result = cache.get("formula", "z3")
stats = cache.get_statistics()
```

---

## Batch Processing API

### `FOLBatchProcessor`

Optimized batch processor for FOL conversion.

```python
class FOLBatchProcessor:
    def __init__(self, max_concurrency: int = 10)
```

**Methods:**

#### `convert_batch()`

```python
async def convert_batch(
    self,
    texts: List[str],
    use_nlp: bool = True,
    confidence_threshold: float = 0.7,
) -> BatchResult
```

**Returns:**
```python
BatchResult(
    total_items: int,
    successful: int,
    failed: int,
    total_time: float,
    items_per_second: float,
    results: List[Dict[str, Any]],
    errors: List[Dict[str, Any]]
)
```

**Example:**
```python
processor = FOLBatchProcessor(max_concurrency=10)
texts = ["sentence 1", "sentence 2", ...]
result = await processor.convert_batch(texts, use_nlp=True)
```

---

### `ChunkedBatchProcessor`

Memory-efficient processing for large datasets.

```python
class ChunkedBatchProcessor:
    def __init__(
        self,
        chunk_size: int = 100,
        max_concurrency: int = 10,
    )
```

**Methods:**

#### `process_large_batch()`

```python
async def process_large_batch(
    self,
    items: List[Any],
    process_func: Callable,
    **kwargs
) -> BatchResult
```

Process large batch in memory-efficient chunks.

**Example:**
```python
processor = ChunkedBatchProcessor(chunk_size=100)
result = await processor.process_large_batch(
    items=large_dataset,
    process_func=convert_text_to_fol
)
```

---

## Benchmarking API

### `PerformanceBenchmark`

Framework for performance benchmarking.

```python
class PerformanceBenchmark:
    def __init__(self, warmup_iterations: int = 3)
```

**Methods:**

#### `benchmark()`

```python
def benchmark(
    self,
    name: str,
    func: Callable,
    iterations: int = 100,
    description: str = "",
    **kwargs
) -> BenchmarkResult
```

Benchmark synchronous function.

#### `benchmark_async()`

```python
async def benchmark_async(
    self,
    name: str,
    func: Callable,
    iterations: int = 100,
    description: str = "",
    **kwargs
) -> BenchmarkResult
```

Benchmark asynchronous function.

**Returns:**
```python
BenchmarkResult(
    name: str,
    description: str,
    iterations: int,
    total_time: float,
    mean_time: float,
    median_time: float,
    std_dev: float,
    min_time: float,
    max_time: float,
    throughput: float  # ops/sec
)
```

**Example:**
```python
benchmark = PerformanceBenchmark()
result = await benchmark.benchmark_async(
    name="FOL Conversion",
    func=convert_text_to_fol,
    text_input="All humans are mortal",
    iterations=100
)
print(result.summary())
```

---

## ML Confidence API

### `MLConfidenceScorer`

ML-based confidence scoring for FOL conversion.

```python
class MLConfidenceScorer:
    def __init__(self, config: Optional[MLConfidenceConfig] = None)
```

**Methods:**

#### `predict_confidence()`

```python
def predict_confidence(
    self,
    sentence: str,
    fol_formula: str,
    predicates: Dict[str, List[str]],
    quantifiers: List[str],
    operators: List[str],
) -> float
```

Predict confidence score (0.0-1.0).

#### `train()`

```python
def train(
    self,
    X: np.ndarray,
    y: np.ndarray,
    validation_split: float = 0.2,
) -> Dict[str, float]
```

Train model on labeled data.

**Parameters:**
- `X`: Feature matrix (n_samples, n_features)
- `y`: Target labels (n_samples,) in range [0, 1]
- `validation_split`: Fraction for validation

**Returns:**
```python
{
    "train_accuracy": float,
    "val_accuracy": float,
    "n_train": int,
    "n_val": int
}
```

#### `save_model()` / `load_model()`

```python
def save_model(self, path: Path) -> None
def load_model(self, path: Path) -> None
```

Persist and load trained models.

#### `get_feature_importance()`

```python
def get_feature_importance(self) -> Optional[Dict[str, float]]
```

Get feature importance scores.

**Example:**
```python
scorer = MLConfidenceScorer()

# Train
X, y = prepare_training_data()
metrics = scorer.train(X, y)

# Predict
confidence = scorer.predict_confidence(
    sentence="All humans are mortal",
    fol_formula="∀x(Human(x) → Mortal(x))",
    predicates={"nouns": ["humans"], "verbs": ["are"]},
    quantifiers=["∀"],
    operators=["→"]
)

# Save
scorer.save_model(Path("model.pkl"))
```

---

## Error Handling

All APIs follow consistent error handling:

```python
try:
    result = await convert_text_to_fol(text)
except ValueError as e:
    # Invalid parameters
    pass
except RuntimeError as e:
    # Execution error
    pass
except Exception as e:
    # Unexpected error
    pass
```

**Common Exceptions:**
- `ValueError`: Invalid input parameters
- `RuntimeError`: Execution failures
- `TimeoutError`: Proof/conversion timeout
- `ImportError`: Missing dependencies (spaCy, XGBoost)

---

## Type Definitions

### Enums

```python
class DeonticOperator(Enum):
    OBLIGATION = "O"
    PERMISSION = "P"
    PROHIBITION = "F"

class ProofStatus(Enum):
    PROVEN = "proven"
    UNPROVEN = "unproven"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
```

### Data Classes

See individual API sections for data class definitions.

---

## Version Information

Current API version: `1.0.0`

**Stability:**
- Core APIs (FOL, Deontic, Proof): Stable
- Caching API: Stable
- Batch Processing: Stable
- ML Confidence: Beta (API may evolve)

---

## Support

For questions or issues:
- Documentation: https://ipfs-datasets-py.readthedocs.io/
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
