# Ontology Extraction Baseline Benchmark

**Generated**: 2026-02-24 22:23:11

## Performance Summary

| Case | Strategy | Domain | Tokens | Avg (ms) | P95 (ms) | Entities | Relationships |
|------|----------|--------|--------|----------|----------|----------|---------------|
| 1k_general_rule | rule_based | general | 1,000 | 8.24 | 8.60 | 38.0 | 158.0 |
| 1k_legal_rule | rule_based | legal | 1,000 | 8.25 | 8.93 | 40.0 | 179.0 |
| 5k_general_rule | rule_based | general | 5,000 | 21.72 | 22.00 | 38.0 | 158.0 |
| 5k_legal_rule | rule_based | legal | 5,000 | 22.51 | 22.98 | 40.0 | 179.0 |
| 5k_business_rule | rule_based | business | 5,000 | 21.79 | 22.42 | 38.0 | 158.0 |
| 10k_general_rule | rule_based | general | 10,000 | 38.94 | 39.50 | 38.0 | 158.0 |
| 10k_legal_rule | rule_based | legal | 10,000 | 40.69 | 41.23 | 40.0 | 179.0 |
| 10k_medical_rule | rule_based | medical | 10,000 | 39.95 | 40.77 | 38.0 | 158.0 |
| 20k_general_rule | rule_based | general | 20,000 | 73.49 | 74.88 | 38.0 | 158.0 |

## Detailed Metrics

### 1k_general_rule

**Configuration**:
- Strategy: rule_based
- Domain: general
- Text size: 1,000 tokens
- Iterations: 20 (warmups: 3)

**Performance**:
- Average: 8.24 ms
- Median: 8.25 ms
- P95: 8.60 ms
- P99: 8.60 ms
- Min/Max: 7.79 / 8.76 ms
- Stddev: 0.27 ms

**Quality**:
- Entities: 38.00
- Relationships: 158.00
- Confidence: 0.7000

### 1k_legal_rule

**Configuration**:
- Strategy: rule_based
- Domain: legal
- Text size: 1,000 tokens
- Iterations: 20 (warmups: 3)

**Performance**:
- Average: 8.25 ms
- Median: 8.14 ms
- P95: 8.93 ms
- P99: 8.93 ms
- Min/Max: 7.09 / 9.74 ms
- Stddev: 0.58 ms

**Quality**:
- Entities: 40.00
- Relationships: 179.00
- Confidence: 0.7000

### 5k_general_rule

**Configuration**:
- Strategy: rule_based
- Domain: general
- Text size: 5,000 tokens
- Iterations: 15 (warmups: 2)

**Performance**:
- Average: 21.72 ms
- Median: 21.73 ms
- P95: 22.00 ms
- P99: 22.00 ms
- Min/Max: 21.40 / 22.11 ms
- Stddev: 0.23 ms

**Quality**:
- Entities: 38.00
- Relationships: 158.00
- Confidence: 0.7000

### 5k_legal_rule

**Configuration**:
- Strategy: rule_based
- Domain: legal
- Text size: 5,000 tokens
- Iterations: 15 (warmups: 2)

**Performance**:
- Average: 22.51 ms
- Median: 22.51 ms
- P95: 22.98 ms
- P99: 22.98 ms
- Min/Max: 22.11 / 23.05 ms
- Stddev: 0.26 ms

**Quality**:
- Entities: 40.00
- Relationships: 179.00
- Confidence: 0.7000

### 5k_business_rule

**Configuration**:
- Strategy: rule_based
- Domain: business
- Text size: 5,000 tokens
- Iterations: 15 (warmups: 2)

**Performance**:
- Average: 21.79 ms
- Median: 21.77 ms
- P95: 22.42 ms
- P99: 22.42 ms
- Min/Max: 21.19 / 22.83 ms
- Stddev: 0.47 ms

**Quality**:
- Entities: 38.00
- Relationships: 158.00
- Confidence: 0.7000

### 10k_general_rule

**Configuration**:
- Strategy: rule_based
- Domain: general
- Text size: 10,000 tokens
- Iterations: 10 (warmups: 2)

**Performance**:
- Average: 38.94 ms
- Median: 38.79 ms
- P95: 39.50 ms
- P99: 39.50 ms
- Min/Max: 38.13 / 40.14 ms
- Stddev: 0.61 ms

**Quality**:
- Entities: 38.00
- Relationships: 158.00
- Confidence: 0.7000

### 10k_legal_rule

**Configuration**:
- Strategy: rule_based
- Domain: legal
- Text size: 10,000 tokens
- Iterations: 10 (warmups: 2)

**Performance**:
- Average: 40.69 ms
- Median: 40.71 ms
- P95: 41.23 ms
- P99: 41.23 ms
- Min/Max: 39.83 / 41.42 ms
- Stddev: 0.48 ms

**Quality**:
- Entities: 40.00
- Relationships: 179.00
- Confidence: 0.7000

### 10k_medical_rule

**Configuration**:
- Strategy: rule_based
- Domain: medical
- Text size: 10,000 tokens
- Iterations: 10 (warmups: 2)

**Performance**:
- Average: 39.95 ms
- Median: 40.10 ms
- P95: 40.77 ms
- P99: 40.77 ms
- Min/Max: 37.48 / 41.48 ms
- Stddev: 1.06 ms

**Quality**:
- Entities: 38.00
- Relationships: 158.00
- Confidence: 0.7000

### 20k_general_rule

**Configuration**:
- Strategy: rule_based
- Domain: general
- Text size: 20,000 tokens
- Iterations: 5 (warmups: 1)

**Performance**:
- Average: 73.49 ms
- Median: 73.92 ms
- P95: 74.88 ms
- P99: 74.88 ms
- Min/Max: 70.03 / 75.65 ms
- Stddev: 2.18 ms

**Quality**:
- Entities: 38.00
- Relationships: 158.00
- Confidence: 0.7000
