# USPTO offline replay fixtures (PATLAW-072)

Compact, network-free receipts for end-to-end deterministic replay of public
and synthetic private matters.

## Layout

| Path | Role |
| --- | --- |
| `replay_manifest.json` | Version pins, matter ids, binding keys, acceptance gates |
| `public_matter_recipe.json` | Public matter receipt (ODP + synthetic analysis seeds) |
| `private_matter_recipe.json` | Synthetic private matter receipt (tenant-bound) |
| `generators.py` | Materializes receipts into SDK-ready inputs (no bulk gold dumps) |

## Design

* Prefer recipes + generators over re-emitting full envelopes per case.
* Public status uses recorded ODP HTTP under `../odp/http` (no live network).
* Private path reuses `../private_import` package bytes under explicit tenant auth.
* Digests bind input artifacts, parser, model, ruleset, config, and tree pins.
* Unknowns stay first-class (never vacuous pass).
* No sign / file / pay capability is exercised or required.

## Consumers

* `tests/e2e/test_uspto_application_analysis.py` — SDK path
* `tests/e2e/test_uspto_application_analysis_cli_mcp.py` — CLI + MCP parity
