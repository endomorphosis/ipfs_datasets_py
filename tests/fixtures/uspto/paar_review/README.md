# PAAR review fixtures

Hermetic, synthetic fixtures for Patent Automated Application Review e2e and
fail-closed unit tests (PAAR-110 / PAAR-111 / PAAR-141).

| Variant | Purpose | Expected (screening only) |
| --- | --- | --- |
| `planted_conflict/` | High lexical overlap claim × hit pair | `matter_risk` ≥ medium |
| `clean_package/` | Unrelated prior art; foreign/NPL gaps visible | not high without evidence |
| `missing_authority/` | Authority unbound → fail closed | not ready / unknown; never vacuous satisfied |
| `claims/` | Standalone claim text samples | parse-only |

Each variant has a `manifest.json` (`paar.review-fixture.v1`) listing files and
soft expected outcomes. Prior-hit rows include a `text` field for direct engine
consumption (`body_excerpt` / `abstract` retained as aliases).

**Consumers:**
- `tests/integration/processors/domains/uspto/test_paar_review_e2e.py` (PAAR-111)
- `tests/unit/processors/domains/uspto/test_paar_fail_closed.py` (PAAR-141)

**Rules:** synthetic public-like text only; no live matter bodies; no secrets;
no network; not legal advice; no patentability conclusions; `auto_file_blocked`.
