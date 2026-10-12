# Matched LegalIR curriculum experiment, 2026-10-12

Eight retained source-span decoder checkpoints compare actor curriculum, scope curriculum, and modality loss weight at a fixed training budget. This release is an authored engineering experiment; its scores do not establish independently reviewed statutory fidelity.

Each cell starts from the same retained 400-update parent model, resets Adam moments, uses seed 1729, 168 rows, batch size 12, and completes 32 new updates. The first 96 rehearsal rows, row IDs, batch schedule and source lengths remain matched. Actor and scope factors change only their declared twelve-row slots. Modality weight is 1 or 2, with total loss normalization 7 or 8 respectively.

The authoritative saved schema is `bounded-curriculum-span-legal-formula-checkpoint/v1`. Its outer `training_policy` records the actual weighted objective, initialization, and update limit. Nested legacy checkpoint descriptors describe their standalone constructor; they must not be treated as the authoritative weighted training objective. `SpanCurriculumDecoder` is the compatible loader. Existing warm-start loaders deliberately refuse the new outer schema.

Conditioning is configured as 384D but disabled: these runs make zero encoder calls. Placeholder parity checks do not qualify real 8D, 384D, or 768D autoencoders.

The evaluation sources contain no targets in the admitted child. All eight checkpoints and output bundles were frozen before evaluation references were scored. Those references were authored by the corpus builder and share templates with training; deferred scoring is not independent legal gold. Older tuning, fresh diagnostic panels and authored development remain exposed. Eight previously exposed statutory rows are retained without scored targets.

## Exact authored IR results

Each entry is raw decoder / joint span selection exact IR count. Joint selection retains top K=8 and the existing compatibility rules.

| State (actor/scope/weight2) | Older tuning /96 | Challenge /36 | Development /72 | Deferred evaluation /72 |
| --- | ---: | ---: | ---: | ---: |
| Original parent | 96 / 96 | 7 / 7 | 5 / 5 | 12 / 12 |
| actor0-scope0-modality0 | 92 / 92 | 21 / 21 | 28 / 38 | 45 / 46 |
| actor0-scope0-modality1 | 93 / 93 | 21 / 21 | 31 / 40 | 47 / 49 |
| actor0-scope1-modality0 | 94 / 94 | 21 / 22 | 34 / 43 | 45 / 46 |
| actor0-scope1-modality1 | 94 / 94 | 21 / 23 | 36 / 43 | 49 / 49 |
| actor1-scope0-modality0 | 91 / 91 | 22 / 22 | 32 / 40 | 46 / 50 |
| actor1-scope0-modality1 | 93 / 93 | 23 / 23 | 35 / 43 | 49 / 52 |
| actor1-scope1-modality0 | 92 / 92 | 21 / 23 | 38 / 45 | 51 / 52 |
| actor1-scope1-modality1 | 94 / 94 | 23 / 25 | 37 / 44 | 51 / 52 |

The all-factor cell (`actor1-scope1-modality1`) reaches raw 51/72 (70.8%) and joint 52/72 (72.2%) on authored evaluation, compared with 12/72 (16.7%) for both at the original parent. It retains 94/96 older exact outputs; both remaining older failures change permission to obligation. Three cells tie at joint 52/72. All eight checkpoints are archived; there is no selected or promoted default.

Descriptive evaluation main effects average across the other two factors: actor curriculum adds four joint-exact rows; weight 2 adds two; scope adds half a row. These are single-seed matched contrasts, without significance or seed-robustness claims. Weighted tuning losses use different objectives and must not be ranked as interchangeable losses.

Temporal presence is correct on all 72 evaluation rows in the all-factor cell, but full IR correctness remains lower. Only 2/12 actor-name examples and 6/12 combined condition/exception examples are joint-exact. Longer actor names and clause boundaries therefore remain the next training priorities.

## Custody and validation

All eight guardians completed with child exit 0, durable artifacts, released distinct 200 MB reservations and absent owned leases/process groups. The opening ledger had 514 records; the closing endpoint has 522, preserving every earlier record body. The maximum sampled model RSS was 756,764,672 bytes; this is sampled monitoring, not a kernel hard-memory cap. No reservation caps were raised and no old weights were deleted.

The pure corpus and trainer suite passed 68 tests plus 183 subtests. Separate frozen-source checks and saved-output replay verify schedules, policy, span arithmetic and output custody. These checks do not prove legal semantics.

## Reproduction and remaining work

Source base: `endomorphosis/ipfs_datasets_py` commit `f47161b757190380e9898aff155067c1ad609217`, plus the exact new modules and tests archived under `source/`. Checkpoints pin their producer bytes. Keep the producer closure when restoring; do not relax source pins or substitute historical weights. The `recipe/` scripts preserve the exact bounded workspace protocol and paths, rather than offering an unrestricted training launcher.

The additive Hub prefix is `releases/20261012-matched-curriculum-v1` in `Publicus/legal-ir-autoencoder`. It contains all eight checkpoints, raw saved outputs, the authored reference packet, and finite public evidence. Global ledger bodies and private endpoint snapshots are excluded.

Next experiments should use a new disjoint authored evaluation panel because this one is now inspected. Measure candidate coverage and ranking for remaining actor and combined-scope failures, compare targeted span ranking or boundary-aware training at a matched update budget, and retain an explicit permission-rehearsal regression constraint. Separately, obtain reviewed US Code references, test genuine latent conditioning across all three widths, and compile independently mapped outputs through `lake build legal` and each supported logic-family contract before claiming wider autoformalization fidelity. No Lake compilation or broader logic-family qualification was executed in this experiment.
