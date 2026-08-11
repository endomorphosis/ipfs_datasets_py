# Synthetic USPTO office-action fixtures (PATLAW-032)

Compact **generators** (not bulk golden dumps) for office-action analysis tests.

```python
from tests.fixtures.uspto.office_actions.generators import (
    build_non_final_office_action_text,
    build_rescinded_reissued_pair,
    fixture_manifest,
)

text = build_non_final_office_action_text()
pair = build_rescinded_reissued_pair()
fixture_manifest("/tmp/uspto-office-actions")
```

All content is synthetic. Canaries are markers for span and lifecycle tests.
