# Synthetic USPTO-style PDF fixtures

Compact **generators** (not bulk golden dumps) used by PATLAW-004 tests.

Generate fixtures:

```python
from tests.fixtures.uspto.pdf.generators import fixture_manifest
fixture_manifest("/path/to/out")
```

All content is synthetic. Canaries are markers for OCR/coverage/non-disclosure
tests and are not real confidential filings.
