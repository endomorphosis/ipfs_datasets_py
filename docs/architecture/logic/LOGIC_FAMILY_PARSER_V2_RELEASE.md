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

## Goal evidence (LFP2-G100)

This seal covers every LFP2-G100 evidence term without authority escalation.
Machine receipt field `goal_evidence` binds the same terms for exact-text scan.

| Evidence term | Covered | Owner |
| --- | --- | --- |
| `LogicParserReleaseReceipt@2` | yes | LFP2-050 |
| `immutable-v1-predecessor-binding` | yes | LFP2-050 |
| `wave2-release-validation` | yes | LFP2-053 |

### wave2-release-validation

`wave2-release-validation` is the joined Wave-2 release validation gate. It holds only when:

1. acceptance floors in the machine receipt are true;
2. reachable-matrix hard-zero floors remain zero;
3. the objective-refill fixed point is current with two quiet epochs;
4. Wave-1 predecessor digests match the immutable anchors;
5. release self-outputs stay excluded from semantic projection; and
6. the logic unit, conformance, and fuzz suites pass:

```text
cd ipfs_datasets_py && python -m pytest -q tests/unit/logic tests/conformance/logic tests/fuzz/logic
```

Validation surfaces for `wave2-release-validation` include
`ipfs_datasets_py/tests/unit/logic/conformance/test_release_v2.py`,
`ipfs_datasets_py/tests/conformance/logic`, `ipfs_datasets_py/tests/fuzz/logic`,
and the deterministic materializer
`ipfs_datasets_py/ipfs_datasets_py/logic/conformance/release_v2.py`.

### immutable-v1-predecessor-binding

`immutable-v1-predecessor-binding` is proven by the exact predecessor block:
accelerator commit `e162c19d087d4e6511f8eb97fd34ecb449777897`, datasets commit
`fc49cbb3e0e96bf07b367859da32123187d706c1`, seed definition
`sha256:f5d01bcc13c0b62d35b713cccb2e04abe49da454e9fa6f35cd28a5ad4b72eb44`,
terminal task `LFP-047`, and Wave-1 release
`sha256:86412a60bfde9b8a13156ab097b44443a4a8f70a7b286f1c7a707366c93757ce`.

Never edit evidence to make a red floor green; repair the owning semantic path.

## Authority

This receipt grants no completion, mutation, promotion, solver, theorem, or kernel authority. Official kernel acceptance and independent refutation validation remain required by policy.
