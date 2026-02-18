# CEC API Interface Design

**Version:** 1.0  
**Date:** 2026-02-18  
**Status:** Design Phase

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [API Endpoints](#api-endpoints)
4. [Data Models](#data-models)
5. [Authentication & Security](#authentication--security)
6. [Rate Limiting](#rate-limiting)
7. [Error Handling](#error-handling)
8. [Performance & Caching](#performance--caching)
9. [Monitoring & Logging](#monitoring--logging)
10. [Deployment](#deployment)

---

## 📊 Overview

### Purpose

Provide a RESTful API interface for the CEC (Cognitive Event Calculus) system, enabling remote access to:
- Natural language ↔ DCEC conversion
- Theorem proving
- Knowledge base management
- Reasoning workflows

### Technology Stack

- **Framework:** FastAPI 0.104+ (async support, auto docs)
- **Validation:** Pydantic 2.0+ (data models)
- **Authentication:** JWT tokens, API keys
- **Caching:** Redis 7.0+
- **Database:** PostgreSQL 15+ (optional, for persistence)
- **Monitoring:** Prometheus + Grafana
- **Documentation:** OpenAPI 3.0 (auto-generated)
- **Deployment:** Docker + Docker Compose

### Design Principles

1. **RESTful** - Follow REST conventions
2. **Async** - Async/await throughout for concurrency
3. **Type-safe** - Pydantic models for all data
4. **Self-documenting** - Auto-generated OpenAPI docs
5. **Secure** - Authentication, rate limiting, validation
6. **Observable** - Metrics, logging, tracing
7. **Scalable** - Horizontal scaling support

---

## 🏗️ Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         API Gateway                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Rate Limiter │  │ Auth Checker │  │ Request Log  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Convert    │  │    Prove     │  │   Reason     │     │
│  │  Endpoints   │  │  Endpoints   │  │  Endpoints   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   KB Mgmt    │  │   Sessions   │  │   Workflow   │     │
│  │  Endpoints   │  │  Endpoints   │  │  Endpoints   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Business Logic                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ NL Converter │  │ Theorem      │  │   KB         │     │
│  │              │  │ Prover       │  │ Manager      │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │    Redis     │  │  PostgreSQL  │  │   Native     │     │
│  │   (Cache)    │  │ (Persistence)│  │     CEC      │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### Layered Architecture

**Layer 1: API Gateway**
- Rate limiting (token bucket)
- Authentication/authorization
- Request/response logging
- CORS handling

**Layer 2: API Endpoints**
- Request validation (Pydantic)
- Response serialization
- Error handling
- OpenAPI documentation

**Layer 3: Business Logic**
- CEC native implementation
- Prover orchestration
- Knowledge base management
- Workflow execution

**Layer 4: Data Layer**
- Redis (session cache, result cache)
- PostgreSQL (optional persistence)
- Native CEC (in-memory processing)

---

## 🔌 API Endpoints

### Base URL

```
Production:  https://api.cec.example.com/v1
Development: http://localhost:8000/v1
```

### Endpoint Categories

1. **Conversion** - NL ↔ DCEC conversion
2. **Proving** - Theorem proving
3. **Reasoning** - Complete workflows
4. **Knowledge Base** - KB management
5. **Sessions** - Session management
6. **System** - Health, metrics, info

---

### 1. Conversion Endpoints

#### POST /api/v1/convert/nl-to-dcec

Convert natural language to DCEC formula.

**Request:**
```json
{
  "text": "The agent is obligated to perform the action",
  "language": "en",
  "use_grammar": true,
  "context": {
    "domain": "legal",
    "previous_statements": []
  }
}
```

**Response:**
```json
{
  "success": true,
  "dcec_formula": "O(act(agent))",
  "confidence": 0.95,
  "alternatives": [
    {
      "formula": "O(perform(agent, action))",
      "confidence": 0.85
    }
  ],
  "parse_tree": {
    "type": "obligation",
    "agent": "agent",
    "action": "performAction"
  },
  "processing_time_ms": 45
}
```

**Errors:**
- `400` - Invalid input, unparseable text
- `422` - Validation error
- `429` - Rate limit exceeded
- `500` - Internal server error

---

#### POST /api/v1/convert/dcec-to-nl

Convert DCEC formula to natural language.

**Request:**
```json
{
  "formula": "O(act(agent))",
  "language": "en",
  "style": "formal",
  "context": {
    "domain": "legal"
  }
}
```

**Response:**
```json
{
  "success": true,
  "natural_language": "The agent is obligated to act",
  "alternatives": [
    "It is obligatory that the agent acts",
    "The agent must act"
  ],
  "processing_time_ms": 25
}
```

---

#### POST /api/v1/convert/batch

Batch conversion (multiple texts).

**Request:**
```json
{
  "texts": [
    "The agent must act",
    "The agent believes something",
    "The agent has permission"
  ],
  "language": "en",
  "use_grammar": true
}
```

**Response:**
```json
{
  "success": true,
  "results": [
    {
      "text": "The agent must act",
      "dcec_formula": "O(act(agent))",
      "confidence": 0.95
    },
    {
      "text": "The agent believes something",
      "dcec_formula": "B(agent, something)",
      "confidence": 0.90
    },
    {
      "text": "The agent has permission",
      "dcec_formula": "P(agent)",
      "confidence": 0.92
    }
  ],
  "processing_time_ms": 120
}
```

---

### 2. Proving Endpoints

#### POST /api/v1/prove

Prove a theorem.

**Request:**
```json
{
  "conjecture": "O(act(agent))",
  "axioms": [
    "K(agent, obligation)",
    "obligation → O(act(agent))"
  ],
  "prover": "auto",
  "timeout_seconds": 30,
  "options": {
    "use_temporal": false,
    "max_depth": 100
  }
}
```

**Response:**
```json
{
  "success": true,
  "result": "proved",
  "prover_used": "native_python",
  "proof": {
    "steps": [
      "1. K(agent, obligation) [axiom]",
      "2. obligation → O(act(agent)) [axiom]",
      "3. obligation [from 1, knowledge extraction]",
      "4. O(act(agent)) [from 2, 3, modus ponens]"
    ],
    "step_count": 4,
    "depth": 2
  },
  "proof_tree": {
    "root": "O(act(agent))",
    "children": [...]
  },
  "processing_time_ms": 156,
  "prover_info": {
    "name": "Native Python Prover",
    "version": "1.0.0",
    "rules_used": ["modus_ponens", "knowledge_extraction"]
  }
}
```

**Result Values:**
- `proved` - Theorem successfully proved
- `disproved` - Counterexample found
- `timeout` - Timeout reached
- `unknown` - Could not determine

---

#### GET /api/v1/provers

List available theorem provers.

**Response:**
```json
{
  "provers": [
    {
      "id": "native_python",
      "name": "Native Python Prover",
      "version": "1.0.0",
      "capabilities": ["forward_chaining", "backward_chaining"],
      "rules_count": 80,
      "supports_temporal": true,
      "available": true
    },
    {
      "id": "z3",
      "name": "Z3 SMT Solver",
      "version": "4.12.0",
      "capabilities": ["smt", "model_checking"],
      "available": true
    },
    {
      "id": "vampire",
      "name": "Vampire Prover",
      "version": "4.7",
      "capabilities": ["saturation", "tptp"],
      "available": false,
      "reason": "Binary not found"
    }
  ]
}
```

---

#### POST /api/v1/prove/parallel

Try multiple provers in parallel.

**Request:**
```json
{
  "conjecture": "O(act(agent))",
  "axioms": [...],
  "provers": ["native_python", "z3", "vampire"],
  "timeout_seconds": 60
}
```

**Response:**
```json
{
  "success": true,
  "fastest_prover": "z3",
  "results": [
    {
      "prover": "z3",
      "result": "proved",
      "time_ms": 234,
      "completed": true
    },
    {
      "prover": "native_python",
      "result": "proved",
      "time_ms": 456,
      "completed": true
    },
    {
      "prover": "vampire",
      "result": "timeout",
      "time_ms": 60000,
      "completed": false
    }
  ],
  "consensus": "proved"
}
```

---

### 3. Reasoning Endpoints

#### POST /api/v1/reason

Complete reasoning workflow (NL → DCEC → Prove).

**Request:**
```json
{
  "natural_language": "The agent is obligated to perform action",
  "prove": true,
  "axioms": [
    "K(agent, obligation)",
    "obligation → O(act(agent))"
  ],
  "language": "en"
}
```

**Response:**
```json
{
  "success": true,
  "natural_language": "The agent is obligated to perform action",
  "dcec_formula": "O(act(agent))",
  "conversion_confidence": 0.95,
  "proof_result": "proved",
  "proof": {
    "steps": [...],
    "step_count": 4
  },
  "processing_time_ms": 201
}
```

---

#### POST /api/v1/workflow

Execute custom workflow.

**Request:**
```json
{
  "workflow": {
    "steps": [
      {
        "type": "convert",
        "input": "The agent must act",
        "output_var": "formula1"
      },
      {
        "type": "convert",
        "input": "The agent believes it is necessary",
        "output_var": "formula2"
      },
      {
        "type": "prove",
        "conjecture": "{formula1}",
        "axioms": ["{formula2}"],
        "output_var": "proof1"
      }
    ]
  }
}
```

**Response:**
```json
{
  "success": true,
  "results": {
    "formula1": "O(act(agent))",
    "formula2": "B(agent, necessary)",
    "proof1": {
      "result": "proved",
      "steps": [...]
    }
  },
  "processing_time_ms": 345
}
```

---

### 4. Knowledge Base Endpoints

#### POST /api/v1/kb/create

Create a new knowledge base.

**Request:**
```json
{
  "name": "Legal KB",
  "description": "Legal domain knowledge base",
  "metadata": {
    "domain": "legal",
    "language": "en"
  }
}
```

**Response:**
```json
{
  "success": true,
  "kb_id": "kb_1a2b3c4d",
  "name": "Legal KB",
  "created_at": "2026-02-18T10:30:00Z"
}
```

---

#### GET /api/v1/kb/{kb_id}

Get knowledge base details.

**Response:**
```json
{
  "kb_id": "kb_1a2b3c4d",
  "name": "Legal KB",
  "description": "Legal domain knowledge base",
  "statement_count": 156,
  "created_at": "2026-02-18T10:30:00Z",
  "updated_at": "2026-02-18T12:45:00Z",
  "metadata": {
    "domain": "legal",
    "language": "en"
  }
}
```

---

#### POST /api/v1/kb/{kb_id}/statements

Add statements to KB.

**Request:**
```json
{
  "statements": [
    {
      "formula": "O(act(agent))",
      "label": "obligation1",
      "is_axiom": true,
      "metadata": {
        "source": "regulation_42"
      }
    },
    {
      "formula": "B(agent, necessary)",
      "label": "belief1",
      "is_axiom": false
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "added_count": 2,
  "statement_ids": ["stmt_1", "stmt_2"]
}
```

---

#### GET /api/v1/kb/{kb_id}/statements

List statements in KB.

**Query Parameters:**
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 50, max: 200)
- `filter`: Filter expression
- `sort`: Sort field

**Response:**
```json
{
  "statements": [
    {
      "id": "stmt_1",
      "formula": "O(act(agent))",
      "label": "obligation1",
      "is_axiom": true,
      "created_at": "2026-02-18T10:30:00Z"
    },
    ...
  ],
  "pagination": {
    "page": 1,
    "per_page": 50,
    "total_items": 156,
    "total_pages": 4
  }
}
```

---

#### POST /api/v1/kb/{kb_id}/query

Query knowledge base.

**Request:**
```json
{
  "query": {
    "type": "contains",
    "pattern": "O(*)"
  },
  "limit": 10
}
```

**Response:**
```json
{
  "success": true,
  "results": [
    {
      "statement_id": "stmt_1",
      "formula": "O(act(agent))",
      "label": "obligation1",
      "relevance_score": 1.0
    },
    ...
  ],
  "result_count": 7
}
```

---

#### DELETE /api/v1/kb/{kb_id}

Delete knowledge base.

**Response:**
```json
{
  "success": true,
  "message": "Knowledge base deleted successfully"
}
```

---

### 5. Session Management Endpoints

#### POST /api/v1/sessions

Create a new session.

**Request:**
```json
{
  "kb_id": "kb_1a2b3c4d",
  "ttl_seconds": 3600,
  "metadata": {
    "user": "alice",
    "purpose": "legal_analysis"
  }
}
```

**Response:**
```json
{
  "success": true,
  "session_id": "sess_xyz789",
  "expires_at": "2026-02-18T11:30:00Z"
}
```

---

#### GET /api/v1/sessions/{session_id}

Get session details.

**Response:**
```json
{
  "session_id": "sess_xyz789",
  "kb_id": "kb_1a2b3c4d",
  "created_at": "2026-02-18T10:30:00Z",
  "expires_at": "2026-02-18T11:30:00Z",
  "request_count": 42,
  "metadata": {
    "user": "alice",
    "purpose": "legal_analysis"
  }
}
```

---

#### GET /api/v1/sessions/{session_id}/history

Get session history.

**Response:**
```json
{
  "session_id": "sess_xyz789",
  "history": [
    {
      "timestamp": "2026-02-18T10:31:00Z",
      "endpoint": "/api/v1/convert/nl-to-dcec",
      "request": {...},
      "response": {...},
      "processing_time_ms": 45
    },
    ...
  ],
  "total_requests": 42
}
```

---

#### DELETE /api/v1/sessions/{session_id}

End session.

**Response:**
```json
{
  "success": true,
  "message": "Session ended successfully"
}
```

---

### 6. System Endpoints

#### GET /api/v1/health

Health check.

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "components": {
    "api": "ok",
    "redis": "ok",
    "postgres": "ok",
    "native_cec": "ok"
  },
  "uptime_seconds": 86400
}
```

---

#### GET /api/v1/metrics

System metrics (Prometheus format).

**Response:**
```
# HELP cec_api_requests_total Total API requests
# TYPE cec_api_requests_total counter
cec_api_requests_total{endpoint="/api/v1/convert/nl-to-dcec",status="200"} 1234
...
```

---

#### GET /api/v1/info

System information.

**Response:**
```json
{
  "version": "1.0.0",
  "api_version": "v1",
  "native_cec_version": "1.0.0",
  "supported_languages": ["en", "es", "fr", "de"],
  "available_provers": ["native_python", "z3"],
  "max_request_size_mb": 10,
  "rate_limits": {
    "requests_per_minute": 60,
    "burst": 10
  }
}
```

---

## 📦 Data Models

### Pydantic Models

#### ConversionRequest
```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, List

class ConversionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    language: str = Field(default="en", pattern="^[a-z]{2}$")
    use_grammar: bool = Field(default=True)
    context: Optional[Dict[str, Any]] = None
```

#### ConversionResponse
```python
class ConversionResponse(BaseModel):
    success: bool
    dcec_formula: str
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: List[Dict[str, Any]] = []
    parse_tree: Optional[Dict[str, Any]] = None
    processing_time_ms: int
```

#### ProvingRequest
```python
class ProvingRequest(BaseModel):
    conjecture: str = Field(..., min_length=1)
    axioms: List[str] = Field(default_factory=list)
    prover: str = Field(default="auto")
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    options: Optional[Dict[str, Any]] = None
```

#### ProvingResponse
```python
class ProofStep(BaseModel):
    step_number: int
    formula: str
    justification: str
    rule_used: Optional[str] = None

class ProvingResponse(BaseModel):
    success: bool
    result: str  # proved, disproved, timeout, unknown
    prover_used: str
    proof: Optional[Dict[str, Any]] = None
    proof_tree: Optional[Dict[str, Any]] = None
    processing_time_ms: int
    prover_info: Dict[str, Any]
```

#### KnowledgeBaseCreate
```python
class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    metadata: Optional[Dict[str, Any]] = None
```

#### Statement
```python
class Statement(BaseModel):
    formula: str = Field(..., min_length=1)
    label: Optional[str] = None
    is_axiom: bool = Field(default=False)
    metadata: Optional[Dict[str, Any]] = None
```

---

## 🔐 Authentication & Security

### Authentication Methods

#### 1. API Keys (Recommended for Clients)

**Header:**
```
X-API-Key: your_api_key_here
```

**Features:**
- Simple to use
- Per-key rate limiting
- Can be revoked
- Scoped permissions

#### 2. JWT Tokens (Recommended for Users)

**Header:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Features:**
- Short-lived (15 min access token)
- Long-lived refresh token (7 days)
- User-specific permissions
- Contains user metadata

### Token Endpoint

#### POST /api/v1/auth/token

Get JWT token.

**Request:**
```json
{
  "username": "alice",
  "password": "secure_password"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
```

#### POST /api/v1/auth/refresh

Refresh access token.

**Request:**
```json
{
  "refresh_token": "eyJ..."
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
```

### Security Headers

**Required Headers:**
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

### Input Validation

- **Pydantic models** for all requests
- **Max request size:** 10 MB
- **SQL injection protection** (parameterized queries)
- **XSS protection** (escape HTML)
- **CSRF protection** (for cookie-based auth)

---

## ⏱️ Rate Limiting

### Strategy

**Token Bucket Algorithm**
- Each API key/user has a bucket
- Bucket capacity: 60 tokens
- Refill rate: 60 tokens/minute (1 token/second)
- Burst capacity: 10 tokens

### Rate Limit Headers

**Response Headers:**
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1708250400
Retry-After: 30
```

### Rate Limit Response (429)

```json
{
  "error": "Rate limit exceeded",
  "limit": 60,
  "remaining": 0,
  "reset_at": "2026-02-18T10:35:00Z",
  "retry_after_seconds": 30
}
```

### Rate Limit Tiers

| Tier | Requests/Min | Burst | Description |
|------|--------------|-------|-------------|
| Free | 60 | 10 | Default tier |
| Basic | 300 | 50 | Paid tier |
| Pro | 1000 | 200 | Professional tier |
| Enterprise | Unlimited | Unlimited | Custom agreement |

---

## ⚠️ Error Handling

### Error Response Format

```json
{
  "error": {
    "code": "INVALID_INPUT",
    "message": "The provided DCEC formula is invalid",
    "details": {
      "field": "formula",
      "reason": "Unbalanced parentheses at position 15"
    },
    "request_id": "req_abc123",
    "timestamp": "2026-02-18T10:30:00Z"
  }
}
```

### Error Codes

| HTTP Code | Error Code | Description |
|-----------|-----------|-------------|
| 400 | INVALID_INPUT | Invalid request data |
| 401 | UNAUTHORIZED | Missing/invalid authentication |
| 403 | FORBIDDEN | Insufficient permissions |
| 404 | NOT_FOUND | Resource not found |
| 409 | CONFLICT | Resource conflict |
| 422 | VALIDATION_ERROR | Validation failed |
| 429 | RATE_LIMIT_EXCEEDED | Too many requests |
| 500 | INTERNAL_ERROR | Server error |
| 503 | SERVICE_UNAVAILABLE | Service temporarily unavailable |

### Validation Errors (422)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": {
      "errors": [
        {
          "field": "text",
          "message": "Field required",
          "type": "missing"
        },
        {
          "field": "language",
          "message": "Invalid language code",
          "type": "value_error"
        }
      ]
    },
    "request_id": "req_abc123"
  }
}
```

---

## 🚀 Performance & Caching

### Caching Strategy

#### Redis Cache Layers

**1. Result Cache (1 hour TTL)**
- Key: `result:{endpoint}:{hash(request)}`
- Value: Response JSON
- Use case: Expensive conversions/proofs

**2. Session Cache (1 hour TTL)**
- Key: `session:{session_id}`
- Value: Session state
- Use case: Session management

**3. KB Cache (10 min TTL)**
- Key: `kb:{kb_id}`
- Value: KB metadata + statements
- Use case: Frequent KB access

#### Cache Headers

**Response:**
```
Cache-Control: public, max-age=3600
ETag: "abc123def456"
Last-Modified: Wed, 18 Feb 2026 10:30:00 GMT
```

**Request:**
```
If-None-Match: "abc123def456"
If-Modified-Since: Wed, 18 Feb 2026 10:30:00 GMT
```

### Performance Targets

| Operation | Target | P95 | P99 |
|-----------|--------|-----|-----|
| NL → DCEC | <50ms | <100ms | <200ms |
| DCEC → NL | <30ms | <60ms | <120ms |
| Simple proof | <100ms | <200ms | <500ms |
| Complex proof | <3s | <5s | <10s |
| KB query | <50ms | <100ms | <200ms |

### Optimization Techniques

1. **Async/Await** - Non-blocking I/O
2. **Connection Pooling** - Reuse DB/Redis connections
3. **Result Caching** - Cache expensive operations
4. **Request Coalescing** - Deduplicate concurrent requests
5. **Lazy Loading** - Load data on demand
6. **Background Tasks** - Offload long-running tasks

---

## 📊 Monitoring & Logging

### Prometheus Metrics

#### Counter Metrics
```
cec_api_requests_total{endpoint, status, method}
cec_api_errors_total{endpoint, error_type}
cec_api_cache_hits_total{cache_type}
cec_api_cache_misses_total{cache_type}
```

#### Histogram Metrics
```
cec_api_request_duration_seconds{endpoint}
cec_api_proof_duration_seconds{prover}
cec_api_conversion_duration_seconds{direction}
```

#### Gauge Metrics
```
cec_api_active_sessions
cec_api_kb_count
cec_api_kb_statement_count
```

### Logging

#### Log Levels
- **DEBUG** - Detailed debug information
- **INFO** - General informational messages
- **WARNING** - Warning messages
- **ERROR** - Error messages
- **CRITICAL** - Critical errors

#### Log Format (JSON)
```json
{
  "timestamp": "2026-02-18T10:30:00.123Z",
  "level": "INFO",
  "message": "API request processed",
  "request_id": "req_abc123",
  "endpoint": "/api/v1/convert/nl-to-dcec",
  "method": "POST",
  "status_code": 200,
  "processing_time_ms": 45,
  "user_id": "user_123",
  "api_key_id": "key_456"
}
```

### Tracing

**OpenTelemetry Integration**
- Distributed tracing across services
- Span correlation
- Performance analysis
- Error tracking

---

## 🚢 Deployment

### Docker Compose

```yaml
version: '3.8'

services:
  api:
    image: cec-api:1.0.0
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379
      - POSTGRES_URL=postgresql://postgres:5432/cec
      - JWT_SECRET=your_secret_here
    depends_on:
      - redis
      - postgres
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  
  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=cec
      - POSTGRES_USER=cec
      - POSTGRES_PASSWORD=secure_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
  
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
  
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    depends_on:
      - prometheus

volumes:
  postgres_data:
```

### Environment Variables

```bash
# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
API_RELOAD=false

# Security
JWT_SECRET=your_secret_here_minimum_32_chars
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=15

# Database
REDIS_URL=redis://localhost:6379
POSTGRES_URL=postgresql://user:pass@localhost:5432/cec

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10

# Caching
CACHE_TTL_SECONDS=3600
ENABLE_CACHE=true

# Monitoring
ENABLE_METRICS=true
ENABLE_TRACING=false

# CEC Configuration
CEC_PROVER=native_python
CEC_USE_GRAMMAR=true
CEC_TIMEOUT_SECONDS=30
```

### Kubernetes Deployment (Optional)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cec-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: cec-api
  template:
    metadata:
      labels:
        app: cec-api
    spec:
      containers:
      - name: api
        image: cec-api:1.0.0
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: cec-config
              key: redis_url
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
```

---

## 📝 Example Client Code

### Python Client

```python
import requests

class CECClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
    
    def convert_nl_to_dcec(self, text: str) -> dict:
        response = requests.post(
            f"{self.base_url}/api/v1/convert/nl-to-dcec",
            json={"text": text},
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def prove(self, conjecture: str, axioms: list[str]) -> dict:
        response = requests.post(
            f"{self.base_url}/api/v1/prove",
            json={
                "conjecture": conjecture,
                "axioms": axioms
            },
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

# Usage
client = CECClient("http://localhost:8000", "your_api_key")
result = client.convert_nl_to_dcec("The agent must act")
print(result["dcec_formula"])
```

### JavaScript Client

```javascript
class CECClient {
  constructor(baseUrl, apiKey) {
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
  }

  async convertNLtoDCEC(text) {
    const response = await fetch(`${this.baseUrl}/api/v1/convert/nl-to-dcec`, {
      method: 'POST',
      headers: {
        'X-API-Key': this.apiKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ text })
    });
    
    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }
    
    return await response.json();
  }

  async prove(conjecture, axioms) {
    const response = await fetch(`${this.baseUrl}/api/v1/prove`, {
      method: 'POST',
      headers: {
        'X-API-Key': this.apiKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ conjecture, axioms })
    });
    
    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }
    
    return await response.json();
  }
}

// Usage
const client = new CECClient('http://localhost:8000', 'your_api_key');
const result = await client.convertNLtoDCEC('The agent must act');
console.log(result.dcec_formula);
```

---

## 📚 References

- **FastAPI Documentation:** https://fastapi.tiangolo.com
- **Pydantic Documentation:** https://docs.pydantic.dev
- **OpenAPI Specification:** https://swagger.io/specification/
- **OAuth 2.0 / JWT:** https://jwt.io
- **Redis Documentation:** https://redis.io/documentation
- **Prometheus Documentation:** https://prometheus.io/docs/

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-18  
**Status:** Design Phase  
**Next Steps:** Implementation in Phase 8 (Weeks 25-29)
