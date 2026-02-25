# Ontology Extraction Baseline Benchmark

**Generated**: 2026-02-24 21:00:36

## Performance Summary

| Case | Strategy | Domain | Tokens | Avg (ms) | P95 (ms) | Entities | Relationships |
|------|----------|--------|--------|----------|----------|----------|---------------|
| 1k_general_rule | rule_based | general | 1,000 | 10.99 | 14.91 | 38.0 | 158.0 |
| 1k_legal_rule | rule_based | legal | 1,000 | 11.51 | 13.27 | 40.0 | 179.0 |
| 5k_general_rule | rule_based | general | 5,000 | 28.08 | 30.47 | 38.0 | 158.0 |
| 5k_legal_rule | rule_based | legal | 5,000 | 31.12 | 35.52 | 40.0 | 179.0 |
| 5k_business_rule | rule_based | business | 5,000 | 28.93 | 31.70 | 38.0 | 158.0 |
| 10k_general_rule | rule_based | general | 10,000 | 67.70 | 73.74 | 38.0 | 158.0 |
| 10k_legal_rule | rule_based | legal | 10,000 | 61.75 | 66.52 | 40.0 | 179.0 |
| 10k_medical_rule | rule_based | medical | 10,000 | 59.25 | 65.18 | 38.0 | 158.0 |
| 20k_general_rule | rule_based | general | 20,000 | 107.49 | 110.15 | 38.0 | 158.0 |

## Detailed Metrics

### 1k_general_rule

**Configuration**:
- Strategy: rule_based
- Domain: general
- Text size: 1,000 tokens
- Iterations: 20 (warmups: 3)

**Performance**:
- Average: 10.99 ms
- Median: 10.34 ms
- P95: 14.91 ms
- P99: 14.91 ms
- Min/Max: 9.43 / 15.62 ms
- Stddev: 1.66 ms

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
- Average: 11.51 ms
- Median: 11.48 ms
- P95: 13.27 ms
- P99: 13.27 ms
- Min/Max: 9.92 / 13.44 ms
- Stddev: 1.26 ms

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
- Average: 28.08 ms
- Median: 27.03 ms
- P95: 30.47 ms
- P99: 30.47 ms
- Min/Max: 26.30 / 37.64 ms
- Stddev: 2.86 ms

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
- Average: 31.12 ms
- Median: 30.78 ms
- P95: 35.52 ms
- P99: 35.52 ms
- Min/Max: 27.79 / 37.63 ms
- Stddev: 2.53 ms

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
- Average: 28.93 ms
- Median: 28.21 ms
- P95: 31.70 ms
- P99: 31.70 ms
- Min/Max: 26.20 / 34.76 ms
- Stddev: 2.25 ms

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
- Average: 67.70 ms
- Median: 70.78 ms
- P95: 73.74 ms
- P99: 73.74 ms
- Min/Max: 50.12 / 75.72 ms
- Stddev: 8.63 ms

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
- Average: 61.75 ms
- Median: 59.17 ms
- P95: 66.52 ms
- P99: 66.52 ms
- Min/Max: 57.08 / 72.99 ms
- Stddev: 5.29 ms

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
- Average: 59.25 ms
- Median: 57.11 ms
- P95: 65.18 ms
- P99: 65.18 ms
- Min/Max: 51.30 / 76.22 ms
- Stddev: 7.37 ms

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
- Average: 107.49 ms
- Median: 104.03 ms
- P95: 110.15 ms
- P99: 110.15 ms
- Min/Max: 100.58 / 120.82 ms
- Stddev: 8.30 ms

**Quality**:
- Entities: 38.00
- Relationships: 158.00
- Confidence: 0.7000
