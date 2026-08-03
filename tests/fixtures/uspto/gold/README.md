# USPTO reviewed gold corpus (PATLAW-070)

Synthetic and approved-public fixtures with **reviewer-labeled truth** for
requirement, citation, date, and provenance evaluation.

## Layout

| Path | Role |
| --- | --- |
| `cases/` | Compact synthetic/public case recipes (no bulk envelopes) |
| `annotations/` | Reviewer-labeled expected requirements, citations, dates, provenance |
| `metrics/metric_gates.json` | Machine-readable recall/precision/provenance/FN gates |
| `../GOLD_CORPUS_MANIFEST.json` | Inventory + SHA-256 of every fixture and annotation |

## Privacy

Repository gold fixtures are **public synthetic** or **approved public official**
only. No confidential applications, privileged work product, export-review
material, credentials, or real private Patent Center exports are admitted.

## Regeneration

Case and annotation digests are locked by `GOLD_CORPUS_MANIFEST.json`. Edit
fixtures, recompute digests, update the manifest, then re-run:

```bash
python -m pytest tests/contract/processors/test_uspto_gold_corpus_contract.py -q
```
