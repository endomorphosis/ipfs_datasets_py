# Logic-Family Parser Wave-2 Release

- Interface: `LogicParserReleaseReceipt@2`
- Receipt ID: `sha256:ed2d52a5cb67efadc1a2b6634301124afa8358c687291260138459afc51b934e`
- Machine receipt: `data/logic/conformance/logic_family_parser_v2_release.json`
- Wave-1 release: `sha256:86412a60bfde9b8a13156ab097b44443a4a8f70a7b286f1c7a707366c93757ce`
- Semantic tree projection: `sha256:6cc4929f3506920c40e1a9553c232465e50c5b439cafa37da2062c132d34f5d0`
- Fixed point: `sha256:3d18b0c27067b25f88121b973f30d68c186670409ad59cc30acb3ec91a800c0d`
- Reachable matrix: `sha256:93266a6997d2bd32f1175ad0a5af03eef4b87ca651168c4bccab3693bcfb0820` (228 cells)

## Acceptance

Every task except the sealing card is terminal, no derived task is open, the two-scan fixed point is current, and all reachable-matrix safety floors are zero. The LFP2-050 todo-to-completed transition and these two release files are normalized/excluded from semantic identity.

## Hard-zero floors

- `all_clear`: `True`
- `authority_escalation`: `0`
- `false_capability`: `0`
- `family_drift`: `0`
- `kernel_trust_escape`: `0`
- `raw_ingress`: `0`
- `silent_node_drop`: `0`
- `silent_node_loss`: `0`
- `unexplained_reachable_gap`: `0`

## Authority

This receipt grants no completion, mutation, promotion, solver, theorem, or kernel authority. Official kernel acceptance and independent refutation validation remain required by policy.
