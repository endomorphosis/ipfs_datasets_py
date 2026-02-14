# Production Readiness Implementation Plan

**Date:** 2026-02-12  
**Status:** Ready for Implementation  
**Timeline:** 9 weeks  
**Priority:** HIGH

---

## Executive Summary

This document provides a concrete, actionable plan to address all gaps identified in the comprehensive logic module review and achieve production readiness.

**Current State:**
- 43,165 LOC across multiple logic systems
- 2/5 external provers working (Z3, SymbolicAI)
- 30-40% test coverage
- No security hardening
- Fragmented APIs

**Target State:**
- 80%+ test coverage
- 5/5 external provers working
- Security hardened
- Unified API
- Production-ready deployment

---

## Phase 1: Critical Production Gaps (2 weeks) - P0

### Week 1: Test Coverage Sprint

#### Day 1-2: TDFOL Test Suite
**Files to Create:**
```
tests/unit_tests/logic/TDFOL/
├── test_tdfol_core.py (expand existing)
├── test_tdfol_parser.py  
├── test_tdfol_prover.py
├── test_tdfol_converter.py
├── test_tdfol_dcec_parser.py
└── test_tdfol_inference_rules.py
```

**Test Categories:**
- Formula construction (all 8 types)
- Parser edge cases (malformed input, max depth)
- Prover correctness (40 inference rules)
- Converter accuracy (TDFOL ↔ DCEC/FOL/TPTP)
- Performance (parsing <1ms, proving <100ms)

**Target:** 100+ TDFOL tests

#### Day 3-4: Integration Module Tests
**Priority Files** (highest risk, most-used):
1. `symbolic_contracts.py` (763 LOC)
2. `temporal_deontic_rag_store.py` (575 LOC)
3. `deontic_logic_converter.py` (791 LOC)
4. `symbolic_fol_bridge.py` (550 LOC)
5. `legal_symbolic_analyzer.py` (637 LOC)

**Test Template:**
```python
# tests/unit_tests/logic/integration/test_symbolic_contracts.py

import pytest
from ipfs_datasets_py.logic.integration import symbolic_contracts

class TestSymbolicContracts:
    """Test symbolic contracts module."""
    
    def test_contract_creation(self):
        """Test creating a contract."""
        contract = symbolic_contracts.create_contract(
            parties=["Alice", "Bob"],
            obligations=["Alice pays 100", "Bob delivers goods"]
        )
        assert contract is not None
        assert len(contract.obligations) == 2
    
    def test_contract_validation(self):
        """Test validating contract consistency."""
        contract = symbolic_contracts.create_contract(...)
        result = symbolic_contracts.validate(contract)
        assert result.is_valid
    
    def test_contract_violation_detection(self):
        """Test detecting contract violations."""
        contract = symbolic_contracts.create_contract(...)
        state = {"Alice_paid": False}
        violations = symbolic_contracts.check_violations(contract, state)
        assert len(violations) > 0
```

**Target:** 50+ integration tests

#### Day 5: External Prover Tests
```python
# tests/unit_tests/logic/external_provers/test_z3_integration.py

class TestZ3Integration:
    def test_z3_availability(self):
        """Test Z3 is available."""
        assert check_z3_availability()
    
    def test_formula_conversion(self):
        """Test TDFOL → Z3 conversion."""
        formula = parse_tdfol("P -> Q")
        z3_formula = convert_to_z3(formula)
        assert z3_formula is not None
    
    def test_simple_proof(self):
        """Test proving P -> P."""
        prover = Z3ProverBridge()
        result = prover.prove(parse_tdfol("P -> P"))
        assert result.is_valid
    
    def test_with_axioms(self):
        """Test proving with axioms."""
        prover = Z3ProverBridge()
        axioms = [parse_tdfol("P"), parse_tdfol("P -> Q")]
        result = prover.prove(parse_tdfol("Q"), axioms=axioms)
        assert result.is_valid
    
    def test_cache_hit(self):
        """Test cache hit improves performance."""
        prover = Z3ProverBridge(enable_cache=True)
        formula = parse_tdfol("P -> P")
        
        # First call
        result1 = prover.prove(formula)
        time1 = result1.proof_time
        
        # Second call (cache hit)
        result2 = prover.prove(formula)
        time2 = result2.proof_time
        
        assert time2 < time1 / 10  # At least 10x faster
```

**Target:** 30+ external prover tests

#### Summary Week 1:
- **Total Tests:** 180+ new tests
- **Coverage Improvement:** 30% → 55%
- **Files Created:** 15+

### Week 2: Security & Deployment

#### Day 1-2: Security Hardening

**1. Input Validation:**
```python
# ipfs_datasets_py/logic/security/input_validation.py

class InputValidator:
    """Validate inputs to prevent attacks."""
    
    MAX_TEXT_LENGTH = 10_000
    MAX_FORMULA_DEPTH = 100
    MAX_FORMULA_COMPLEXITY = 1_000
    
    @staticmethod
    def validate_text(text: str) -> str:
        """Validate text input."""
        if not isinstance(text, str):
            raise TypeError(f"Expected str, got {type(text)}")
        
        if len(text) > InputValidator.MAX_TEXT_LENGTH:
            raise ValueError(
                f"Input too long: {len(text)} > {InputValidator.MAX_TEXT_LENGTH}"
            )
        
        # Check for suspicious patterns
        if re.search(r'[^\x00-\x7F]{100,}', text):
            raise ValueError("Suspicious non-ASCII pattern detected")
        
        return text
    
    @staticmethod
    def validate_formula(formula) -> None:
        """Validate formula complexity."""
        depth = get_formula_depth(formula)
        if depth > InputValidator.MAX_FORMULA_DEPTH:
            raise ValueError(f"Formula too deep: {depth}")
        
        complexity = get_formula_complexity(formula)
        if complexity > InputValidator.MAX_FORMULA_COMPLEXITY:
            raise ValueError(f"Formula too complex: {complexity}")
```

**2. Rate Limiting:**
```python
# ipfs_datasets_py/logic/security/rate_limiting.py

from functools import wraps
from time import time
from collections import defaultdict

class RateLimiter:
    """Simple rate limiter."""
    
    def __init__(self, calls: int, period: int):
        self.calls = calls
        self.period = period
        self.cache = defaultdict(list)
    
    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_id = get_current_user_id()
            now = time()
            
            # Remove old entries
            self.cache[user_id] = [
                t for t in self.cache[user_id]
                if now - t < self.period
            ]
            
            # Check rate limit
            if len(self.cache[user_id]) >= self.calls:
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self.calls} calls per {self.period}s"
                )
            
            # Record call
            self.cache[user_id].append(now)
            
            return func(*args, **kwargs)
        
        return wrapper

# Usage
class SecureNeurosymbolicReasoner:
    @RateLimiter(calls=100, period=60)
    def prove(self, formula, **kwargs):
        """Prove with rate limiting."""
        return self._prove_impl(formula, **kwargs)
```

**3. Audit Logging:**
```python
# ipfs_datasets_py/logic/security/audit_log.py

import logging
import json
from datetime import datetime

audit_logger = logging.getLogger('logic.audit')

class AuditLogger:
    """Structured audit logging."""
    
    @staticmethod
    def log_proof_attempt(
        user_id: str,
        formula: str,
        prover: str,
        success: bool,
        duration_ms: float
    ):
        """Log proof attempt for audit."""
        audit_logger.info(json.dumps({
            'event': 'proof_attempt',
            'timestamp': datetime.utcnow().isoformat(),
            'user_id': user_id,
            'formula': formula[:100],  # Truncate
            'prover': prover,
            'success': success,
            'duration_ms': duration_ms
        }))
```

#### Day 3: Deployment Guide

**Create:** `DEPLOYMENT_GUIDE.md`

```markdown
# Production Deployment Guide

## Prerequisites
- Python 3.12+
- Docker (optional)
- Redis (for distributed cache)

## Installation

### Option 1: pip
```bash
pip install ipfs-datasets-py[logic,provers]
```

### Option 2: Docker
```bash
docker pull ipfs-datasets-py:latest
docker run -p 8000:8000 ipfs-datasets-py
```

## Configuration

### Environment Variables
```bash
# Required
export PYTHONPATH=/path/to/ipfs_datasets_py

# Optional - External Provers
export Z3_TIMEOUT=5.0
export SYMBOLICAI_API_KEY=sk-...
export SYMBOLICAI_MODEL=gpt-4

# Optional - Caching
export CACHE_BACKEND=redis
export REDIS_URL=redis://localhost:6379

# Optional - Monitoring
export ENABLE_MONITORING=true
export METRICS_PORT=9090
```

### Configuration File
```yaml
# config.yaml
provers:
  native:
    enabled: true
    timeout: 5.0
  z3:
    enabled: true
    timeout: 5.0
    max_memory_mb: 2048
  symbolicai:
    enabled: false  # Requires API key
    model: gpt-4
    temperature: 0.0

cache:
  backend: redis  # or memory
  maxsize: 10000
  ttl: 3600
  redis_url: ${REDIS_URL}

security:
  rate_limit_calls: 100
  rate_limit_period: 60
  max_formula_complexity: 1000

monitoring:
  enabled: true
  port: 9090
  log_level: INFO
```

## Resource Requirements

### Minimum
- CPU: 2 cores
- RAM: 4GB
- Disk: 5GB

### Recommended
- CPU: 4+ cores
- RAM: 8GB+
- Disk: 20GB+

### High Load
- CPU: 8+ cores
- RAM: 16GB+
- Disk: 50GB+
- Redis: 4GB+ memory

## Scaling

### Horizontal Scaling
```bash
# Run multiple instances behind load balancer
docker-compose up --scale logic-api=4
```

### Vertical Scaling
```bash
# Increase resource limits
docker run -m 8g --cpus=4 ipfs-datasets-py
```

## Monitoring

### Metrics
- Prometheus metrics on port 9090
- Key metrics:
  - proof_attempts_total
  - proof_latency_seconds
  - cache_hit_rate
  - prover_success_rate

### Logs
- JSON structured logs
- Audit trail in separate log file
- Log rotation configured

### Alerts
```yaml
alerts:
  - name: high_error_rate
    expr: rate(proof_failures_total[5m]) > 0.05
    severity: critical
  
  - name: high_latency
    expr: histogram_quantile(0.95, proof_latency_seconds) > 1.0
    severity: warning
```

## Backup & Recovery
- Cache can be rebuilt (no data loss)
- Audit logs should be backed up
- Configuration should be version controlled

## Security Checklist
- [ ] Rate limiting enabled
- [ ] Input validation active
- [ ] Audit logging configured
- [ ] TLS/HTTPS enabled
- [ ] API keys secured
- [ ] Resource limits set

## Troubleshooting
See TROUBLESHOOTING.md
```

#### Day 4-5: Configuration Management

**Create:** `ipfs_datasets_py/logic/config.py`

```python
"""Configuration management for logic module."""

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pathlib import Path

@dataclass
class ProverConfig:
    """Configuration for a single prover."""
    enabled: bool = True
    timeout: float = 5.0
    max_memory_mb: int = 2048
    options: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CacheConfig:
    """Configuration for caching."""
    backend: str = "memory"  # or "redis"
    maxsize: int = 10000
    ttl: int = 3600
    redis_url: Optional[str] = None

@dataclass
class SecurityConfig:
    """Configuration for security."""
    rate_limit_calls: int = 100
    rate_limit_period: int = 60
    max_text_length: int = 10000
    max_formula_complexity: int = 1000
    enable_audit_log: bool = True

@dataclass
class MonitoringConfig:
    """Configuration for monitoring."""
    enabled: bool = True
    port: int = 9090
    log_level: str = "INFO"

@dataclass
class LogicConfig:
    """Master configuration for logic module."""
    provers: Dict[str, ProverConfig] = field(default_factory=lambda: {
        'native': ProverConfig(),
        'z3': ProverConfig(),
        'symbolicai': ProverConfig(enabled=False)
    })
    cache: CacheConfig = field(default_factory=CacheConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    
    @classmethod
    def from_file(cls, path: Path) -> 'LogicConfig':
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        
        return cls(
            provers={
                k: ProverConfig(**v) 
                for k, v in data.get('provers', {}).items()
            },
            cache=CacheConfig(**data.get('cache', {})),
            security=SecurityConfig(**data.get('security', {})),
            monitoring=MonitoringConfig(**data.get('monitoring', {}))
        )
    
    @classmethod
    def from_env(cls) -> 'LogicConfig':
        """Load configuration from environment variables."""
        return cls(
            provers={
                'z3': ProverConfig(
                    enabled=os.getenv('Z3_ENABLED', 'true').lower() == 'true',
                    timeout=float(os.getenv('Z3_TIMEOUT', '5.0'))
                ),
                'symbolicai': ProverConfig(
                    enabled=bool(os.getenv('SYMBOLICAI_API_KEY')),
                    timeout=float(os.getenv('SYMBOLICAI_TIMEOUT', '10.0'))
                )
            },
            cache=CacheConfig(
                backend=os.getenv('CACHE_BACKEND', 'memory'),
                redis_url=os.getenv('REDIS_URL')
            )
        )

# Global configuration instance
_config: Optional[LogicConfig] = None

def get_config() -> LogicConfig:
    """Get global configuration."""
    global _config
    if _config is None:
        # Try to load from file
        config_path = Path('config.yaml')
        if config_path.exists():
            _config = LogicConfig.from_file(config_path)
        else:
            # Fall back to environment
            _config = LogicConfig.from_env()
    return _config

def set_config(config: LogicConfig):
    """Set global configuration."""
    global _config
    _config = config
```

#### Summary Week 2:
- **Security:** Input validation, rate limiting, audit logging
- **Deployment:** Complete guide with Docker, scaling, monitoring
- **Configuration:** Flexible config management (file + env)
- **Status:** Production-ready infrastructure

---

## Phase 2: External Prover Completion (2 weeks) - P0

### Week 3: CVC5 Integration

#### Implementation Checklist:
- [ ] Install CVC5 Python bindings
- [ ] Create `cvc5_prover_bridge.py` (full implementation)
- [ ] Implement TDFOL → CVC5 converter
- [ ] Add caching support
- [ ] Create 20+ tests
- [ ] Write documentation
- [ ] Add usage example

**Estimated LOC:** 800-1000 (similar to Z3)

### Week 4: Lean 4 or Coq Integration

**Choose One:** Lean 4 (recommended for better tooling)

#### Implementation Checklist:
- [ ] Implement TDFOL → Lean converter
- [ ] Create Lean project template
- [ ] Implement subprocess management
- [ ] Add tactic suggestion (using SymbolicAI)
- [ ] Create 15+ tests
- [ ] Write documentation
- [ ] Add usage example

**Estimated LOC:** 1200-1500

---

## Phase 3: API Consolidation (1 week) - P1

### Week 5: Unified API

#### Day 1-3: Implement Unified API

**Create:** `ipfs_datasets_py/logic/api.py`

See Section 5.2 of COMPREHENSIVE_LOGIC_MODULE_REVIEW.md for full implementation.

**Key Classes:**
- `Logic` - Main unified interface
- `LogicConfig` - Configuration
- `ProofResult` - Standardized result
- Convenience functions: `prove()`, `parse()`, `explain()`

#### Day 4-5: Update Examples & Documentation

**Tasks:**
- Update all 7 examples to use new API
- Create migration guide
- Add deprecation warnings to old APIs
- Update all documentation

---

## Phase 4: Performance & Observability (1 week) - P1

### Week 6: Production Hardening

#### Day 1-2: Load Testing

**Create:** `tests/performance/test_load.py`

```python
def test_concurrent_proving():
    """Test 100 concurrent proof requests."""
    pass

def test_sustained_load():
    """Test 1000 proofs over 10 minutes."""
    pass

def test_memory_stability():
    """Test memory doesn't leak over 10K proofs."""
    pass
```

#### Day 3-4: Distributed Tracing

**Add OpenTelemetry:**
```bash
pip install opentelemetry-api opentelemetry-sdk
```

**Instrument:**
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

class TracedProver:
    def prove(self, formula):
        with tracer.start_as_current_span("prove") as span:
            span.set_attribute("formula.type", type(formula).__name__)
            result = self._prove_impl(formula)
            span.set_attribute("result.proved", result.is_proved())
            return result
```

#### Day 5: Structured Logging & Alerting

**Implement:**
- Structured JSON logging
- Prometheus metrics export
- Alert rules for Grafana

---

## Phase 5: GraphRAG Integration (2 weeks) - P1

### Week 7: Logic-Aware GraphRAG

#### Implementation:
- Logic-aware entity extraction
- Logical type annotations
- Consistency checking

### Week 8: Theorem-Augmented Knowledge Graph

#### Implementation:
- Add proven theorems to graph
- Link theorems to concepts
- Query interface

---

## Phase 6: Polish & Documentation (1 week) - P2

### Week 9: Final Polish

#### Day 1-2: Complete Documentation
- API reference
- User guide
- Developer guide
- Troubleshooting

#### Day 3-4: Performance Optimization
- Profile hot paths
- Optimize bottlenecks
- Add benchmarks

#### Day 5: Final Review
- Security review
- Code review
- Documentation review
- Production readiness checklist

---

## Success Metrics

### Phase 1 (Week 2):
- [ ] Test coverage: 55%+
- [ ] Security hardening complete
- [ ] Deployment guide published

### Phase 2 (Week 4):
- [ ] 3/5 external provers working
- [ ] Test coverage: 60%+

### Phase 3 (Week 5):
- [ ] Unified API complete
- [ ] Migration guide published
- [ ] All examples updated

### Phase 4 (Week 6):
- [ ] Load testing passing
- [ ] Distributed tracing working
- [ ] Prometheus metrics exported

### Phase 5 (Week 8):
- [ ] GraphRAG integration complete
- [ ] Test coverage: 70%+

### Phase 6 (Week 9):
- [ ] Test coverage: 80%+
- [ ] All documentation complete
- [ ] Production ready ✅

---

## Resource Requirements

**Team:**
- 1-2 Senior Developers (full-time)
- 1 DevOps Engineer (part-time, weeks 2, 4, 6)
- 1 Technical Writer (part-time, weeks 5, 9)

**Infrastructure:**
- Development environment
- CI/CD pipeline
- Test/staging environment
- Monitoring stack (Prometheus + Grafana)

---

## Risk Mitigation

### High Priority Risks:

1. **Timeline Slippage**
   - Mitigation: Buffer time built in
   - Contingency: Reduce Phase 5 scope

2. **External Dependencies**
   - Risk: CVC5/Lean integration harder than expected
   - Mitigation: Start with CVC5 (easier)
   - Contingency: Skip Lean/Coq for v1.0

3. **Test Coverage**
   - Risk: Hard to reach 80%
   - Mitigation: Focus on critical paths first
   - Contingency: Accept 70% for v1.0

---

## Tracking & Reporting

**Weekly Cadence:**
- Monday: Sprint planning
- Daily: Standups (15 min)
- Friday: Demo + retrospective

**Metrics Dashboard:**
- Test coverage trend
- Bugs opened vs closed
- Feature completion %
- Performance benchmarks

**Status Reports:**
- Weekly email update
- Monthly stakeholder presentation
- GitHub project board

---

## Conclusion

This 9-week plan provides a clear path to production readiness:

- **Phase 1 (2 weeks):** Critical fixes - testing & security
- **Phase 2 (2 weeks):** Complete external provers
- **Phase 3 (1 week):** Unify APIs
- **Phase 4 (1 week):** Performance & observability
- **Phase 5 (2 weeks):** GraphRAG integration
- **Phase 6 (1 week):** Polish & ship

**Outcome:** Production-ready neurosymbolic reasoning platform with 80%+ test coverage, unified API, and comprehensive observability.

**Ready to begin!** 🚀
