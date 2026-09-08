# UI/UX IR guide and migration notes

## What this is

UI/UX IR is a **semantic** intermediate representation. Round-trips preserve
declared meaning (components, actions, norms, bindings), not pixel layout or
source HTML/JS.

## Public surface

```python
from ipfs_datasets_py.logic.ui_ux_ir import (
    decode_ui_ir,
    canonicalize_ui_ir,
    ui_ir_identity,
    evaluate_ui_interaction,
    public_api_manifest,
)
```

Importing `ipfs_datasets_py.logic.ui_ux_ir` is offline and side-effect free.

## Authority (do not substitute)

1. **Declaration** — `ui_ir_identity` / canonical bytes
2. **Projection** — device/layout adaptation and loss receipts
3. **Runtime policy** — `evaluate_ui_interaction` / `UIMediator`
4. **Formal proof** — theorem/sat/monitor results stay typed and distinct

A passing projection never proves policy allow; a theorem pass never replaces
policy evidence.

## Migration from raw IDL HTML UIs

1. Bind actions via `UIActionBinding` / MCP-IDL identity (not `innerHTML` handlers).
2. Route invocation through mediated ORB / `evaluate_ui_interaction`.
3. Escape all descriptor/result text in renderers (see UIR-035).
4. Prefer golden vectors under `tests/fixtures/ui_ux_ir/v1/`.

## Pilots

Fixtures under `tests/fixtures/ui_ux_ir/pilots/` exercise form, destructive,
glasses, and agent-supervisor flows without hardware.
