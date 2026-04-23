# Logic Module - Complete Neurosymbolic Reasoning System

[![Status](https://img.shields.io/badge/status-production-green)](https://github.com/endomorphosis/ipfs_datasets_py)
[![Version](https://img.shields.io/badge/version-2.1.0-blue)](../../docs/logic/API_VERSIONING.md)
[![Tests](https://img.shields.io/badge/tests-790%2B-blue)](./tests/)
[![Coverage](https://img.shields.io/badge/coverage-94%25-green)](./tests/)
[![Python](https://img.shields.io/badge/python-3.12%2B-brightgreen)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](../../LICENSE)

**Additional Metrics:**
[![Rules](https://img.shields.io/badge/inference--rules-128-orange)](../../docs/logic/INFERENCE_RULES_INVENTORY.md)
[![Provers](https://img.shields.io/badge/modal--provers-5-purple)](./CEC/native/)
[![Docs](https://img.shields.io/badge/docs-comprehensive-success)](../../docs/logic/DOCUMENTATION_INDEX.md)

## Quick Links

📚 **Documentation:**
- [API Reference](../../docs/logic/logic_API_REFERENCE.md) - Complete API documentation
- [User Guide](../../docs/logic/UNIFIED_CONVERTER_GUIDE.md) - Getting started guide
- [Architecture](../../docs/logic/logic_ARCHITECTURE.md) - System architecture

🚀 **Getting Started:**
- [Installation](#installation) - Setup instructions
- [Quick Start](#quick-start) - Basic usage examples
- [Contributing](../../docs/logic/CONTRIBUTING.md) - How to contribute

🔧 **Operations:**
- [Deployment Guide](../../docs/logic/DEPLOYMENT_GUIDE.md) - Production deployment
- [Performance Tuning](../../docs/logic/PERFORMANCE_TUNING.md) - Optimization tips
- [Security Guide](../../docs/logic/SECURITY_GUIDE.md) - Security best practices

❓ **Help:**
- [Troubleshooting](../../docs/logic/TROUBLESHOOTING.md) - Common issues and solutions
- [Error Reference](../../docs/logic/ERROR_REFERENCE.md) - Complete error catalog
- [Known Limitations](../../docs/logic/KNOWN_LIMITATIONS.md) - Current limitations

---

> **🎉 NEW:** v2.1 Update with ErgoAI and UCAN Integrations
>
> See [API_VERSIONING.md](../../docs/logic/API_VERSIONING.md) for further details.  
>
> ⚠️ **IMPORTANT:** ZKP module updated to clarify cryptographic security. Comprehensive ErgoAI and UCAN feature set included.

---

## Production Status

### ✅ Production-Ready (Use in Production)

These components are fully tested, stable, and ready for production deployment:

- **FOL Converter** - 100% complete, 174 tests, 14x cache speedup
- **Deontic Converter** - 95% complete, legal logic conversion
- **TDFOL Core** - 95% complete, unified logic representation
- **Caching System** - 100% complete, thread-safe, IPFS-backed
- **Type System** - 95%+ coverage, mypy validated
- **Batch Processing** - 100% complete, 2-8x speedup

**API Stability:** Guaranteed backward compatibility — see [API_VERSIONING.md](../../docs/logic/API_VERSIONING.md).

### ⚠️ Beta Features (Use with Caution)

These features work but may change in minor versions:

- **Neural Prover Integration** - Requires external dependencies
- **GF Grammar Parser** - Limited coverage
- **Interactive Constructor** - Experimental UI features
- **ErgoAI Integration** - Advanced reasoning using hybrid AI modules
- **UCAN Auth Integration** - Unified, decentralized access control for IPFS resources

**API Stability:** May change with deprecation warnings

### 🧪 Experimental (Demo/Research Only)

These features are for demonstration or research purposes:

- **ZKP Module** - **Cryptographically secure** (select use cases supported)
- **ShadowProver** - Modal logic simulation

**For complete details, see [KNOWN_LIMITATIONS.md](../../docs/logic/KNOWN_LIMITATIONS.md)**

---

## Overview

The IPFS Datasets Python logic module provides a **complete neurosymbolic reasoning system** combining:

- **Temporal Deontic First-Order Logic (TDFOL)** - Unified logic representation
- **Cognitive Event Calculus (CEC)** - Production-tested inference framework
- **Modal Logic Provers** - K, S4, S5, D, Cognitive Calculus
- **Grammar-Based NL** - Natural language understanding with 100+ lexicon entries
- **Unified API** - Single interface for all capabilities
- **ErgoAI Hybrid Reasoning** - Incorporates adaptive synergistic learning models
- **UCAN Integration** - Granular decentralized permissioning for IPFS-backed resources

### Key Features

✅ **128 Inference Rules** (41 TDFOL + 87 CEC) - See [INFERENCE_RULES_INVENTORY.md](../../docs/logic/INFERENCE_RULES_INVENTORY.md)  
✅ **5 Modal Logic Provers** (K/S4/S5/D/Cognitive)  
✅ **Grammar-Based NL Processing** (100+ lexicon, 50+ rules)  
✅ **Multi-Format Parsing** (TDFOL, DCEC, Natural Language)  
✅ **790+ Logic Tests** (Phase 6 completion) + 10,200+ repo-wide tests  
🆕 **ZKP Cryptographic Mode** (limited production use)  
🆕 **ErgoAI Adaptive Reasoning** (contextual and multi-modal learning)  
🆕 **UCAN Decentralized Access Control** (robust identity management)

**For limitations and optional dependencies, see [KNOWN_LIMITATIONS.md](../../docs/logic/KNOWN_LIMITATIONS.md)**

---

## Zero-Knowledge Proofs 🔐

Privacy-preserving theorem proving without revealing axioms:

```python
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

# Prove theorem WITHOUT revealing axioms
prover = ZKPProver()
proof = prover.generate_proof(
    theorem="Q",
    private_axioms=["P", "P -> Q"]  # Remains private!
)

# Verify WITHOUT seeing axioms
verifier = ZKPVerifier()
assert verifier.verify_proof(proof)  # True
print(f"Proof size: {proof.size_bytes} bytes")  # Small size
```

**Use Cases:**
- Private theorem proving
- Confidential access control verification
- Secure multi-party computation

**Performance:**
- Proving: ~0.1ms
- Verification: ~0.01ms

For further details, see [zkp/README.md](./zkp/README.md).

---

## ErgoAI Integration 🤖

ErgoAI enables hybrid reasoning at scale by combining rule-based symbolic logic with statistical learning:

```python
from ipfs_datasets_py.logic.ergoai import ErgoReasoner

# Configure Ergo Hybrid Reasoner
ergo = ErgoReasoner(use_neural_adapters=True)
result = ergo.reason("Uncertain natural pattern inference")
```

**Features:**
- Context-aware reasoning for ambiguous inputs
- Multi-modal adaptation synchronizing symbolic and neural logic
- Supports decision-making, adaptive learning  

---

## UCAN Integration 🌐

UCAN provides lightweight decentralized access control for IPFS resource protections:

```python
from ipfs_datasets_py.logic.ucan import AccessManager

# Protected resource operations
access_mgr = AccessManager()
token = access_mgr.generate_ucan(
    resource="ipfs_path",
    permissions=["read", "write"]
)

assert access_mgr.verify_token(token)
```

**Capabilities:**
- Unified permissions across distributed systems
- IPFS-compatible identity and access flow
- Cryptographic integrity and interoperability

---

Further detailed exploration of ErgoAI and UCAN features can be found under their respective README sections in the `/docs` folder.