# Synthetic USPTO document fixtures (PATLAW-031)

Compact **generators** (not bulk golden dumps) for document extraction tests.

```python
from tests.fixtures.uspto.documents.generators import (
    build_native_pdf_with_metadata,
    build_docx_application,
    fixture_manifest,
)

pdf = build_native_pdf_with_metadata()
docx = build_docx_application()
fixture_manifest("/tmp/uspto-docs")
```

All content is synthetic. Canaries are markers for coverage and provenance tests.
