# UI/UX IR (`UIUXIRPublicAPI@1`)

Offline intermediate representation for multimodal UI declarations, projections,
runtime mediation, receipts, and assurance.

## Public imports

```python
from ipfs_datasets_py.logic.ui_ux_ir import (
    decode_ui_ir,
    canonicalize_ui_ir,
    ui_ir_identity,
    evaluate_ui_interaction,
)
```

Cold import starts no process, network, model, browser, or device action.

## Authority layers

| Layer | Authority |
| --- | --- |
| Declaration | Canonical `ui_ir` identity (`sha256:` of declaration bytes) |
| Projection | Adaptive presentation; never grants permission |
| Runtime mediation | Fail-closed allow/deny/confirm/...; only `allow` builds invocations |
| Proof / formalization | Typed evidence; never substituted for policy or mediation |

## Examples

See `docs/logic/UI_UX_IR_GUIDE.md` and `tests/unit/logic/ui_ux_ir/test_public_api.py`.
